"""Vector memory store: ChromaDB + Ollama bge-m3 embeddings.

Three-layer memory architecture:
  Hot  — profile.json + recent task_history (always injected)
  Warm — ChromaDB semantic search top-K (per-task RAG)
  Cold — full ChromaDB collection (explicit recall only)

Search is hybrid: vector (ChromaDB) + keyword (SQLite FTS5) fused via
RRF-style weighted merge, temporal decay, and MMR diversity re-ranking.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, List, Dict, Any

import aiosqlite
import chromadb
from chromadb.api.types import EmbeddingFunction, Embeddings, Documents

from models import MemoryEntry

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3:567m"


# ── Embedding ────────────────────────────────────────────────────────────────

def _embed_texts(texts: list) -> list:
    """POST to Ollama, return list of 1024-dim vectors."""
    if not texts:
        return []
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("embeddings", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        logger.warning(f"Ollama embedding failed: {e}")
        return []


class OllamaEmbeddingFunction(EmbeddingFunction[Documents]):
    """ChromaDB-compatible embedding function using Ollama bge-m3."""

    def __call__(self, input: Documents) -> Embeddings:
        result = _embed_texts(list(input))
        if not result:
            raise RuntimeError("Ollama embedding returned empty — is bge-m3:567m running?")
        return result


# ── Per-Agent ChromaDB collection ────────────────────────────────────────────

_clients: dict = {}  # agent_id → chromadb.ClientAPI cache
_embed_fn = OllamaEmbeddingFunction()


def _get_memory_dir(agent_id: str) -> str:
    """Return agent_homes/{agent_id}/memory/chroma/ path."""
    from agents.agent_home import get_agent_memory_dir
    return os.path.join(get_agent_memory_dir(agent_id), "chroma")


def get_agent_collection(agent_id: str) -> chromadb.Collection:
    """Get or create a ChromaDB PersistentClient + collection for an agent."""
    if agent_id not in _clients:
        chroma_path = _get_memory_dir(agent_id)
        os.makedirs(chroma_path, exist_ok=True)
        _clients[agent_id] = chromadb.PersistentClient(path=chroma_path)
    client = _clients[agent_id]
    return client.get_or_create_collection(
        name="memories",
        embedding_function=_embed_fn,
        metadata={"hnsw:space": "cosine"},
    )


# ── CRUD (async wrappers around sync ChromaDB) ──────────────────────────────

async def save_memory_to_store(entry: MemoryEntry) -> None:
    """Persist a MemoryEntry into the agent's ChromaDB collection.

    Deduplication: if an existing memory has cosine distance < 0.08
    (very similar content), skip insertion to avoid redundant entries.
    """
    def _save():
        col = get_agent_collection(entry.agent_id)

        # Near-duplicate check before inserting
        if col.count() > 0:
            try:
                existing = col.query(
                    query_texts=[entry.content],
                    n_results=1,
                    where={"agent_id": entry.agent_id},
                    include=["distances"],
                )
                if (
                    existing
                    and existing.get("distances")
                    and existing["distances"][0]
                    and existing["distances"][0][0] < 0.08
                ):
                    logger.info(
                        f"[MemoryStore] Skipping near-duplicate memory for "
                        f"{entry.agent_id} (distance={existing['distances'][0][0]:.4f})"
                    )
                    return
            except Exception as e:
                logger.warning(f"[MemoryStore] Dedup check failed, proceeding with save: {e}")

        col.add(
            ids=[entry.id],
            documents=[entry.content],
            metadatas=[{
                "agent_id": entry.agent_id,
                "category": entry.category,
                "importance": entry.importance,
                "created_at": entry.created_at.isoformat(),
            }],
        )

    await asyncio.to_thread(_save)


async def _fts5_search(
    agent_id: str,
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search agent memories using SQLite FTS5 full-text search (trigram tokenizer).

    Returns a list of dicts with keys: id, content, category, importance,
    timestamp, score.  Falls back to empty list on any error.
    """
    from agents.memory_hybrid import build_fts_query, bm25_rank_to_score
    from database import DB_PATH

    fts_query = build_fts_query(query)
    if not fts_query:
        return []

    results: List[Dict[str, Any]] = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # FTS5 table only indexes `content`; agent filtering is done via JOIN.
            # `rank` is the BM25 score exposed by FTS5 (more negative = more relevant).
            sql = """
                SELECT m.id,
                       m.content,
                       m.category,
                       m.importance,
                       m.created_at,
                       fts.rank
                FROM agent_memories_fts fts
                JOIN agent_memories m ON m.rowid = fts.rowid
                WHERE agent_memories_fts MATCH ?
                  AND m.agent_id = ?
                ORDER BY fts.rank
                LIMIT ?
            """
            async with db.execute(sql, (fts_query, agent_id, limit)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    results.append({
                        "id": str(row[0]),
                        "content": row[1],
                        "category": row[2] or "general",
                        "importance": float(row[3]) if row[3] is not None else 0.5,
                        "timestamp": row[4],   # ISO string; hybrid pipeline parses it
                        "score": bm25_rank_to_score(row[5]),
                    })
    except Exception as e:
        logger.warning(f"[MemoryStore] FTS5 search failed for {agent_id}, skipping: {e}")

    return results


async def search_memory_store(
    agent_id: str,
    query: str,
    limit: int = 5,
    category: Optional[str] = None,
) -> List[MemoryEntry]:
    """Hybrid memory search: vector (ChromaDB) + keyword (FTS5) with temporal
    decay and MMR diversity re-ranking.

    Pipeline:
      1. ChromaDB cosine-similarity search  (weight 0.7)
      2. SQLite FTS5 BM25 keyword search    (weight 0.3)
      3. Weighted score merge (RRF-style)
      4. Temporal decay  (half-life = 30 days)
      5. MMR re-ranking  (lambda = 0.7 — balanced relevance/diversity)
    """
    from agents.memory_hybrid import hybrid_search_pipeline

    # ── 1. Vector search (ChromaDB, synchronous) ──────────────────────────
    def _vector_search() -> List[Dict[str, Any]]:
        col = get_agent_collection(agent_id)
        if col.count() == 0:
            return []

        where_filter: Dict[str, Any] = {"agent_id": agent_id}
        if category:
            where_filter = {"$and": [
                {"agent_id": agent_id},
                {"category": category},
            ]}

        try:
            raw = col.query(
                query_texts=[query],
                n_results=min(limit * 3, col.count()),
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.warning(f"[MemoryStore] ChromaDB query failed: {e}")
            return []

        if not raw or not raw.get("ids") or not raw["ids"][0]:
            return []

        vector_hits: List[Dict[str, Any]] = []
        for i, doc_id in enumerate(raw["ids"][0]):
            meta = raw["metadatas"][0][i]
            distance = raw["distances"][0][i]      # cosine distance (0 = identical)
            similarity = max(0.0, 1.0 - distance)  # convert to [0, 1] similarity
            vector_hits.append({
                "id": str(doc_id),
                "content": raw["documents"][0][i],
                "category": meta.get("category", "general"),
                "importance": float(meta.get("importance", 0.5)),
                "timestamp": meta.get("created_at"),   # ISO string
                "score": similarity,
            })
        return vector_hits

    # Run vector search in thread (ChromaDB is sync), FTS5 concurrently
    vector_results, keyword_results = await asyncio.gather(
        asyncio.to_thread(_vector_search),
        _fts5_search(agent_id, query, limit=limit * 3),
    )

    # ── 2-5. Hybrid pipeline: merge → decay → MMR ────────────────────────
    merged = hybrid_search_pipeline(
        vector_results=vector_results,
        keyword_results=keyword_results,
        vector_weight=0.7,
        text_weight=0.3,
        enable_decay=True,
        half_life_days=30.0,
        enable_mmr=True,
        mmr_lambda=0.7,
        max_results=limit,
    )

    # ── 6. Convert merged dicts back to MemoryEntry objects ───────────────
    entries: List[MemoryEntry] = []
    for hit in merged:
        ts_raw = hit.get("timestamp")
        try:
            created_at = (
                datetime.fromisoformat(ts_raw) if ts_raw else datetime.utcnow()
            )
        except (ValueError, TypeError):
            created_at = datetime.utcnow()

        entries.append(MemoryEntry(
            id=hit["id"],
            agent_id=agent_id,
            content=hit["content"],
            category=hit.get("category", "general"),
            importance=float(hit.get("importance", 0.5)),
            created_at=created_at,
        ))

    return entries


async def get_recent_from_store(agent_id: str, limit: int = 10) -> list:
    """Get most recent memories (by created_at DESC)."""
    def _get():
        col = get_agent_collection(agent_id)
        count = col.count()
        if count == 0:
            return []

        results = col.get(
            where={"agent_id": agent_id},
            include=["documents", "metadatas"],
            limit=min(limit * 3, count),  # over-fetch then sort
        )
        if not results or not results["ids"]:
            return []

        entries = []
        for i, doc_id in enumerate(results["ids"]):
            meta = results["metadatas"][i]
            try:
                created = datetime.fromisoformat(meta["created_at"])
            except (ValueError, KeyError):
                created = datetime.utcnow()
            entries.append(MemoryEntry(
                id=doc_id,
                agent_id=meta.get("agent_id", agent_id),
                content=results["documents"][i],
                category=meta.get("category", "general"),
                importance=float(meta.get("importance", 0.5)),
                created_at=created,
            ))

        entries.sort(key=lambda x: x.created_at, reverse=True)
        return entries[:limit]

    return await asyncio.to_thread(_get)


async def delete_agent_store(agent_id: str) -> None:
    """Delete the agent's ChromaDB collection and clear cache."""
    def _delete():
        if agent_id in _clients:
            try:
                _clients[agent_id].delete_collection("memories")
            except Exception:
                pass
            del _clients[agent_id]
    await asyncio.to_thread(_delete)


# ── Agent Profile ────────────────────────────────────────────────────────────

def _get_profile_path(agent_id: str) -> str:
    from agents.agent_home import get_agent_profile_path
    return get_agent_profile_path(agent_id)


async def update_agent_profile(
    agent_id: str,
    memories: list,
    model: str = "deepseek/deepseek-chat",
    llm_kwargs: Optional[dict] = None,
) -> None:
    """LLM-summarize recent memories into a compact profile.json (~200 tokens)."""
    if not memories:
        return

    from litellm import acompletion

    mem_text = "\n".join(f"- {m.content[:200]}" for m in memories[:15])
    kwargs = llm_kwargs or {}

    try:
        resp = await acompletion(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are a memory profiler. Given an agent's recent memories, "
                    "produce a JSON object with these keys:\n"
                    '  "expertise": ["skill1", "skill2", ...],\n'
                    '  "preferences": ["pref1", "pref2", ...],\n'
                    '  "notable_facts": ["fact1", "fact2", ...]\n'
                    "Keep each list to 3-5 items. Be concise. "
                    "Output ONLY valid JSON, no markdown."
                )},
                {"role": "user", "content": f"Agent memories:\n{mem_text}"},
            ],
            max_tokens=300,
            temperature=0.3,
            **kwargs,
        )
        raw = resp.choices[0].message.content.strip()
        # Try to parse JSON (handle possible markdown wrapping)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        profile = json.loads(raw)
    except Exception as e:
        logger.warning(f"Profile generation failed for {agent_id}: {e}")
        return

    profile["updated_at"] = datetime.utcnow().isoformat()
    profile_path = _get_profile_path(agent_id)
    os.makedirs(os.path.dirname(profile_path), exist_ok=True)

    def _write():
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)

    await asyncio.to_thread(_write)
    logger.info(f"[MemoryStore] Updated profile for {agent_id}")


def load_agent_profile(agent_id: str) -> Optional[dict]:
    """Read profile.json synchronously (fast, small file)."""
    path = _get_profile_path(agent_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Cannot read profile for {agent_id}: {e}")
        return None

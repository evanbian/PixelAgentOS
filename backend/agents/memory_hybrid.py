# -*- coding: utf-8 -*-
"""Hybrid memory search: vector + BM25 fusion, MMR re-ranking, temporal decay.

Ported from OpenClaw's memory system (hybrid.ts, mmr.ts, temporal-decay.ts).
Composable pipeline: merge -> decay -> MMR -> return.
"""
from __future__ import annotations

import math
import re
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════
# Temporal Decay
# ═══════════════════════════════════════════════════════════════════

DEFAULT_HALF_LIFE_DAYS = 30
DAY_SECONDS = 24 * 60 * 60


def temporal_decay_multiplier(age_days: float, half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Calculate exponential decay multiplier based on age.

    Formula: multiplier = e^(-λ * age) where λ = ln(2) / half_life

    Examples:
        age=0  -> 1.00  (today)
        age=7  -> 0.85  (1 week)
        age=30 -> 0.50  (1 month)
        age=90 -> 0.125 (3 months)
    """
    if half_life_days <= 0 or not math.isfinite(half_life_days):
        return 1.0
    lam = math.log(2) / half_life_days
    clamped_age = max(0.0, age_days)
    if not math.isfinite(clamped_age):
        return 1.0
    return math.exp(-lam * clamped_age)


def apply_temporal_decay(
    score: float, age_days: float, half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Apply temporal decay to a single score."""
    return score * temporal_decay_multiplier(age_days, half_life_days)


def _age_in_days(timestamp: datetime) -> float:
    """Calculate age in days from a timestamp to now."""
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    delta = now - timestamp
    return max(0.0, delta.total_seconds() / DAY_SECONDS)


def apply_decay_to_results(
    results: List[Dict[str, Any]],
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    timestamp_key: str = "timestamp",
    score_key: str = "score",
    evergreen_categories: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Apply temporal decay to a list of search results.

    Entries with categories in evergreen_categories are not decayed.
    """
    if not results:
        return results

    evergreen = evergreen_categories or {"profile", "identity"}
    decayed = []

    for entry in results:
        category = entry.get("category", "")
        if category in evergreen:
            decayed.append(entry)
            continue

        ts = entry.get(timestamp_key)
        if ts is None:
            decayed.append(entry)
            continue

        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                decayed.append(entry)
                continue

        if isinstance(ts, datetime):
            age = _age_in_days(ts)
            new_score = apply_temporal_decay(entry.get(score_key, 0), age, half_life_days)
            decayed.append({**entry, score_key: new_score})
        else:
            decayed.append(entry)

    return decayed


# ═══════════════════════════════════════════════════════════════════
# BM25 Score Conversion
# ═══════════════════════════════════════════════════════════════════

def bm25_rank_to_score(rank: float) -> float:
    """Convert BM25 rank (0 = best) to a 0-1 score.

    From OpenClaw: score = 1 / (1 + rank)
    Rank 0 -> 1.0, Rank 9 -> 0.1

    SQLite FTS5 returns negative BM25 scores where more negative = more relevant.
    We handle both conventions.
    """
    if not math.isfinite(rank):
        return 1 / (1 + 999)
    if rank < 0:
        # SQLite FTS5 returns negative values, more negative = more relevant
        relevance = -rank
        return relevance / (1 + relevance)
    return 1 / (1 + rank)


def build_fts_query(raw: str) -> Optional[str]:
    """Build FTS5 query from raw text.

    Tokenizes input and joins with AND for conjunctive search.
    Handles CJK and Unicode characters.
    """
    tokens = re.findall(r'[\w]+', raw, re.UNICODE)
    tokens = [t.strip() for t in tokens if t.strip()]
    if not tokens:
        return None
    quoted = [f'"{t}"' for t in tokens]
    return " AND ".join(quoted)


# ═══════════════════════════════════════════════════════════════════
# Hybrid Search Merger
# ═══════════════════════════════════════════════════════════════════

def merge_hybrid_results(
    vector_results: List[Dict[str, Any]],
    keyword_results: List[Dict[str, Any]],
    vector_weight: float = 0.7,
    text_weight: float = 0.3,
    id_key: str = "id",
    score_key: str = "score",
    content_key: str = "content",
) -> List[Dict[str, Any]]:
    """Merge vector search and keyword search results with weighted scoring.

    Entries appearing in both result sets get boosted (scores combined).

    Args:
        vector_results: Results from vector similarity search (ChromaDB)
        keyword_results: Results from BM25/FTS5 keyword search
        vector_weight: Weight for vector scores (default 0.7)
        text_weight: Weight for keyword scores (default 0.3)

    Returns:
        Merged results sorted by combined score (descending)
    """
    by_id = {}  # type: Dict[str, Dict[str, Any]]

    for r in vector_results:
        rid = r.get(id_key, id(r))
        by_id[rid] = {
            **r,
            "_vector_score": r.get(score_key, 0),
            "_text_score": 0,
        }

    for r in keyword_results:
        rid = r.get(id_key, id(r))
        if rid in by_id:
            by_id[rid]["_text_score"] = r.get(score_key, 0)
            # Prefer keyword snippet if available (often more contextual)
            content = r.get(content_key)
            if content:
                by_id[rid][content_key] = content
        else:
            by_id[rid] = {
                **r,
                "_vector_score": 0,
                "_text_score": r.get(score_key, 0),
            }

    merged = []
    for entry in by_id.values():
        combined = vector_weight * entry["_vector_score"] + text_weight * entry["_text_score"]
        result = {k: v for k, v in entry.items() if not k.startswith("_")}
        result[score_key] = combined
        merged.append(result)

    return sorted(merged, key=lambda x: x.get(score_key, 0), reverse=True)


# ═══════════════════════════════════════════════════════════════════
# MMR Re-ranking
# ═══════════════════════════════════════════════════════════════════

def tokenize(text: str) -> Set[str]:
    """Tokenize text for Jaccard similarity.

    Produces lowercase alphanumeric tokens. Supports CJK characters:
    - Basic CJK Unified Ideographs: U+4E00-U+9FFF
    - Hiragana: U+3040-U+309F
    - Katakana: U+30A0-U+30FF
    """
    return set(re.findall(r'[a-z0-9_\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+', text.lower()))


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute Jaccard similarity between two token sets. Range [0, 1]."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def text_similarity(text_a: str, text_b: str) -> float:
    """Compute text similarity using Jaccard on tokens."""
    return jaccard_similarity(tokenize(text_a), tokenize(text_b))


def mmr_rerank(
    items: List[Dict[str, Any]],
    lambda_param: float = 0.7,
    score_key: str = "score",
    content_key: str = "content",
    max_results: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Re-rank items using Maximal Marginal Relevance (MMR).

    MMR = λ * relevance - (1-λ) * max_similarity_to_selected

    Balances relevance with diversity to avoid redundant results.

    Args:
        items: Items to re-rank (must have score and content fields)
        lambda_param: 0 = max diversity, 1 = max relevance (default 0.7)
        score_key: Key for relevance score
        content_key: Key for text content
        max_results: Maximum number of results to return

    Returns:
        Re-ranked items in MMR order
    """
    if len(items) <= 1:
        return list(items)

    lambda_param = max(0.0, min(1.0, lambda_param))

    # Pure relevance mode -- skip MMR overhead
    if lambda_param == 1.0:
        sorted_items = sorted(items, key=lambda x: x.get(score_key, 0), reverse=True)
        return sorted_items[:max_results] if max_results else sorted_items

    # Pre-tokenize all items once
    token_cache = {}  # type: Dict[int, Set[str]]
    for i, item in enumerate(items):
        token_cache[i] = tokenize(item.get(content_key, ""))

    # Normalize scores to [0, 1]
    scores = [item.get(score_key, 0) for item in items]
    max_score = max(scores) if scores else 0
    min_score = min(scores) if scores else 0
    score_range = max_score - min_score

    def normalize(score: float) -> float:
        if score_range == 0:
            return 1.0
        return (score - min_score) / score_range

    selected = []  # type: List[int]
    remaining = set(range(len(items)))
    limit = max_results or len(items)

    while remaining and len(selected) < limit:
        best_idx = -1
        best_mmr = float("-inf")

        for idx in remaining:
            norm_relevance = normalize(items[idx].get(score_key, 0))

            # Max similarity to already-selected items
            max_sim = 0.0
            for sel_idx in selected:
                sim = jaccard_similarity(token_cache[idx], token_cache[sel_idx])
                if sim > max_sim:
                    max_sim = sim

            mmr_score = lambda_param * norm_relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_mmr or (
                mmr_score == best_mmr
                and items[idx].get(score_key, 0) > items[best_idx].get(score_key, 0)
                if best_idx >= 0
                else True
            ):
                best_mmr = mmr_score
                best_idx = idx

        if best_idx >= 0:
            selected.append(best_idx)
            remaining.discard(best_idx)
        else:
            break

    return [items[i] for i in selected]


# ═══════════════════════════════════════════════════════════════════
# Search Pipeline
# ═══════════════════════════════════════════════════════════════════

def hybrid_search_pipeline(
    vector_results: List[Dict[str, Any]],
    keyword_results: List[Dict[str, Any]],
    vector_weight: float = 0.7,
    text_weight: float = 0.3,
    enable_decay: bool = True,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    enable_mmr: bool = True,
    mmr_lambda: float = 0.7,
    max_results: int = 10,
    id_key: str = "id",
    score_key: str = "score",
    content_key: str = "content",
    timestamp_key: str = "timestamp",
    evergreen_categories: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Complete hybrid search pipeline: merge -> decay -> MMR -> limit.

    This is the main entry point. Composes all three algorithms.

    Args:
        vector_results: Results from ChromaDB vector search
        keyword_results: Results from SQLite FTS5 search
        vector_weight: Weight for vector scores
        text_weight: Weight for BM25 scores
        enable_decay: Whether to apply temporal decay
        half_life_days: Half-life for temporal decay
        enable_mmr: Whether to apply MMR re-ranking
        mmr_lambda: MMR diversity parameter (0=diverse, 1=relevant)
        max_results: Maximum results to return

    Returns:
        Final ranked results
    """
    # Step 1: Merge vector and keyword results
    merged = merge_hybrid_results(
        vector_results, keyword_results,
        vector_weight=vector_weight,
        text_weight=text_weight,
        id_key=id_key,
        score_key=score_key,
        content_key=content_key,
    )

    # Step 2: Apply temporal decay
    if enable_decay:
        merged = apply_decay_to_results(
            merged,
            half_life_days=half_life_days,
            timestamp_key=timestamp_key,
            score_key=score_key,
            evergreen_categories=evergreen_categories,
        )
        # Re-sort after decay scores have changed
        merged.sort(key=lambda x: x.get(score_key, 0), reverse=True)

    # Step 3: MMR re-ranking for diversity
    if enable_mmr and len(merged) > 1:
        merged = mmr_rerank(
            merged,
            lambda_param=mmr_lambda,
            score_key=score_key,
            content_key=content_key,
            max_results=max_results,
        )

    return merged[:max_results]

"""Agent memory management — async, LLM-powered, three-layer architecture.

Three-layer model:
  Hot  (~500 tok): profile.json + last 2 task_history  → always injected
  Warm (~800 tok): ChromaDB semantic search top-3      → per-task RAG
  Cold           : full ChromaDB collection             → explicit recall only

Total context budget: ~1300 tokens (fixed, doesn't grow with memory).
"""
from __future__ import annotations

import logging
from typing import Optional
from models import AgentMemory, AgentMemoryItem, MemoryEntry
from database import save_memory_entry
from litellm import acompletion
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_SHORT_TERM = 20  # Maximum messages in short-term memory


async def add_to_memory(memory: AgentMemory, role: str, content: str) -> AgentMemory:
    """Add item to short-term memory. When overflow, LLM-summarize old items."""
    item = AgentMemoryItem(role=role, content=content)
    memory.short_term.append(item)

    if len(memory.short_term) > MAX_SHORT_TERM:
        old_items = memory.short_term[:5]
        summary = await _llm_summarize(old_items)
        if summary:
            memory.long_term_summary = (
                (memory.long_term_summary + "\n" + summary)
                if memory.long_term_summary else summary
            )
        memory.short_term = memory.short_term[5:]

    return memory


async def record_task_completion(
    memory: AgentMemory, agent_id: str, task_title: str, output: str
) -> AgentMemory:
    """Record completed task in memory + persistent ChromaDB store."""
    entry_text = f"{task_title}: {output[:200]}..." if len(output) > 200 else f"{task_title}: {output}"
    memory.task_history.append(entry_text)

    if len(memory.task_history) > 10:
        memory.task_history = memory.task_history[-10:]

    # Persist to ChromaDB vector store
    mem_entry = MemoryEntry(
        agent_id=agent_id,
        content=f"Completed task: {task_title}\nResult: {output[:500]}",
        category="task",
        importance=0.7,
    )
    await save_memory_entry(mem_entry)

    # Trigger profile update every 5 tasks
    if len(memory.task_history) % 5 == 0:
        try:
            from agents.memory_store import update_agent_profile, get_recent_from_store
            from database import get_agent
            recent = await get_recent_from_store(agent_id, limit=15)
            if recent:
                # Resolve agent's own model + api_key for the LLM call
                agent = await get_agent(agent_id)
                if agent:
                    from agents.worker import _resolve_model, _resolve_llm_kwargs
                    model = _resolve_model(agent.model)
                    llm_kwargs = _resolve_llm_kwargs(agent)
                    await update_agent_profile(agent_id, recent, model=model, llm_kwargs=llm_kwargs)
                else:
                    await update_agent_profile(agent_id, recent)
        except Exception as e:
            logger.warning(f"Profile update failed for {agent_id}: {e}")

    return memory


async def get_memory_context(
    memory: AgentMemory,
    agent_id: str = "",
    task_description: str = "",
) -> str:
    """Build three-layer memory context for prompt injection.

    Hot layer:  profile.json + last 2 task_history (~500 tokens)
    Warm layer: semantic search top-3 from ChromaDB (~800 tokens)

    Total budget: ~1300 tokens, fixed regardless of memory growth.
    """
    context_parts = []

    # ── Hot Layer: Agent Profile ──
    if agent_id:
        try:
            from agents.memory_store import load_agent_profile
            profile = load_agent_profile(agent_id)
            if profile:
                parts = []
                if profile.get("expertise"):
                    parts.append("Expertise: " + ", ".join(profile["expertise"]))
                if profile.get("preferences"):
                    parts.append("Preferences: " + ", ".join(profile["preferences"]))
                if profile.get("notable_facts"):
                    parts.append("Key facts: " + ", ".join(profile["notable_facts"]))
                if parts:
                    context_parts.append("Agent profile:\n" + "\n".join(parts))
        except Exception as e:
            logger.debug(f"Profile load skipped: {e}")

    # ── Hot Layer: Recent task_history (last 2) ──
    if memory.task_history:
        recent = memory.task_history[-2:]
        context_parts.append(
            "Recent tasks:\n" + "\n".join(f"- {t}" for t in recent)
        )

    # ── Warm Layer: Semantic search (only when we have a query) ──
    if agent_id and task_description:
        try:
            from agents.memory_store import search_memory_store
            results = await search_memory_store(agent_id, task_description, limit=3)
            if results:
                warm_parts = []
                for entry in results:
                    # Truncate each entry to ~250 chars to stay within budget
                    text = entry.content[:250]
                    if len(entry.content) > 250:
                        text += "..."
                    warm_parts.append(f"- [{entry.category}] {text}")
                context_parts.append(
                    "Relevant memories:\n" + "\n".join(warm_parts)
                )
        except Exception as e:
            logger.debug(f"Warm layer search skipped: {e}")

    # ── Fallback: long_term_summary if no profile available ──
    if not context_parts and memory.long_term_summary:
        context_parts.append(
            f"Previous experience summary:\n{memory.long_term_summary}"
        )

    return "\n\n".join(context_parts)


def get_short_term_messages(memory: AgentMemory) -> list:
    """Convert short-term memory to message format for LLM."""
    return [
        {"role": item.role, "content": item.content}
        for item in memory.short_term
    ]


async def _llm_summarize(items: list, model: str = "deepseek/deepseek-chat") -> str:
    """Use LLM to summarize old memory items."""
    text = "\n".join(f"[{it.role}]: {it.content}" for it in items)
    try:
        resp = await acompletion(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "Summarize the following conversation snippet in 2-3 concise sentences. "
                    "Preserve key facts, decisions, and outcomes. "
                    "Use the same language as the input."
                )},
                {"role": "user", "content": text},
            ],
            max_tokens=200,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarize failed: {e}, falling back to truncation")
        parts = [f"[{it.role}]: {it.content[:100]}" for it in items]
        return "Earlier context: " + " | ".join(parts)

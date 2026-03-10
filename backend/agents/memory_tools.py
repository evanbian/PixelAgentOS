"""Factory for LangChain memory tools bound to a specific agent."""
from __future__ import annotations
import asyncio
import threading
from datetime import datetime
from langchain_core.tools import tool
from database import save_memory_entry, search_memories
from models import MemoryEntry


def _run_async(coro, loop):
    """Run an async coroutine from a sync tool context.

    In production, worker.py calls tools via ``asyncio.to_thread`` so we
    are in a **worker thread** and can safely schedule the coroutine on
    the main event loop with ``run_coroutine_threadsafe``.

    In edge cases (tests, direct calls from the loop thread) we spin up
    a temporary event loop in a helper thread to avoid deadlocks.
    """
    if loop is not None and loop.is_running():
        # Check if we are on the same thread that owns the loop.
        # If yes → run_coroutine_threadsafe would deadlock, so use a
        # temporary loop in a helper thread.
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            # Same thread as the event loop — spawn a helper thread.
            result = [None]
            exc = [None]

            def _worker():
                try:
                    result[0] = asyncio.run(coro)
                except Exception as e:
                    exc[0] = e

            t = threading.Thread(target=_worker)
            t.start()
            t.join(timeout=10)
            if exc[0]:
                raise exc[0]
            return result[0]
        else:
            # Different thread — safe to schedule on the main loop.
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=10)
    else:
        # No running loop — just run directly.
        return asyncio.run(coro)


def create_memory_tools(agent_id: str, agent_name: str, loop=None):
    """Return [save_memory, recall_memory] LangChain tools."""
    _loop = loop

    @tool
    def save_memory(content: str, category: str = "general") -> str:
        """Save important information to your long-term memory for future recall.
        Use this to remember key facts, user preferences, decisions, or insights.

        Args:
            content: The information to remember
            category: Category — general | task | insight | preference
        Returns:
            Confirmation message
        """
        entry = MemoryEntry(
            agent_id=agent_id,
            content=content,
            category=category,
            importance=0.6,
        )
        _run_async(save_memory_entry(entry), _loop)
        preview = content[:50] + "..." if len(content) > 50 else content
        return f"Memory saved: '{preview}' [{category}]"

    @tool
    def recall_memory(query: str) -> str:
        """Search your long-term memory for relevant information.
        Use this to recall past experiences, user preferences, or task outcomes.

        Args:
            query: What to search for in your memory
        Returns:
            Relevant memories found
        """
        entries = _run_async(search_memories(agent_id, query, limit=5), _loop)

        if not entries:
            return "No relevant memories found."

        lines = []
        for e in entries:
            age = (datetime.utcnow() - e.created_at).days
            age_str = f"{age}d ago" if age > 0 else "today"
            lines.append(f"[{e.category}|{age_str}] {e.content}")
        return "\n---\n".join(lines)

    return [save_memory, recall_memory]

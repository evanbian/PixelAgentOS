"""Tests for memory.py — context building and short-term management."""
from __future__ import annotations
import pytest
from models import AgentMemory, AgentMemoryItem
from agents.memory import get_memory_context, get_short_term_messages


class TestGetMemoryContext:
    @pytest.mark.asyncio
    async def test_empty_memory(self):
        mem = AgentMemory()
        result = await get_memory_context(mem)
        assert result == ""

    @pytest.mark.asyncio
    async def test_long_term_summary_fallback(self):
        """When no profile/agent_id, falls back to long_term_summary."""
        mem = AgentMemory(long_term_summary="Agent learned about APIs")
        ctx = await get_memory_context(mem)
        assert "Previous experience summary" in ctx
        assert "APIs" in ctx

    @pytest.mark.asyncio
    async def test_task_history_only(self):
        mem = AgentMemory(task_history=["Built login page", "Fixed API bug"])
        ctx = await get_memory_context(mem)
        assert "Recent tasks" in ctx
        assert "Built login page" in ctx

    @pytest.mark.asyncio
    async def test_task_history_shows_last_2(self):
        """Three-layer model shows last 2 (hot layer), not last 3."""
        mem = AgentMemory(task_history=["t1", "t2", "t3", "t4", "t5"])
        ctx = await get_memory_context(mem)
        assert "t4" in ctx
        assert "t5" in ctx
        # t1, t2, t3 should NOT be in hot layer
        assert "t1" not in ctx
        assert "t2" not in ctx
        assert "t3" not in ctx

    @pytest.mark.asyncio
    async def test_both_sections(self):
        mem = AgentMemory(
            long_term_summary="Expert in React",
            task_history=["Built dashboard"],
        )
        ctx = await get_memory_context(mem)
        # With task_history present, long_term_summary is only fallback
        assert "Recent tasks" in ctx


class TestGetShortTermMessages:
    def test_empty(self):
        mem = AgentMemory()
        assert get_short_term_messages(mem) == []

    def test_converts_to_dicts(self):
        mem = AgentMemory(short_term=[
            AgentMemoryItem(role="user", content="hello"),
            AgentMemoryItem(role="assistant", content="hi"),
        ])
        msgs = get_short_term_messages(mem)
        assert len(msgs) == 2
        assert msgs[0] == {"role": "user", "content": "hello"}
        assert msgs[1] == {"role": "assistant", "content": "hi"}

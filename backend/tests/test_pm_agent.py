"""Tests for pm_agent.py — cycle detection, JSON parsing, agent matching."""
from __future__ import annotations
import pytest
from models import SubTask
from agents.pm_agent import PMAgent


class TestHasCycle:
    """Test the static cycle detection method."""

    def test_no_cycle_linear(self, make_subtask):
        st1 = make_subtask(subtask_id="a", depends_on=[])
        st2 = make_subtask(subtask_id="b", depends_on=["a"])
        st3 = make_subtask(subtask_id="c", depends_on=["b"])
        assert PMAgent._has_cycle([st1, st2, st3]) is False

    def test_no_cycle_parallel(self, make_subtask):
        st1 = make_subtask(subtask_id="a", depends_on=[])
        st2 = make_subtask(subtask_id="b", depends_on=[])
        st3 = make_subtask(subtask_id="c", depends_on=["a", "b"])
        assert PMAgent._has_cycle([st1, st2, st3]) is False

    def test_no_cycle_single(self, make_subtask):
        st1 = make_subtask(subtask_id="a", depends_on=[])
        assert PMAgent._has_cycle([st1]) is False

    def test_cycle_simple(self, make_subtask):
        st1 = make_subtask(subtask_id="a", depends_on=["b"])
        st2 = make_subtask(subtask_id="b", depends_on=["a"])
        assert PMAgent._has_cycle([st1, st2]) is True

    def test_cycle_triangle(self, make_subtask):
        st1 = make_subtask(subtask_id="a", depends_on=["c"])
        st2 = make_subtask(subtask_id="b", depends_on=["a"])
        st3 = make_subtask(subtask_id="c", depends_on=["b"])
        assert PMAgent._has_cycle([st1, st2, st3]) is True

    def test_self_cycle(self, make_subtask):
        st1 = make_subtask(subtask_id="a", depends_on=["a"])
        assert PMAgent._has_cycle([st1]) is True

    def test_empty_list(self):
        assert PMAgent._has_cycle([]) is False

    def test_diamond_no_cycle(self, make_subtask):
        """A → B, A → C, B → D, C → D — diamond shape, no cycle."""
        st_a = make_subtask(subtask_id="a", depends_on=[])
        st_b = make_subtask(subtask_id="b", depends_on=["a"])
        st_c = make_subtask(subtask_id="c", depends_on=["a"])
        st_d = make_subtask(subtask_id="d", depends_on=["b", "c"])
        assert PMAgent._has_cycle([st_a, st_b, st_c, st_d]) is False

    def test_partial_cycle(self, make_subtask):
        """A → B → C (ok), but D → E → D (cycle)."""
        st_a = make_subtask(subtask_id="a", depends_on=[])
        st_b = make_subtask(subtask_id="b", depends_on=["a"])
        st_c = make_subtask(subtask_id="c", depends_on=["b"])
        st_d = make_subtask(subtask_id="d", depends_on=["e"])
        st_e = make_subtask(subtask_id="e", depends_on=["d"])
        assert PMAgent._has_cycle([st_a, st_b, st_c, st_d, st_e]) is True

    def test_unknown_dep_ignored(self, make_subtask):
        """Dependencies referencing non-existent IDs should not cause cycles."""
        st1 = make_subtask(subtask_id="a", depends_on=["unknown_id"])
        st2 = make_subtask(subtask_id="b", depends_on=["a"])
        assert PMAgent._has_cycle([st1, st2]) is False


class TestPMAgentInit:
    def test_model_prefixing(self):
        pm = PMAgent(model="gpt-4o", api_key="key123")
        assert pm.model == "openai/gpt-4o"

    def test_model_with_provider(self):
        pm = PMAgent(model="deepseek/deepseek-chat", api_key="key123")
        assert pm.model == "deepseek/deepseek-chat"

    def test_api_key_parsing_simple(self):
        pm = PMAgent(model="gpt-4", api_key="sk-test123")
        assert pm.extra_kwargs == {"api_key": "sk-test123"}

    def test_api_key_parsing_with_base(self):
        pm = PMAgent(model="gpt-4", api_key="sk-test|||https://api.example.com")
        assert pm.extra_kwargs["api_key"] == "sk-test"
        assert pm.extra_kwargs["api_base"] == "https://api.example.com"

    def test_empty_api_key(self):
        pm = PMAgent(model="gpt-4", api_key="")
        assert pm.extra_kwargs == {}

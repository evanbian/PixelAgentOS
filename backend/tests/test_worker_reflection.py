"""Tests for worker.py adaptive reflection mechanism."""
from __future__ import annotations
import pytest
from agents.worker import (
    _LoopMetrics,
    _detect_task_complexity,
    _should_reflect,
    _build_reflection_prompt,
)


# ── _detect_task_complexity ─────────────────────────────────────────────────

class TestDetectTaskComplexity:
    def test_simple_task(self):
        assert _detect_task_complexity("Write hello world") == "simple"

    def test_simple_short_task(self):
        assert _detect_task_complexity("Fix the bug") == "simple"

    def test_complex_english(self):
        desc = "Research and analyze comprehensive market data, compare all options"
        assert _detect_task_complexity(desc) == "complex"

    def test_complex_chinese(self):
        assert _detect_task_complexity("研究并分析市场数据") == "complex"

    def test_complex_by_length(self):
        # Long task with one keyword → score 2 (keyword + length)
        desc = "analyze " + "x " * 300
        assert _detect_task_complexity(desc) == "complex"

    def test_single_keyword_is_simple(self):
        assert _detect_task_complexity("analyze this") == "simple"

    def test_empty_string(self):
        assert _detect_task_complexity("") == "simple"

    def test_case_insensitive(self):
        assert _detect_task_complexity("RESEARCH AND COMPARE options") == "complex"


# ── _should_reflect ─────────────────────────────────────────────────────────

class TestShouldReflect:
    def test_no_trigger_on_zero_calls(self):
        m = _LoopMetrics(tool_call_count=0)
        assert _should_reflect(m, "simple", 0, 15) is None

    def test_no_trigger_on_last_iteration(self):
        m = _LoopMetrics(tool_call_count=5)
        assert _should_reflect(m, "simple", 14, 15) is None

    def test_no_trigger_early(self):
        m = _LoopMetrics(tool_call_count=2)
        assert _should_reflect(m, "simple", 1, 15) is None

    # Periodic trigger (simple period=8, complex period=6)
    def test_periodic_simple_at_8(self):
        m = _LoopMetrics(tool_call_count=8)
        result = _should_reflect(m, "simple", 6, 15)
        assert result is not None
        assert "Periodic" in result

    def test_periodic_simple_no_trigger_at_5(self):
        m = _LoopMetrics(tool_call_count=5)
        assert _should_reflect(m, "simple", 3, 15) is None

    def test_periodic_complex_at_6(self):
        m = _LoopMetrics(tool_call_count=6)
        result = _should_reflect(m, "complex", 4, 15)
        assert result is not None
        assert "Periodic" in result

    def test_periodic_complex_at_12(self):
        m = _LoopMetrics(tool_call_count=12)
        result = _should_reflect(m, "complex", 10, 15)
        assert result is not None

    def test_no_periodic_at_4_complex(self):
        m = _LoopMetrics(tool_call_count=4)
        assert _should_reflect(m, "complex", 3, 15) is None

    # Consecutive errors
    def test_consecutive_errors_trigger(self):
        m = _LoopMetrics(tool_call_count=2, consecutive_errors=2)
        result = _should_reflect(m, "simple", 1, 15)
        assert result is not None
        assert "consecutive" in result.lower()

    def test_consecutive_errors_3_trigger(self):
        m = _LoopMetrics(tool_call_count=4, consecutive_errors=3)
        result = _should_reflect(m, "simple", 3, 15)
        assert result is not None

    def test_one_error_no_trigger(self):
        m = _LoopMetrics(tool_call_count=2, consecutive_errors=1)
        assert _should_reflect(m, "simple", 1, 15) is None

    # Low progress
    def test_low_progress_trigger(self):
        m = _LoopMetrics(
            tool_call_count=3,
            recent_result_lens=[10, 20, 15],
        )
        result = _should_reflect(m, "simple", 2, 15)
        assert result is not None
        assert "Low output" in result

    def test_adequate_progress_no_trigger(self):
        m = _LoopMetrics(
            tool_call_count=3,
            recent_result_lens=[50, 60, 100],
        )
        assert _should_reflect(m, "simple", 2, 15) is None

    def test_low_progress_needs_3_results(self):
        m = _LoopMetrics(
            tool_call_count=2,
            recent_result_lens=[10, 20],
        )
        assert _should_reflect(m, "simple", 1, 15) is None

    # Priority: periodic fires before error check
    def test_periodic_takes_precedence(self):
        m = _LoopMetrics(
            tool_call_count=8,
            consecutive_errors=2,
        )
        result = _should_reflect(m, "simple", 6, 15)
        assert "Periodic" in result


# ── _build_reflection_prompt ────────────────────────────────────────────────

class TestBuildReflectionPrompt:
    def test_contains_checkpoint_header(self):
        m = _LoopMetrics(tool_call_count=5, recent_tools=["a", "b", "c"])
        prompt = _build_reflection_prompt(m, "Test reason", 4, 15)
        assert "[Reflection Checkpoint" in prompt
        assert "iteration 5/15" in prompt

    def test_contains_tool_count(self):
        m = _LoopMetrics(tool_call_count=7)
        prompt = _build_reflection_prompt(m, "reason", 6, 15)
        assert "7 tool calls" in prompt

    def test_contains_recent_tools(self):
        m = _LoopMetrics(
            tool_call_count=3,
            recent_tools=["web_search", "code_execute", "analyze_data"],
        )
        prompt = _build_reflection_prompt(m, "reason", 2, 10)
        assert "web_search, code_execute, analyze_data" in prompt

    def test_empty_recent_tools(self):
        m = _LoopMetrics(tool_call_count=1)
        prompt = _build_reflection_prompt(m, "reason", 0, 10)
        assert "none" in prompt

    def test_contains_trigger_reason(self):
        m = _LoopMetrics(tool_call_count=5)
        prompt = _build_reflection_prompt(m, "Custom trigger reason", 4, 15)
        assert "Custom trigger reason" in prompt

    def test_contains_reflection_questions(self):
        m = _LoopMetrics(tool_call_count=3)
        prompt = _build_reflection_prompt(m, "reason", 2, 10)
        assert "Am I making progress" in prompt
        assert "change my approach" in prompt
        assert "final answer" in prompt

    def test_prompt_length_under_800_chars(self):
        m = _LoopMetrics(
            tool_call_count=99,
            recent_tools=["very_long_tool_name_here"] * 5,
        )
        prompt = _build_reflection_prompt(
            m, "A somewhat verbose trigger reason for testing", 50, 100,
        )
        assert len(prompt) < 800


# ── _LoopMetrics ────────────────────────────────────────────────────────────

class TestLoopMetrics:
    def test_defaults(self):
        m = _LoopMetrics()
        assert m.tool_call_count == 0
        assert m.consecutive_errors == 0
        assert m.recent_tools == []
        assert m.recent_result_lens == []
        assert m.reflection_count == 0

    def test_mutable_defaults_are_independent(self):
        m1 = _LoopMetrics()
        m2 = _LoopMetrics()
        m1.recent_tools.append("x")
        assert m2.recent_tools == []

    def test_field_updates(self):
        m = _LoopMetrics()
        m.tool_call_count += 1
        m.consecutive_errors = 3
        m.reflection_count = 2
        assert m.tool_call_count == 1
        assert m.consecutive_errors == 3
        assert m.reflection_count == 2

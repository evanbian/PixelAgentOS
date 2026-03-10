"""Tests for worker.py utility functions — model resolution, scratchpad arg parser."""
from __future__ import annotations
import pytest
from agents.worker import _resolve_model, _ScratchpadArgParser


class TestResolveModel:
    def test_bare_model_gets_openai_prefix(self):
        assert _resolve_model("gpt-4o") == "openai/gpt-4o"

    def test_provider_model_unchanged(self):
        assert _resolve_model("deepseek/deepseek-chat") == "deepseek/deepseek-chat"

    def test_anthropic_provider(self):
        assert _resolve_model("anthropic/claude-3") == "anthropic/claude-3"


class TestScratchpadArgParser:
    def test_extracts_content_value(self):
        parser = _ScratchpadArgParser()
        result = parser.feed('{"key":"test","content":"hello world"}')
        assert "hello world" in result

    def test_handles_chunked_input(self):
        parser = _ScratchpadArgParser()
        out = ""
        out += parser.feed('{"key":"te')
        out += parser.feed('st","content":"he')
        out += parser.feed('llo wor')
        out += parser.feed('ld"}')
        assert "hello world" in out

    def test_handles_escaped_chars(self):
        parser = _ScratchpadArgParser()
        result = parser.feed('{"content":"line1\\nline2"}')
        assert "line1\nline2" in result

    def test_handles_escaped_quotes(self):
        parser = _ScratchpadArgParser()
        result = parser.feed('{"content":"say \\"hello\\""}')
        assert 'say "hello"' in result

    def test_no_content_key(self):
        parser = _ScratchpadArgParser()
        result = parser.feed('{"key":"test","value":"data"}')
        assert result == ""

    def test_empty_content(self):
        parser = _ScratchpadArgParser()
        result = parser.feed('{"content":""}')
        assert result == ""

    def test_content_with_spaces_in_key(self):
        parser = _ScratchpadArgParser()
        result = parser.feed('{"content": "spaced"}')
        assert "spaced" in result

    def test_done_state_ignores_further_input(self):
        parser = _ScratchpadArgParser()
        parser.feed('{"content":"done"}')
        result = parser.feed("more stuff")
        assert result == ""

"""Tests for models.py — model creation and validation."""
from __future__ import annotations
import pytest
from models import Agent, Task, SubTask, AgentMemory, ScratchpadEntryModel


class TestAgentModel:
    def test_default_status(self):
        a = Agent(name="Test", role="Developer", workstation_id="ws-1")
        assert a.status == "idle"

    def test_default_memory(self):
        a = Agent(name="Test", role="Developer", workstation_id="ws-1")
        assert isinstance(a.memory, AgentMemory)
        assert a.memory.short_term == []
        assert a.memory.long_term_summary == ""

    def test_auto_generates_id(self):
        a1 = Agent(name="A", role="Developer", workstation_id="ws-1")
        a2 = Agent(name="B", role="Developer", workstation_id="ws-1")
        assert a1.id != a2.id


class TestSubTaskModel:
    def test_default_status(self):
        st = SubTask(title="Test")
        assert st.status == "todo"

    def test_default_depends_on(self):
        st = SubTask(title="Test")
        assert st.depends_on == []

    def test_with_dependencies(self):
        st = SubTask(title="Test", depends_on=["st-1", "st-2"])
        assert len(st.depends_on) == 2


class TestTaskModel:
    def test_default_status(self):
        t = Task(title="Test", description="desc")
        assert t.status == "todo"

    def test_default_subtasks(self):
        t = Task(title="Test", description="desc")
        assert t.subtasks == []

    def test_default_scratchpad(self):
        t = Task(title="Test", description="desc")
        assert t.scratchpad == []


class TestScratchpadEntryModel:
    def test_creation(self):
        entry = ScratchpadEntryModel(
            key="findings",
            content="some data",
            author_id="a1",
            author_name="Alice",
        )
        assert entry.key == "findings"
        assert entry.content == "some data"

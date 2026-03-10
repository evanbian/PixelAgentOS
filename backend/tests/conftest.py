"""Shared fixtures for PixelAgentOS backend tests."""
from __future__ import annotations
import sys
import os

# Ensure backend root is on sys.path so `from agents.xxx` works
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from models import Agent, AgentMemory, Task, SubTask


@pytest.fixture
def make_agent():
    """Factory fixture to create Agent instances with sensible defaults."""
    def _make(
        name: str = "TestAgent",
        role: str = "Developer",
        agent_id: str = "agent-001",
        skills: list = None,
        model: str = "openai/gpt-4",
        api_key: str = "test-key",
        workstation_id: str = "ws-1",
    ) -> Agent:
        return Agent(
            id=agent_id,
            name=name,
            role=role,
            skills=skills or ["web-search"],
            model=model,
            api_key=api_key,
            workstation_id=workstation_id,
            memory=AgentMemory(),
        )
    return _make


@pytest.fixture
def make_task():
    """Factory fixture to create Task instances."""
    def _make(
        title: str = "Test Task",
        description: str = "A test task description",
        task_id: str = "task-001",
        assigned_to: list = None,
    ) -> Task:
        return Task(
            id=task_id,
            title=title,
            description=description,
            assigned_to=assigned_to or [],
        )
    return _make


@pytest.fixture
def make_subtask():
    """Factory fixture to create SubTask instances."""
    def _make(
        title: str = "Sub",
        subtask_id: str = "st-001",
        assigned_to: str = "agent-001",
        depends_on: list = None,
        status: str = "todo",
    ) -> SubTask:
        return SubTask(
            id=subtask_id,
            title=title,
            assigned_to=assigned_to,
            depends_on=depends_on or [],
            status=status,
        )
    return _make

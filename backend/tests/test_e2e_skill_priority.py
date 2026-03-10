"""E2E tests: Skill priority model — agent autonomous decision-making.

Principle: NEVER mention skills, tools, or implementation hints in task descriptions.
Give natural requirements only. Verify the agent autonomously chooses the correct
tool chain (read_skill → shell_execute vs find_skill vs code_execute).

Requirements:
  - Backend running on localhost:8000
  - Evan_Dev has personal skills: web-asset-generator, image-processing
  - Evan_Researcher has no skills (empty list)

Run:
  cd backend && source .venv/bin/activate
  pytest tests/test_e2e_skill_priority.py -v -s --timeout=600
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Optional

import pytest
import requests

BASE = os.environ.get("PIXELAGENT_BASE_URL", "http://localhost:8000")
API = f"{BASE}/api"

EVAN_DEV_ID = "ddcb214e-cc21-4308-853e-c5773cd506cb"
EVAN_RESEARCHER_ID = "729e1109-c901-41ed-bf79-c845fda7b725"

POLL_INTERVAL = 5
TASK_TIMEOUT = 1200  # 20 min — PM pipeline decomposes tasks into subtasks


# ── Helpers ────────────────────────────────────────────────────────────────

def _require_backend():
    try:
        r = requests.get(f"{API}/agents", timeout=5)
        r.raise_for_status()
    except Exception:
        pytest.skip("Backend not running on localhost:8000")


def _create_task(title: str, description: str, assigned_to: list) -> str:
    r = requests.post(f"{API}/tasks", json={
        "title": title,
        "description": description,
        "assigned_to": assigned_to,
    })
    r.raise_for_status()
    return r.json()["id"]


def _execute_task(task_id: str):
    r = requests.post(f"{API}/tasks/{task_id}/execute")
    r.raise_for_status()


def _poll_task(task_id: str, timeout: int = TASK_TIMEOUT) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{API}/tasks/{task_id}")
        r.raise_for_status()
        task = r.json()
        if task["status"] in ("done", "cancelled"):
            return task
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Task {task_id} did not finish within {timeout}s")


def _get_metrics(task_id: str) -> Optional[dict]:
    r = requests.get(f"{API}/tasks/{task_id}/metrics")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _cleanup_task(task_id: str):
    requests.delete(f"{API}/tasks/{task_id}")
    ws = os.path.join(os.path.dirname(__file__), "..", "workspaces", task_id)
    if os.path.isdir(ws):
        shutil.rmtree(ws, ignore_errors=True)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def check_backend():
    _require_backend()


# ── E2E: Evan_Dev (has personal skills) ────────────────────────────────────

class TestDevAutonomousSkillUsage:
    """Give Evan_Dev natural tasks that overlap with his personal skills.
    Verify he autonomously discovers and executes skill scripts."""

    task_id: Optional[str] = None

    def teardown_method(self):
        if self.task_id:
            _cleanup_task(self.task_id)
            self.task_id = None

    def test_favicon_generation(self):
        """Natural request: 'make me a favicon'. No skill name mentioned."""
        self.task_id = _create_task(
            title="[TEST] 生成网站图标",
            description="帮我生成一套网站 favicon，用火箭 emoji 🚀 作为图标。",
            assigned_to=[EVAN_DEV_ID],
        )
        _execute_task(self.task_id)
        task = _poll_task(self.task_id)
        metrics = _get_metrics(self.task_id)

        assert task["status"] == "done", f"Task failed: {task.get('output', '')}"
        assert metrics is not None, "No metrics recorded"

        dist = metrics["tool_call_distribution"]
        print(f"\n  Tool distribution: {dist}")

        # Agent should autonomously: read_skill → shell_execute
        assert dist.get("read_skill", 0) >= 1, (
            f"Agent did not call read_skill. dist={dist}"
        )
        assert dist.get("shell_execute", 0) >= 1, (
            f"Agent did not call shell_execute. dist={dist}"
        )

    def test_image_resize(self):
        """Natural request: 'resize an image'. Overlaps with image-processing skill."""
        self.task_id = _create_task(
            title="[TEST] 缩放图片",
            description=(
                "我有一张 512x512 的 PNG 图片，请帮我生成 64x64 和 128x128 两个缩略图版本。"
                "先用代码创建一张 512x512 的纯色测试图片，再缩放。"
            ),
            assigned_to=[EVAN_DEV_ID],
        )
        _execute_task(self.task_id)
        task = _poll_task(self.task_id)
        metrics = _get_metrics(self.task_id)

        assert task["status"] == "done"
        assert metrics is not None

        dist = metrics["tool_call_distribution"]
        print(f"\n  Tool distribution: {dist}")

        # Should have at least consulted the image-processing skill
        assert dist.get("read_skill", 0) >= 1, (
            f"Agent did not consult any skill for image task. dist={dist}"
        )


# ── E2E: Evan_Researcher (no skills) ──────────────────────────────────────

class TestResearcherEcosystemSearch:
    """Give Evan_Researcher a specialized task he has no tools for.
    Verify he searches the skill ecosystem instead of blindly coding."""

    task_id: Optional[str] = None

    def teardown_method(self):
        if self.task_id:
            _cleanup_task(self.task_id)
            self.task_id = None

    def test_seo_analysis(self):
        """SEO analysis — no built-in tool covers this domain."""
        self.task_id = _create_task(
            title="[TEST] SEO 分析",
            description=(
                "分析 https://example.com 的 SEO 状况：检查 meta tags、"
                "标题结构、关键词密度，输出简要报告。"
            ),
            assigned_to=[EVAN_RESEARCHER_ID],
        )
        _execute_task(self.task_id)
        task = _poll_task(self.task_id)
        metrics = _get_metrics(self.task_id)

        assert metrics is not None

        dist = metrics["tool_call_distribution"]
        print(f"\n  Tool distribution: {dist}")

        find_calls = dist.get("find_skill", 0)
        code_errors = dist.get("code_execute", 0)

        # Ideal: find_skill >= 1 (searched ecosystem)
        # Acceptable: used web_search to gather info
        # Bad: hammered code_execute with no web_search and no find_skill
        if find_calls >= 1:
            print("  ✅ find_skill triggered — ecosystem search working")
        elif dist.get("web_search", 0) >= 1:
            print(f"  ⚠️  find_skill=0 but web_search used — acceptable fallback")
        else:
            pytest.fail(
                f"Agent used neither find_skill nor web_search. "
                f"Likely stuck in code_execute loop. dist={dist}"
            )


# ── Unit: infrastructure correctness ───────────────────────────────────────

class TestSystemPromptBranching:
    """Verify prompt structure varies based on skill availability."""

    def test_dev_gets_three_layer_prompt(self):
        from models import Agent, AgentMemory
        from agents.worker import _build_system_prompt

        agent = Agent(
            id=EVAN_DEV_ID, name="Dev", role="Developer",
            skills=["web-asset-generator", "image-processing", "frontend-slides"],
            workstation_id="ws-1", memory=AgentMemory(),
        )
        prompt = _build_system_prompt(agent, "")

        assert "Layer 1: CHECK YOUR INSTALLED SKILLS" in prompt
        assert "ABSOLUTE paths" in prompt
        assert "Do NOT search your workspace" in prompt
        assert "Layer 2: SEARCH THE SKILL ECOSYSTEM" in prompt
        assert "Layer 3: USE BUILT-IN TOOLS (LAST RESORT)" in prompt

    def test_researcher_gets_two_layer_prompt(self):
        from models import Agent, AgentMemory
        from agents.worker import _build_system_prompt

        agent = Agent(
            id=EVAN_RESEARCHER_ID, name="Researcher", role="Researcher",
            skills=[], workstation_id="ws-2", memory=AgentMemory(),
        )
        prompt = _build_system_prompt(agent, "")

        assert "CHECK YOUR INSTALLED SKILLS" not in prompt
        assert "Layer 1: SEARCH THE SKILL ECOSYSTEM" in prompt
        assert "Layer 2: USE BUILT-IN TOOLS (LAST RESORT)" in prompt

    def test_read_skill_returns_absolute_paths(self):
        from agents.tools import read_skill, _agent_id_var
        import re

        _agent_id_var.set(EVAN_DEV_ID)
        result = read_skill.invoke({"skill_name": "web-asset-generator"})

        assert "generate_favicons.py" in result
        bare = re.findall(r'(?<![/\w])scripts/', result)
        assert len(bare) == 0, f"Found unresolved scripts/ references: {len(bare)}"

    def test_shell_execute_uses_venv_python(self):
        from agents.tools import shell_execute, _workspace_var
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            _workspace_var.set(tmp)
            result = shell_execute.invoke({
                "command": 'python -c "import PIL; print(PIL.__version__)"',
            })
            _workspace_var.set(None)

        assert "Error" not in result, f"venv Python missing Pillow: {result}"


class TestSkillRegistryCleanup:
    """Verify shared skill cleanup is complete."""

    def test_zero_shared_skills(self):
        from agents.skill_registry import list_skills
        assert len(list_skills()) == 0

    def test_all_role_defaults_empty(self):
        from agents.skill_registry import get_default_skills_for_role, get_all_role_ids
        for role_id in get_all_role_ids():
            assert get_default_skills_for_role(role_id) == []

    def test_migration_json_empty(self):
        import json
        path = os.path.join(os.path.dirname(__file__), "..", "skills", "_migration.json")
        with open(path) as f:
            assert json.load(f) == {}

    def test_validator_allows_personal_skills(self):
        from models import AgentCreate
        agent = AgentCreate(
            name="T", role="Developer",
            skills=["web-asset-generator", "some-new-skill"],
            workstation_id="ws",
        )
        assert "web-asset-generator" in agent.skills
        assert "some-new-skill" in agent.skills

    def test_validator_deduplicates(self):
        from models import AgentCreate
        agent = AgentCreate(
            name="T", role="Developer",
            skills=["web-asset-generator", "web-asset-generator"],
            workstation_id="ws",
        )
        assert agent.skills == ["web-asset-generator"]

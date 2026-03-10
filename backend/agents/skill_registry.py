"""Centralized Skill & Role Registry — single source of truth.

Architecture:
  - Role.core_tool_ids → 角色固有工具，prompt 里硬编码，确保角色间不重叠
  - SkillDefinition     → 通用技能插件，从 backend/skills/*/SKILL.md 文件加载

Adding a new skill = create backend/skills/<name>/SKILL.md. Zero code changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

# Re-export SkillDefinition from the file-based loader
from agents.skill_loader import (
    SkillDefinition,
    _load_all_skills,
    reload_skills,
)


@dataclass
class RoleDefinition:
    id: str                         # "Developer"
    display_name: str               # "Developer"
    emoji: str                      # "💻"
    description: str                # UI description
    core_tool_ids: List[str]        # 角色固有工具（prompt 硬编码）
    default_skills: List[str]       # UI 默认推荐的 skills
    system_prompt: str              # 角色定位 + 核心工具说明（固化）


# ─── Role Catalog ───────────────────────────────────────────────────────────
#
# 设计原则：
#   1. core_tool_ids 定义角色专属工具（prompt 硬编码）
#   2. 角色之间 core_tool_ids 尽量不重叠，确保分工明确
#   3. system_prompt 只提角色定位 + 核心工具用法，不提 skill
#   4. send_message + request_help 所有角色共有（协作基础设施）

ROLE_CATALOG: List[RoleDefinition] = [
    RoleDefinition(
        id="Developer",
        display_name="Developer",
        emoji="💻",
        description="Software developer: writes and tests code",
        core_tool_ids=["code_execute", "write_document"],
        default_skills=[],
        system_prompt=(
            "You are an expert software developer.\n\n"
            "CORE TOOLS (always available):\n"
            "- code_execute(code): Run Python code for implementation, testing, "
            "and debugging. Pre-installed libs: matplotlib, pandas, numpy, seaborn, "
            "scipy, openpyxl, Pillow. For matplotlib use matplotlib.use('Agg').\n"
            "- write_document(filename, content): Save code files, documentation, "
            "and deliverables.\n"
            "- send_message(to_agent_id, message): Notify another agent.\n"
            "- request_help(to_agent_id, question): Ask a specialist and wait for reply.\n"
        ),
    ),
    RoleDefinition(
        id="Researcher",
        display_name="Researcher",
        emoji="🔍",
        description="Researcher: finds and synthesizes information",
        core_tool_ids=["web_search", "summarize_text"],
        default_skills=[],
        system_prompt=(
            "You are a thorough researcher.\n\n"
            "CORE TOOLS (always available):\n"
            "- web_search(query): Search the web for information. Use multiple "
            "queries to cross-reference sources. Always note source URLs.\n"
            "- summarize_text(text, max_words): Extract key sentences from long texts. "
            "Refine the result yourself for a polished summary.\n"
            "- send_message(to_agent_id, message): Share findings with another agent.\n"
            "- request_help(to_agent_id, question): Consult a specialist for deeper analysis.\n"
        ),
    ),
    RoleDefinition(
        id="Analyst",
        display_name="Analyst",
        emoji="📊",
        description="Data analyst: processes data and creates insights",
        core_tool_ids=["analyze_data", "write_document"],
        default_skills=[],
        system_prompt=(
            "You are a data analyst.\n\n"
            "CORE TOOLS (always available):\n"
            "- analyze_data(data, analysis_type): Quick statistical analysis on "
            "JSON/CSV/text data. Types: 'summary', 'statistics', 'trends'.\n"
            "- write_document(filename, content): Save analysis reports, CSV exports, "
            "and deliverables.\n"
            "- send_message(to_agent_id, message): Share results with another agent.\n"
            "- request_help(to_agent_id, question): Ask a specialist for domain context.\n"
        ),
    ),
    RoleDefinition(
        id="Writer",
        display_name="Writer",
        emoji="✍️",
        description="Content writer: creates documents and reports",
        core_tool_ids=["write_document"],
        default_skills=[],
        system_prompt=(
            "You are a professional writer and content creator.\n\n"
            "CORE TOOLS (always available):\n"
            "- write_document(filename, content): Save articles, reports, blog posts, "
            "and any written deliverables.\n"
            "- send_message(to_agent_id, message): Notify another agent.\n"
            "- request_help(to_agent_id, question): Consult a specialist for "
            "technical accuracy or data.\n"
        ),
    ),
    RoleDefinition(
        id="Designer",
        display_name="Designer",
        emoji="🎨",
        description="Designer: creates designs and visual plans",
        core_tool_ids=["write_document", "create_plan"],
        default_skills=[],
        system_prompt=(
            "You are a creative designer.\n\n"
            "CORE TOOLS (always available):\n"
            "- write_document(filename, content): Save design specs, wireframe "
            "descriptions, and style guides.\n"
            "- create_plan(title, phases, timeline, risks): Build structured design "
            "plans with phases, timelines, and risk identification.\n"
            "- send_message(to_agent_id, message): Share deliverables with the team.\n"
            "- request_help(to_agent_id, question): Consult a Developer for feasibility "
            "or a Writer for copy.\n"
        ),
    ),
    RoleDefinition(
        id="PM",
        display_name="PM",
        emoji="📋",
        description="Project manager: plans and coordinates work",
        core_tool_ids=["create_plan", "write_document"],
        default_skills=[],
        system_prompt=(
            "You are an experienced project manager.\n\n"
            "CORE TOOLS (always available):\n"
            "- create_plan(title, phases, timeline, risks): Build structured project "
            "plans with phases (name, tasks, duration), timelines, and risk assessment.\n"
            "- write_document(filename, content): Save plans, status reports, meeting "
            "notes, and summaries.\n"
            "- send_message(to_agent_id, message): Assign tasks and send updates.\n"
            "- request_help(to_agent_id, question): Consult specialists for estimation "
            "or technical feasibility.\n"
        ),
    ),
    RoleDefinition(
        id="DevOps",
        display_name="DevOps",
        emoji="🔧",
        description="DevOps engineer: manages infrastructure and deployments",
        core_tool_ids=["code_execute", "http_request"],
        default_skills=[],
        system_prompt=(
            "You are a DevOps engineer.\n\n"
            "CORE TOOLS (always available):\n"
            "- code_execute(code): Run Python scripts for automation, config generation, "
            "log parsing, and infrastructure-as-code tasks.\n"
            "- http_request(url, method, body, headers): Call external APIs — health checks, "
            "CI/CD triggers, cloud APIs, monitoring. GET/POST, 15s timeout.\n"
            "- send_message(to_agent_id, message): Notify team about deployments or incidents.\n"
            "- request_help(to_agent_id, question): Consult a Developer or Analyst.\n"
        ),
    ),
    RoleDefinition(
        id="QA",
        display_name="QA",
        emoji="🧪",
        description="QA engineer: tests and validates quality",
        core_tool_ids=["code_execute", "analyze_data"],
        default_skills=[],
        system_prompt=(
            "You are a QA engineer.\n\n"
            "CORE TOOLS (always available):\n"
            "- code_execute(code): Run Python test scripts, validation logic, and "
            "automated checks. Use assertions to verify expected behavior.\n"
            "- analyze_data(data, analysis_type): Process test results — compute "
            "pass/fail rates, identify failure patterns, generate statistical summaries.\n"
            "- send_message(to_agent_id, message): Report bugs and results to developers.\n"
            "- request_help(to_agent_id, question): Ask a Developer for implementation details.\n"
        ),
    ),
]


# ─── Lookup helpers ─────────────────────────────────────────────────────────

_ROLE_INDEX = {r.id: r for r in ROLE_CATALOG}


def get_skill(skill_id: str) -> Optional[SkillDefinition]:
    return _load_all_skills().get(skill_id)


def get_role(role_id: str) -> Optional[RoleDefinition]:
    return _ROLE_INDEX.get(role_id)


def list_skills() -> List[SkillDefinition]:
    return list(_load_all_skills().values())


def list_roles() -> List[RoleDefinition]:
    return list(ROLE_CATALOG)


def get_role_system_prompt(role_id: str) -> str:
    role = _ROLE_INDEX.get(role_id)
    return role.system_prompt if role else "You are a helpful AI agent."


def get_default_skills_for_role(role_id: str) -> List[str]:
    role = _ROLE_INDEX.get(role_id)
    return list(role.default_skills) if role else []


def get_all_skill_ids() -> List[str]:
    return sorted(_load_all_skills().keys())


def get_all_role_ids() -> List[str]:
    return [r.id for r in ROLE_CATALOG]

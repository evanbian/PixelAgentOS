"""File-system skill loader aligned with Anthropic Agent Skills open standard.

Architecture:
  - Each skill lives in its own directory under backend/skills/
  - Directory name = skill id (kebab-case, 1-64 chars)
  - SKILL.md has YAML frontmatter (---...---) + Markdown body
  - Frontmatter: name (required, must match dir), description (required)
  - Body: detailed usage guide (read_skill returns this)

Standard: https://agentskills.io
Adding a new skill = create backend/skills/<name>/SKILL.md. Zero code changes.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
_MIGRATION_PATH = os.path.join(SKILLS_DIR, "_migration.json")


@dataclass
class SkillDefinition:
    id: str              # directory name = kebab-case name
    name: str            # frontmatter "name" (must match id)
    description: str     # one-line description
    content: str = ""    # full markdown body below ---
    base_dir: str = ""   # absolute path to skill directory (for script resolution)


def _parse_skill_md(skill_id: str, filepath: str) -> Optional[SkillDefinition]:
    """Parse SKILL.md: YAML frontmatter + markdown body (standard format)."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        logger.warning("Cannot read %s: %s", filepath, e)
        return None

    # Split on --- to extract frontmatter and body
    parts = raw.split("---", 2)
    if len(parts) < 3:
        logger.warning("Invalid SKILL.md format (no frontmatter) in %s", filepath)
        return None

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        logger.warning("YAML parse error in %s: %s", filepath, e)
        return None

    if not isinstance(meta, dict):
        logger.warning("Frontmatter is not a dict in %s", filepath)
        return None

    body = parts[2].strip()

    name = meta.get("name", skill_id)
    description = meta.get("description", "")

    if name != skill_id:
        logger.warning(
            "Skill name '%s' does not match directory '%s' in %s",
            name, skill_id, filepath,
        )

    # Resolve symlinks to get the real directory containing scripts
    real_filepath = os.path.realpath(filepath)
    base_dir = os.path.dirname(real_filepath)

    return SkillDefinition(
        id=skill_id,
        name=name,
        description=description,
        content=body,
        base_dir=base_dir,
    )


def build_script_listing(skill: SkillDefinition) -> str:
    """Scan a skill's scripts/ directory and return a clear listing of
    all executable scripts with absolute paths.

    Returns empty string if no scripts/ directory exists.
    """
    if not skill.base_dir:
        return ""
    scripts_dir = os.path.join(skill.base_dir, "scripts")
    if not os.path.isdir(scripts_dir):
        return ""

    entries = []
    for root, _dirs, files in os.walk(scripts_dir):
        for fname in sorted(files):
            # Skip hidden files, __pycache__, etc.
            if fname.startswith(".") or fname.startswith("__"):
                continue
            fpath = os.path.join(root, fname)
            try:
                size = os.path.getsize(fpath)
            except OSError:
                size = 0
            # Human-readable size
            if size < 1024:
                size_str = f"{size}B"
            else:
                size_str = f"{size / 1024:.1f}KB"
            entries.append(f"  {fpath}  ({size_str})")

    if not entries:
        return ""

    return (
        "\n\n📁 AVAILABLE SCRIPTS (use these absolute paths with shell_execute):\n"
        + "\n".join(entries)
    )


def resolve_skill_content(skill: SkillDefinition) -> str:
    """Return the full skill content with:
    1. Relative script paths resolved to absolute paths
    2. An explicit script listing appended at the end

    This is the single canonical function for preparing skill content
    for agent consumption — used by both read_skill tool and planning
    phase pre-loading.
    """
    content = skill.content

    # Step 1: Regex-replace relative script/ references with absolute paths
    if skill.base_dir and os.path.isdir(os.path.join(skill.base_dir, "scripts")):
        abs_scripts = os.path.join(skill.base_dir, "scripts")
        content = re.sub(
            r'(?<![/\w])(?:\./)?scripts/',
            abs_scripts + "/",
            content,
        )

    # Step 2: Append explicit script listing with absolute paths
    listing = build_script_listing(skill)
    if listing:
        content += listing

    return content


_skill_cache: Optional[Dict[str, SkillDefinition]] = None


def _load_all_skills() -> Dict[str, SkillDefinition]:
    """Scan skills/ dir, lazy-load and cache."""
    global _skill_cache
    if _skill_cache is not None:
        return _skill_cache

    skills: Dict[str, SkillDefinition] = {}

    if not os.path.isdir(SKILLS_DIR):
        logger.warning("Skills directory not found: %s", SKILLS_DIR)
        _skill_cache = skills
        return skills

    for entry in sorted(os.listdir(SKILLS_DIR)):
        skill_dir = os.path.join(SKILLS_DIR, entry)
        if not os.path.isdir(skill_dir):
            continue
        md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(md_path):
            continue
        skill = _parse_skill_md(entry, md_path)
        if skill:
            skills[skill.id] = skill

    logger.info("Loaded %d skills from %s", len(skills), SKILLS_DIR)
    _skill_cache = skills
    return skills


def reload_skills() -> None:
    """Force reload from disk (hot-reload)."""
    global _skill_cache
    _skill_cache = None
    _load_all_skills()


# ── Migration compatibility ────────────────────────────────────────────────

_migration_map: Optional[Dict[str, str]] = None


def _load_migration_map() -> None:
    """Load the old→new skill ID mapping from _migration.json."""
    global _migration_map
    _migration_map = {}
    if os.path.isfile(_MIGRATION_PATH):
        try:
            with open(_MIGRATION_PATH, "r", encoding="utf-8") as f:
                _migration_map = json.load(f)
            logger.info("Loaded %d migration mappings", len(_migration_map))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Cannot read migration map: %s", e)


def _resolve_skill_id(raw_id: str) -> str:
    """Resolve old snake_case skill IDs to new kebab-case."""
    global _migration_map
    if _migration_map is None:
        _load_migration_map()
    return _migration_map.get(raw_id, raw_id)


# ── XML builder for system prompt injection ────────────────────────────────

def build_available_skills_xml(skill_ids: Optional[List[str]] = None) -> str:
    """Build <available_skills> XML block for system prompt injection.

    Args:
        skill_ids: Optional list of skill IDs to include. If None, all skills.
    """
    skills = _load_all_skills()
    if skill_ids:
        # Resolve old IDs and filter
        resolved_ids = {_resolve_skill_id(sid) for sid in skill_ids}
        skills = {k: v for k, v in skills.items() if k in resolved_ids}

    lines = ["<available_skills>"]
    for sid in sorted(skills):
        s = skills[sid]
        lines.append(f'  <skill name="{s.name}">{s.description}</skill>')
    lines.append("</available_skills>")
    logger.info(
        f"[Skills] XML block built: requested={skill_ids}, "
        f"resolved={sorted(skills.keys())} ({len(skills)} skills)"
    )
    return "\n".join(lines)


# ── Per-Agent personal skills (open-source skill ecosystem) ───────────────

def load_agent_personal_skills(agent_id: str) -> Dict[str, SkillDefinition]:
    """Scan agent personal skill directories for SKILL.md files.

    Searches:
      - agent_homes/{id}/skills/            (manual placement, persistent)
      - agent_homes/{id}/.agents/skills/    (pre-installed, persistent)
      - workspace/_skills/skills/           (task-installed, ephemeral)
      - workspace/_skills/.agents/skills/   (task-installed, ephemeral)
    No caching — install-then-use pattern.
    """
    from agents.agent_home import get_agent_skills_dir, ensure_agent_home
    from agents.tools import _workspace_var

    skills: Dict[str, SkillDefinition] = {}

    # 1. Pre-installed skills from agent_homes (persistent)
    home = ensure_agent_home(agent_id)
    search_dirs = [
        get_agent_skills_dir(agent_id),                # agent_homes/{id}/skills/
        os.path.join(home, ".agents", "skills"),        # agent_homes/{id}/.agents/skills/
    ]

    # 2. Workspace-installed skills (ephemeral, per-task)
    # Skills are installed at agent-level dir (parent of subtask workspace),
    # so search both the workspace itself and its parent for _skills/.
    workspace = _workspace_var.get(None)
    if workspace:
        for base in [workspace, os.path.dirname(workspace)]:
            skills_home = os.path.join(base, "_skills")
            search_dirs.extend([
                os.path.join(skills_home, "skills"),
                os.path.join(skills_home, ".agents", "skills"),
            ])

    for skills_dir in search_dirs:
        if not os.path.isdir(skills_dir):
            continue
        for entry in sorted(os.listdir(skills_dir)):
            skill_dir = os.path.join(skills_dir, entry)
            if not os.path.isdir(skill_dir):
                continue
            md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(md_path):
                continue
            skill = _parse_skill_md(entry, md_path)
            if skill and skill.id not in skills:  # first match wins
                skills[skill.id] = skill

    if skills:
        logger.info(
            "[Skills] Loaded %d personal skills for agent %s",
            len(skills), agent_id,
        )
    return skills


def load_merged_skills(agent_id: str) -> Dict[str, SkillDefinition]:
    """Merge shared skills + agent personal skills. Personal overrides shared on name conflict."""
    shared = dict(_load_all_skills())  # copy to avoid mutating cache
    personal = load_agent_personal_skills(agent_id)
    shared.update(personal)  # personal wins on conflict
    return shared


def build_available_skills_xml_for_agent(
    agent_id: str, skill_ids: Optional[List[str]] = None,
) -> str:
    """Build <available_skills> XML with both shared and personal skills.

    Each skill element includes source="shared" or source="personal".
    """
    shared = _load_all_skills()
    personal = load_agent_personal_skills(agent_id)

    # Merge: start with shared, overlay personal
    merged: Dict[str, SkillDefinition] = {}
    merged.update(shared)
    merged.update(personal)

    if skill_ids:
        resolved_ids = {_resolve_skill_id(sid) for sid in skill_ids}
        merged = {k: v for k, v in merged.items() if k in resolved_ids}

    personal_ids = set(personal.keys())

    lines = ["<available_skills>"]
    for sid in sorted(merged):
        s = merged[sid]
        source = "personal" if sid in personal_ids else "shared"
        lines.append(f'  <skill name="{s.name}" source="{source}">{s.description}</skill>')
    lines.append("</available_skills>")

    logger.info(
        f"[Skills] Agent XML block: agent={agent_id}, "
        f"shared={len(shared)}, personal={len(personal)}, "
        f"merged={len(merged)}"
    )
    return "\n".join(lines)

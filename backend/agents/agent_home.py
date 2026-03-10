"""Per-Agent home directory management.

Each agent gets a persistent home under backend/agent_homes/{agent_id}/:
  skills/               # npx skills add installs here
  .installed_skills.json # installation records
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

AGENT_HOMES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_homes")


def ensure_agent_home(agent_id: str) -> str:
    """Create agent home + skills + memory subdirectories if not exists. Returns home path."""
    home = os.path.join(AGENT_HOMES_DIR, agent_id)
    skills_dir = os.path.join(home, "skills")
    memory_dir = os.path.join(home, "memory")
    os.makedirs(skills_dir, exist_ok=True)
    os.makedirs(memory_dir, exist_ok=True)

    record_path = os.path.join(home, ".installed_skills.json")
    if not os.path.isfile(record_path):
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump([], f)

    return home


def get_agent_memory_dir(agent_id: str) -> str:
    """Return the memory directory path for an agent (creates home if needed)."""
    home = ensure_agent_home(agent_id)
    return os.path.join(home, "memory")


def get_agent_profile_path(agent_id: str) -> str:
    """Return the profile.json path for an agent."""
    return os.path.join(get_agent_memory_dir(agent_id), "profile.json")


def get_agent_skills_dir(agent_id: str) -> str:
    """Return the skills directory path for an agent (creates home if needed)."""
    home = ensure_agent_home(agent_id)
    return os.path.join(home, "skills")


def record_installed_skill(agent_id: str, package: str, skill_id: str) -> None:
    """Append an installation record to .installed_skills.json."""
    home = ensure_agent_home(agent_id)
    record_path = os.path.join(home, ".installed_skills.json")

    records = _read_records(record_path)
    records.append({
        "package": package,
        "skill_id": skill_id,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    })

    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    logger.info(f"[AgentHome] Recorded install: agent={agent_id}, pkg={package}, skill={skill_id}")


def get_installed_skills(agent_id: str) -> List[dict]:
    """Read the installation records for an agent."""
    home = os.path.join(AGENT_HOMES_DIR, agent_id)
    record_path = os.path.join(home, ".installed_skills.json")
    return _read_records(record_path)


def _read_records(record_path: str) -> List[dict]:
    """Read JSON array from record file, return [] on any error."""
    if not os.path.isfile(record_path):
        return []
    try:
        with open(record_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[AgentHome] Cannot read records: {e}")
        return []

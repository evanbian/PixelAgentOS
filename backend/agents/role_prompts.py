"""Default system prompts per agent role — shim delegating to skill_registry."""
from agents.skill_registry import list_roles, get_role_system_prompt

ROLE_PROMPTS = {r.id: r.system_prompt for r in list_roles()}
DEFAULT_PROMPT = "You are a helpful AI agent."

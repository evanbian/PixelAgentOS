from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List
from datetime import datetime
import uuid


class AgentMemoryItem(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentMemory(BaseModel):
    short_term: list[AgentMemoryItem] = Field(default_factory=list)
    long_term_summary: str = ""
    task_history: list[str] = Field(default_factory=list)


class MemoryEntry(BaseModel):
    """Persistent memory entry stored in agent_memories table."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    content: str
    category: str = "general"  # general | task | insight | preference
    importance: float = 0.5    # 0.0~1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentCreate(BaseModel):
    name: str
    role: str = "Developer"
    avatar_index: int = 0
    skills: List[str] = Field(default_factory=list)
    system_prompt: str = ""
    workstation_id: str
    model: str = "deepseek/deepseek-chat"
    api_key: str = ""

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        from agents.skill_registry import get_all_role_ids
        valid = get_all_role_ids()
        if v not in valid:
            raise ValueError(f"Unknown role '{v}'. Valid: {valid}")
        return v

    @field_validator("skills")
    @classmethod
    def deduplicate_skills(cls, v: List[str]) -> List[str]:
        """Deduplicate skill IDs while preserving order.

        We no longer validate against the shared skills directory because
        personal skills are dynamically installed per-agent and won't
        appear in backend/skills/.
        """
        from agents.skill_loader import _resolve_skill_id
        seen: set = set()
        result = []
        for s in v:
            resolved = _resolve_skill_id(s)
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
        return result


class AgentUpdate(BaseModel):
    status: Optional[Literal["idle", "working", "thinking", "communicating"]] = None
    workstation_id: Optional[str] = None
    system_prompt: Optional[str] = None


class Agent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    role: str
    avatar_index: int = 0
    skills: list[str] = Field(default_factory=list)
    system_prompt: str = ""
    workstation_id: str
    status: Literal["idle", "working", "thinking", "communicating"] = "idle"
    memory: AgentMemory = Field(default_factory=AgentMemory)
    model: str = "deepseek/deepseek-chat"
    api_key: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SubTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str = ""
    assigned_to: Optional[str] = None
    status: Literal["todo", "in_progress", "done", "cancelled"] = "todo"
    output: Optional[str] = None
    depends_on: list = Field(default_factory=list)  # subtask IDs this depends on
    read_from: list = Field(default_factory=list)    # subtask IDs whose drafts are visible
    max_iterations: int = 0  # PM-assigned iteration budget (0 = use default)


class PMConfig(BaseModel):
    """Global PM configuration."""
    model: str = ""          # e.g. "openai/gpt-4o"
    api_key: str = ""        # key or key|||api_base


class TaskCreate(BaseModel):
    title: str
    description: str
    assigned_to: list[str] = Field(default_factory=list)
    pm_model: str = ""       # deprecated: use global PM config instead
    pm_api_key: str = ""     # deprecated: use global PM config instead
    schedule: Optional[str] = None  # cron expression, e.g. "0 9 * * *"


class TaskUpdate(BaseModel):
    status: Optional[Literal["todo", "in_progress", "done", "cancelled"]] = None
    assigned_to: Optional[list[str]] = None
    output: Optional[str] = None


class ScratchpadEntryModel(BaseModel):
    key: str
    content: str
    author_id: str
    author_name: str


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    status: Literal["todo", "in_progress", "done", "cancelled"] = "todo"
    assigned_to: list[str] = Field(default_factory=list)
    subtasks: list[SubTask] = Field(default_factory=list)
    scratchpad: list[ScratchpadEntryModel] = Field(default_factory=list)
    created_by: str = "human"
    output: Optional[str] = None
    pm_model: str = ""
    pm_api_key: str = ""
    schedule: Optional[str] = None
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# WebSocket event models
class WSEvent(BaseModel):
    event: str
    data: dict


class AgentStatusEvent(BaseModel):
    agent_id: str
    status: str
    animation: str = ""


class AgentMessageEvent(BaseModel):
    from_id: str
    to_id: str
    content: str
    type: str = "chat"


class TaskUpdateEvent(BaseModel):
    task_id: str
    status: str
    progress: int = 0
    output: Optional[str] = None


class SystemLogEvent(BaseModel):
    timestamp: str
    level: str
    message: str


# ── Task Execution Metrics ─────────────────────────────────────────────────

class TaskMetrics(BaseModel):
    """Structured execution metrics collected during task execution."""
    task_id: str
    total_duration_s: float = 0.0
    subtask_count: int = 0
    subtask_durations: dict = Field(default_factory=dict)   # {subtask_id: seconds}
    tool_call_count: int = 0
    tool_call_distribution: dict = Field(default_factory=dict)  # {tool_name: count}
    reflection_count: int = 0
    reflection_triggers: list = Field(default_factory=list)  # ["Periodic ...", ...]
    self_critique_count: int = 0
    self_critique_revised: int = 0
    rework_count: int = 0
    replan_count: int = 0
    llm_errors: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

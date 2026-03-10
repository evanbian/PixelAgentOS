"""Agent CRUD API routes."""
from fastapi import APIRouter, HTTPException
from models import Agent, AgentCreate, AgentUpdate
from database import save_agent, get_agent, get_all_agents, update_agent_status, delete_agent
from websocket_manager import manager
from agents.role_prompts import ROLE_PROMPTS, DEFAULT_PROMPT
from agents.skill_registry import list_skills, list_roles

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/skills")
async def get_skills():
    """Return all available skills."""
    return [
        {
            "id": s.id,
            "display_name": s.name,
            "description": s.description,
        }
        for s in list_skills()
    ]


@router.get("/roles")
async def get_roles():
    """Return all available roles with defaults."""
    return [
        {
            "id": r.id,
            "display_name": r.display_name,
            "emoji": r.emoji,
            "description": r.description,
            "core_tool_ids": r.core_tool_ids,
            "default_skills": r.default_skills,
            "system_prompt": r.system_prompt,
        }
        for r in list_roles()
    ]


@router.get("/role-prompts")
async def get_role_prompts():
    """Return default system prompts per role (legacy compat)."""
    return ROLE_PROMPTS


@router.post("")
async def create_agent(data: AgentCreate):
    # Auto-fill system_prompt with role default if empty
    from agents.skill_registry import get_role_system_prompt
    system_prompt = data.system_prompt or get_role_system_prompt(data.role)

    agent = Agent(
        name=data.name,
        role=data.role,
        avatar_index=data.avatar_index,
        skills=data.skills,
        system_prompt=system_prompt,
        workstation_id=data.workstation_id,
        model=data.model,
        api_key=data.api_key,
    )
    await save_agent(agent)
    await manager.emit_system_log(
        f"Agent '{agent.name}' ({agent.role}) joined the office!"
    )
    # Exclude api_key from broadcast / response for safety
    agent_data = agent.model_dump(mode="json")
    agent_data.pop("api_key", None)
    await manager.broadcast("agent:created", agent_data)
    return agent_data


def _safe_agent(agent: Agent) -> dict:
    """Return agent dict with api_key masked."""
    d = agent.model_dump(mode="json")
    if d.get("api_key"):
        key = d["api_key"]
        d["api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return d


@router.get("")
async def list_agents():
    agents = await get_all_agents()
    return [_safe_agent(a) for a in agents]


@router.get("/{agent_id}")
async def get_agent_by_id(agent_id: str):
    agent = await get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _safe_agent(agent)


@router.patch("/{agent_id}", response_model=Agent)
async def update_agent(agent_id: str, data: AgentUpdate):
    agent = await get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if data.status is not None:
        agent.status = data.status
        await update_agent_status(agent_id, data.status)
        await manager.emit_agent_status(agent_id, data.status)

    if data.system_prompt is not None:
        agent.system_prompt = data.system_prompt
        await save_agent(agent)

    return agent


@router.delete("/{agent_id}")
async def remove_agent(agent_id: str):
    agent = await get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from database import delete_agent_memories
    await delete_agent_memories(agent_id)
    await delete_agent(agent_id)
    await manager.broadcast("agent:removed", {"agent_id": agent_id})
    return {"success": True}


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: str, body: dict):
    """Send a message to an agent and get a response."""
    from database import update_agent_memory
    from agents.worker import execute_worker_task

    agent = await get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    message = body.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Send user message to log
    await manager.emit_agent_message("human", agent_id, message, "chat")

    async def on_status(aid, status):
        await manager.emit_agent_status(aid, status)

    async def on_message(from_id, to_id, content, msg_type):
        await manager.emit_agent_message(from_id, to_id, content, msg_type)

    import asyncio
    from agents.memory_tools import create_memory_tools
    mem_tools = create_memory_tools(agent.id, agent.name, loop=asyncio.get_event_loop())

    response, _, _, _ = await execute_worker_task(
        agent=agent,
        task_description=message,
        on_status_change=on_status,
        on_message=on_message,
        extra_tools=mem_tools,
    )

    from agents.memory import record_task_completion
    await record_task_completion(agent.memory, agent.id, message[:80], response)
    await update_agent_memory(agent_id, agent.memory)
    await manager.emit_agent_message(agent_id, "human", response, "chat")

    return {"response": response, "agent_id": agent_id}

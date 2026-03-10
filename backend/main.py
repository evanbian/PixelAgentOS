"""PixelAgentOS Backend — FastAPI entry point."""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

LOG_FILE = os.path.join(os.path.dirname(__file__), "agent_tasks.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import init_db
    from scheduler import init_scheduler, shutdown_scheduler
    await init_db()
    logger.info("Database initialized")
    await init_scheduler()
    logger.info("Scheduler initialized")
    yield
    await shutdown_scheduler()
    logger.info("Shutting down")


app = FastAPI(
    title="PixelAgentOS API",
    description="Multi-Agent Collaboration Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
from routes.agents import router as agents_router
from routes.tasks import router as tasks_router
from routes.config import router as config_router

app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(config_router)

# Serve generated files (charts, CSV, etc.) from task workspaces
from fastapi.staticfiles import StaticFiles

workspaces_dir = os.path.join(os.path.dirname(__file__), "workspaces")
os.makedirs(workspaces_dir, exist_ok=True)
app.mount("/api/workspaces", StaticFiles(directory=workspaces_dir), name="workspaces")


@app.get("/")
async def root():
    return {
        "name": "PixelAgentOS",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/api/status")
async def status():
    from websocket_manager import manager
    from database import get_all_agents, get_all_tasks
    agents = await get_all_agents()
    tasks = await get_all_tasks()
    return {
        "agents": len(agents),
        "tasks": len(tasks),
        "ws_connections": manager.connection_count,
    }


@app.get("/api/models")
async def list_models():
    """Return available LLM models grouped by provider.

    Model ids use the LiteLLM native ``provider/model`` format so the
    backend can pass them directly to ``litellm.acompletion()``.
    """
    return {
        "providers": [
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "api_base": "https://api.deepseek.com",
                "models": [
                    {"id": "deepseek/deepseek-chat", "name": "DeepSeek-V3 Chat", "recommended": True},
                    {"id": "deepseek/deepseek-reasoner", "name": "DeepSeek-R1 Reasoner"},
                    {"id": "deepseek/deepseek-coder", "name": "DeepSeek Coder"},
                ],
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "api_base": "https://api.openai.com",
                "models": [
                    {"id": "openai/gpt-4o", "name": "GPT-4o"},
                    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "recommended": True},
                    {"id": "openai/o3-mini", "name": "o3-mini"},
                ],
            },
            {
                "id": "anthropic",
                "name": "Anthropic",
                "api_base": "https://api.anthropic.com",
                "models": [
                    {"id": "anthropic/claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
                    {"id": "anthropic/claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
                    {"id": "anthropic/claude-opus-4-6", "name": "Claude Opus 4.6"},
                ],
            },
            {
                "id": "qwen",
                "name": "Qwen (通义千问)",
                "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "models": [
                    {"id": "openai/qwen-plus", "name": "Qwen-Plus", "recommended": True},
                    {"id": "openai/qwen-turbo", "name": "Qwen-Turbo"},
                    {"id": "openai/qwen-max", "name": "Qwen-Max"},
                    {"id": "openai/qwen-long", "name": "Qwen-Long"},
                ],
            },
            {
                "id": "moonshot",
                "name": "Moonshot (月之暗面)",
                "api_base": "https://api.moonshot.cn/v1",
                "models": [
                    {"id": "openai/moonshot-v1-8k", "name": "Moonshot v1 8K"},
                    {"id": "openai/moonshot-v1-32k", "name": "Moonshot v1 32K", "recommended": True},
                    {"id": "openai/moonshot-v1-128k", "name": "Moonshot v1 128K"},
                ],
            },
            {
                "id": "zhipu",
                "name": "Zhipu (智谱)",
                "api_base": "https://open.bigmodel.cn/api/paas/v4",
                "models": [
                    {"id": "openai/glm-4-flash", "name": "GLM-4 Flash", "recommended": True},
                    {"id": "openai/glm-4-plus", "name": "GLM-4 Plus"},
                    {"id": "openai/glm-4-long", "name": "GLM-4 Long"},
                ],
            },
            {
                "id": "minimax",
                "name": "MiniMax",
                "api_base": "https://api.minimax.chat/v1",
                "models": [
                    {"id": "openai/MiniMax-Text-01", "name": "MiniMax-Text-01", "recommended": True},
                ],
            },
            {
                "id": "yi",
                "name": "Yi (零一万物)",
                "api_base": "https://api.lingyiwanwu.com/v1",
                "models": [
                    {"id": "openai/yi-lightning", "name": "Yi-Lightning", "recommended": True},
                    {"id": "openai/yi-large", "name": "Yi-Large"},
                    {"id": "openai/yi-medium", "name": "Yi-Medium"},
                ],
            },
            {
                "id": "baichuan",
                "name": "Baichuan (百川)",
                "api_base": "https://api.baichuan-ai.com/v1",
                "models": [
                    {"id": "openai/Baichuan4", "name": "Baichuan-4", "recommended": True},
                    {"id": "openai/Baichuan3-Turbo", "name": "Baichuan-3 Turbo"},
                ],
            },
            {
                "id": "stepfun",
                "name": "StepFun (阶跃星辰)",
                "api_base": "https://api.stepfun.com/v1",
                "models": [
                    {"id": "openai/step-2-16k", "name": "Step-2 16K", "recommended": True},
                    {"id": "openai/step-1-8k", "name": "Step-1 8K"},
                ],
            },
            {
                "id": "siliconflow",
                "name": "SiliconFlow (硅基流动)",
                "api_base": "https://api.siliconflow.cn/v1",
                "models": [
                    {"id": "openai/deepseek-ai/DeepSeek-V3", "name": "DeepSeek-V3 (硅基)"},
                    {"id": "openai/deepseek-ai/DeepSeek-R1", "name": "DeepSeek-R1 (硅基)"},
                    {"id": "openai/Qwen/Qwen2.5-72B-Instruct", "name": "Qwen2.5-72B (硅基)", "recommended": True},
                    {"id": "openai/THUDM/glm-4-9b-chat", "name": "GLM-4-9B (硅基)"},
                ],
            },
            {
                "id": "openrouter",
                "name": "OpenRouter (聚合)",
                "api_base": "https://openrouter.ai/api/v1",
                "models": [
                    {"id": "openai/deepseek/deepseek-chat-v3-0324", "name": "DeepSeek V3 (OR)"},
                    {"id": "openai/deepseek/deepseek-r1", "name": "DeepSeek R1 (OR)"},
                    {"id": "openai/qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B (OR)", "recommended": True},
                    {"id": "openai/google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash (OR)"},
                ],
            },
        ],
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    from websocket_manager import manager
    from database import get_all_agents, get_all_tasks

    await manager.connect(websocket)

    # Send initial state to new client
    agents = await get_all_agents()
    tasks = await get_all_tasks()
    await manager.send_to(websocket, "init", {
        "agents": [a.model_dump(mode="json") for a in agents],
        "tasks": [t.model_dump(mode="json") for t in tasks],
    })

    try:
        while True:
            data = await websocket.receive_text()
            await _handle_ws_message(websocket, data, manager)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# Registry for running task coroutines (task_id -> asyncio.Task)
_running_tasks: dict[str, asyncio.Task] = {}


async def _handle_ws_message(websocket, data: str, manager):
    """Handle incoming WebSocket messages from client."""
    from routes.agents import create_agent
    from routes.tasks import create_task, execute_task
    from database import get_agent, get_all_agents
    from models import AgentCreate, TaskCreate

    try:
        msg = json.loads(data)
        event = msg.get("event", "")
        payload = msg.get("data", {})

        if event == "agent:create":
            data_obj = AgentCreate(**payload)
            from database import save_agent
            from models import Agent
            agent = Agent(
                name=data_obj.name,
                role=data_obj.role,
                avatar_index=data_obj.avatar_index,
                skills=data_obj.skills,
                system_prompt=data_obj.system_prompt,
                workstation_id=data_obj.workstation_id,
                model=data_obj.model,
                api_key=data_obj.api_key,
            )
            await save_agent(agent)
            await manager.emit_system_log(
                f"Agent '{agent.name}' ({agent.role}) joined!"
            )
            # Exclude api_key from broadcast for safety
            agent_data = agent.model_dump(mode="json")
            agent_data.pop("api_key", None)
            await manager.broadcast("agent:created", agent_data)

        elif event == "task:create":
            from database import save_task
            from models import Task
            from scheduler import schedule_task, get_next_run_time
            cron_expr = payload.get("schedule")
            task = Task(
                title=payload.get("title", ""),
                description=payload.get("description", ""),
                assigned_to=payload.get("assigned_to", []),
                pm_model=payload.get("pm_model", ""),
                pm_api_key=payload.get("pm_api_key", ""),
                schedule=cron_expr if cron_expr else None,
                next_run_at=get_next_run_time(cron_expr) if cron_expr else None,
                created_by="human",
            )
            await save_task(task)
            if cron_expr:
                schedule_task(task.id, cron_expr)
            # Exclude pm_api_key from broadcast for safety
            task_data = task.model_dump(mode="json")
            task_data.pop("pm_api_key", None)
            await manager.broadcast("task:created", task_data)

        elif event == "task:assign":
            from database import get_task, update_task
            task = await get_task(payload.get("task_id", ""))
            if task:
                task.assigned_to = payload.get("agent_ids", [])
                await update_task(task)
                await manager.broadcast("task:assigned", {
                    "task_id": task.id,
                    "agent_ids": task.assigned_to
                })

        elif event == "task:execute":
            from agents.graph import run_task_graph
            from database import get_task

            task_id = payload.get("task_id", "")
            task = await get_task(task_id)
            if task:
                all_agents = await get_all_agents()
                agents = (
                    [a for a in all_agents if a.id in task.assigned_to]
                    if task.assigned_to else all_agents
                )
                coro = run_task_graph(task, agents, manager)
                aio_task = asyncio.create_task(coro)
                _running_tasks[task_id] = aio_task
                aio_task.add_done_callback(lambda _t, _id=task_id: _running_tasks.pop(_id, None))

        elif event == "task:cancel":
            from database import get_task, update_task

            task_id = payload.get("task_id", "")
            task = await get_task(task_id)
            if task and task.status == "in_progress":
                # Cancel the asyncio task — graph.py CancelledError handler
                # will clear data, update DB, and broadcast events.
                aio_task = _running_tasks.pop(task_id, None)
                if aio_task and not aio_task.done():
                    aio_task.cancel()
                else:
                    # No running coroutine (edge case) — clean up directly
                    for st in task.subtasks:
                        if st.status in ("in_progress", "todo"):
                            if st.status == "in_progress":
                                st.output = None
                            st.status = "cancelled"
                    task.scratchpad = []
                    task.output = None
                    task.status = "cancelled"
                    await update_task(task)
                    await manager.broadcast("task:update", {
                        "task_id": task_id,
                        "status": "cancelled",
                        "progress": 0,
                    })
                    await manager.broadcast("scratchpad:clear", {"task_id": task_id})
                    await manager.emit_system_log(f"Task '{task.title}' cancelled by user")
                    for aid in task.assigned_to:
                        await manager.emit_agent_status(aid, "idle")

        elif event == "agent:chat":
            agent_id = payload.get("agent_id", "")
            message = payload.get("message", "")
            if agent_id and message:
                agent = await get_agent(agent_id)
                if agent:
                    from agents.worker import execute_worker_task
                    from database import update_agent_memory

                    # NOTE: User message already optimistically inserted by frontend.
                    # Do NOT broadcast emit_agent_message("human"...) here to avoid duplication.

                    async def on_status(aid, status):
                        await manager.emit_agent_status(aid, status)

                    async def on_message(from_id, to_id, content, msg_type):
                        await manager.emit_agent_message(from_id, to_id, content, msg_type)

                    asyncio.create_task(_handle_chat(
                        agent, message, on_status, on_message, manager
                    ))

    except json.JSONDecodeError:
        logger.warning("Invalid JSON from WebSocket client")
    except Exception as e:
        logger.error(f"Error handling WS message: {e}")


async def _handle_chat(agent, message, on_status, on_message, manager):
    """Handle agent chat in background."""
    from agents.worker import execute_worker_task
    from agents.memory_tools import create_memory_tools
    from database import update_agent_memory
    try:
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
        await update_agent_memory(agent.id, agent.memory)
        await manager.emit_agent_message(agent.id, "human", response, "chat")
    except Exception as e:
        logger.error(f"Chat error: {e}")
        await manager.emit_agent_message(
            agent.id, "human", f"Error: {str(e)}", "error"
        )


if __name__ == "__main__":
    import uvicorn
    _base = os.path.dirname(__file__)
    uvicorn.run(
        app, host="0.0.0.0", port=8000,
        reload=True,
        reload_excludes=[
            os.path.join(_base, "workspaces"),
            os.path.join(_base, "agent_homes"),
        ],
    )

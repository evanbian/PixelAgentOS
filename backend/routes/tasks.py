"""Task CRUD and execution API routes."""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from models import Task, TaskCreate, TaskUpdate
from database import (
    save_task, get_task, get_all_tasks, update_task, delete_task,
    get_agent, get_task_metrics, get_all_task_metrics,
)
from scheduler import schedule_task, unschedule_task, get_next_run_time
from websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=Task)
async def create_task(data: TaskCreate):
    task = Task(
        title=data.title,
        description=data.description,
        assigned_to=data.assigned_to,
        pm_model=data.pm_model,
        pm_api_key=data.pm_api_key,
        schedule=data.schedule,
        next_run_at=get_next_run_time(data.schedule) if data.schedule else None,
        created_by="human",
    )
    await save_task(task)
    if data.schedule:
        schedule_task(task.id, data.schedule)
    await manager.emit_system_log(f"New task created: '{task.title}'")
    task_data = task.model_dump(mode="json")
    task_data.pop("pm_api_key", None)
    await manager.broadcast("task:created", task_data)
    return task


@router.get("", response_model=list[Task])
async def list_tasks():
    return await get_all_tasks()


@router.get("/metrics/all")
async def get_all_metrics():
    """Return execution metrics for all tasks."""
    return await get_all_task_metrics()


@router.get("/{task_id}", response_model=Task)
async def get_task_by_id(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=Task)
async def update_task_endpoint(task_id: str, data: TaskUpdate):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if data.status is not None:
        task.status = data.status
    if data.assigned_to is not None:
        task.assigned_to = data.assigned_to
    if data.output is not None:
        task.output = data.output

    await update_task(task)
    await manager.emit_task_update(task_id, task.status, 0, task.output)
    return task


@router.delete("/{task_id}")
async def remove_task(task_id: str):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    unschedule_task(task_id)
    await delete_task(task_id)
    await manager.broadcast("task:removed", {"task_id": task_id})
    return {"success": True}


@router.post("/{task_id}/execute")
async def execute_task(task_id: str, background_tasks: BackgroundTasks):
    """Trigger task execution by the assigned agents."""
    from database import get_all_agents
    from agents.graph import run_task_graph

    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "in_progress":
        raise HTTPException(status_code=409, detail="Task already running")

    # Get assigned agents
    all_agents = await get_all_agents()
    if task.assigned_to:
        agents = [a for a in all_agents if a.id in task.assigned_to]
    else:
        agents = all_agents  # Use all available agents

    if not agents:
        raise HTTPException(
            status_code=400,
            detail="No agents assigned or available for this task"
        )

    # Run in background
    background_tasks.add_task(
        _run_task_background, task, agents
    )

    return {"message": "Task execution started", "task_id": task_id}


async def _run_task_background(task: Task, agents):
    """Background task execution."""
    from agents.graph import run_task_graph
    try:
        await run_task_graph(task, agents, manager)
    except Exception as e:
        logger.error(f"Task execution failed: {e}")
        await manager.emit_system_log(
            f"Task '{task.title}' failed: {str(e)}", "error"
        )
        task.status = "todo"
        await update_task(task)
        await manager.emit_task_update(task.id, "todo", 0)


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running or pending task."""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("todo", "in_progress"):
        raise HTTPException(status_code=409, detail=f"Cannot cancel task with status '{task.status}'")

    # Cancel asyncio task if running
    from main import _running_tasks
    aio_task = _running_tasks.pop(task_id, None)
    if aio_task and not aio_task.done():
        # graph.py CancelledError handler will clean data, update DB, broadcast
        aio_task.cancel()
    else:
        # No running coroutine — clean up directly
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

    await manager.emit_system_log(f"Task '{task.title}' cancelled")
    return {"success": True, "task_id": task_id}


class ScheduleUpdate(BaseModel):
    schedule: Optional[str] = None  # null to remove schedule


@router.patch("/{task_id}/schedule")
async def update_task_schedule(task_id: str, data: ScheduleUpdate):
    """Update or remove a task's cron schedule."""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if data.schedule:
        # Validate cron expression
        next_run = get_next_run_time(data.schedule)
        if next_run is None:
            raise HTTPException(status_code=400, detail="Invalid cron expression")
        task.schedule = data.schedule
        task.next_run_at = next_run
        schedule_task(task_id, data.schedule)
    else:
        task.schedule = None
        task.next_run_at = None
        unschedule_task(task_id)

    await update_task(task)
    task_data = task.model_dump(mode="json")
    task_data.pop("pm_api_key", None)
    await manager.broadcast("task:update", {
        "task_id": task_id,
        "status": task.status,
        "progress": task.progress if hasattr(task, 'progress') else 0,
        "schedule": task.schedule,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
    })
    return task


@router.post("/{task_id}/assign")
async def assign_task(task_id: str, body: dict):
    """Assign task to specific agents."""
    agent_ids = body.get("agent_ids", [])
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.assigned_to = agent_ids
    await update_task(task)
    await manager.broadcast("task:assigned", {
        "task_id": task_id,
        "agent_ids": agent_ids
    })
    return task


@router.get("/{task_id}/metrics")
async def get_task_metrics_endpoint(task_id: str):
    """Return execution metrics for a completed task."""
    metrics = await get_task_metrics(task_id)
    if not metrics:
        raise HTTPException(status_code=404, detail="Metrics not found for this task")
    return metrics

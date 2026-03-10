"""APScheduler integration for cron tasks."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None


async def init_scheduler():
    """Initialize scheduler and load existing scheduled tasks from DB."""
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.start()

    from database import get_scheduled_tasks
    tasks = await get_scheduled_tasks()
    for task in tasks:
        if task.schedule:
            _add_task_job(task.id, task.schedule)
    logger.info(f"Scheduler initialized with {len(tasks)} scheduled tasks")


def schedule_task(task_id: str, cron_expr: str):
    """Add or update a cron job for a task."""
    if _scheduler is None:
        return
    # Remove existing job if any
    try:
        _scheduler.remove_job(f"task_{task_id}")
    except Exception:
        pass
    _add_task_job(task_id, cron_expr)


def unschedule_task(task_id: str):
    """Remove a scheduled task."""
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(f"task_{task_id}")
    except Exception:
        pass


def get_next_run_time(cron_expr: str) -> Optional[datetime]:
    """Calculate next run time from a cron expression (uses system local timezone)."""
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        now = datetime.now(tz=trigger.timezone)
        return trigger.get_next_fire_time(None, now)
    except Exception:
        return None


def _add_task_job(task_id: str, cron_expr: str):
    """Internal: add a cron job."""
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        _scheduler.add_job(
            _execute_scheduled_task,
            trigger=trigger,
            id=f"task_{task_id}",
            args=[task_id],
            replace_existing=True,
        )
        logger.info(f"Scheduled task {task_id} with cron: {cron_expr}")
    except Exception as e:
        logger.error(f"Failed to schedule task {task_id}: {e}")


async def _execute_scheduled_task(task_id: str):
    """Callback: execute a scheduled task."""
    from database import get_task, get_all_agents, update_task
    from agents.graph import run_task_graph
    from websocket_manager import manager

    task = await get_task(task_id)
    if not task or task.status == 'cancelled':
        unschedule_task(task_id)
        return

    # Reset task for re-execution
    task.status = "in_progress"
    task.output = None
    task.subtasks = []
    task.scratchpad = []
    task.last_run_at = datetime.now()
    # Calculate next run time
    if task.schedule:
        task.next_run_at = get_next_run_time(task.schedule)
    await update_task(task)

    await manager.emit_system_log(f"Scheduled task '{task.title}' starting (cron)")
    await manager.broadcast("task:update", {
        "task_id": task.id,
        "status": "in_progress",
        "progress": 0,
    })

    all_agents = await get_all_agents()
    agents = (
        [a for a in all_agents if a.id in task.assigned_to]
        if task.assigned_to else all_agents
    )

    if agents:
        asyncio.create_task(run_task_graph(task, agents, manager))


async def shutdown_scheduler():
    """Graceful shutdown."""
    if _scheduler:
        _scheduler.shutdown(wait=False)

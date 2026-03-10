from __future__ import annotations
import json
import logging
from typing import Optional
from datetime import datetime
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def send_to(self, websocket: WebSocket, event: str, data: dict):
        try:
            message = json.dumps({"event": event, "data": data})
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Error sending to client: {e}")
            self.disconnect(websocket)

    async def broadcast(self, event: str, data: dict):
        if not self.active_connections:
            return
        message = json.dumps({"event": event, "data": data})
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def emit_agent_status(self, agent_id: str, status: str, animation: str = ""):
        await self.broadcast("agent:status", {
            "agent_id": agent_id,
            "status": status,
            "animation": animation or status
        })

    async def emit_agent_message(
        self, from_id: str, to_id: str, content: str, msg_type: str = "chat"
    ):
        await self.broadcast("agent:message", {
            "from_id": from_id,
            "to_id": to_id,
            "content": content,
            "type": msg_type
        })

    async def emit_task_update(
        self, task_id: str, status: str, progress: int = 0, output: Optional[str] = None
    ):
        data = {
            "task_id": task_id,
            "status": status,
            "progress": progress,
        }
        if output is not None:
            data["output"] = output
        await self.broadcast("task:update", data)

    async def emit_subtask(self, parent_id: str, subtask: dict):
        await self.broadcast("task:subtask", {
            "parent_id": parent_id,
            "subtask": subtask
        })

    async def emit_system_log(self, message: str, level: str = "info"):
        await self.broadcast("system:log", {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message
        })

    async def emit_scratchpad_update(
        self, task_id: str, key: str, content: str, author_id: str, author_name: str
    ):
        await self.broadcast("scratchpad:update", {
            "task_id": task_id,
            "key": key,
            "content": content,
            "author_id": author_id,
            "author_name": author_name,
        })

    async def emit_subtask_stream(self, task_id: str, subtask_id: str, chunk: str):
        """Broadcast a streaming token chunk for a subtask."""
        await self.broadcast("subtask:stream", {
            "task_id": task_id,
            "subtask_id": subtask_id,
            "chunk": chunk,
        })

    async def emit_subtask_stream_end(self, task_id: str, subtask_id: str):
        """Signal that streaming for a subtask has ended."""
        await self.broadcast("subtask:stream_end", {
            "task_id": task_id,
            "subtask_id": subtask_id,
        })

    async def emit_task_metrics(self, task_id: str, metrics: dict):
        """Broadcast execution metrics when a task completes."""
        await self.broadcast("task:metrics", {
            "task_id": task_id,
            **metrics,
        })

    async def emit_pm_message(self, content: str):
        await self.broadcast("agent:message", {
            "from_id": "pm-agent",
            "to_id": "all",
            "content": content,
            "type": "agent",
        })

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)


# Singleton instance
manager = ConnectionManager()

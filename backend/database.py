from __future__ import annotations
import aiosqlite
import json
import os
from typing import Optional
from datetime import datetime
from models import Agent, Task, AgentMemory, MemoryEntry, TaskMetrics


DB_PATH = os.getenv("DB_PATH", "./pixel_agent_os.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                avatar_index INTEGER DEFAULT 0,
                skills TEXT DEFAULT '[]',
                system_prompt TEXT DEFAULT '',
                workstation_id TEXT NOT NULL,
                status TEXT DEFAULT 'idle',
                memory TEXT DEFAULT '{}',
                model TEXT DEFAULT 'deepseek/deepseek-chat',
                api_key TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        # Migration: add api_key column for existing databases
        try:
            await db.execute("ALTER TABLE agents ADD COLUMN api_key TEXT DEFAULT ''")
        except Exception:
            pass
        # Migration: add scratchpad column for existing databases
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN scratchpad TEXT DEFAULT '[]'")
        except Exception:
            pass
        # Migration: add schedule columns for cron tasks
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN schedule TEXT DEFAULT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN next_run_at TEXT DEFAULT NULL")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN last_run_at TEXT DEFAULT NULL")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'todo',
                assigned_to TEXT DEFAULT '[]',
                subtasks TEXT DEFAULT '[]',
                created_by TEXT DEFAULT 'human',
                output TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # agent_memories table for persistent long-term memory
        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_memories (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance REAL DEFAULT 0.5,
                created_at TEXT NOT NULL
            )
        """)
        # FTS5 virtual table for full-text search (trigram for CJK support)
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS agent_memories_fts
            USING fts5(content, content=agent_memories, content_rowid=rowid, tokenize='trigram')
        """)
        # Triggers to keep FTS in sync
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS agent_memories_ai
            AFTER INSERT ON agent_memories
            BEGIN
                INSERT INTO agent_memories_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS agent_memories_ad
            AFTER DELETE ON agent_memories
            BEGIN
                INSERT INTO agent_memories_fts(agent_memories_fts, rowid, content)
                VALUES('delete', old.rowid, old.content);
            END
        """)
        # task_metrics table for execution observability
        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_metrics (
                task_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # system_config table for global settings (e.g. PM model config)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()


# ── System Config CRUD ────────────────────────────────────────────────────

async def get_config(key: str) -> Optional[str]:
    """Get a config value. Falls back to env var if not in DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM system_config WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
    # Fallback to environment variable
    return os.environ.get(key)


async def set_config(key: str, value: str):
    """Set a config value."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO system_config (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, datetime.utcnow().isoformat()))
        await db.commit()


async def get_all_config() -> dict:
    """Get all config key-value pairs."""
    result = {}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM system_config") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                result[row[0]] = row[1]
    return result


async def delete_config(key: str):
    """Delete a config value."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM system_config WHERE key = ?", (key,))
        await db.commit()


async def save_agent(agent: Agent):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO agents
            (id, name, role, avatar_index, skills, system_prompt,
             workstation_id, status, memory, model, api_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent.id, agent.name, agent.role, agent.avatar_index,
            json.dumps(agent.skills), agent.system_prompt,
            agent.workstation_id, agent.status,
            agent.memory.model_dump_json(), agent.model,
            agent.api_key, agent.created_at.isoformat()
        ))
        await db.commit()


async def get_agent(agent_id: str) -> Optional[Agent]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return _row_to_agent(dict(row))
    return None


async def get_all_agents() -> list[Agent]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM agents ORDER BY created_at") as cursor:
            rows = await cursor.fetchall()
            return [_row_to_agent(dict(r)) for r in rows]


async def update_agent_status(agent_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE agents SET status = ? WHERE id = ?",
            (status, agent_id)
        )
        await db.commit()


async def update_agent_memory(agent_id: str, memory: AgentMemory):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE agents SET memory = ? WHERE id = ?",
            (memory.model_dump_json(), agent_id)
        )
        await db.commit()


async def update_agent_skills(agent_id: str, skills: list):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE agents SET skills = ? WHERE id = ?",
            (json.dumps(skills), agent_id)
        )
        await db.commit()


async def delete_agent(agent_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await db.commit()


async def save_memory_entry(entry: MemoryEntry):
    """Persist memory entry to ChromaDB vector store."""
    from agents.memory_store import save_memory_to_store
    await save_memory_to_store(entry)


async def search_memories(agent_id: str, query: str, limit: int = 5) -> list:
    """Semantic search via ChromaDB + Ollama bge-m3 embeddings."""
    from agents.memory_store import search_memory_store
    return await search_memory_store(agent_id, query, limit)


async def get_recent_memories(agent_id: str, limit: int = 10) -> list:
    """Get most recent memories from ChromaDB store."""
    from agents.memory_store import get_recent_from_store
    return await get_recent_from_store(agent_id, limit)


async def delete_agent_memories(agent_id: str):
    """Delete all memories for an agent from ChromaDB store."""
    from agents.memory_store import delete_agent_store
    await delete_agent_store(agent_id)


async def save_task(task: Task):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO tasks
            (id, title, description, status, assigned_to, subtasks,
             scratchpad, created_by, output, schedule, next_run_at,
             last_run_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.id, task.title, task.description, task.status,
            json.dumps(task.assigned_to),
            json.dumps([s.model_dump() for s in task.subtasks]),
            json.dumps([e.model_dump() for e in task.scratchpad]),
            task.created_by, task.output,
            task.schedule,
            task.next_run_at.isoformat() if task.next_run_at else None,
            task.last_run_at.isoformat() if task.last_run_at else None,
            task.created_at.isoformat(), task.updated_at.isoformat()
        ))
        await db.commit()


async def get_task(task_id: str) -> Optional[Task]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return _row_to_task(dict(row))
    return None


async def get_all_tasks() -> list[Task]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks ORDER BY created_at") as cursor:
            rows = await cursor.fetchall()
            return [_row_to_task(dict(r)) for r in rows]


async def update_task(task: Task):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE tasks SET status=?, assigned_to=?, subtasks=?,
            scratchpad=?, output=?, schedule=?, next_run_at=?,
            last_run_at=?, updated_at=? WHERE id=?
        """, (
            task.status, json.dumps(task.assigned_to),
            json.dumps([s.model_dump() for s in task.subtasks]),
            json.dumps([e.model_dump() for e in task.scratchpad]),
            task.output,
            task.schedule,
            task.next_run_at.isoformat() if task.next_run_at else None,
            task.last_run_at.isoformat() if task.last_run_at else None,
            datetime.utcnow().isoformat(), task.id
        ))
        await db.commit()


async def get_scheduled_tasks() -> list:
    """Get all tasks with a schedule that are not cancelled."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE schedule IS NOT NULL AND status != 'cancelled'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_task(dict(r)) for r in rows]


async def delete_task(task_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()


def _row_to_agent(row: dict) -> Agent:
    from models import AgentMemory
    memory_data = json.loads(row.get("memory", "{}"))
    return Agent(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        avatar_index=row["avatar_index"],
        skills=json.loads(row.get("skills", "[]")),
        system_prompt=row.get("system_prompt", ""),
        workstation_id=row["workstation_id"],
        status=row.get("status", "idle"),
        memory=AgentMemory(**memory_data) if memory_data else AgentMemory(),
        model=row.get("model", "deepseek/deepseek-chat"),
        api_key=row.get("api_key", ""),
        created_at=datetime.fromisoformat(row["created_at"])
    )


def _row_to_task(row: dict) -> Task:
    from models import SubTask, ScratchpadEntryModel
    subtasks_data = json.loads(row.get("subtasks", "[]"))
    scratchpad_data = json.loads(row.get("scratchpad", "[]")) if row.get("scratchpad") else []
    next_run = row.get("next_run_at")
    last_run = row.get("last_run_at")
    return Task(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        status=row.get("status", "todo"),
        assigned_to=json.loads(row.get("assigned_to", "[]")),
        subtasks=[SubTask(**s) for s in subtasks_data],
        scratchpad=[ScratchpadEntryModel(**e) for e in scratchpad_data],
        created_by=row.get("created_by", "human"),
        output=row.get("output"),
        schedule=row.get("schedule"),
        next_run_at=datetime.fromisoformat(next_run) if next_run else None,
        last_run_at=datetime.fromisoformat(last_run) if last_run else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"])
    )


# ── Task Metrics ────────────────────────────────────────────────────────────

async def save_task_metrics(metrics: TaskMetrics):
    """Save or replace task execution metrics."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO task_metrics (task_id, data, created_at)
            VALUES (?, ?, ?)
        """, (
            metrics.task_id,
            metrics.model_dump_json(),
            metrics.created_at.isoformat(),
        ))
        await db.commit()


async def get_task_metrics(task_id: str) -> Optional[TaskMetrics]:
    """Get metrics for a specific task."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT data FROM task_metrics WHERE task_id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return TaskMetrics(**json.loads(row["data"]))
    return None


async def get_all_task_metrics(limit: int = 50) -> list[TaskMetrics]:
    """Get recent task metrics."""
    results = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT data FROM task_metrics ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                results.append(TaskMetrics(**json.loads(row["data"])))
    return results

"""Shared Scratchpad (blackboard pattern) for multi-agent collaboration."""
from __future__ import annotations
import json
import logging
import re
import threading
from typing import Optional, Callable, Awaitable
from datetime import datetime

logger = logging.getLogger(__name__)


def _validate_and_repair_json(raw: str) -> Optional[dict]:
    """Try to parse raw string as JSON, with light repair on failure.

    Returns parsed dict if successful, None if not repairable.
    """
    # Fast path: valid JSON
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return None
    except (json.JSONDecodeError, TypeError):
        pass

    # Repair attempts
    text = raw.strip()

    # Strip code fences
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()

    # Single quotes → double quotes (only outside existing double-quoted strings)
    repaired = text.replace("'", '"')

    # Trailing comma before closing brace/bracket
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

    try:
        data = json.loads(repaired)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _try_structure_content(content: str) -> str:
    """Try to parse/repair content as structured JSON. Never blocks writes.

    - If content is already valid JSON with a 'type' field → accept as-is
    - If content looks like JSON but is malformed → attempt repair
    - If content is free text → wrap as {"type":"data_export",...}
      only if it's short enough to benefit from structuring
    - Returns the (possibly unchanged) content string
    """
    stripped = content.strip()

    # Already looks like JSON? Try to validate/repair
    if stripped.startswith("{"):
        repaired = _validate_and_repair_json(stripped)
        if repaired and repaired.get("type"):
            # Valid structured JSON — use repaired version
            return json.dumps(repaired, ensure_ascii=False)
        if repaired:
            # Valid JSON but no type field — accept as-is
            return content

    # Don't wrap large free-text content (it would just add overhead)
    # Only wrap short structured-looking content
    if len(stripped) > 2000 or not stripped:
        return content

    # Content is free text — leave as-is (don't force structure on everything)
    return content


def _render_entry(entry: "ScratchpadEntry") -> str:
    """Render a scratchpad entry in agent-readable format.

    Supports structured types:
      - file_deliverable: section index + key data points + grep hints
      - data_export: compact structured data display
      - status_update: stage/message/deliverables
      - file (legacy): path + brief
    """
    content = entry.content
    # Try to detect and render structured JSON entries
    if content.lstrip().startswith("{"):
        try:
            data = json.loads(content)

            entry_type = data.get("type", "")

            if entry_type == "file_deliverable":
                # New structured file index from auto-sync
                lines = [
                    f"[{entry.key}] by {entry.author_name}:",
                    f"  📄 **{data.get('filename', '?')}** "
                    f"({data.get('file_type', 'file')}, "
                    f"{data.get('size_chars', '?')} chars)",
                    f"  Path: `{data.get('path', 'N/A')}`",
                ]
                # Summary
                summary = data.get("summary", "")
                if summary:
                    lines.append(f"  Summary: {summary}")
                # Sections table
                sections = data.get("sections", [])
                if sections:
                    lines.append("  Sections:")
                    for sec in sections[:15]:
                        kw = ", ".join(sec.get("keywords", [])[:5])
                        kw_str = f" [{kw}]" if kw else ""
                        lines.append(
                            f"    L{sec.get('line_start', '?')}-"
                            f"{sec.get('line_end', '?')}: "
                            f"{sec.get('heading', '?')}{kw_str}"
                        )
                # Key data points
                kdp = data.get("key_data_points", [])
                if kdp:
                    lines.append("  Key data:")
                    for dp in kdp[:10]:
                        lines.append(
                            f"    L{dp.get('line', '?')}: "
                            f"{dp.get('label', '?')} = {dp.get('value', '?')}"
                        )
                lines.append(
                    f"  → Targeted access: grep_workspace(\"keyword\") or "
                    f"read_file_lines(\"{data.get('path', '')}\", start, end)"
                )
                return "\n".join(lines)

            if entry_type == "data_export":
                # Structured data from agent
                label = data.get("label", "data")
                fmt = data.get("format", "")
                inner = data.get("data", data)
                if isinstance(inner, (dict, list)):
                    rendered = json.dumps(inner, indent=1, ensure_ascii=False)
                else:
                    rendered = str(inner)
                return (
                    f"[{entry.key}] by {entry.author_name} ({label}, {fmt}):\n"
                    f"{rendered}"
                )

            if entry_type == "status_update":
                stage = data.get("stage", "?")
                message = data.get("message", "")
                deliverables = data.get("deliverables", [])
                lines = [
                    f"[{entry.key}] by {entry.author_name}:",
                    f"  Stage: {stage}",
                ]
                if message:
                    lines.append(f"  Message: {message}")
                if deliverables:
                    lines.append(f"  Deliverables: {', '.join(str(d) for d in deliverables)}")
                return "\n".join(lines)

            if entry_type == "file":
                # Legacy file reference from auto-sync
                return (
                    f"[{entry.key}] by {entry.author_name}:\n"
                    f"  📄 **{data['filename']}** ({data.get('file_type', 'file')}, "
                    f"{data.get('size_chars', '?')} chars)\n"
                    f"  Path: `{data.get('path', 'N/A')}`\n"
                    f"  Brief: {data.get('brief', 'N/A')}\n"
                    f"  → To access full content: read_file(\"{data.get('path', '')}\")"
                )

            # Generic structured data with type field
            return (
                f"[{entry.key}] by {entry.author_name}:\n"
                f"{json.dumps(data, indent=2, ensure_ascii=False)}"
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Not valid JSON, fall through to raw render

    return f"[{entry.key}] by {entry.author_name}:\n{content}"


class ScratchpadEntry:
    """Single scratchpad record."""

    def __init__(self, key: str, content: str, author_id: str, author_name: str):
        self.key = key
        self.content = content
        self.author_id = author_id
        self.author_name = author_name
        self.updated_at = datetime.utcnow()


class Scratchpad:
    """
    Shared Scratchpad (blackboard pattern).
    - threading.Lock for thread-safe sync tool calls from worker.py
    - on_write async callback for WS broadcast, injected by graph.py
    - _loop set by graph.py to the asyncio event loop
    """

    def __init__(
        self,
        task_id: str,
        on_write: Optional[Callable[..., Awaitable]] = None,
    ):
        self.task_id = task_id
        self._entries: dict[str, ScratchpadEntry] = {}
        self._lock = threading.Lock()
        self._on_write = on_write
        self._loop = None  # set by graph.py to asyncio event loop

    def write(self, key: str, content: str, author_id: str, author_name: str) -> str:
        # Reject empty or whitespace-only content (typically from truncated args)
        if not content or not content.strip():
            logger.warning(
                f"[Scratchpad] REJECTED empty write: key='{key}' by {author_name}, "
                f"task={self.task_id[:8]}"
            )
            return (
                f"Error: cannot write empty content to scratchpad key [{key}]. "
                "Please provide meaningful data."
            )
        # Attempt to structure free-text content as JSON (non-blocking)
        content = _try_structure_content(content)

        logger.info(
            f"[Scratchpad] WRITE key='{key}' by {author_name} "
            f"({len(content)} chars), task={self.task_id[:8]}"
        )
        with self._lock:
            self._entries[key] = ScratchpadEntry(key, content, author_id, author_name)
        # Fire-and-forget WS broadcast from sync context
        if self._on_write and self._loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self._on_write(self.task_id, key, content, author_id, author_name),
                self._loop,
            )
        return f"Written to scratchpad: [{key}]"

    def read(self, key: Optional[str] = None) -> str:
        with self._lock:
            if key:
                entry = self._entries.get(key)
                if not entry:
                    logger.info(
                        f"[Scratchpad] READ key='{key}' → NOT FOUND, "
                        f"available keys: {list(self._entries.keys())}"
                    )
                    available = list(self._entries.keys())
                    hint = (
                        f" Available keys: {available}."
                        " Tip: use empty key to read all entries."
                    ) if available else ""
                    return f"No entry found for key: [{key}].{hint}"
                logger.info(
                    f"[Scratchpad] READ key='{key}' → "
                    f"{len(entry.content)} chars by {entry.author_name}"
                )
                return _render_entry(entry)
            # Read all
            entry_count = len(self._entries)
            total_chars = sum(len(e.content) for e in self._entries.values())
            keys = list(self._entries.keys())
            logger.info(
                f"[Scratchpad] READ ALL → {entry_count} entries, "
                f"{total_chars} total chars, keys={keys}"
            )
            if not self._entries:
                return "Scratchpad is empty."
            parts = [_render_entry(e) for e in self._entries.values()]
            return "\n---\n".join(parts)

    def read_filtered(self, readable_keys: Optional[list] = None) -> str:
        """Read scratchpad entries filtered by key prefixes.

        Args:
            readable_keys: list of allowed key prefixes. If None, returns all entries (PM behavior).
        """
        with self._lock:
            if readable_keys is None:
                # Return all entries (PM has full visibility)
                if not self._entries:
                    return "Scratchpad is empty."
                parts = [_render_entry(e) for e in self._entries.values()]
                return "\n---\n".join(parts)

            filtered = {}
            for k, e in self._entries.items():
                for prefix in readable_keys:
                    if k.startswith(prefix):
                        filtered[k] = e
                        break

            if not filtered:
                return "Scratchpad is empty (no visible entries)."
            parts = [_render_entry(e) for e in filtered.values()]
            return "\n---\n".join(parts)

    def keys(self) -> list:
        with self._lock:
            return list(self._entries.keys())

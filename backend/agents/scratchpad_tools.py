"""Factory for LangChain scratchpad tools bound to a specific agent."""
from __future__ import annotations
from typing import Optional
from langchain_core.tools import tool
from agents.scratchpad import Scratchpad


def create_scratchpad_tools(
    scratchpad: Scratchpad,
    agent_id: str,
    agent_name: str,
    is_pm: bool = False,
    subtask_id: Optional[str] = None,
    readable_subtask_ids: Optional[list] = None,
):
    """Return [read_scratchpad, write_scratchpad] LangChain tools.

    Key prefixing convention:
      - PM writes:    lifecycle:{key}  (task lifecycle info)
      - Worker writes: draft:{subtask_id}:{key} (subtask drafts)
      - PM can also write raw keys with _raw: prefix (bypasses prefixing)

    Visibility rules:
      - PM (is_pm=True): sees ALL entries
      - Worker (is_pm=False): sees lifecycle:*, own draft:{subtask_id}:*,
        and draft:{id}:* for each id in readable_subtask_ids
    """

    # Build list of readable key prefixes for workers
    _readable_prefixes: Optional[list] = None
    if not is_pm:
        prefixes = ["lifecycle:"]
        if subtask_id:
            prefixes.append(f"draft:{subtask_id}:")
        if readable_subtask_ids:
            for rid in readable_subtask_ids:
                prefix = f"draft:{rid}:"
                if prefix not in prefixes:
                    prefixes.append(prefix)
        _readable_prefixes = prefixes

    @tool
    def read_scratchpad(key: str = "") -> str:
        """Read the shared scratchpad. You MUST call this BEFORE starting your own work
        to see what other agents have already contributed. Pass empty string to read all
        visible entries, or a specific key to read one entry.

        Args:
            key: The scratchpad key to read, or empty string to read all visible entries
        Returns:
            Content from the shared scratchpad
        """
        if key:
            return scratchpad.read(key)
        # Use filtered read based on visibility rules
        if is_pm:
            return scratchpad.read_filtered(None)  # PM sees all
        return scratchpad.read_filtered(_readable_prefixes)

    @tool
    def write_scratchpad(key: str, content: str) -> str:
        """Write structured findings to the shared scratchpad for downstream agents.
        Use the same language as the task.

        Write CONCISE, STRUCTURED data — not full documents. Focus on:
        - Key findings, metrics, conclusions (not raw paragraphs)
        - File references with absolute paths (downstream agents CAN read them)

        Format as JSON for structured data:
          {"key_metrics": {...}, "files": [{"path": "/abs/path", "type": "md"}]}
        Or use concise markdown for narrative findings.

        NOTE: write_document content is auto-synced to scratchpad as a file
        reference. Use write_scratchpad for ADDITIONAL data not in documents:
        intermediate findings, structured metrics, comparison tables, etc.

        Args:
            key: A descriptive key for this entry (e.g. 'research_results', 'analysis_v1')
            content: Structured data to share (min 10 chars) — keep concise, max ~1500 chars
        Returns:
            Confirmation message
        """
        if is_pm:
            # PM writes to lifecycle zone by default
            if key.startswith("_raw:"):
                # Bypass: write raw key (strip _raw: prefix)
                actual_key = key[5:]
            else:
                actual_key = f"lifecycle:{key}"
        else:
            # Worker writes to draft zone
            sid = subtask_id or "unknown"
            actual_key = f"draft:{sid}:{key}"

        return scratchpad.write(actual_key, content, agent_id, agent_name)

    return [read_scratchpad, write_scratchpad]

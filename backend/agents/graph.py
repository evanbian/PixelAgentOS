"""LangGraph orchestration: PM Agent + Shared Scratchpad."""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional
from models import Agent, Task, SubTask, ScratchpadEntryModel
from agents.pm_agent import PMAgent, PM_AGENT_ID, PM_AGENT_NAME
from agents.scratchpad import Scratchpad
from agents.scratchpad_tools import create_scratchpad_tools
from agents.memory_tools import create_memory_tools
from agents.worker import execute_worker_task
from agents.tools import set_workspace, clear_workspace, get_pm_tools, _agent_id_var, _readable_workspaces_var
from database import update_task, update_agent_memory, update_agent_status, save_task_metrics
from models import TaskMetrics
import time as _time

logger = logging.getLogger(__name__)


def _pick_synthesis_agent_fallback(
    agents: list, subtask_results: dict, subtasks: list,
) -> Agent:
    """Fallback heuristic when PM LLM call fails.

    Picks the agent who completed the most subtasks.
    """
    counts: dict = {}
    for st in subtasks:
        if st.id in subtask_results and st.assigned_to:
            counts[st.assigned_to] = counts.get(st.assigned_to, 0) + 1

    if counts:
        best_id = max(counts, key=counts.get)
        agent_map = {a.id: a for a in agents}
        if best_id in agent_map:
            return agent_map[best_id]
    return agents[0]


def _read_best_workspace_file(ws_dir: str) -> str | None:
    """Read the best document file from a workspace directory.

    Selection priority: .md files first, then by modification time (newest),
    then by file size (largest). This handles the case where an agent writes
    multiple versions of a document during iterative refinement.
    Returns the file content string, or None if no suitable file found.
    """
    if not os.path.isdir(ws_dir):
        return None
    _doc_exts = {".md", ".txt", ".html", ".csv", ".json"}
    candidates: list[tuple[str, str, float, int]] = []  # (path, name, mtime, size)
    for fname in os.listdir(ws_dir):
        fpath = os.path.join(ws_dir, fname)
        if os.path.isfile(fpath):
            ext = os.path.splitext(fname)[1].lower()
            if ext in _doc_exts:
                stat = os.stat(fpath)
                candidates.append((fpath, fname, stat.st_mtime, stat.st_size))
    if not candidates:
        return None
    # Sort: .md first, then newest mtime, then largest size
    candidates.sort(key=lambda x: (0 if x[1].endswith(".md") else 1, -x[2], -x[3]))
    best_path, best_name, _, _ = candidates[0]
    try:
        with open(best_path, "r", encoding="utf-8") as f:
            content = f.read()
        logger.info(f"[Graph] _read_best_workspace_file: picked '{best_name}' ({len(content)} chars) from {ws_dir}")
        return content
    except Exception:
        return None


def _scan_workspace_recursive(workspace_dir: str) -> list:
    """Recursively scan workspace for files, return sorted relative paths."""
    results = []
    for dirpath, _dirnames, filenames in os.walk(workspace_dir):
        for name in filenames:
            if name.startswith("_"):
                continue
            fpath = os.path.join(dirpath, name)
            relpath = os.path.relpath(fpath, workspace_dir)
            results.append(relpath)
    return sorted(results)


def _clean_final_output(text: str, ws_url: str = "") -> str:
    """Sanitize final deliverable before showing to user.

    Removes:
      - DeepSeek DSML tags (<｜DSML｜...>)
      - Raw "Generated Files:" blocks with internal workspace paths
      - Trailing agent meta-commentary (after the last markdown HR)
    """
    import re as _r

    # 1. Strip DSML tags (DeepSeek artifacts)
    text = _r.sub(r'<[/｜|]*\s*DSML\s*[｜|]*[^>]*>', '', text)
    # Also strip incomplete DSML-style tags: </| ... > patterns
    text = _r.sub(r'</?[｜|][^>]{0,50}>', '', text)

    # 2. Remove "Generated Files:" / "**Generated Files:**" blocks
    #    These contain raw workspace paths with UUIDs — not useful to users.
    #    Pattern: starts with "Generated Files" line, continues with indented
    #    bullet lines containing /api/workspaces/ paths
    text = _r.sub(
        r'\n*-{2,3}\n\*?\*?Generated Files:?\*?\*?\n[\s\S]*$',
        '', text
    )

    # 3. Remove any stray lines that are just workspace URL paths
    if ws_url:
        lines = text.split('\n')
        cleaned_lines = [
            ln for ln in lines
            if ws_url not in ln or not ln.strip().startswith('-')
        ]
        text = '\n'.join(cleaned_lines)

    # 4. Trim trailing whitespace / blank lines
    text = text.rstrip()

    return text


async def run_task_graph(task: Task, agents: list[Agent], ws_manager) -> str:
    """
    6-phase orchestration:
    1. PM Decompose — PM splits task into subtasks
    2. Parallel Execute — run subtasks with scratchpad tools
    3. PM Review — PM reviews each subtask (1 rework chance)
    3.5. Worker Synthesis — designated agent writes final deliverable
    4. PM Acceptance — PM validates quality (read-only)
    5. Finalize — update DB + broadcast

    Supports graceful cancellation via asyncio.CancelledError.
    """
    if not agents:
        await ws_manager.emit_system_log("No agents available", "warning")
        return "No agents available."

    agent_map = {a.id: a for a in agents}
    lead = agents[0]

    # ── Init PM + Scratchpad ──────────────────────
    # Load global PM config (preferred), with per-task override (deprecated)
    from database import get_config
    pm_model = await get_config("PM_MODEL")
    pm_api_key = await get_config("PM_API_KEY")

    # Per-task override (deprecated, backward compat)
    if task.pm_model:
        pm_model = task.pm_model
    if task.pm_api_key:
        pm_api_key = task.pm_api_key

    if not pm_model or not pm_api_key:
        error_msg = "PM not configured. Please set PM model and API key in Settings."
        await ws_manager.emit_system_log(error_msg, "error")
        await ws_manager.emit_task_update(task.id, "cancelled", 0)
        task.status = "cancelled"
        await update_task(task)
        return error_msg

    pm = PMAgent(model=pm_model, api_key=pm_api_key)

    # Async lock to protect task.scratchpad read-modify-write from
    # concurrent on_scratchpad_write calls during parallel subtask execution.
    _sp_persist_lock = asyncio.Lock()

    async def on_scratchpad_write(task_id, key, content, author_id, author_name):
        # Persist scratchpad entry to task model (serialized to avoid lost writes)
        async with _sp_persist_lock:
            entry = ScratchpadEntryModel(
                key=key, content=content, author_id=author_id, author_name=author_name
            )
            # Replace existing entry with same key, or append
            task.scratchpad = [e for e in task.scratchpad if e.key != key] + [entry]
            await update_task(task)
        await ws_manager.emit_scratchpad_update(task_id, key, content, author_id, author_name)

    scratchpad = Scratchpad(task_id=task.id, on_write=on_scratchpad_write)
    scratchpad._loop = asyncio.get_event_loop()

    # PM tools: scratchpad (full visibility) + supervisor-level tools
    pm_sp_tools = create_scratchpad_tools(
        scratchpad, PM_AGENT_ID, PM_AGENT_NAME, is_pm=True,
    )
    pm_tools = get_pm_tools(extra_tools=pm_sp_tools)

    # Metrics collection
    task_metrics = TaskMetrics(task_id=task.id)
    task_start_time = _time.monotonic()

    logger.info(
        f"[Graph] Task '{task.title}' (id={task.id}) — "
        f"agents: {[(a.name, a.role, a.id[:8]) for a in agents]}"
    )
    await ws_manager.emit_system_log(
        f"PM starting task: '{task.title}' with {len(agents)} agents"
    )
    await ws_manager.emit_pm_message(f"Starting task decomposition for: {task.title}")

    try:
        # ── Phase 1: PM Decompose (0->15%) ────────────
        await ws_manager.emit_task_update(task.id, "in_progress", 5)

        # Decompose: PM only plans — no research tools to avoid duplicating worker work
        subtasks = await pm.decompose(task, agents, tools=None)
        task.subtasks = subtasks
        await update_task(task)

        for st in subtasks:
            await ws_manager.emit_subtask(task.id, {
                "id": st.id,
                "title": st.title,
                "description": st.description,
                "assigned_to": st.assigned_to,
                "status": st.status,
                "depends_on": st.depends_on,
                "read_from": st.read_from,
            })

        await ws_manager.emit_task_update(task.id, "in_progress", 15)
        await ws_manager.emit_pm_message(
            f"Decomposed into {len(subtasks)} subtasks: "
            + ", ".join(st.title for st in subtasks)
        )

        # ── Setup task workspace root ──
        workspace_dir = os.path.join(
            os.path.dirname(__file__), "..", "workspaces", task.id
        )
        os.makedirs(workspace_dir, exist_ok=True)

        try:
            # ── Phase 2+3: Parallel Execute + Review (15->80%) ──
            subtask_results: dict[str, str] = {}
            total = len(subtasks)
            completed_ids: set = set()
            replan_used = False

            # Build dependency map for quick lookup
            subtask_map: dict = {st.id: st for st in subtasks}

            async def _execute_single_subtask(st: SubTask) -> tuple:
                """Execute a single subtask with review. Returns (subtask_id, result, approved)."""
                st_start = _time.monotonic()
                agent = agent_map.get(st.assigned_to or "", agents[0])

                # Set per-subtask workspace context (isolated via contextvars).
                # Using agent.id/st.id ensures each subtask gets its own directory,
                # even when the same agent handles multiple subtasks in parallel.
                agent_ws = os.path.join(workspace_dir, agent.id, st.id)
                os.makedirs(agent_ws, exist_ok=True)
                set_workspace(agent_ws, f"/api/workspaces/{task.id}/{agent.id}/{st.id}")
                _agent_id_var.set(agent.id)

                # Set readable upstream workspaces (from read_from subtasks).
                # This allows the agent to read_file on files created by
                # upstream agents, enabling cross-workspace file references
                # via structured scratchpad entries.
                upstream_ws_dirs = []
                for dep_st_id in (st.read_from or []):
                    dep_st = subtask_map.get(dep_st_id)
                    if dep_st:
                        dep_agent = agent_map.get(dep_st.assigned_to or "", agents[0])
                        dep_ws = os.path.join(workspace_dir, dep_agent.id, dep_st_id)
                        if os.path.isdir(dep_ws):
                            upstream_ws_dirs.append(dep_ws)
                _readable_workspaces_var.set(upstream_ws_dirs)
                if upstream_ws_dirs:
                    logger.info(
                        f"[Graph] Subtask '{st.title}' can read {len(upstream_ws_dirs)} "
                        f"upstream workspaces"
                    )

                # Update status -> in_progress
                st.status = "in_progress"
                await update_task(task)
                await ws_manager.emit_subtask(task.id, {"id": st.id, "status": "in_progress"})

                dep_info = ""
                if st.depends_on:
                    dep_names = [subtask_map[d].title for d in st.depends_on if d in subtask_map]
                    dep_info = f" (after: {', '.join(dep_names)})"
                await ws_manager.emit_pm_message(
                    f"Assigning '{st.title}' to {agent.name}{dep_info}"
                )

                # Callbacks — each subtask gets its own closures
                async def on_status(aid, status, _agent=agent):
                    _agent.status = status
                    await update_agent_status(aid, status)
                    await ws_manager.emit_agent_status(aid, status)

                async def on_msg(from_id, to_id, content, msg_type):
                    await ws_manager.emit_agent_message(from_id, to_id, content, msg_type)

                # Build scratchpad + memory tools for this agent (with routing)
                readable_subtask_ids = st.read_from if st.read_from else []
                sp_tools = create_scratchpad_tools(
                    scratchpad, agent.id, agent.name,
                    is_pm=False,
                    subtask_id=st.id,
                    readable_subtask_ids=readable_subtask_ids,
                )
                mem_tools = create_memory_tools(agent.id, agent.name, loop=asyncio.get_event_loop())
                sp_tools = sp_tools + mem_tools
                sp_keys = scratchpad.keys()
                logger.info(
                    f"[Graph] Subtask '{st.title}' → "
                    f"agent={agent.name} (id={agent.id[:8]}), "
                    f"role={agent.role}, skills={agent.skills}, "
                    f"model={agent.model}, "
                    f"max_iterations={st.max_iterations or 'default'}, "
                    f"scratchpad has {len(sp_keys)} entries: {sp_keys}, "
                    f"extra_tools=[{', '.join(t.name for t in sp_tools)}]"
                )

                # Create stream callback for this subtask
                async def on_stream(chunk, _st=st):
                    await ws_manager.emit_subtask_stream(task.id, _st.id, chunk)

                # Build teammate info for request_help
                teammates_info = ""
                other_agents = [a for a in agents if a.id != agent.id]
                if other_agents:
                    teammate_lines = [
                        f"  - id=\"{a.id}\" name=\"{a.name}\" role=\"{a.role}\""
                        for a in other_agents
                    ]
                    teammates_info = (
                        "\n\nYOUR TEAMMATES (use request_help to ask them questions):\n"
                        + "\n".join(teammate_lines)
                        + "\n  Use request_help(to_agent_id=\"<id>\", question=\"...\") "
                        "when you need their expertise."
                    )

                # Execute with scratchpad
                # Build budget-aware task description
                budget_hint = ""
                if st.max_iterations > 0:
                    budget_hint = (
                        f"\n⏱️ ITERATION BUDGET: {st.max_iterations} rounds. "
                        f"Plan your work to finish within this budget.\n"
                        f"   Suggested split: ~60% research/reading, ~40% writing deliverables.\n"
                        f"   Finishing under budget = efficient. Going to the limit = wasteful."
                    )

                result, st_metrics, st_critique, st_messages = await execute_worker_task(
                    agent=agent,
                    task_description=(
                        f"OVERALL TASK: {task.title}\n"
                        + (f"Task context: {task.description}\n" if task.description and task.description != task.title else "")
                        + f"\nYour subtask: {st.title}\n"
                        f"Details: {st.description}\n\n"
                        f"PROTOCOL:\n"
                        f"1. read_scratchpad('') → see file index (sections, keywords, data points).\n"
                        f"2. grep_workspace(\"keyword\") or read_file_lines(path, start, end) for targeted retrieval.\n"
                        f"3. Do your work. write_document for deliverables (auto-indexed to scratchpad).\n"
                        f"4. write_scratchpad for key metrics as {{\"type\":\"data_export\",...}}.\n"
                        f"5. Respond in the same language as the task title."
                        + budget_hint
                        + teammates_info
                    ),
                    subtask_id=st.id,
                    on_status_change=on_status,
                    on_message=on_msg,
                    on_stream_chunk=on_stream,
                    extra_tools=sp_tools,
                    iteration_budget=st.max_iterations,
                )

                # Signal stream end
                await ws_manager.emit_subtask_stream_end(task.id, st.id)

                # Gather scratchpad + workspace context for PM review
                # Include both current subtask entries AND upstream entries
                # (from read_from subtasks) so PM can see the full picture.
                _sp_prefixes = [f"draft:{st.id}:"]
                for dep_st_id in (st.read_from or []):
                    _sp_prefixes.append(f"draft:{dep_st_id}:")
                _sp_entries_for_review = scratchpad.read_filtered(_sp_prefixes)

                _ws_files_for_review = ""
                try:
                    # Include files from current workspace
                    ws_files_list = os.listdir(agent_ws) if os.path.isdir(agent_ws) else []
                    all_ws_files = list(ws_files_list)
                    # Also include files from upstream workspaces
                    for dep_st_id in (st.read_from or []):
                        dep_st = subtask_map.get(dep_st_id)
                        if dep_st:
                            dep_agent = agent_map.get(dep_st.assigned_to or "", agents[0])
                            dep_ws = os.path.join(workspace_dir, dep_agent.id, dep_st_id)
                            if os.path.isdir(dep_ws):
                                dep_files = os.listdir(dep_ws)
                                for f in dep_files:
                                    all_ws_files.append(f"[upstream:{dep_st.title}] {f}")
                    if all_ws_files:
                        _ws_files_for_review = "\n".join(all_ws_files[:30])
                except OSError:
                    pass

                # PM Review
                logger.info(
                    f"[Graph] PM reviewing subtask '{st.title}' "
                    f"(result={len(result)} chars, "
                    f"scratchpad={len(_sp_entries_for_review)} chars, "
                    f"ws_files={len(_ws_files_for_review)} chars)"
                )
                review = await pm.review(
                    st, result, task,
                    scratchpad_content=_sp_entries_for_review,
                    workspace_files=_ws_files_for_review,
                )
                logger.info(
                    f"[Graph] PM review result: approved={review.get('approved')}, "
                    f"feedback='{review.get('feedback', '')[:100]}'"
                )
                approved = True
                review_severity = review.get("severity", "pass")

                # Three-tier review handling:
                #   "pass"  → approved, no rework
                #   "minor" → approved, lightweight rework (2 iterations)
                #   "fail"  → not approved, full rework (4 iterations)
                if review_severity == "minor":
                    # Minor issues: quick fix, still counts as approved
                    await ws_manager.emit_pm_message(
                        f"Minor issues in '{st.title}': {review.get('feedback', '')}. Quick fix..."
                    )
                    task_metrics.rework_count += 1
                    rework_feedback = (
                        f"⚠️ PM MINOR FEEDBACK — small fix needed:\n"
                        f"{review.get('feedback', '')}\n\n"
                        f"Make ONLY the specific fix mentioned above. "
                        f"Do NOT redo your entire work. 1-2 tool calls max.\n"
                        f"IMPORTANT: Respond in the same language as the task title: {task.title}"
                    )
                    result, _, _, st_messages = await execute_worker_task(
                        agent=agent,
                        task_description=rework_feedback,
                        subtask_id=st.id,
                        on_status_change=on_status,
                        on_message=on_msg,
                        on_stream_chunk=on_stream,
                        extra_tools=sp_tools,
                        _resume_messages=st_messages,
                        _resume_max_iter=2,
                    )
                    await ws_manager.emit_subtask_stream_end(task.id, st.id)
                    # Minor rework is always accepted (no re-review)

                elif review_severity == "fail":
                    await ws_manager.emit_pm_message(
                        f"Review failed for '{st.title}': {review.get('feedback', '')}. Requesting rework..."
                    )
                    task_metrics.rework_count += 1
                    rework_feedback = (
                        f"⚠️ PM REVIEW FEEDBACK — please fix the following:\n"
                        f"{review.get('feedback', '')}\n\n"
                        f"Continue from your previous work. "
                        f"Fix only what the PM flagged. "
                        f"Update your deliverables (write_document) and scratchpad as needed.\n"
                        f"IMPORTANT: Respond in the same language as the task title: {task.title}"
                    )
                    result, _, _, st_messages = await execute_worker_task(
                        agent=agent,
                        task_description=rework_feedback,
                        subtask_id=st.id,
                        on_status_change=on_status,
                        on_message=on_msg,
                        on_stream_chunk=on_stream,
                        extra_tools=sp_tools,
                        _resume_messages=st_messages,
                        _resume_max_iter=4,
                    )
                    await ws_manager.emit_subtask_stream_end(task.id, st.id)

                    # Re-gather scratchpad after rework
                    _sp_entries_for_review = scratchpad.read_filtered(
                        [f"draft:{st.id}:"]
                    )
                    try:
                        ws_files_list = os.listdir(agent_ws) if os.path.isdir(agent_ws) else []
                        _ws_files_for_review = "\n".join(ws_files_list[:20]) if ws_files_list else ""
                    except OSError:
                        _ws_files_for_review = ""

                    # Second review after fail-rework
                    review2 = await pm.review(
                        st, result, task,
                        scratchpad_content=_sp_entries_for_review,
                        workspace_files=_ws_files_for_review,
                    )
                    if review2.get("severity", "pass") == "fail":
                        approved = False

                # Aggregate subtask metrics
                st_duration = _time.monotonic() - st_start
                task_metrics.subtask_durations[st.id] = round(st_duration, 2)
                task_metrics.tool_call_count += st_metrics.tool_call_count
                for tool_name, count in st_metrics.tool_distribution.items():
                    task_metrics.tool_call_distribution[tool_name] = (
                        task_metrics.tool_call_distribution.get(tool_name, 0) + count
                    )
                task_metrics.reflection_count += st_metrics.reflection_count
                task_metrics.reflection_triggers.extend(st_metrics.reflection_triggers)
                task_metrics.llm_errors += st_metrics.llm_errors
                if st_critique:
                    task_metrics.self_critique_count += 1

                return st.id, result, approved

            # ── Parallel execution loop ──
            while len(completed_ids) < len(subtasks):
                # Find ready subtasks: all dependencies completed
                ready = [
                    st for st in subtasks
                    if st.id not in completed_ids
                    and set(st.depends_on).issubset(completed_ids)
                ]

                if not ready:
                    # Deadlock: remaining subtasks have unresolvable deps
                    remaining = [st for st in subtasks if st.id not in completed_ids]
                    logger.error(
                        f"[Graph] Deadlock detected! {len(remaining)} subtasks stuck. "
                        f"Force-executing sequentially."
                    )
                    ready = remaining

                if len(ready) > 1:
                    logger.info(
                        f"[Graph] Executing {len(ready)} subtasks in PARALLEL: "
                        f"{[st.title for st in ready]}"
                    )
                    await ws_manager.emit_pm_message(
                        f"⚡ Running {len(ready)} subtasks in parallel: "
                        + ", ".join(st.title for st in ready)
                    )

                # Execute ready subtasks concurrently
                results_batch = await asyncio.gather(
                    *[_execute_single_subtask(st) for st in ready],
                    return_exceptions=True,
                )

                for i, batch_result in enumerate(results_batch):
                    st = ready[i]
                    if isinstance(batch_result, Exception):
                        logger.error(f"[Graph] Subtask '{st.title}' raised exception: {batch_result}")
                        result_str = f"Task failed with error: {str(batch_result)}"
                        approved = False
                    else:
                        _, result_str, approved = batch_result

                    # Register result BEFORE replan so replanned subtasks
                    # get read_from access to this subtask's scratchpad data
                    subtask_results[st.id] = result_str

                    # Handle replan on failure
                    if not approved and not replan_used:
                        replan_used = True
                        remaining_sts = [
                            s for s in subtasks
                            if s.id not in completed_ids and s.id != st.id
                        ]
                        try:
                            replanned = await pm.replan(
                                task, st, result_str,
                                remaining_sts, subtask_results, agents,
                            )
                            if replanned:
                                task_metrics.replan_count += 1
                                await ws_manager.emit_pm_message(
                                    f"🔄 PM replanned: {len(replanned)} subtasks after '{st.title}' failed"
                                )
                                # Remove old remaining from subtasks, add replanned
                                remaining_ids = {s.id for s in remaining_sts}
                                subtasks = [s for s in subtasks if s.id not in remaining_ids] + replanned
                                total = len(subtasks)
                                subtask_map = {s.id: s for s in subtasks}
                                # Broadcast new subtasks to frontend
                                for new_st in replanned:
                                    await ws_manager.emit_subtask(task.id, {
                                        "id": new_st.id,
                                        "title": new_st.title,
                                        "description": new_st.description,
                                        "assigned_to": new_st.assigned_to,
                                        "status": new_st.status,
                                        "depends_on": new_st.depends_on,
                                        "read_from": new_st.read_from,
                                    })
                                task.subtasks = subtasks
                                await update_task(task)
                        except Exception as e:
                            logger.error(f"[Graph] Replan failed: {e}")

                    st.status = "done"
                    st.output = result_str
                    completed_ids.add(st.id)

                    from agents.memory import record_task_completion
                    agent = agent_map.get(st.assigned_to or "", agents[0])
                    await record_task_completion(agent.memory, agent.id, st.title, result_str)
                    await update_agent_memory(agent.id, agent.memory)
                    await update_task(task)
                    await ws_manager.emit_subtask(task.id, {
                        "id": st.id,
                        "status": "done",
                        "output": st.output,
                    })
                    await ws_manager.emit_pm_message(f"'{st.title}' completed by {agent.name}")

                # Progress: 15% -> 80% proportional to completed subtasks
                progress = 15 + int(65 * len(completed_ids) / total)
                await ws_manager.emit_task_update(task.id, "in_progress", progress)

            # ── Phase 3.5: Worker Synthesis (80->90%) ──────────
            await ws_manager.emit_task_update(task.id, "in_progress", 82)

            # Collect context for synthesis evaluation
            sp_content = scratchpad.read(None)
            ws_url = f"/api/workspaces/{task.id}"
            ws_files_text = ""
            if os.path.isdir(workspace_dir):
                ws_files = _scan_workspace_recursive(workspace_dir)
                if ws_files:
                    ws_files_text = "\n".join(
                        f"  - {relpath}: {ws_url}/{relpath}"
                        for relpath in ws_files
                    )

            # ── Heuristic pre-check: skip synthesis without LLM call ──
            # If the last subtask already produced a deliverable file that
            # covers upstream data, synthesis is redundant.
            _heuristic_skip = False
            _heuristic_st_id = None
            _last_st = subtasks[-1] if subtasks else None
            if _last_st and _last_st.id in subtask_results:
                _last_agent_id = _last_st.assigned_to or ""
                _last_ws = os.path.join(workspace_dir, _last_agent_id, _last_st.id)
                _last_file = _read_best_workspace_file(_last_ws)
                if _last_file and len(_last_file) > 500:
                    # Check if it references content from upstream subtasks
                    _upstream_titles = [s.title for s in subtasks[:-1]]
                    _ref_hits = sum(
                        1 for t in _upstream_titles
                        if t[:8].lower() in _last_file.lower()
                    )
                    if _ref_hits >= max(1, len(_upstream_titles) * 0.3):
                        _heuristic_skip = True
                        _heuristic_st_id = _last_st.id
                        logger.info(
                            f"[Graph] Synthesis heuristic SKIP: last subtask "
                            f"'{_last_st.title}' has {len(_last_file)} char file "
                            f"referencing {_ref_hits}/{len(_upstream_titles)} upstream topics"
                        )

            if _heuristic_skip:
                eval_result = {
                    "needed": False,
                    "reason": "Last subtask already produced integrated deliverable (heuristic)",
                    "final_subtask_id": _heuristic_st_id,
                }
            else:
                # ── PM evaluates synthesis need + picks agent (1 LLM call) ──
                eval_result = await pm.evaluate_and_pick_synthesis(
                    task, agents, subtask_results,
                    workspace_files=ws_files_text,
                    scratchpad_content=sp_content,
                )

            synthesis_needed = eval_result.get("needed", True)
            skip_reason = eval_result.get("reason", "")
            final_st_id = eval_result.get("final_subtask_id")

            if not synthesis_needed and final_st_id:
                # Try to match the subtask ID (PM may return truncated ID)
                matched_id = None
                for st in subtasks:
                    if st.id == final_st_id or st.id.startswith(final_st_id):
                        matched_id = st.id
                        break
                if matched_id and matched_id in subtask_results:
                    # subtask_results stores the agent's LAST LLM text response,
                    # NOT the actual document content written via write_document().
                    # We must read the real file from the workspace directory.
                    matched_st = subtask_map.get(matched_id, SubTask(id="", title="?"))
                    matched_title = matched_st.title
                    matched_agent_id = matched_st.assigned_to or ""

                    # Try to find and read the actual deliverable file
                    _st_ws = os.path.join(workspace_dir, matched_agent_id, matched_id)
                    _deliverable_content = _read_best_workspace_file(_st_ws)

                    if _deliverable_content and len(_deliverable_content) > 200:
                        synthesis_result = _deliverable_content
                        logger.info(
                            f"[Graph] Read actual deliverable file "
                            f"({len(_deliverable_content)} chars) from {_st_ws}"
                        )
                    else:
                        # Fallback: use the subtask result (agent's last response)
                        synthesis_result = subtask_results[matched_id]
                        logger.info(
                            f"[Graph] No workspace file found for subtask "
                            f"'{matched_title}', using agent's last response"
                        )

                    logger.info(
                        f"[Graph] Phase 3.5 SKIPPED: PM says synthesis not needed. "
                        f"Using subtask '{matched_title}' output ({len(synthesis_result)} chars). "
                        f"Reason: {skip_reason}"
                    )
                    await ws_manager.emit_pm_message(
                        f"Existing deliverable is sufficient — skipping extra synthesis. "
                        f"({skip_reason})"
                    )
                    await ws_manager.emit_task_update(task.id, "in_progress", 90)
                else:
                    # PM returned an ID we can't match — fall through to synthesis
                    logger.warning(
                        f"[Graph] PM said synthesis not needed but final_subtask_id "
                        f"'{final_st_id}' not matched. Proceeding with synthesis."
                    )
                    synthesis_needed = True

            if synthesis_needed:
                # Use agent picked by PM, or fallback
                agent_map_local = {a.id: a for a in agents}
                picked_id = eval_result.get("synthesis_agent_id")
                if picked_id and picked_id in agent_map_local:
                    synthesis_agent = agent_map_local[picked_id]
                    logger.info(f"[Graph] PM picked synthesis agent: {synthesis_agent.name}")
                else:
                    synthesis_agent = _pick_synthesis_agent_fallback(
                        agents, subtask_results, subtasks,
                    )
                    logger.info(
                        f"[Graph] PM pick failed, fallback to: {synthesis_agent.name}"
                    )
                await ws_manager.emit_pm_message(
                    f"Deliverables need integration — assigning synthesis to {synthesis_agent.name}..."
                )
                logger.info(
                    f"[Graph] Phase 3.5: Worker Synthesis — "
                    f"agent={synthesis_agent.name}, "
                    f"scratchpad={len(sp_content)} chars, "
                    f"workspace_files={len(ws_files_text)} chars"
                )

                # Generate synthesis subtask ID first (needed for workspace path)
                import uuid as _uuid
                synthesis_st_id = str(_uuid.uuid4())

                # Set workspace context for synthesis agent (subtask-scoped)
                synth_ws = os.path.join(workspace_dir, synthesis_agent.id, synthesis_st_id)
                os.makedirs(synth_ws, exist_ok=True)
                set_workspace(synth_ws, f"/api/workspaces/{task.id}/{synthesis_agent.id}/{synthesis_st_id}")
                _agent_id_var.set(synthesis_agent.id)

                # Build synthesis subtask
                synthesis_st = SubTask(
                    id=synthesis_st_id,
                    title="Final Report Synthesis",
                    description="Integrate all subtask outputs into the final deliverable",
                    assigned_to=synthesis_agent.id,
                    status="in_progress",
                )
                # Broadcast to frontend
                await ws_manager.emit_subtask(task.id, {
                    "id": synthesis_st.id,
                    "title": synthesis_st.title,
                    "description": synthesis_st.description,
                    "assigned_to": synthesis_st.assigned_to,
                    "status": "in_progress",
                    "depends_on": [],
                    "read_from": [],
                })

                # Build subtask summaries for the synthesis prompt
                subtask_summaries = "\n\n".join(
                    f"### {st.title}\n{subtask_results.get(st.id, 'No result')}"
                    for st in subtasks
                    if st.id in subtask_results
                )

                # Extra context
                extra_ctx = ""
                if ws_files_text:
                    extra_ctx += (
                        f"\n\nGENERATED FILES (reference by URL in your report):\n"
                        f"{ws_files_text}"
                    )

                # Synthesis agent tools: scratchpad (full read) + workspace tools
                synth_sp_tools = create_scratchpad_tools(
                    scratchpad, synthesis_agent.id, synthesis_agent.name,
                    is_pm=False,
                    subtask_id=synthesis_st_id,
                    readable_subtask_ids=[st.id for st in subtasks],
                )
                synth_mem_tools = create_memory_tools(
                    synthesis_agent.id, synthesis_agent.name,
                    loop=asyncio.get_event_loop(),
                )
                synth_extra_tools = synth_sp_tools + synth_mem_tools

                # Callbacks
                async def on_synth_status(aid, status):
                    synthesis_agent.status = status
                    await update_agent_status(aid, status)
                    await ws_manager.emit_agent_status(aid, status)

                async def on_synth_msg(from_id, to_id, content, msg_type):
                    await ws_manager.emit_agent_message(from_id, to_id, content, msg_type)

                async def on_synth_stream(chunk):
                    await ws_manager.emit_subtask_stream(task.id, synthesis_st_id, chunk)

                synth_start = _time.monotonic()
                synthesis_result, synth_metrics, synth_critique, _ = await execute_worker_task(
                    agent=synthesis_agent,
                    task_description=(
                        f"You are writing the FINAL DELIVERABLE for the following task.\n\n"
                        f"TASK GOAL: {task.title}\n"
                        f"DESCRIPTION: {task.description}\n\n"
                        f"ALL SUBTASK OUTPUTS (from your colleagues):\n"
                        f"{subtask_summaries}\n\n"
                        f"SCRATCHPAD DATA:\n"
                        f"Call read_scratchpad('') to access all shared data from agents.\n"
                        f"{extra_ctx}\n\n"
                        f"YOUR JOB:\n"
                        f"1. Read the scratchpad to get the ACTUAL data, numbers, and findings.\n"
                        f"2. Integrate ALL subtask outputs into ONE coherent, well-structured report.\n"
                        f"3. DATA FIDELITY: Use EXACT numbers and statistics from the sources. "
                        f"NEVER fabricate or alter any data.\n"
                        f"4. FILE REFERENCES: Use markdown image syntax ![desc](url) for images, "
                        f"[filename](url) for other files.\n"
                        f"5. Use write_document to save the final report as a file.\n"
                        f"6. LANGUAGE: Write in the same language as the task title.\n"
                        f"7. Be thorough — this is the final deliverable the user will see."
                    ),
                    subtask_id=synthesis_st_id,
                    on_status_change=on_synth_status,
                    on_message=on_synth_msg,
                    on_stream_chunk=on_synth_stream,
                    extra_tools=synth_extra_tools,
                )
                await ws_manager.emit_subtask_stream_end(task.id, synthesis_st_id)

                # Record synthesis metrics
                synth_duration = _time.monotonic() - synth_start
                task_metrics.subtask_durations[synthesis_st_id] = round(synth_duration, 2)
                task_metrics.tool_call_count += synth_metrics.tool_call_count
                for tool_name, count in synth_metrics.tool_distribution.items():
                    task_metrics.tool_call_distribution[tool_name] = (
                        task_metrics.tool_call_distribution.get(tool_name, 0) + count
                    )
                if synth_critique:
                    task_metrics.self_critique_count += 1

                synthesis_st.status = "done"
                synthesis_st.output = synthesis_result
                await ws_manager.emit_subtask(task.id, {
                    "id": synthesis_st.id,
                    "status": "done",
                    "output": synthesis_result[:500] + "..." if len(synthesis_result) > 500 else synthesis_result,
                })

                logger.info(
                    f"[Graph] Phase 3.5 done: synthesis={len(synthesis_result)} chars, "
                    f"duration={synth_duration:.1f}s"
                )

            await ws_manager.emit_task_update(task.id, "in_progress", 90)

            # ── Phase 4: PM Acceptance Check (90->95%) ──────────
            # Set workspace to task root for PM (sees all agent outputs)
            set_workspace(workspace_dir, f"/api/workspaces/{task.id}")
            _agent_id_var.set(None)
            await ws_manager.emit_pm_message("PM reviewing final deliverable...")

            # Re-scan workspace (synthesis agent may have created new files)
            ws_files_text = ""
            if os.path.isdir(workspace_dir):
                ws_files = _scan_workspace_recursive(workspace_dir)
                if ws_files:
                    ws_files_text = "\n".join(
                        f"  - {relpath}: {ws_url}/{relpath}"
                        for relpath in ws_files
                    )

            logger.info(
                f"[Graph] Phase 4: PM Acceptance — "
                f"synthesis={len(synthesis_result)} chars, "
                f"workspace_files={len(ws_files_text)} chars"
            )
            acceptance_raw = await pm.synthesize(
                task, subtask_results,
                scratchpad_content=sp_content,
                workspace_files=ws_files_text,
                tools=pm_tools,
            )
            logger.info(f"[Graph] Acceptance raw: {len(acceptance_raw)} chars")

            # Clean DSML tags from acceptance output before parsing
            import json as _json
            import re as _re
            if "DSML" in acceptance_raw or "｜" in acceptance_raw:
                acceptance_raw = _re.sub(
                    r'<[｜|]DSML[｜|][^>]*>', '', acceptance_raw, flags=_re.DOTALL
                ).strip()
                logger.info(f"[Graph] Cleaned DSML from acceptance, remaining={len(acceptance_raw)} chars")

            # ── Try to read actual workspace file as deliverable ──
            # synthesis_result from execute_worker_task is the agent's last LLM
            # text response (e.g. "I have completed the report..."), NOT the
            # actual document content written via write_document().  We must
            # check the workspace for real document files.
            if synthesis_needed:
                # Synthesis agent wrote to synth_ws
                _final_doc = _read_best_workspace_file(synth_ws)
                if _final_doc and len(_final_doc) > len(synthesis_result):
                    logger.info(
                        f"[Graph] Using actual synthesis file "
                        f"({len(_final_doc)} chars) instead of agent response "
                        f"({len(synthesis_result)} chars)"
                    )
                    synthesis_result = _final_doc

            # Parse acceptance JSON; synthesis_result is the primary deliverable
            final_output = synthesis_result  # default: use synthesis as-is
            try:
                json_match = _re.search(r'\{[\s\S]*\}', acceptance_raw)
                verdict = _json.loads(json_match.group()) if json_match else _json.loads(acceptance_raw)
                quality_score = verdict.get("quality_score", "N/A")
                issues = verdict.get("issues", [])
                logger.info(
                    f"[Graph] Acceptance: status={verdict.get('status')}, "
                    f"score={quality_score}"
                )
                if issues:
                    note = "; ".join(issues)
                    logger.info(f"[Graph] Acceptance issues: {note}")
            except Exception as e:
                logger.warning(f"[Graph] Acceptance JSON parse failed: {e}")

            # ── Clean final output before delivery ──
            final_output = _clean_final_output(final_output, ws_url)
            logger.info(f"[Graph] Final output: {len(final_output)} chars")

            await ws_manager.emit_task_update(task.id, "in_progress", 95)

            # ── Phase 5: Finalize ─────────────────────────
            task.status = "done"
            task.output = final_output
            await update_task(task)

            # Save execution metrics
            task_metrics.total_duration_s = round(_time.monotonic() - task_start_time, 2)
            task_metrics.subtask_count = len(subtasks)
            try:
                await save_task_metrics(task_metrics)
                logger.info(
                    f"[Graph] Metrics saved: duration={task_metrics.total_duration_s}s, "
                    f"tools={task_metrics.tool_call_count}, "
                    f"reflections={task_metrics.reflection_count}, "
                    f"reworks={task_metrics.rework_count}"
                )
                # Broadcast metrics to frontend
                await ws_manager.emit_task_metrics(task.id, {
                    "total_duration_s": task_metrics.total_duration_s,
                    "subtask_count": task_metrics.subtask_count,
                    "tool_call_count": task_metrics.tool_call_count,
                    "tool_call_distribution": task_metrics.tool_call_distribution,
                    "reflection_count": task_metrics.reflection_count,
                    "self_critique_count": task_metrics.self_critique_count,
                    "rework_count": task_metrics.rework_count,
                    "replan_count": task_metrics.replan_count,
                    "llm_errors": task_metrics.llm_errors,
                    "subtask_durations": task_metrics.subtask_durations,
                })
            except Exception as e:
                logger.warning(f"[Graph] Failed to save metrics: {e}")

            await ws_manager.emit_task_update(task.id, "done", 100, final_output)
            await ws_manager.emit_pm_message(f"Task '{task.title}' delivered!")
            await ws_manager.emit_system_log(f"Task '{task.title}' completed successfully!")

            return final_output
        finally:
            # Clean up ephemeral skill installations from all agent workspaces
            if os.path.isdir(workspace_dir):
                for entry in os.listdir(workspace_dir):
                    skills_dir = os.path.join(workspace_dir, entry, "_skills")
                    if os.path.isdir(skills_dir):
                        import shutil
                        shutil.rmtree(skills_dir, ignore_errors=True)
                        logger.info(f"[Graph] Cleaned workspace skills: {skills_dir}")
            clear_workspace()

    except asyncio.CancelledError:
        logger.info(f"Task '{task.title}' ({task.id}) was cancelled")

        # End active streams + clear incomplete subtask data
        for st in task.subtasks:
            if st.status == "in_progress":
                await ws_manager.emit_subtask_stream_end(task.id, st.id)
                st.output = None
                st.status = "cancelled"
                await ws_manager.emit_subtask(task.id, {
                    "id": st.id, "status": "cancelled", "output": "",
                })
            elif st.status == "todo":
                st.status = "cancelled"
                await ws_manager.emit_subtask(task.id, {
                    "id": st.id, "status": "cancelled",
                })

        # Clear incomplete scratchpad + task output
        task.scratchpad = []
        task.output = None
        task.status = "cancelled"
        await update_task(task)

        # Notify frontend to clear scratchpad for this task
        await ws_manager.broadcast("scratchpad:clear", {"task_id": task.id})

        # Reset all assigned agents to idle
        for a in agents:
            a.status = "idle"
            await update_agent_status(a.id, "idle")
            await ws_manager.emit_agent_status(a.id, "idle")

        # Clean up ephemeral skill installations on cancel too
        if os.path.isdir(workspace_dir):
            for entry in os.listdir(workspace_dir):
                skills_dir = os.path.join(workspace_dir, entry, "_skills")
                if os.path.isdir(skills_dir):
                    import shutil
                    shutil.rmtree(skills_dir, ignore_errors=True)
                    logger.info(f"[Graph] Cleaned workspace skills (cancel): {skills_dir}")

        await ws_manager.emit_pm_message(
            f"Task '{task.title}' has been cancelled. Incomplete data cleared."
        )
        return "Task cancelled."

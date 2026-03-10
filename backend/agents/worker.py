"""Worker Agent: executes assigned subtasks using LLM + tools."""
from __future__ import annotations
import asyncio
import logging
import os
import re
from typing import Optional
from dataclasses import dataclass, field as dc_field
from litellm import acompletion
import json

from models import Agent
from agents.memory import add_to_memory, get_memory_context, get_short_term_messages
from agents.tools import get_tools_for_agent

logger = logging.getLogger(__name__)


# ── Adaptive Reflection ───────────────────────────────────────────────────

@dataclass
class _LoopMetrics:
    """Track agentic loop execution state for reflection decisions."""
    tool_call_count: int = 0
    consecutive_errors: int = 0
    recent_tools: list = dc_field(default_factory=list)      # last 5 tool names
    recent_result_lens: list = dc_field(default_factory=list) # last 3 result lengths
    reflection_count: int = 0
    has_deliverable: bool = False  # True once write_document or write_scratchpad called
    # Observability fields
    tool_distribution: dict = dc_field(default_factory=dict)  # {tool_name: count}
    reflection_triggers: list = dc_field(default_factory=list) # trigger reasons
    llm_errors: int = 0


def _detect_task_complexity(task_description: str) -> str:
    """Simple heuristic to classify task complexity."""
    indicators = [
        "research", "analyze", "compare", "investigate", "comprehensive",
        "研究", "分析", "比较", "调查", "综合",
    ]
    score = sum(1 for k in indicators if k in task_description.lower())
    if len(task_description) > 500:
        score += 1
    return "complex" if score >= 2 else "simple"


def _should_reflect(
    metrics: _LoopMetrics, complexity: str, iteration: int, max_iter: int,
) -> Optional[str]:
    """Return a trigger reason string if reflection should fire, else None."""
    if metrics.tool_call_count == 0:
        return None
    if iteration >= max_iter - 1:
        return None  # don't reflect on the last iteration

    period = 6 if complexity == "complex" else 8

    # 1. Periodic checkpoint (less frequent to avoid interrupting productive work)
    if metrics.tool_call_count % period == 0:
        return f"Periodic checkpoint after {metrics.tool_call_count} tool calls."

    # 2. Consecutive errors (keep — genuine anomaly signal)
    if metrics.consecutive_errors >= 2:
        return f"Warning: {metrics.consecutive_errors} consecutive tool errors detected."

    # 3. Low progress (keep — genuine anomaly signal)
    if (len(metrics.recent_result_lens) >= 3
            and sum(metrics.recent_result_lens[-3:]) < 100):
        return "Low output detected in recent tool calls — results may not be productive."

    return None


def _build_reflection_prompt(
    metrics: _LoopMetrics,
    trigger_reason: str,
    iteration: int,
    max_iterations: int,
) -> str:
    """Build a lightweight reflection prompt (<200 tokens)."""
    recent = ", ".join(metrics.recent_tools[-3:]) if metrics.recent_tools else "none"
    return (
        f"[Reflection Checkpoint — iteration {iteration + 1}/{max_iterations}]\n"
        f"You have used {metrics.tool_call_count} tool calls so far.\n"
        f"Recent tools: {recent}\n"
        f"{trigger_reason}\n\n"
        "Briefly consider:\n"
        "1. Am I making progress toward the goal?\n"
        "2. Should I change my approach?\n"
        "3. Do I have enough information to write my final answer?\n\n"
        "If ready, stop calling tools and write your final response."
    )


def _resolve_model(model: str) -> str:
    """Ensure model string is in LiteLLM provider/model format."""
    if "/" in model:
        return model
    return f"openai/{model}"


def _resolve_llm_kwargs(agent: Agent) -> dict:
    """Extract api_key / api_base kwargs from agent config.

    Supports "key|||base" format for custom endpoints.
    """
    kwargs: dict = {}
    if agent.api_key:
        if "|||" in agent.api_key:
            key_part, base_part = agent.api_key.split("|||", 1)
            kwargs["api_key"] = key_part
            kwargs["api_base"] = base_part
        else:
            kwargs["api_key"] = agent.api_key
    return kwargs


# ── Scratchpad argument streaming parser ────────────────────────────────────

class _ScratchpadArgParser:
    """Extract the 'content' value from streaming write_scratchpad JSON args.

    As tool-call argument chunks arrive (fragments of a JSON string like
    ``{"key":"x","content":"...long text..."}``), this parser detects when
    we are inside the ``"content"`` value and returns the unescaped text so
    it can be streamed to the frontend in real-time.
    """

    _SEARCHING = 0   # looking for "content": "
    _STREAMING = 1   # inside the content string value
    _DONE = 2        # finished (closing quote found)

    def __init__(self):
        self._state = self._SEARCHING
        self._buf = ""
        self._esc = False          # next char is escaped
        self._header_sent = False  # whether we emitted the separator

    def feed(self, chunk: str) -> str:
        """Feed an argument chunk. Returns content text to stream (may be empty)."""
        if self._state == self._DONE:
            return ""

        if self._state == self._SEARCHING:
            self._buf += chunk
            for marker in ('"content":"', '"content": "', '"content" : "'):
                pos = self._buf.find(marker)
                if pos >= 0:
                    self._state = self._STREAMING
                    remaining = self._buf[pos + len(marker):]
                    self._buf = ""
                    return self._process(remaining) if remaining else ""
            # keep buffer small — only need tail for marker detection
            if len(self._buf) > 60:
                self._buf = self._buf[-30:]
            return ""

        # _STREAMING
        return self._process(chunk)

    def _process(self, text: str) -> str:
        out: list[str] = []
        _esc_map = {"n": "\n", "t": "\t", "r": "\r", '"': '"',
                     "\\": "\\", "/": "/"}
        for ch in text:
            if self._esc:
                self._esc = False
                out.append(_esc_map.get(ch, ch))
            elif ch == "\\":
                self._esc = True
            elif ch == '"':
                self._state = self._DONE
                break
            else:
                out.append(ch)
        return "".join(out)


# ── Planning Phase ─────────────────────────────────────────────────────────

def _extract_first_json(text: str) -> Optional[str]:
    """Extract the first balanced JSON object from text.

    Handles nested braces correctly, unlike greedy/non-greedy regex.
    """
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


async def _run_planning_phase(
    agent: Agent,
    task_description: str,
    on_status_change=None,
    on_stream_chunk=None,
) -> Optional[dict]:
    """Lightweight pre-execution planning: keyword match → ecosystem search if needed.

    Flow:
      0. Quick check: does this task even need skills? (skip for generic tasks)
      1. Zero-cost keyword match against installed skills
      2. Ecosystem search only for specialized domains
      3. LLM selects which skills to install (1 call)
      4. Install selected skills

    Returns dict with:
      - "context": str to inject as user message (or None to skip)
      - "installed": list of installed package names
    Or None if planning was skipped / failed.
    """
    from agents.tools import _agent_id_var, find_skill, install_skill
    from agents.skill_loader import load_merged_skills

    litellm_model = _resolve_model(agent.model)
    extra_kwargs = _resolve_llm_kwargs(agent)
    agent_id = _agent_id_var.get(None) or agent.id

    # ── Step 0: Quick task-type check — skip skill search for generic tasks ──
    # Tasks like "research X", "write a report", "analyze data" don't need
    # ecosystem skills. Only specialized tasks (image processing, PDF generation,
    # chart creation, etc.) benefit from skill search.
    _GENERIC_TASK_SIGNALS = [
        "research", "investigate", "search", "find information",
        "write a report", "write report", "summarize", "analysis",
        "analyze", "compare", "review", "study", "gather",
        "调研", "研究", "搜索", "分析", "总结", "撰写", "报告",
        "对比", "评估", "综述", "梳理", "整理",
    ]
    task_lower = task_description.lower()
    is_generic = any(signal in task_lower for signal in _GENERIC_TASK_SIGNALS)

    _SPECIALIZED_TASK_SIGNALS = [
        "image", "photo", "picture", "chart", "graph", "plot",
        "pdf", "excel", "spreadsheet", "powerpoint", "pptx",
        "audio", "video", "3d", "render", "svg", "animation",
        "ocr", "scrape", "crawl", "deploy", "docker",
        "图片", "图表", "可视化", "渲染", "部署",
    ]
    is_specialized = any(signal in task_lower for signal in _SPECIALIZED_TASK_SIGNALS)

    # Build current skills summary
    current_skills = load_merged_skills(agent_id)

    # ── Step 1: Zero-cost keyword matching (replaces LLM gap analysis) ──
    matched = _match_skills_to_task(task_description, current_skills)

    if matched:
        # Skills match found — skip ecosystem search entirely.
        # Pre-load matched skill content so agent doesn't need to call
        # read_skill() separately (saves 1 tool call per matched skill).
        names = ", ".join(matched)
        logger.info(
            f"[{agent.name}] Planning: keyword match found {matched}, "
            f"skipping ecosystem search, pre-loading skill content"
        )
        if on_stream_chunk:
            await on_stream_chunk(
                f"✅ Matched skills: {names} — loading instructions...\n\n"
            )

        # Build pre-loaded skill instructions using the canonical resolver
        # (same logic as read_skill tool: regex path fix + explicit script listing)
        from agents.skill_loader import resolve_skill_content

        skill_instructions = []
        for skill_name in matched:
            skill_def = current_skills.get(skill_name)
            if skill_def and skill_def.content:
                content = resolve_skill_content(skill_def)
                skill_instructions.append(
                    f"=== SKILL: {skill_def.name} ===\n"
                    f"{skill_def.description}\n\n{content}\n"
                    f"=== END SKILL ==="
                )

        context_parts = [
            f"[Planning Result] Matched skills: [{names}]. "
            f"Their full instructions are pre-loaded below — "
            f"you do NOT need to call read_skill() for these."
        ]
        if skill_instructions:
            context_parts.append("\n\n".join(skill_instructions))
        else:
            context_parts.append(
                f"Call read_skill(name) for [{names}] to load instructions."
            )

        return {
            "context": "\n\n".join(context_parts),
            "installed": [],
        }

    # ── Step 0b: If generic task with no skill match, skip ecosystem search ──
    if is_generic and not is_specialized:
        logger.info(
            f"[{agent.name}] Planning: generic task detected, "
            f"skipping ecosystem search"
        )
        if on_stream_chunk:
            await on_stream_chunk(
                "📋 Generic task — using built-in tools directly\n\n"
            )
        return {
            "context": (
                "[Planning Result] This task is best handled with built-in tools "
                "(web_search, write_document, code_execute, etc.). "
                "No skill installation needed."
            ),
            "installed": [],
        }

    # No keyword match on specialized task — search ecosystem
    if on_stream_chunk:
        if not current_skills:
            await on_stream_chunk("🔎 Searching ecosystem for specialized skills...\n")
        else:
            await on_stream_chunk("🔎 No skill match — searching ecosystem...\n")

    # ── Step 2: Search skill ecosystem (1 query, derived from task) ──
    # Build a concise search query from the task description
    # Truncate to first 200 chars for a focused query
    search_query = task_description[:200].strip()

    try:
        result = await asyncio.to_thread(
            find_skill.invoke, {"query": search_query}
        )
        logger.info(f"[{agent.name}] find_skill: {result[:200]}")

        if "No skills found" in result or "Error" in result:
            if on_stream_chunk:
                await on_stream_chunk(
                    "ℹ️ No ecosystem skills found — proceeding with built-in tools\n\n"
                )
            return {
                "context": (
                    "[Planning Result] No matching skills found (installed or ecosystem). "
                    "Use built-in tools (code_execute, web_search, etc.) to complete the task."
                ),
                "installed": [],
            }

        # ── Step 3: LLM selects which skills to install (1 LLM call) ──
        if on_stream_chunk:
            await on_stream_chunk("🤔 Selecting best skills to install...\n")

        selection_prompt = (
            f"You need skills for this task:\n{task_description[:500]}\n\n"
            f"Search results:\n{result}\n\n"
            "Which skills should be installed? Pick the MOST relevant (max 2).\n"
            "Respond ONLY with JSON:\n"
            '{"install": ["owner/repo@skill-name", ...]}\n'
            "Use an empty list if none are useful."
        )

        resp = await acompletion(
            model=litellm_model,
            messages=[{"role": "user", "content": selection_prompt}],
            max_tokens=300,
            temperature=0.1,
            **extra_kwargs,
        )
        if not resp.choices:
            logger.warning(f"[{agent.name}] Skill selection: empty choices")
            return None

        raw = resp.choices[0].message.content.strip()
        logger.info(f"[{agent.name}] Skill selection: {raw[:200]}")

        json_str = _extract_first_json(raw)
        packages = []
        if json_str:
            selection = json.loads(json_str)
            packages = selection.get("install", [])

        if not packages:
            if on_stream_chunk:
                await on_stream_chunk(
                    "ℹ️ No suitable skills found — proceeding with built-in tools\n\n"
                )
            return {
                "context": (
                    "[Planning Result] Searched ecosystem but no suitable skills. "
                    "Use built-in tools to complete the task."
                ),
                "installed": [],
            }

        # ── Step 4: Install selected skills ──
        installed = []
        for pkg in packages[:2]:  # max 2 installs
            if on_stream_chunk:
                await on_stream_chunk(f"📦 Installing skill: {pkg}...\n")
            try:
                install_result = await asyncio.to_thread(
                    install_skill.invoke, {"package": pkg}
                )
                installed.append(pkg)
                skill_name = pkg.split("@")[-1] if "@" in pkg else pkg.split("/")[-1]
                logger.info(f"[{agent.name}] Installed: {pkg} → {install_result[:200]}")
                if on_stream_chunk:
                    await on_stream_chunk(f"  ✅ {skill_name} installed\n")
            except Exception as e:
                logger.warning(f"[{agent.name}] Install failed for {pkg}: {e}")
                if on_stream_chunk:
                    await on_stream_chunk(f"  ⚠️ {pkg} install failed\n")

        installed_names = []
        for pkg in installed:
            name = pkg.split("@")[-1] if "@" in pkg else pkg.split("/")[-1]
            installed_names.append(name)

        if on_stream_chunk:
            if installed_names:
                await on_stream_chunk(
                    f"🚀 {len(installed_names)} skill(s) ready — starting execution\n\n"
                )
            else:
                await on_stream_chunk(
                    "⚠️ No skills installed — proceeding with built-in tools\n\n"
                )

        # Update agent.skills in-memory only (workspace skills are ephemeral)
        if installed_names:
            new_skills = [s for s in installed_names if s not in (agent.skills or [])]
            if new_skills:
                agent.skills = list(agent.skills or []) + new_skills
                logger.info(
                    f"[{agent.name}] Agent skills updated (in-memory): "
                    f"+{new_skills} → {agent.skills}"
                )

        # Prompt agent to read newly installed skills
        read_hint = ""
        if installed_names:
            names_list = ", ".join(installed_names)
            read_hint = (
                f"\n\nYou just installed these skills: {names_list}. "
                "NEXT STEP: Call read_skill(name) for each skill to load its "
                "full instructions before proceeding."
            )

        return {
            "context": (
                f"[Planning Result] Newly installed skills: "
                f"{', '.join(installed_names)}.{read_hint}"
            ),
            "installed": installed,
        }

    except json.JSONDecodeError as e:
        logger.warning(f"[{agent.name}] Planning JSON parse error: {e}")
        if on_stream_chunk:
            await on_stream_chunk("📋 Planning: proceeding with current skills\n\n")
        return None
    except Exception as e:
        logger.warning(f"[{agent.name}] Planning phase error: {e}")
        if on_stream_chunk:
            await on_stream_chunk("📋 Planning: skipped (error) — proceeding\n\n")
        return None


# ── Public API ──────────────────────────────────────────────────────────────

async def execute_worker_task(
    agent: Agent,
    task_description: str,
    subtask_id: Optional[str] = None,
    on_status_change=None,  # async callback(agent_id, status)
    on_message=None,        # async callback(from_id, to_id, content, type)
    on_stream_chunk=None,   # async callback(chunk: str)
    extra_tools: Optional[list] = None,
    help_depth: int = 0,
    iteration_budget: int = 0,
    _resume_messages: Optional[list] = None,
    _resume_max_iter: Optional[int] = None,
) -> tuple:
    """Execute a task as a worker agent.

    Returns (result_str, loop_metrics, did_critique, messages).
    The messages list can be passed back as _resume_messages for rework
    to continue from existing context instead of restarting from scratch.

    Args:
        iteration_budget: PM-assigned iteration budget (0 = use default).
            Clamped to 4-10 range. Overrides the default 10.
        _resume_messages: If provided, skip system prompt / planning and
            continue from this message history. A new user message with
            task_description (PM feedback) is appended before resuming.
        _resume_max_iter: Override max_iterations for resume runs (default 5).
    """
    if on_status_change:
        await on_status_change(agent.id, "thinking")

    tools = get_tools_for_agent(agent.skills, agent.role, extra_tools=extra_tools)

    # Strip request_help from nested helper agents to prevent recursion
    if help_depth >= 1:
        tools = [t for t in tools if t.name != "request_help"]

    tool_map = {t.name: t for t in tools}
    litellm_tools = _build_litellm_tools(tools)

    if _resume_messages is not None:
        # ── REWORK MODE: continue from previous context ──
        messages = _resume_messages
        # Inject PM feedback as a new user message
        messages.append({"role": "user", "content": task_description})
        loop_max = _resume_max_iter or 5
        logger.info(
            f"[{agent.name}] Resuming agentic loop with PM feedback "
            f"(history={len(messages)} msgs, max_iter={loop_max})"
        )
    else:
        # ── NORMAL MODE: build fresh context ──
        memory_context = await get_memory_context(agent.memory, agent.id, task_description)
        system_content = _build_system_prompt(
            agent, memory_context, extra_tools=extra_tools, task_hint=task_description,
        )

        messages: list[dict] = [{"role": "system", "content": system_content}]
        for msg in get_short_term_messages(agent.memory):
            messages.append(msg)
        messages.append({"role": "user", "content": task_description})

        # ── Planning Phase: analyze task → detect skill gaps → auto-install ──
        # Only for primary workers (not helpers, not help responses)
        if help_depth == 0 and subtask_id and subtask_id != "__help__":
            planning_result = await _run_planning_phase(
                agent=agent,
                task_description=task_description,
                on_status_change=on_status_change,
                on_stream_chunk=on_stream_chunk,
            )
            if planning_result:
                # If skills were installed, rebuild system prompt (new skills in XML)
                if planning_result.get("installed"):
                    system_content = _build_system_prompt(
                        agent, memory_context, extra_tools=extra_tools,
                        task_hint=task_description,
                    )
                    messages[0] = {"role": "system", "content": system_content}
                    logger.info(
                        f"[{agent.name}] System prompt rebuilt after installing "
                        f"{len(planning_result['installed'])} skill(s)"
                    )

                # Inject planning context so the agentic loop knows the plan
                planning_ctx = planning_result.get("context", "")
                if planning_ctx:
                    messages.append({"role": "user", "content": planning_ctx})

        # Determine iteration limit:
        # 1. Helper agents: always 5
        # 2. PM-assigned budget (iteration_budget > 0): use that
        # 3. Default: 10
        if help_depth >= 1:
            loop_max = 5
        elif iteration_budget > 0:
            loop_max = max(4, min(10, iteration_budget))
        else:
            loop_max = 10

    if on_status_change:
        await on_status_change(agent.id, "working")

    result, loop_metrics = await _run_agentic_loop(
        agent=agent,
        messages=messages,
        tools=litellm_tools,
        tool_map=tool_map,
        on_status_change=on_status_change,
        on_message=on_message,
        on_stream_chunk=on_stream_chunk,
        max_iterations=loop_max,
        help_depth=help_depth,
        enable_reflection=(help_depth == 0),
        task_description=task_description,
    )

    # Self-critique removed: PM review already provides external quality gate.
    did_critique = False

    if not subtask_id:
        await add_to_memory(agent.memory, "user", task_description)
        await add_to_memory(agent.memory, "assistant", result)

    if on_status_change:
        await on_status_change(agent.id, "idle")

    return result, loop_metrics, did_critique, messages


# ── Agentic loop ────────────────────────────────────────────────────────────

async def _run_agentic_loop(
    agent: Agent,
    messages: list[dict],
    tools: list[dict],
    tool_map: dict,
    on_status_change=None,
    on_message=None,
    on_stream_chunk=None,
    max_iterations: int = 15,
    help_depth: int = 0,
    enable_reflection: bool = True,
    task_description: str = "",
    llm_extra_kwargs: Optional[dict] = None,
) -> tuple:
    """Run the agentic tool-use loop.

    When *on_stream_chunk* is provided **every** LLM call uses ``stream=True``
    so the user sees real-time token output including scratchpad content as it
    is generated.

    Args:
        llm_extra_kwargs: Optional dict of extra kwargs for acompletion (e.g. api_key/api_base).
            If provided, overrides agent.api_key based kwargs. Used by PM Agent.

    Returns ``(result_str, reflection_count)``.
    """
    litellm_model = _resolve_model(agent.model)

    extra_kwargs: dict = {}
    if llm_extra_kwargs:
        extra_kwargs = dict(llm_extra_kwargs)
    else:
        extra_kwargs = _resolve_llm_kwargs(agent)

    # Role-aware max_tokens: Writer/Analyst roles need more tokens for long
    # document content in tool_call arguments. DeepSeek consumes reasoning
    # tokens first, so 4000 is often insufficient for report generation.
    _high_token_roles = {"writer", "analyst", "designer"}
    _agent_role_lower = (getattr(agent, "role", "") or "").lower()
    loop_max_tokens = 8000 if _agent_role_lower in _high_token_roles else 4000

    last_content = ""
    metrics = _LoopMetrics()
    complexity = _detect_task_complexity(task_description) if enable_reflection else "simple"
    llm_consecutive_errors = 0  # for exponential backoff
    logger.info(
        f"[{agent.name}] === agentic loop start === "
        f"(model={litellm_model}, max_iter={max_iterations}, "
        f"tools={[t['function']['name'] for t in tools] if tools else []})"
    )
    for iteration in range(max_iterations):
        force_no_tools = iteration >= max_iterations - 1
        use_tools = tools if (tools and not force_no_tools) else None

        logger.info(f"[{agent.name}] iteration {iteration + 1}/{max_iterations}")

        try:
            # Exponential backoff on consecutive LLM failures
            if llm_consecutive_errors > 0:
                backoff = min(2 ** llm_consecutive_errors, 16)
                logger.info(
                    f"[{agent.name}] backoff {backoff}s after "
                    f"{llm_consecutive_errors} LLM error(s)"
                )
                await asyncio.sleep(backoff)

            if on_stream_chunk:
                content, tool_calls = await _streaming_llm_call(
                    model=litellm_model,
                    messages=messages,
                    tools=use_tools,
                    on_stream_chunk=on_stream_chunk,
                    extra_kwargs=extra_kwargs,
                    max_tokens=loop_max_tokens,
                )
            else:
                content, tool_calls = await _blocking_llm_call(
                    model=litellm_model,
                    messages=messages,
                    tools=use_tools,
                    extra_kwargs=extra_kwargs,
                    max_tokens=loop_max_tokens,
                )

            llm_consecutive_errors = 0  # reset on success

            # Clean DeepSeek DSML tags from content (can appear mid-loop)
            if content and ("DSML" in content or "｜" in content):
                import re as _re
                cleaned = _re.sub(r'<[｜|]DSML[｜|][^>]*>', '', content, flags=_re.DOTALL).strip()
                if cleaned != content:
                    logger.info(
                        f"[{agent.name}] Cleaned DSML from content: "
                        f"{len(content)} → {len(cleaned)} chars"
                    )
                    content = cleaned if cleaned else None

            if content:
                last_content = content
                logger.info(
                    f"[{agent.name}] LLM content ({len(content)} chars): "
                    f"{content[:150]}..."
                )

            if tool_calls:
                logger.info(
                    f"[{agent.name}] LLM requested {len(tool_calls)} tool call(s): "
                    f"{[tc['function']['name'] for tc in tool_calls]}"
                )
                # Append assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": tool_calls,
                })
                # Execute each tool call
                for tc in tool_calls:
                    tc_name = tc["function"]["name"]
                    tc_id = tc["id"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    logger.info(
                        f"[{agent.name}] tool_call: {tc_name}({args})"
                    )

                    # DeepSeek fix: write_document with empty args
                    # DeepSeek sometimes puts document content in message body
                    # instead of tool call arguments due to max_tokens truncation.
                    # Strategy: try current content first, then last_content as
                    # fallback (content from a previous iteration that may contain
                    # the actual report the model was trying to write).
                    _skip_invoke = False
                    if not args and tc_name == "write_document":
                        # Pick the best available content source
                        _candidate = content if (content and len(content) > 200) else None
                        if not _candidate and last_content and len(last_content) > 200:
                            _candidate = last_content
                            logger.info(
                                f"[{agent.name}] Using last_content as fallback "
                                f"({len(last_content)} chars)"
                            )

                        if _candidate and len(_candidate) > 200:
                            # Substantial content available — inject as args
                            logger.warning(
                                f"[{agent.name}] Empty write_document args, "
                                f"injecting content ({len(_candidate)} chars)"
                            )
                            first_line = _candidate.strip().split("\n")[0][:60].lstrip("#").strip()
                            safe_fname = "".join(
                                c for c in first_line if c.isalnum() or c in "._- "
                            ).strip()[:50] or "report"
                            args = {"filename": f"{safe_fname}.md", "content": _candidate}
                        else:
                            # No usable content — return error with stronger hint
                            logger.warning(
                                f"[{agent.name}] Empty write_document args, "
                                f"no usable content (current={len(content) if content else 0}, "
                                f"last={len(last_content) if last_content else 0} chars) "
                                f"— returning error to agent"
                            )
                            tool_result = (
                                "ERROR: write_document was called with empty arguments. "
                                "This is likely caused by response truncation.\n"
                                "IMPORTANT: You MUST put the document content DIRECTLY in "
                                "the tool call arguments, NOT in your message text.\n"
                                "Call write_document like this:\n"
                                "  write_document(filename='report.md', content='<your full report>')\n"
                                "If your report is very long, split it into sections and write "
                                "each section separately, then combine."
                            )
                            _skip_invoke = True

                    # Truncation guard: write_scratchpad with empty/short content
                    # When max_tokens truncates the arguments JSON mid-stream,
                    # json.loads fails and args becomes {}. Detect this and ask
                    # the agent to retry instead of writing garbage to scratchpad.
                    if tc_name == "write_scratchpad" and not _skip_invoke:
                        sp_content_val = args.get("content", "")
                        sp_key_val = args.get("key", "")
                        if not sp_content_val or len(sp_content_val.strip()) < 10:
                            logger.warning(
                                f"[{agent.name}] write_scratchpad with empty/short "
                                f"content ({len(sp_content_val)} chars), "
                                f"key='{sp_key_val}' — returning error to agent"
                            )
                            tool_result = (
                                "ERROR: write_scratchpad was called with empty or very short content "
                                f"({len(sp_content_val)} chars). This usually means your response "
                                "was truncated.\n"
                                "Please call write_scratchpad again with COMPLETE content:\n"
                                "  write_scratchpad(key='your_key', content='<your full data>')\n"
                                "Include ALL key findings, numbers, and analysis in the content."
                            )
                            _skip_invoke = True

                    # ── Auto-sync: write_document → scratchpad file reference ──
                    # Write a structured JSON entry to scratchpad with file
                    # metadata instead of dumping the full document content.
                    # Downstream agents can read the actual file via cross-
                    # workspace read access (enabled through read_from).
                    if (tc_name == "write_document" and not _skip_invoke
                            and "write_scratchpad" in tool_map):
                        doc_content = args.get("content", "")
                        doc_fname = args.get("filename", "document")
                        if doc_content and len(doc_content) > 50:
                            from agents.tools import _workspace_var
                            _ws = _workspace_var.get(None) or ""
                            _abs_path = os.path.join(_ws, doc_fname) if _ws else doc_fname

                            # Detect file type from extension
                            _ext = os.path.splitext(doc_fname)[1].lower()
                            _type_map = {
                                ".md": "markdown", ".txt": "text",
                                ".py": "python", ".js": "javascript",
                                ".html": "html", ".css": "css",
                                ".csv": "csv", ".json": "json",
                                ".png": "image", ".jpg": "image",
                                ".svg": "image",
                            }
                            _ftype = _type_map.get(_ext, "document")

                            # Build brief summary (first 300 chars)
                            _brief = doc_content[:300].replace("\n", " ").strip()
                            if len(doc_content) > 300:
                                _brief += "..."

                            # Structured metadata entry
                            _meta = json.dumps({
                                "type": "file",
                                "filename": doc_fname,
                                "path": _abs_path,
                                "file_type": _ftype,
                                "size_chars": len(doc_content),
                                "brief": _brief,
                            }, ensure_ascii=False)

                            try:
                                sp_key = f"file:{doc_fname}"
                                tool_map["write_scratchpad"].invoke({
                                    "key": sp_key,
                                    "content": _meta,
                                })
                                logger.info(
                                    f"[{agent.name}] Auto-synced write_document "
                                    f"'{doc_fname}' → scratchpad '{sp_key}' "
                                    f"(structured, {len(_meta)} chars)"
                                )
                            except Exception as sp_err:
                                logger.warning(
                                    f"[{agent.name}] Auto-sync to scratchpad "
                                    f"failed: {sp_err}"
                                )

                    if _skip_invoke:
                        pass  # tool_result already set above
                    elif tc_name in tool_map:
                        try:
                            # Run synchronous tools in thread to avoid blocking
                            # the event loop (e.g. code_execute uses subprocess)
                            tool_result = await asyncio.to_thread(
                                tool_map[tc_name].invoke, args
                            )
                        except Exception as e:
                            tool_result = f"Tool error: {str(e)}"

                        # Log tool result with preview
                        result_str = str(tool_result)
                        preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
                        logger.info(
                            f"[{agent.name}] tool_result: {tc_name} → "
                            f"({len(result_str)} chars) {preview}"
                        )

                        if (tc_name == "send_message"
                                and isinstance(tool_result, str)
                                and tool_result.startswith("MESSAGE_SENT|")):
                            parts = tool_result.split("|", 2)
                            if len(parts) == 3 and on_message:
                                logger.info(
                                    f"[AgentComm] SEND_MESSAGE: "
                                    f"{agent.name} → agent={parts[1][:8]}, "
                                    f"content={parts[2][:120]}..."
                                )
                                await on_message(agent.id, parts[1], parts[2], "agent")

                        # Handle request_help: synchronously invoke target agent
                        if (tc_name == "request_help"
                                and isinstance(tool_result, str)
                                and tool_result.startswith("HELP_REQUEST|")):
                            parts = tool_result.split("|", 2)
                            if len(parts) == 3:
                                target_agent_id = parts[1]
                                question = parts[2]
                                logger.info(
                                    f"[AgentComm] REQUEST_HELP: "
                                    f"{agent.name} → target={target_agent_id[:8]}, "
                                    f"question={question[:120]}..."
                                )

                                # Recursion guard: prevent nested help chains
                                if help_depth >= 1:
                                    tool_result = (
                                        "Cannot request help: you are already "
                                        "responding to a help request. Answer "
                                        "based on your own knowledge."
                                    )
                                else:
                                    # Broadcast the question as agent-to-agent message
                                    if on_message:
                                        await on_message(agent.id, target_agent_id, question, "agent")
                                    # Invoke target agent for a response
                                    from database import get_agent as _get_agent
                                    target_agent = await _get_agent(target_agent_id)
                                    if target_agent:
                                        # Save original status to restore after help
                                        original_target_status = target_agent.status
                                        if on_status_change:
                                            await on_status_change(agent.id, "communicating")
                                            await on_status_change(target_agent.id, "thinking")

                                        # Suppress internal status changes during help
                                        # to avoid the final "idle" in execute_worker_task
                                        async def _helper_status(aid, status):
                                            if status != "idle" and on_status_change:
                                                await on_status_change(aid, status)

                                        # Give helper read-only scratchpad access
                                        helper_extra = None
                                        if "read_scratchpad" in tool_map:
                                            helper_extra = [tool_map["read_scratchpad"]]

                                        try:
                                            logger.info(
                                                f"[AgentComm] Invoking helper: "
                                                f"{target_agent.name} (depth={help_depth+1})"
                                            )
                                            help_response, _, _, _ = await asyncio.wait_for(
                                                execute_worker_task(
                                                    agent=target_agent,
                                                    task_description=(
                                                        f"Context: The team is working on: {task_description[:500]}\n\n"
                                                        f"A colleague ({agent.name}) asks: {question}\n"
                                                        "Respond concisely based on your knowledge and the task context."
                                                    ),
                                                    subtask_id="__help__",
                                                    on_status_change=_helper_status,
                                                    on_message=on_message,
                                                    help_depth=help_depth + 1,
                                                    extra_tools=helper_extra,
                                                ),
                                                timeout=60.0,
                                            )
                                            logger.info(
                                                f"[AgentComm] HELP_RESPONSE: "
                                                f"{target_agent.name} → {agent.name}, "
                                                f"{len(help_response)} chars: "
                                                f"{help_response[:120]}..."
                                            )
                                        except asyncio.TimeoutError:
                                            help_response = (
                                                f"Agent {target_agent.name} timed out "
                                                "while processing your question."
                                            )
                                            logger.warning(
                                                f"[AgentComm] HELP_TIMEOUT: "
                                                f"{agent.name} → {target_agent.name} (60s)"
                                            )
                                        # Broadcast the response
                                        if on_message:
                                            await on_message(target_agent.id, agent.id, help_response, "agent")
                                        # Restore original statuses
                                        if on_status_change:
                                            await on_status_change(target_agent.id, original_target_status)
                                            await on_status_change(agent.id, "working")
                                        tool_result = help_response
                                    else:
                                        tool_result = f"Agent {target_agent_id} not found."
                    else:
                        tool_result = f"Unknown tool: {tc_name}"
                        logger.warning(f"[{agent.name}] unknown tool: {tc_name}")

                    tool_result_str = str(tool_result)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tool_result_str,
                    })

                    # Update loop metrics for reflection decisions
                    metrics.tool_call_count += 1
                    metrics.recent_tools.append(tc_name)
                    if len(metrics.recent_tools) > 5:
                        metrics.recent_tools.pop(0)
                    metrics.tool_distribution[tc_name] = metrics.tool_distribution.get(tc_name, 0) + 1

                    result_len = len(tool_result_str)
                    metrics.recent_result_lens.append(result_len)
                    if len(metrics.recent_result_lens) > 3:
                        metrics.recent_result_lens.pop(0)

                    if "error" in tool_result_str.lower()[:100]:
                        metrics.consecutive_errors += 1
                    else:
                        metrics.consecutive_errors = 0

                    # Track whether agent has produced actual deliverables
                    if tc_name in ("write_document", "write_scratchpad"):
                        metrics.has_deliverable = True

                # ── Deadline pressure: force agent to wrap up ──
                # If approaching max_iterations and no deliverable yet,
                # inject an urgent prompt to stop researching and start writing.
                remaining_iters = max_iterations - iteration - 1
                if (remaining_iters <= 2
                        and not metrics.has_deliverable
                        and metrics.tool_call_count >= 3):
                    deadline_msg = (
                        f"⏰ DEADLINE: You have only {remaining_iters} iteration(s) left. "
                        f"You MUST write your deliverables NOW.\n"
                        f"Stop searching/reading. Use the data you already have.\n"
                        f"Call write_document() to save your main deliverable, "
                        f"then write_scratchpad() for key data.\n"
                        f"If you do not write deliverables, your work will be LOST."
                    )
                    messages.append({"role": "user", "content": deadline_msg})
                    logger.info(
                        f"[{agent.name}] Deadline pressure injected "
                        f"(remaining={remaining_iters}, tools_used={metrics.tool_call_count})"
                    )

                # Inject reflection prompt if conditions are met
                if enable_reflection:
                    trigger = _should_reflect(
                        metrics, complexity, iteration, max_iterations,
                    )
                    if trigger:
                        reflection_prompt = _build_reflection_prompt(
                            metrics, trigger, iteration, max_iterations,
                        )
                        messages.append({
                            "role": "user",
                            "content": reflection_prompt,
                        })
                        metrics.reflection_count += 1
                        metrics.reflection_triggers.append(trigger)
                        logger.info(
                            f"[{agent.name}] reflection injected "
                            f"(#{metrics.reflection_count}): {trigger}"
                        )

                continue  # next iteration

            # No tool calls → final response
            final = content or last_content or "Task completed."
            # Clean DeepSeek DSML tags (e.g. <｜DSML｜...>)
            if "DSML" in final or "｜" in final:
                import re as _re
                final = _re.sub(r'<[｜|]DSML[｜|][^>]*>', '', final, flags=_re.DOTALL).strip()
                if not final:
                    final = last_content or "Task completed."
            logger.info(
                f"[{agent.name}] === agentic loop end === "
                f"(iterations={iteration + 1}, result={len(final)} chars, "
                f"reflections={metrics.reflection_count})"
            )
            return final, metrics

        except Exception as e:
            llm_consecutive_errors += 1
            metrics.llm_errors += 1
            logger.error(
                f"Agent {agent.name} LLM error (iter {iteration}, "
                f"consecutive={llm_consecutive_errors}): {e}"
            )
            if llm_consecutive_errors >= 3 or iteration == max_iterations - 1:
                return f"Task completed with errors: {str(e)}", metrics
            continue

    return last_content or "Task completed (max iterations reached).", metrics


# ── LLM call helpers ────────────────────────────────────────────────────────

async def _streaming_llm_call(
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]],
    on_stream_chunk,
    extra_kwargs: dict,
    max_tokens: int = 4000,
) -> tuple:
    """Make a streaming LLM call.

    Streams content text AND write_scratchpad content in real-time.
    Returns ``(collected_content, tool_calls_list_or_None)``.
    """
    response = await acompletion(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto" if tools else None,
        max_tokens=max_tokens,
        temperature=0.7,
        stream=True,
        **extra_kwargs,
    )

    collected_content = ""
    tc_data: dict[int, dict] = {}       # index -> {id, name, arguments}
    sp_parsers: dict[int, _ScratchpadArgParser] = {}

    async for chunk in response:
        delta = chunk.choices[0].delta

        # ── Stream regular content ──
        if hasattr(delta, "content") and delta.content:
            collected_content += delta.content
            await on_stream_chunk(delta.content)

        # ── Collect tool-call deltas ──
        if hasattr(delta, "tool_calls") and delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tc_data:
                    tc_data[idx] = {"id": "", "name": "", "arguments": ""}

                if tc.id:
                    tc_data[idx]["id"] = tc.id

                if hasattr(tc, "function") and tc.function:
                    if tc.function.name:
                        tc_data[idx]["name"] = tc.function.name
                        # Start a scratchpad parser for write_scratchpad calls
                        if tc.function.name == "write_scratchpad":
                            sp_parsers[idx] = _ScratchpadArgParser()

                    if tc.function.arguments:
                        tc_data[idx]["arguments"] += tc.function.arguments
                        # Stream scratchpad content as it arrives
                        parser = sp_parsers.get(idx)
                        if parser:
                            text = parser.feed(tc.function.arguments)
                            if text:
                                # Emit separator before first scratchpad chunk
                                if not parser._header_sent:
                                    await on_stream_chunk("\n\n📝 [Scratchpad] ")
                                    parser._header_sent = True
                                await on_stream_chunk(text)

    if not tc_data:
        return collected_content, None

    # Format tool calls for the messages list
    formatted = [
        {
            "id": tc_data[idx]["id"],
            "type": "function",
            "function": {
                "name": tc_data[idx]["name"],
                "arguments": tc_data[idx]["arguments"],
            },
        }
        for idx in sorted(tc_data.keys())
    ]
    return collected_content, formatted


async def _blocking_llm_call(
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]],
    extra_kwargs: dict,
    max_tokens: int = 4000,
) -> tuple:
    """Non-streaming LLM call (used when no stream callback is provided).

    Returns ``(content, tool_calls_list_or_None)``.
    """
    response = await acompletion(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto" if tools else None,
        max_tokens=max_tokens,
        temperature=0.7,
        **extra_kwargs,
    )

    message = response.choices[0].message
    content = message.content or ""

    if hasattr(message, "tool_calls") and message.tool_calls:
        formatted = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
        return content, formatted

    return content, None


def _match_skills_to_task(
    task_hint: str, merged_skills: dict,
) -> list[str]:
    """Keyword matching: find skills whose descriptions overlap
    with the task description. Returns list of matched skill names.

    Uses stricter filtering to avoid matching generic/irrelevant skills:
    - Minimum token length of 5 chars (filters 'data', 'best', 'code', etc.)
    - Requires at least 2 overlapping tokens per skill
    - Excludes common stopwords that appear in many skill descriptions
    """
    if not task_hint or not merged_skills:
        return []

    # Stopwords common in skill descriptions but not indicative of relevance
    _stopwords = {
        "about", "agent", "based", "build", "check", "common", "create",
        "document", "example", "execute", "following", "generate", "guide",
        "input", "learn", "model", "output", "process", "project", "provide",
        "query", "result", "search", "should", "simple", "source", "start",
        "tasks", "tools", "using", "value", "write", "analysis", "content",
        "information", "practice", "practices", "report", "skill", "skills",
        "system", "patterns", "quality",
    }

    task_lower = task_hint.lower()
    # Build a set of meaningful task tokens (skip short words and stopwords)
    task_tokens = {
        w for w in re.split(r'\W+', task_lower)
        if len(w) >= 5 and w not in _stopwords
    }

    if not task_tokens:
        return []

    matched: list[str] = []
    for sid, skill in merged_skills.items():
        desc_lower = (skill.description + " " + skill.name).lower()
        desc_tokens = {
            w for w in re.split(r'\W+', desc_lower)
            if len(w) >= 5 and w not in _stopwords
        }
        overlap = task_tokens & desc_tokens
        # Require at least 2 meaningful overlapping tokens
        if len(overlap) >= 2:
            matched.append(skill.name)

    return matched


def _build_system_prompt(
    agent: Agent, memory_context: str,
    extra_tools: Optional[list] = None,
    task_hint: str = "",
) -> str:
    """Build the system prompt for a worker agent.

    Structure:
      1. Role identity + core tools (hardcoded in role prompt)
      2. AVAILABLE SKILLS section (dynamic, from assigned skills)
      3. Skill match hint (zero-cost keyword matching against task)
      4. Workflow instruction (plan before execute)
      5. Rules
    """
    from agents.skill_registry import get_role_system_prompt

    base_prompt = agent.system_prompt if agent.system_prompt else get_role_system_prompt(agent.role)

    prompt = f"""You are {agent.name}, an AI agent with the role of {agent.role}.

{base_prompt}

IMPORTANT RULES:
1. Be concise and effective. Complete tasks thoroughly but efficiently.
2. Minimize tool calls — combine searches, avoid redundant lookups.
3. When you have enough information, STOP calling tools and write your final answer directly.
4. When you finish, provide a clear summary of what you accomplished.

PARALLEL TOOL CALLING (CRITICAL FOR EFFICIENCY):
You can and SHOULD call multiple tools in a SINGLE response when the calls are independent.
Examples:
  ✅ GOOD: Call web_search("topic A") AND web_search("topic B") AND web_search("topic C") in ONE response
  ✅ GOOD: Call read_file("file1.md") AND read_file("file2.md") in ONE response
  ✅ GOOD: Call write_document(...) AND write_scratchpad(...) in ONE response
  ❌ BAD: Call web_search("topic A"), wait for result, then call web_search("topic B") in next turn
Each turn costs one iteration. Batching independent calls into one turn saves iterations and time.
Only sequentialize when a later call DEPENDS on an earlier call's result."""

    # Skill system — XML injection of available skills (merged: shared + personal)
    from agents.skill_loader import (
        build_available_skills_xml_for_agent,
        load_merged_skills,
    )
    from agents.tools import _agent_id_var

    agent_ctx_id = _agent_id_var.get(None) or agent.id
    skills_xml = build_available_skills_xml_for_agent(agent_ctx_id)

    # Check if agent has any skills
    has_skills = "<skill " in skills_xml

    prompt += f"\n\n{skills_xml}"

    # ── Proactive skill match hint (zero LLM cost) ──
    # Only highlight skills that actually match the task; don't encourage
    # the agent to read_skill on every single installed skill.
    matched_skills: list[str] = []
    if has_skills and task_hint:
        merged = load_merged_skills(agent_ctx_id)
        matched_skills = _match_skills_to_task(task_hint, merged)
        if matched_skills:
            names = ", ".join(matched_skills)
            prompt += (
                f"\n\n⚡ SKILL MATCH: These installed skills are relevant to your task: "
                f"{names}.\n"
                f"→ Call read_skill(name) ONLY for these matched skills before starting work.\n"
                f"→ Do NOT read_skill on skills that are NOT listed here."
            )

    if has_skills:
        prompt += """

SKILL USAGE GUIDE:

1. USE MATCHED SKILLS (if any are listed above)
   → read_skill(name) to load its full instructions
   → The returned content contains ABSOLUTE paths to executable scripts.
     Run via shell_execute(), e.g.: shell_execute("python /path/script.py args")
   → Do NOT search your workspace for scripts — they live outside it.
   → Do NOT rewrite script logic yourself. The skill script is better.

2. SEARCH ECOSYSTEM ONLY FOR SPECIALIZED NEEDS
   Only when your task involves a specialized domain (e.g. image processing,
   PDF generation, data visualization) and no installed skill matches:
   → find_skill(query) to search community skills
   → install_skill(package) → read_skill(name) → execute
   Do NOT search the ecosystem for generic tasks like web search, writing,
   or data analysis — use built-in tools directly for those.

3. USE BUILT-IN TOOLS FOR COMMON TASKS
   For research, writing, calculations, and general analysis:
   → Use web_search, write_document, code_execute, etc. directly
   → These are NOT "last resort" — they are the right tool for most tasks."""
    else:
        prompt += """

TOOL USAGE GUIDE:

1. USE BUILT-IN TOOLS FOR COMMON TASKS
   For research, writing, calculations, and general analysis:
   → Use web_search, write_document, code_execute, etc. directly.
   These are the right tools for most tasks.

2. SEARCH SKILL ECOSYSTEM ONLY FOR SPECIALIZED NEEDS
   Only when your task involves a specialized domain (e.g. image processing,
   PDF generation, data visualization) that built-in tools can't handle:
   → find_skill(query) to search community skills
   → install_skill(package) → read_skill(name) → execute
   Do NOT search the ecosystem for generic tasks."""

    if memory_context:
        prompt += f"\n\n{memory_context}"

    # Add scratchpad instructions if scratchpad tools are provided
    if extra_tools:
        tool_names = [t.name for t in extra_tools]
        if "read_scratchpad" in tool_names:
            prompt += (
                "\n\nDATA SHARING & COLLABORATION:"
                "\n"
                "\n📋 SCRATCHPAD = structured inter-agent data channel:"
                "\n   • read_scratchpad('') → see what upstream agents shared"
                "\n   • Entries may contain file references with absolute paths"
                "\n     → Use read_file(path) to read those files directly"
                "\n   • write_scratchpad: share KEY METRICS and structured findings"
                "\n     → Keep entries concise (~500-1500 chars), use JSON or markdown"
                "\n     → Focus on conclusions, not raw data"
                "\n"
                "\n📁 WORKSPACE & FILES:"
                "\n   • write_document: save final deliverables (auto-synced to scratchpad as file reference)"
                "\n   • read_file: read files from your workspace OR upstream agent workspaces"
                "\n   • When scratchpad shows a file with a path, use read_file(path) to get full content"
                "\n"
                "\n🔄 PROTOCOL:"
                "\n   1. read_scratchpad('') → check upstream data and file references"
                "\n   2. If scratchpad has file references you need → read_file(path) to get full content"
                "\n   3. Do your work"
                "\n   4. write_document for deliverables (auto-shared as file ref to downstream)"
                "\n   5. write_scratchpad for key metrics/findings not already in documents"
                "\n   6. Use the same language as the task."
            )

        if "save_memory" in tool_names:
            prompt += (
                "\n\nPERSONAL MEMORY TOOLS:"
                "\n- save_memory: Save important facts, preferences, or insights to long-term memory."
                "\n- recall_memory: Search your memory for relevant past experiences."
                "\n- Use save_memory when you learn something important about the user or task."
                "\n- Use recall_memory at the START of conversations to check for relevant context."
            )

    prompt += (
        "\n\nLANGUAGE: You MUST respond in the same language as the task you are given. "
        "If the task description is in Chinese, ALL your output must be in Chinese. "
        "If in English, respond in English. This includes tool outputs like write_scratchpad."
    )

    return prompt


def _build_litellm_tools(tools: list) -> list[dict]:
    """Convert LangChain tools to LiteLLM/OpenAI tool format."""
    litellm_tools = []
    for tool in tools:
        schema = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.args_schema.schema() if tool.args_schema else {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        litellm_tools.append(schema)
    return litellm_tools

"""PM (Project Manager) Agent — task decomposition, review, and synthesis."""
from __future__ import annotations
import json
import re
import logging
import uuid
from typing import Optional
from litellm import acompletion
from models import Agent, Task, SubTask
from agents.skill_registry import get_role, get_skill

PM_AGENT_ID = "pm-agent"
PM_AGENT_NAME = "PM"

logger = logging.getLogger(__name__)


def _build_agents_info(agents: list) -> str:
    """Build rich agent capability description for PM planning.

    Includes role description, core tools, and skill descriptions
    so PM can make informed delegation decisions.
    """
    blocks = []
    for a in agents:
        role_def = get_role(a.role)
        lines = [f"- {a.name} (ID: {a.id})"]
        if role_def:
            lines.append(f"  Role: {role_def.display_name} — {role_def.description}")
            lines.append(f"  Core tools: {', '.join(role_def.core_tool_ids)}")
        else:
            lines.append(f"  Role: {a.role}")

        # Resolve skill descriptions
        if a.skills:
            skill_parts = []
            for sid in a.skills:
                sk = get_skill(sid)
                if sk:
                    skill_parts.append(f"{sk.name} ({sk.description})")
                else:
                    skill_parts.append(sid)
            lines.append(f"  Skills: {'; '.join(skill_parts)}")

        blocks.append("\n".join(lines))
    return "\n".join(blocks)


class _PMPseudoAgent:
    """Adapter to make PM compatible with _run_agentic_loop interface."""

    def __init__(self, pm: PMAgent):
        self.id = PM_AGENT_ID
        self.name = PM_AGENT_NAME
        self.model = pm.model
        self.api_key = ""  # stored in extra_kwargs, passed via llm_extra_kwargs
        self.skills = []
        self.role = "PM"
        self.system_prompt = ""
        self._extra_kwargs = pm.extra_kwargs


class PMAgent:
    """Project Manager Agent — orchestrates task decomposition, review, and synthesis."""

    def __init__(self, model: str, api_key: str):
        self.model = model if "/" in model else f"openai/{model}"
        self.extra_kwargs: dict = {}
        if api_key:
            if "|||" in api_key:
                k, b = api_key.split("|||", 1)
                self.extra_kwargs = {"api_key": k, "api_base": b}
            else:
                self.extra_kwargs = {"api_key": api_key}

    async def _call_llm(self, prompt: str, max_tokens: int = 1500) -> str:
        import asyncio as _asyncio
        last_err = None
        for attempt in range(3):
            try:
                if attempt > 0:
                    backoff = 2 ** attempt  # 2s, 4s
                    logger.info(f"[PM] retry #{attempt}, backoff {backoff}s")
                    await _asyncio.sleep(backoff)
                resp = await acompletion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=0.3,
                    **self.extra_kwargs,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                last_err = e
                logger.warning(f"[PM] LLM call failed (attempt {attempt + 1}/3): {e}")
        raise last_err

    # ─── agentic PM call ──────────────────────────
    async def _run_pm_agentic(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        on_stream_chunk=None,
        max_iterations: int = 8,
    ) -> str:
        """Run PM with tool-calling capability via worker's agentic loop."""
        from agents.worker import _run_agentic_loop, _build_litellm_tools

        pseudo_agent = _PMPseudoAgent(self)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        litellm_tools = _build_litellm_tools(tools)
        tool_map = {t.name: t for t in tools}

        result, _metrics = await _run_agentic_loop(
            agent=pseudo_agent,
            messages=messages,
            tools=litellm_tools,
            tool_map=tool_map,
            on_stream_chunk=on_stream_chunk,
            max_iterations=max_iterations,
            enable_reflection=False,
            llm_extra_kwargs=self.extra_kwargs,
        )
        return result

    # ─── decompose ────────────────────────────────
    async def decompose(
        self,
        task: Task,
        agents: list[Agent],
        tools: Optional[list] = None,
        on_stream_chunk=None,
    ) -> list[SubTask]:
        agents_info = _build_agents_info(agents)
        prompt = f"""You are a Project Manager. You are responsible for the FINAL QUALITY of the deliverable.
Decompose the task, delegate to agents, and define clear non-overlapping scopes.

Task: {task.title}
Description: {task.description}

Available agents:
{agents_info}

═══ PLANNING PRINCIPLES ═══

1. YOU PLAN, THEY EXECUTE.
   Do NOT research or produce content yourself. Agents do all the work.

2. MATCH DELIVERABLE TO TASK GOAL.
   - The FINAL subtask's deliverable must be exactly what the user asked for (image, code, data, report, etc.).
   - Do NOT always add a "write report" step. Only add documentation/report subtasks when the user explicitly asks for a written document.
   - If the task goal is an artifact (image, chart, code, dataset), the last subtask should PRODUCE that artifact, not describe it in a report.

3. MINIMAL, NON-OVERLAPPING OUTPUT.
   - Each subtask produces ONE distinct deliverable — no two subtasks produce the same type of output.
   - Assign scope based on each agent's role and skills.
   - Only use agents whose skills are needed. Not every agent must participate.

4. NO DUPLICATE WORK.
   Information is gathered ONCE by ONE agent. Downstream agents consume it, never redo it.

5. EXPLICIT DELIVERABLE BOUNDARIES.
   Each subtask description MUST state:
   - "Deliver: ..." — what the agent must produce
   - "Acceptance criteria: ..." — specific, measurable conditions for approval (e.g. "must include at least 3 data sources", "must cover years 2020-2025", "must contain comparison table")
   - "Do NOT: ..." — what is outside this subtask's scope

6. DATA SHARING PROTOCOL (structured scratchpad).
   Agents share data via a structured scratchpad + cross-workspace file access:
   - When an agent writes a file (write_document), it is AUTO-SYNCED to scratchpad as a JSON file reference (path + brief).
   - Agents can also write_scratchpad for key metrics/findings NOT in documents (e.g. structured JSON, comparison tables).
   - Downstream agents use "read_from" to gain READ ACCESS to upstream agents' files.
   - Downstream agents call read_scratchpad('') to see file references, then read_file(path) to get full content.
   → Do NOT instruct agents to copy content into scratchpad. Files are auto-shared.
   → DO instruct agents to write_scratchpad for structured metadata, key metrics, or cross-references.

7. ITERATION BUDGET (max_iterations).
   Each agent has LIMITED iterations (tool-call rounds). Assign a budget based on complexity:
   - Simple tasks (write a short doc, format data): 4-5
   - Medium tasks (research + write, analyze + chart): 6-8
   - Complex tasks (multi-source research + comprehensive analysis): 8-10
   Budget includes ALL steps: read scratchpad, search, process, write deliverables.
   Agents are rewarded for finishing UNDER budget — assign tight but achievable budgets.
   NEVER exceed 10. Minimum is 4.

═══ RULES ═══

- 2-5 subtasks. Use "depends_on" for execution order, "read_from" for data visibility.
- "read_from" MUST use temp_ids (e.g. "st_1"), NOT scratchpad key names. Same IDs as in "depends_on".
- "read_from" grants the downstream agent READ ACCESS to upstream agent's workspace files.
- Empty depends_on = parallel execution.
- Respond in the same language as the task title.

═══ OUTPUT ═══
JSON array ONLY. Each object MUST include "max_iterations" (4-10):
[
  {{"temp_id": "st_1", "title": "...", "description": "Deliver: ...\\nAcceptance criteria: 1) ... 2) ...\\nDo NOT: ...", "assigned_to": "agent_id", "depends_on": [], "read_from": [], "max_iterations": 8}},
  {{"temp_id": "st_2", "title": "...", "description": "Deliver: ...\\nAcceptance criteria: 1) ... 2) ...\\nDo NOT: ...\\nUpstream data: read_scratchpad to get file references from st_1, then read_file to access content.", "assigned_to": "agent_id", "depends_on": ["st_1"], "read_from": ["st_1"], "max_iterations": 6}}
]"""

        if tools:
            system_prompt = (
                "You are a PM Agent responsible for decomposing tasks into subtasks. "
                "You can use tools to research the task before producing your plan. "
                "Your FINAL response must be a JSON array of subtasks."
            )
            content = await self._run_pm_agentic(
                system_prompt=system_prompt,
                user_prompt=prompt,
                tools=tools,
                on_stream_chunk=on_stream_chunk,
                max_iterations=8,
            )
        else:
            content = await self._call_llm(prompt, max_tokens=2000)

        # Clean DeepSeek DSML tags before parsing
        if "DSML" in content or "｜" in content:
            content = re.sub(r'<[｜|]DSML[｜|][^>]*>', '', content, flags=re.DOTALL).strip()
            logger.warning(f"[PM] Cleaned DSML tags from decompose result, remaining={len(content)} chars")

        match = re.search(r'\[[\s\S]*\]', content)
        try:
            data = json.loads(match.group()) if match else json.loads(content)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(
                f"[PM] Failed to parse decompose JSON ({e}), "
                f"doing fallback LLM call for structured output"
            )
            # Fallback: ask LLM directly (no tools) to produce the JSON
            fallback_prompt = (
                f"Based on your research, decompose this task into subtasks.\n\n"
                f"Task: {task.title}\nDescription: {task.description}\n\n"
                f"Agents:\n{agents_info}\n\n"
                f"Output ONLY a JSON array:\n"
                f'[{{"temp_id":"st_1","title":"...","description":"...",'
                f'"assigned_to":"agent_id","depends_on":[],"read_from":[]}}]'
            )
            fallback_content = await self._call_llm(fallback_prompt, max_tokens=2000)
            if "DSML" in fallback_content or "｜" in fallback_content:
                fallback_content = re.sub(r'<[｜|]DSML[｜|][^>]*>', '', fallback_content, flags=re.DOTALL).strip()
            match2 = re.search(r'\[[\s\S]*\]', fallback_content)
            data = json.loads(match2.group()) if match2 else json.loads(fallback_content)

        logger.info(
            f"[PM] Decomposition result: {len(data)} subtasks from LLM"
        )
        for i, item in enumerate(data):
            logger.info(
                f"[PM]   subtask[{i}]: title='{item.get('title', '?')}', "
                f"assigned_to={item.get('assigned_to', '?')}, "
                f"depends_on={item.get('depends_on', [])}, "
                f"read_from={item.get('read_from', [])}, "
                f"max_iterations={item.get('max_iterations', 'default')}"
            )

        valid_ids = {a.id for a in agents}

        # Phase 1: Create subtasks with real UUIDs, build temp→real mapping
        temp_to_real: dict = {}  # temp_id → real uuid
        subtasks: list[SubTask] = []
        for item in data:
            real_id = str(uuid.uuid4())
            temp_id = item.get("temp_id", "")
            if temp_id:
                temp_to_real[temp_id] = real_id

            # Parse and clamp max_iterations (4-10, default 8)
            raw_max_iter = item.get("max_iterations", 8)
            try:
                clamped_max_iter = max(4, min(10, int(raw_max_iter)))
            except (ValueError, TypeError):
                clamped_max_iter = 8

            st = SubTask(
                id=real_id,
                title=item.get("title", "Subtask"),
                description=item.get("description", ""),
                assigned_to=item.get("assigned_to"),
                status="todo",
                depends_on=[],
                max_iterations=clamped_max_iter,
            )
            if st.assigned_to not in valid_ids:
                # Try fuzzy match by name
                for a in agents:
                    if a.name.lower() in str(st.assigned_to).lower():
                        st.assigned_to = a.id
                        break
                else:
                    st.assigned_to = agents[0].id
            subtasks.append(st)

        # Phase 2: Resolve depends_on and read_from temp_ids to real UUIDs
        for i, item in enumerate(data):
            raw_deps = item.get("depends_on", [])
            if isinstance(raw_deps, list):
                resolved = []
                for dep in raw_deps:
                    if dep in temp_to_real:
                        resolved.append(temp_to_real[dep])
                subtasks[i].depends_on = resolved

            raw_reads = item.get("read_from", [])
            if isinstance(raw_reads, list):
                resolved_reads = []
                for rf in raw_reads:
                    if rf in temp_to_real:
                        resolved_reads.append(temp_to_real[rf])
                    else:
                        logger.warning(
                            f"[PM] read_from '{rf}' is not a valid temp_id, ignoring"
                        )
                subtasks[i].read_from = resolved_reads

            # Fallback: if subtask depends on others but read_from resolved
            # to empty (LLM used wrong IDs), auto-inherit from depends_on.
            # A subtask that depends on another should always be able to read
            # its output — otherwise upstream work is invisible.
            if subtasks[i].depends_on and not subtasks[i].read_from:
                subtasks[i].read_from = list(subtasks[i].depends_on)
                logger.info(
                    f"[PM] Auto-inherited read_from from depends_on for "
                    f"subtask '{subtasks[i].title}': {subtasks[i].read_from}"
                )

        # Phase 3: Cycle detection — if graph has a cycle, fall back to sequential
        if self._has_cycle(subtasks):
            logger.warning("[PM] Dependency cycle detected, falling back to sequential")
            for i, st in enumerate(subtasks):
                st.depends_on = [subtasks[j].id for j in range(i)] if i > 0 else []

        return subtasks

    @staticmethod
    def _has_cycle(subtasks: list[SubTask]) -> bool:
        """Detect cycles in the subtask dependency graph using topological sort."""
        id_set = {st.id for st in subtasks}
        in_degree: dict = {st.id: 0 for st in subtasks}
        adjacency: dict = {st.id: [] for st in subtasks}

        for st in subtasks:
            for dep in st.depends_on:
                if dep in id_set:
                    adjacency[dep].append(st.id)
                    in_degree[st.id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return visited != len(subtasks)

    # ─── replan ─────────────────────────────────────
    async def replan(
        self,
        task: Task,
        failed_subtask: SubTask,
        failed_result: str,
        remaining_subtasks: list,
        completed_results: dict,
        agents: list,
    ) -> list:
        """Replan remaining subtasks after a failure.

        The PM can keep, modify, remove remaining subtasks, or add up to 2 new
        ones.  Returns the updated list of remaining SubTask objects.
        Falls back to the original remaining list on any error.
        """
        agents_info = _build_agents_info(agents)
        remaining_info = "\n".join(
            f"- temp_id=st_{i+1}: \"{st.title}\" assigned_to={st.assigned_to}"
            for i, st in enumerate(remaining_subtasks)
        )
        completed_info = "\n".join(
            f"- {k[:8]}...: {v[:200]}" for k, v in completed_results.items()
        )

        prompt = f"""You are a Project Manager. A subtask has failed even after rework.
Replan the remaining subtasks to recover.

Main task: {task.title}
Description: {task.description}

Failed subtask: "{failed_subtask.title}"
Failed output: {failed_result[:1000]}

Already completed results:
{completed_info or "(none)"}

Remaining (not yet started) subtasks:
{remaining_info or "(none)"}

Available agents:
{agents_info}

Rules:
1. You may KEEP, MODIFY, or REMOVE any remaining subtask
2. You may ADD at most 2 NEW subtasks to address the failure
3. Use temp_id (st_1, st_2...) and depends_on for ordering
4. Total remaining subtasks must not exceed 5
5. Be practical — focus on recovering from the failure
6. Each subtask MUST include "max_iterations" (4-10) — the iteration budget

LANGUAGE RULE: Respond in the same language as the task title.

JSON array of the NEW remaining plan (no other text):
[
  {{"temp_id": "st_1", "title": "...", "description": "...", "assigned_to": "agent_id", "depends_on": [], "read_from": [], "max_iterations": 8}}
]

IMPORTANT — read_from:
- read_from lists temp_ids of OTHER subtasks whose scratchpad entries this subtask needs to READ
- If a subtask depends on work done previously, include those temp_ids in read_from
- All completed subtask outputs are automatically visible; read_from is for inter-NEW-subtask visibility"""

        try:
            content = await self._call_llm(prompt, max_tokens=2000)
            match = re.search(r'\[[\s\S]*\]', content)
            data = json.loads(match.group()) if match else json.loads(content)

            if not data or len(data) > 5:
                logger.warning("[PM] Replan returned invalid count, keeping original plan")
                return remaining_subtasks

            valid_ids = {a.id for a in agents}
            temp_to_real: dict = {}
            new_subtasks: list = []

            for item in data:
                real_id = str(uuid.uuid4())
                temp_id = item.get("temp_id", "")
                if temp_id:
                    temp_to_real[temp_id] = real_id

                # Parse and clamp max_iterations (4-10, default 8)
                raw_max_iter = item.get("max_iterations", 8)
                try:
                    clamped_max_iter = max(4, min(10, int(raw_max_iter)))
                except (ValueError, TypeError):
                    clamped_max_iter = 8

                st = SubTask(
                    id=real_id,
                    title=item.get("title", "Subtask"),
                    description=item.get("description", ""),
                    assigned_to=item.get("assigned_to"),
                    status="todo",
                    depends_on=[],
                    max_iterations=clamped_max_iter,
                )
                if st.assigned_to not in valid_ids:
                    for a in agents:
                        if a.name.lower() in str(st.assigned_to).lower():
                            st.assigned_to = a.id
                            break
                    else:
                        st.assigned_to = agents[0].id
                new_subtasks.append(st)

            # Resolve depends_on and read_from temp_ids → real UUIDs
            completed_ids = list(completed_results.keys()) if completed_results else []
            for i, item in enumerate(data):
                raw_deps = item.get("depends_on", [])
                if isinstance(raw_deps, list):
                    new_subtasks[i].depends_on = [
                        temp_to_real[d] for d in raw_deps if d in temp_to_real
                    ]
                # Resolve read_from temp_ids within the replan
                raw_rf = item.get("read_from", [])
                resolved_rf = []
                if isinstance(raw_rf, list):
                    resolved_rf = [
                        temp_to_real[r] for r in raw_rf if r in temp_to_real
                    ]
                # Always inject all completed subtask IDs so replanned tasks
                # can see ALL previous work in the scratchpad
                all_rf = list(set(resolved_rf + completed_ids))
                new_subtasks[i].read_from = all_rf

            # Cycle detection
            if self._has_cycle(new_subtasks):
                logger.warning("[PM] Replan has cycle, keeping original plan")
                return remaining_subtasks

            logger.info(
                f"[PM] Replan successful: {len(new_subtasks)} subtasks "
                f"(was {len(remaining_subtasks)})"
            )
            return new_subtasks

        except Exception as e:
            logger.error(f"[PM] Replan failed: {e}")
            return remaining_subtasks

    # ─── review ───────────────────────────────────
    async def review(
        self,
        subtask: SubTask,
        result: str,
        task: Task,
        scratchpad_content: str = "",
        workspace_files: str = "",
    ) -> dict:
        """Return {"approved": bool, "feedback": str}.

        Uses a single direct LLM call (no agentic loop / tools) — PM review
        almost never uses tools in practice, and the agentic overhead adds
        latency without value.

        Now also receives scratchpad entries and workspace file listings
        so PM can evaluate actual deliverables, not just the text reply.
        """
        # Build extra context sections
        extra_context = ""
        if scratchpad_content:
            extra_context += f"""

=== SCRATCHPAD ENTRIES (structured metadata) ===
NOTE: Scratchpad entries may be JSON file references (type="file" with path and brief)
or structured metrics/findings. File references mean the agent produced a file — check
WORKSPACE FILES below for the actual file listings.
{scratchpad_content[:3000]}
=== END SCRATCHPAD ===
"""
        if workspace_files:
            extra_context += f"""

=== WORKSPACE FILES (generated files) ===
{workspace_files}
=== END FILES ===
"""

        prompt = f"""You are a PM reviewing a subtask result.

Main task: {task.title}
Subtask: {subtask.title}
Description: {subtask.description}

Agent's text reply:
{result[:2000]}
{extra_context}

REVIEW with THREE-TIER severity:

"pass" — Core deliverable is correct and all major requirements met. Minor imperfections are OK.
"minor" — Deliverable exists and is mostly correct, but has small fixable issues (formatting, length slightly off, missing a detail). Agent can fix in 1-2 tool calls.
"fail" — Deliverable is missing, fundamentally wrong, or missing critical requirements.

REVIEW GUIDELINES:
1. Focus on SUBSTANCE over FORM. Did the agent produce what was asked? Is the core content correct?
2. Numeric thresholds in acceptance criteria (word count, source count) have ±30% tolerance. E.g. "100-200 words" accepts 70-260 words.
3. Scratchpad file references (type="file_deliverable") mean the agent wrote a file — this IS a valid deliverable.
4. Short text replies with workspace files + scratchpad data = ACCEPTABLE. Judge by actual output.
5. Style preferences (formatting, exact phrasing) are NEVER grounds for "fail".
6. When in doubt, choose "pass" or "minor" — NOT "fail". Rework is expensive.

LANGUAGE RULE: feedback MUST be in the same language as the task title: "{task.title}".

Reply JSON only: {{"severity": "pass"|"minor"|"fail", "feedback": "brief reason"}}"""

        try:
            logger.info(
                f"[PM] Reviewing subtask '{subtask.title}' "
                f"(result_len={len(result)})"
            )
            content = await self._call_llm(prompt, max_tokens=300)
            match = re.search(r'\{[\s\S]*\}', content)
            verdict = json.loads(match.group()) if match else {"severity": "pass", "feedback": ""}

            # Normalize three-tier severity to approved + severity
            severity = verdict.get("severity", "pass").lower().strip()
            if severity not in ("pass", "minor", "fail"):
                # Fallback: legacy approved field
                if verdict.get("approved") is False:
                    severity = "fail"
                else:
                    severity = "pass"

            verdict["severity"] = severity
            verdict["approved"] = severity != "fail"

            logger.info(
                f"[PM] Review verdict: severity={severity}, "
                f"feedback='{verdict.get('feedback', '')[:100]}'"
            )
            return verdict
        except Exception as e:
            logger.warning(f"[PM] Review parse failed: {e}, auto-approving")
            return {"approved": True, "severity": "pass", "feedback": "Auto-approved (review parse error)"}

    # ─── evaluate synthesis need + pick agent (merged, 1 LLM call) ───
    async def evaluate_and_pick_synthesis(
        self,
        task: Task,
        agents: list[Agent],
        subtask_results: dict,
        workspace_files: str = "",
        scratchpad_content: str = "",
    ) -> dict:
        """Evaluate whether synthesis is needed AND pick the best agent in one call.

        Returns {"needed": bool, "reason": str,
                 "final_subtask_id": str|null, "synthesis_agent_id": str|null}.

        Strengthened skip logic: if the LAST subtask already produced a
        comprehensive integrated deliverable (e.g. a Writer/Analyst agent
        that references other subtask outputs), synthesis is likely redundant.
        """
        agents_info = _build_agents_info(agents)
        valid_ids = {a.id for a in agents}

        results_text = "\n\n".join(
            f"## Subtask: {st.title} (id={st.id[:8]})\n"
            f"Assigned agent: {st.assigned_to}\n"
            f"Output preview:\n{subtask_results.get(st.id, 'No result')[:1500]}"
            for st in task.subtasks
            if st.id in subtask_results
        )

        extra = ""
        if scratchpad_content:
            extra += f"\n\nScratchpad entries (structured metadata — file refs & key findings):\n{scratchpad_content[:3000]}"
        if workspace_files:
            extra += f"\n\nGenerated files:\n{workspace_files}"

        # Check if last subtask looks like a synthesis/report task
        last_st = task.subtasks[-1] if task.subtasks else None
        last_hint = ""
        if last_st and last_st.id in subtask_results:
            last_output = subtask_results[last_st.id]
            # Heuristic: if last subtask output is long and references other subtask titles
            other_titles = [st.title for st in task.subtasks[:-1]]
            ref_count = sum(1 for t in other_titles if t.lower()[:15] in last_output.lower())
            if len(last_output) > 2000 and ref_count >= len(other_titles) * 0.5:
                last_hint = (
                    f"\nNOTE: The last subtask '{last_st.title}' produced a long output "
                    f"({len(last_output)} chars) that references {ref_count}/{len(other_titles)} "
                    f"other subtask topics. This strongly suggests it is already an integrated "
                    f"deliverable — lean towards needed=false."
                )

        prompt = f"""You are a PM. All subtasks are complete. Decide TWO things in ONE response:

1. Is synthesis needed? — Do the deliverables ALREADY contain a complete final product?
2. If synthesis IS needed, which agent should do it?

Task: {task.title}
Description: {task.description}

Completed subtask outputs:
{results_text}
{extra}
{last_hint}

Available agents (for synthesis, if needed):
{agents_info}

DECISION CRITERIA for needed=false:
- A subtask already produced a comprehensive document covering all key aspects
- The output integrates data/findings from other subtasks
- Charts and files are properly referenced
- The deliverable is ready for the end user

DECISION CRITERIA for needed=true:
- Outputs are fragmented across subtasks with no integration
- No single subtask covers the full scope of the task
- Key connections between subtask findings are missing

Reply with ONLY a JSON object:
{{"needed": true/false, "reason": "brief explanation", "final_subtask_id": "subtask id with best deliverable (if needed=false), else null", "synthesis_agent_id": "agent id best suited to synthesize (if needed=true), else null"}}"""

        try:
            logger.info(
                f"[PM] Evaluating synthesis need + picking agent "
                f"({len(agents)} candidates, {len(subtask_results)} results)"
            )
            content = await self._call_llm(prompt, max_tokens=400)
            # Clean DSML artifacts
            if "DSML" in content or "｜" in content:
                content = re.sub(r'<[｜|]DSML[｜|][^>]*>', '', content, flags=re.DOTALL).strip()
            match = re.search(r'\{[\s\S]*\}', content)
            result = json.loads(match.group()) if match else json.loads(content)

            # Validate synthesis_agent_id if synthesis is needed
            if result.get("needed") and result.get("synthesis_agent_id"):
                aid = result["synthesis_agent_id"].strip().strip('"').strip("'")
                if aid in valid_ids:
                    result["synthesis_agent_id"] = aid
                else:
                    # Fuzzy match
                    matched = next((v for v in valid_ids if v in content), None)
                    result["synthesis_agent_id"] = matched

            logger.info(
                f"[PM] Synthesis eval: needed={result.get('needed')}, "
                f"reason='{result.get('reason', '')[:100]}', "
                f"agent={result.get('synthesis_agent_id', 'N/A')}"
            )
            return result
        except Exception as e:
            logger.warning(f"[PM] evaluate_and_pick_synthesis failed: {e}, defaulting to needed=True")
            return {
                "needed": True,
                "reason": f"Evaluation failed: {e}",
                "final_subtask_id": None,
                "synthesis_agent_id": None,
            }

    # ─── synthesize (acceptance check) ───────────────────────────────
    async def synthesize(
        self,
        task: Task,
        subtask_results: dict,
        scratchpad_content: str = "",
        workspace_files: str = "",
        tools: Optional[list] = None,
        on_stream_chunk=None,
    ) -> str:
        """Run acceptance check on completed subtasks. Returns JSON verdict."""
        results_text = "\n\n".join(
            f"## Subtask: {st.title}\n{subtask_results.get(st.id, 'No result')[:2000]}"
            for st in task.subtasks
            if st.id in subtask_results
        )

        # Build context sections
        extra_context = ""
        if scratchpad_content:
            extra_context += f"""

=== SHARED SCRATCHPAD (structured metadata) ===
NOTE: Entries may be JSON file references (type="file" with path/brief) or structured
metrics/findings. File references point to actual deliverable files listed below.
{scratchpad_content[:5000]}
=== END SCRATCHPAD ===
"""
        if workspace_files:
            extra_context += f"""

=== GENERATED FILES ===
{workspace_files}
=== END FILES ===
"""

        prompt = f"""You are a PM performing the FINAL ACCEPTANCE CHECK.

Task: {task.title}
Description: {task.description}

All Subtask Results:
{results_text}
{extra_context}

YOUR JOB: Review the quality of the completed work and produce an acceptance verdict.
Do NOT write any documents. Do NOT create reports. Do NOT use write_document or code_execute.
You are ONLY checking quality and summarizing what was delivered.

Respond with ONLY a JSON object (no markdown, no extra text):
{{
  "status": "accepted" or "needs_improvement",
  "summary": "2-3 sentence summary of the overall deliverable in the task language",
  "deliverables": ["list of key output file paths or descriptions"],
  "quality_score": 1-10,
  "issues": ["list of issues found, empty if none"]
}}

LANGUAGE RULE: The summary MUST be in the same language as the task title: "{task.title}"."""

        # Only give read-only tools (remove write_document, code_execute)
        read_only_tools = None
        if tools:
            read_only_tools = [
                t for t in tools
                if t.name not in ("write_document", "code_execute")
            ]

        if read_only_tools:
            system_prompt = (
                "You are a PM Agent performing acceptance review. "
                "You can use tools to verify data if needed. "
                "Do NOT write any documents or execute code. "
                "Your FINAL response must be a JSON acceptance verdict."
            )
            return await self._run_pm_agentic(
                system_prompt=system_prompt,
                user_prompt=prompt,
                tools=read_only_tools,
                on_stream_chunk=on_stream_chunk,
                max_iterations=5,
            )
        return await self._call_llm(prompt, max_tokens=1500)

"""Supervisor Agent: orchestrates task decomposition and worker assignment."""
import logging
import json
import re
from litellm import acompletion
from models import Agent, Task, SubTask
import uuid

logger = logging.getLogger(__name__)


async def decompose_task(
    task: Task,
    available_agents: list[Agent],
) -> list[SubTask]:
    """
    Use an LLM to decompose a task into subtasks and assign to agents.
    Uses the first available agent's model + api_key for the decomposition call.
    Returns list of SubTask objects.
    """
    if not available_agents:
        return [SubTask(
            id=str(uuid.uuid4()),
            title=task.title,
            description=task.description,
            status="todo"
        )]

    agents_info = "\n".join([
        f"- {a.name} (ID: {a.id}, Role: {a.role}, Skills: {', '.join(a.skills)})"
        for a in available_agents
    ])

    prompt = f"""You are a project supervisor AI. Decompose the following task into subtasks and assign them to the best available agents.

Task Title: {task.title}
Task Description: {task.description}

Available Agents:
{agents_info}

Rules:
1. Create 2-4 focused subtasks
2. Assign each subtask to the most suitable agent based on their role and skills
3. Make subtasks specific and actionable
4. Consider dependencies between subtasks

Respond with a JSON array of subtasks in this exact format:
[
  {{
    "title": "Subtask title",
    "description": "Detailed description of what to do",
    "assigned_to": "agent_id_here"
  }},
  ...
]

Only respond with valid JSON, no other text."""

    # Use the first agent's model/key for supervisor calls
    lead = available_agents[0]
    supervisor_model = lead.model if "/" in lead.model else f"openai/{lead.model}"
    extra_kwargs: dict = {}
    if lead.api_key:
        if "|||" in lead.api_key:
            key_part, base_part = lead.api_key.split("|||", 1)
            extra_kwargs["api_key"] = key_part
            extra_kwargs["api_base"] = base_part
        else:
            extra_kwargs["api_key"] = lead.api_key

    try:
        response = await acompletion(
            model=supervisor_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.3,
            **extra_kwargs,
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON from response
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            subtasks_data = json.loads(json_match.group())
        else:
            subtasks_data = json.loads(content)

        subtasks = []
        for st_data in subtasks_data:
            subtask = SubTask(
                id=str(uuid.uuid4()),
                title=st_data.get("title", "Subtask"),
                description=st_data.get("description", ""),
                assigned_to=st_data.get("assigned_to"),
                status="todo"
            )
            # Validate agent_id
            valid_ids = {a.id for a in available_agents}
            if subtask.assigned_to not in valid_ids:
                # Find by name or assign to first agent
                for agent in available_agents:
                    if agent.name.lower() in str(subtask.assigned_to).lower():
                        subtask.assigned_to = agent.id
                        break
                else:
                    subtask.assigned_to = available_agents[0].id

            subtasks.append(subtask)

        return subtasks

    except Exception as e:
        logger.error(f"Task decomposition error: {e}")
        # Fallback: create one subtask per assigned agent
        if task.assigned_to:
            return [
                SubTask(
                    id=str(uuid.uuid4()),
                    title=task.title,
                    description=task.description,
                    assigned_to=agent_id,
                    status="todo"
                )
                for agent_id in task.assigned_to[:2]
            ]
        return [SubTask(
            id=str(uuid.uuid4()),
            title=task.title,
            description=task.description,
            status="todo"
        )]


async def synthesize_results(
    task: Task,
    subtask_results: dict[str, str],  # subtask_id -> result
    synthesizer_model: str = "deepseek/deepseek-chat",
    api_key: str = "",
) -> str:
    """Combine subtask results into a final coherent output."""
    if not subtask_results:
        return "No results to synthesize."

    if len(subtask_results) == 1:
        return list(subtask_results.values())[0]

    results_text = "\n\n".join([
        f"Subtask: {st.title}\nResult:\n{subtask_results.get(st.id, 'No result')}"
        for st in task.subtasks
        if st.id in subtask_results
    ])

    prompt = f"""You are a project supervisor. Synthesize the following subtask results into a cohesive final report for the main task.

Main Task: {task.title}
Description: {task.description}

Subtask Results:
{results_text}

Create a clear, well-structured final report that:
1. Summarizes all completed work
2. Highlights key findings or outputs
3. Provides actionable conclusions

Be concise but comprehensive."""

    extra_kwargs: dict = {}
    if api_key:
        if "|||" in api_key:
            key_part, base_part = api_key.split("|||", 1)
            extra_kwargs["api_key"] = key_part
            extra_kwargs["api_base"] = base_part
        else:
            extra_kwargs["api_key"] = api_key

    try:
        response = await acompletion(
            model=synthesizer_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.5,
            **extra_kwargs,
        )
        return response.choices[0].message.content or "Synthesis complete."
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        return "\n\n---\n\n".join(subtask_results.values())

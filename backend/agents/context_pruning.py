# -*- coding: utf-8 -*-
"""Context pruning for LLM conversation messages.

Ported from OpenClaw's context-pruning system.
Two-stage approach: soft-trim then hard-clear, protecting recent messages.

Stages
------
1. Soft trim  (triggered when estimated token usage > soft_trim_ratio of context window):
   For old tool_result messages outside the protected tail:
   - If content length > soft_trim_max_chars, keep head + tail and replace
     the middle with an ellipsis note.

2. Hard clear (triggered when estimated token usage still > hard_clear_ratio after soft trim):
   For the same older tool_result messages, replace full content with a
   static placeholder to free the maximum amount of context.

Protection rules
----------------
- Index 0 (system prompt) is never touched.
- The first user message is never touched.
- The last ``keep_last_assistants`` assistant turns and their interleaved
  tool results are never touched.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN_ESTIMATE: int = 4
"""Characters-per-token heuristic used for all token estimates."""

# Default pruning parameters, mirroring OpenClaw defaults.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "keep_last_assistants": 3,
    "soft_trim_ratio": 0.30,   # soft trim when context usage > 30 %
    "hard_clear_ratio": 0.50,  # hard clear when context usage > 50 %
    "soft_trim_max_chars": 4000,
    "soft_trim_head_chars": 1500,
    "soft_trim_tail_chars": 1500,
    "hard_clear_placeholder": "[Old tool result content cleared]",
}

# Known model context windows (tokens).  Used by get_model_context_window().
MODEL_CONTEXT_WINDOWS: Dict[str, int] = {
    "deepseek/deepseek-chat": 64_000,
    "deepseek/deepseek-reasoner": 64_000,
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "openai/gpt-4.1": 1_047_576,
    "openai/gpt-4.1-mini": 1_047_576,
    "anthropic/claude-sonnet-4-20250514": 200_000,
    "anthropic/claude-opus-4-20250514": 200_000,
}


# ---------------------------------------------------------------------------
# Token estimation helpers
# ---------------------------------------------------------------------------

def estimate_message_tokens(message: Dict[str, Any]) -> int:
    """Estimate token count for a single message using the chars/4 heuristic.

    Handles both plain-string content and multi-part list content (the
    multimodal/tool-result format used by some providers).

    Args:
        message: A message dict with at least a ``"content"`` key.

    Returns:
        Estimated number of tokens (floor division).
    """
    content = message.get("content", "")
    if isinstance(content, str):
        return len(content) // CHARS_PER_TOKEN_ESTIMATE

    if isinstance(content, list):
        total_chars = 0
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    total_chars += len(text)
        return total_chars // CHARS_PER_TOKEN_ESTIMATE

    # Fallback: stringify whatever we got
    return len(str(content)) // CHARS_PER_TOKEN_ESTIMATE


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate total token count for a list of messages.

    Args:
        messages: List of message dicts.

    Returns:
        Sum of estimated tokens across all messages.
    """
    return sum(estimate_message_tokens(m) for m in messages)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_content_text(message: Dict[str, Any]) -> str:
    """Extract the plain-text content from a message dict.

    Supports both ``str`` content and list-of-blocks content.
    """
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _is_tool_result(message: Dict[str, Any]) -> bool:
    """Return True if *message* is a tool-result message (``role == "tool"``)."""
    return message.get("role") == "tool"


def _find_first_user_index(messages: List[Dict[str, Any]]) -> Optional[int]:
    """Return the index of the first user message, or None if absent."""
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            return i
    return None


def _find_assistant_cutoff_index(
    messages: List[Dict[str, Any]],
    keep_last: int,
) -> Optional[int]:
    """Return the index of the Nth-from-last assistant message.

    Messages *at or after* this index are in the protected tail and must
    not be pruned.  Messages *before* this index are candidates for pruning
    (subject to additional guards).

    Args:
        messages: Full message list.
        keep_last: How many trailing assistant turns to protect.

    Returns:
        Index of the oldest assistant message that is still in the protected
        tail, or ``None`` if there are fewer than ``keep_last`` assistant
        messages (meaning the entire history is protected).

    Examples:
        If keep_last=3 and there are assistant messages at indices
        [2, 5, 9, 12], the function returns 9 -- the 3rd from the end.
        Messages at indices 0..8 are pruning candidates.
    """
    if keep_last <= 0:
        return len(messages)

    remaining = keep_last
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            remaining -= 1
            if remaining == 0:
                return i

    # Not enough assistant messages -- entire history is protected
    return None


def _soft_trim_content(
    text: str,
    head_chars: int = 1500,
    tail_chars: int = 1500,
) -> Optional[str]:
    """Trim ``text`` by keeping the head and tail, replacing the middle.

    Only trims when the saved space is worth the operation (at least 100
    chars of margin between head + tail and total length).

    Args:
        text: Original content string.
        head_chars: Characters to keep from the start.
        tail_chars: Characters to keep from the end.

    Returns:
        Trimmed string, or ``None`` if no trimming was necessary.
    """
    min_len = head_chars + tail_chars + 100  # margin: only trim if meaningful
    if len(text) <= min_len:
        return None

    head = text[:head_chars]
    tail = text[-tail_chars:] if tail_chars > 0 else ""
    note = (
        f"\n...\n[Tool result trimmed: kept first {head_chars} "
        f"and last {tail_chars} of {len(text)} chars]"
    )
    trimmed = head + note
    if tail:
        trimmed += "\n" + tail
    return trimmed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prune_context_messages(
    messages: List[Dict[str, Any]],
    context_window_tokens: int,
    keep_last_assistants: int = DEFAULT_SETTINGS["keep_last_assistants"],
    soft_trim_ratio: float = DEFAULT_SETTINGS["soft_trim_ratio"],
    hard_clear_ratio: float = DEFAULT_SETTINGS["hard_clear_ratio"],
    soft_trim_max_chars: int = DEFAULT_SETTINGS["soft_trim_max_chars"],
    soft_trim_head_chars: int = DEFAULT_SETTINGS["soft_trim_head_chars"],
    soft_trim_tail_chars: int = DEFAULT_SETTINGS["soft_trim_tail_chars"],
    hard_clear_placeholder: str = DEFAULT_SETTINGS["hard_clear_placeholder"],
) -> List[Dict[str, Any]]:
    """Prune conversation messages to fit within the context window.

    The function implements a two-stage pruning strategy ported from
    OpenClaw's TypeScript context-pruning module.

    **Stage 1 -- Soft trim**
    Triggered when the estimated character usage exceeds
    ``soft_trim_ratio * context_window_chars``.  For each prunable tool
    result whose content length exceeds ``soft_trim_max_chars``, the middle
    section is replaced by an ellipsis note while the head and tail are
    preserved.

    **Stage 2 -- Hard clear**
    Triggered when the ratio *after* soft trimming still exceeds
    ``hard_clear_ratio``.  Prunable tool results are replaced wholesale with
    ``hard_clear_placeholder``, oldest messages first, until the ratio drops
    below the threshold.

    **Protection rules** -- the following messages are never modified:

    - Index 0 (system prompt).
    - The first user message (preserves the original task context).
    - The last ``keep_last_assistants`` assistant turns *and* any tool
      results interleaved with them.

    The original ``messages`` list is never mutated.  A shallow copy of each
    dict is made before any modification.

    Args:
        messages: Conversation messages in OpenAI chat-completion format.
            Each message is a dict with at least ``"role"`` and ``"content"``
            keys.  Tool results use ``role="tool"``.
        context_window_tokens: The model's context window size in tokens.
            Must be > 0; otherwise the original list is returned unchanged.
        keep_last_assistants: Number of trailing assistant turns to protect
            from any pruning.  Default: 3.
        soft_trim_ratio: Fraction of the context window that triggers soft
            trimming.  Default: 0.30 (30 %).
        hard_clear_ratio: Fraction that triggers hard clearing *after* soft
            trimming.  Default: 0.50 (50 %).
        soft_trim_max_chars: Soft trim is only applied to tool results longer
            than this many characters.  Default: 4000.
        soft_trim_head_chars: Characters to keep from the start during soft
            trim.  Default: 1500.
        soft_trim_tail_chars: Characters to keep from the end during soft
            trim.  Default: 1500.
        hard_clear_placeholder: Replacement text used during hard clear.
            Default: ``"[Old tool result content cleared]"``.

    Returns:
        A new list with pruned message dicts.  Unmodified messages share the
        same dict object as the input; modified messages are shallow copies
        with only the ``"content"`` key replaced.

    Examples:
        >>> msgs = [
        ...     {"role": "system", "content": "You are an assistant."},
        ...     {"role": "user",   "content": "Hello"},
        ...     {"role": "assistant", "content": "Hi", "tool_calls": [...]},
        ...     {"role": "tool",  "content": "x" * 8000, "tool_call_id": "1"},
        ...     {"role": "assistant", "content": "Done."},
        ... ]
        >>> pruned = prune_context_messages(msgs, context_window_tokens=4096)
    """
    if not messages or context_window_tokens <= 0:
        return messages

    char_window = context_window_tokens * CHARS_PER_TOKEN_ESTIMATE

    # Find the cutoff: messages at index >= cutoff_index are protected.
    cutoff_index = _find_assistant_cutoff_index(messages, keep_last_assistants)
    if cutoff_index is None:
        # Fewer than keep_last_assistants assistant messages -- everything is
        # protected, nothing to prune.
        return messages

    # Find the first user message -- do not prune at or before this index
    # (protects the system prompt at index 0 implicitly as well).
    first_user_idx = _find_first_user_index(messages)
    prune_start = first_user_idx if first_user_idx is not None else len(messages)

    # -----------------------------------------------------------------
    # Estimate current context usage using character counts (faster than
    # individual token estimates when many messages are present).
    # -----------------------------------------------------------------
    total_chars = sum(len(_get_content_text(m)) for m in messages)
    ratio = total_chars / char_window

    if ratio < soft_trim_ratio:
        logger.debug(
            "Context pruning: no action needed (ratio=%.2f < soft_trim=%.2f)",
            ratio,
            soft_trim_ratio,
        )
        return messages

    # Collect prunable tool-result indices (before cutoff, after first user).
    prunable_indices: List[int] = []
    for i in range(prune_start, cutoff_index):
        if _is_tool_result(messages[i]):
            prunable_indices.append(i)

    if not prunable_indices:
        logger.debug(
            "Context pruning: ratio=%.2f but no prunable tool results found "
            "(prune_range=[%d, %d))",
            ratio,
            prune_start,
            cutoff_index,
        )
        return messages

    # Build a mutable shallow copy of the list; message dicts are copied
    # lazily (only when they are about to be modified).
    result: List[Dict[str, Any]] = list(messages)

    # -----------------------------------------------------------------
    # Stage 1: Soft trim
    # -----------------------------------------------------------------
    soft_trim_count = 0
    for i in prunable_indices:
        text = _get_content_text(result[i])
        if len(text) <= soft_trim_max_chars:
            continue  # too short to bother trimming

        trimmed = _soft_trim_content(text, soft_trim_head_chars, soft_trim_tail_chars)
        if trimmed is not None:
            before_len = len(text)
            result[i] = {**result[i], "content": trimmed}
            total_chars += len(trimmed) - before_len
            soft_trim_count += 1

    ratio = total_chars / char_window

    if ratio < hard_clear_ratio:
        if soft_trim_count:
            logger.debug(
                "Context pruning: soft trim sufficient -- "
                "trimmed %d tool result(s), ratio=%.2f",
                soft_trim_count,
                ratio,
            )
        return result

    # -----------------------------------------------------------------
    # Stage 2: Hard clear (oldest prunable first)
    # -----------------------------------------------------------------
    hard_clear_count = 0
    placeholder_len = len(hard_clear_placeholder)

    for i in prunable_indices:
        if ratio < hard_clear_ratio:
            break

        text = _get_content_text(result[i])
        if text == hard_clear_placeholder:
            continue  # already cleared in a previous call

        before_len = len(text)
        result[i] = {**result[i], "content": hard_clear_placeholder}
        total_chars += placeholder_len - before_len
        ratio = total_chars / char_window
        hard_clear_count += 1

    logger.info(
        "Context pruning complete: ratio=%.2f, "
        "soft_trimmed=%d, hard_cleared=%d tool result(s) "
        "(of %d prunable, cutoff_index=%d)",
        ratio,
        soft_trim_count,
        hard_clear_count,
        len(prunable_indices),
        cutoff_index,
    )
    return result


def auto_truncate_messages(
    messages: List[Dict[str, Any]],
    context_window_tokens: int,
    reserve_ratio: float = 0.30,
) -> List[Dict[str, Any]]:
    """Emergency last-resort truncation: drop oldest non-system messages.

    This is a fallback for when ``prune_context_messages`` is insufficient
    (e.g. the protected tail alone exceeds the budget).  It keeps the system
    prompt and the most-recent messages that fit within the token budget.

    Args:
        messages: Conversation messages.
        context_window_tokens: Model's context window size in tokens.
        reserve_ratio: Fraction of the context window to keep free for the
            model's response.  Default: 0.30 (30 %).

    Returns:
        A new list with the oldest non-system messages dropped as needed.
        If the messages already fit, the original list is returned unchanged.
    """
    if not messages:
        return messages

    budget_tokens = int(context_window_tokens * (1.0 - reserve_ratio))
    current_tokens = estimate_messages_tokens(messages)

    if current_tokens <= budget_tokens:
        return messages

    # Separate the system prompt (always kept) from the rest.
    system_msg: Optional[Dict[str, Any]] = None
    if messages and messages[0].get("role") == "system":
        system_msg = messages[0]
        rest: List[Dict[str, Any]] = list(messages[1:])
    else:
        rest = list(messages)

    prefix: List[Dict[str, Any]] = [system_msg] if system_msg else []

    # Drop messages from the front of ``rest`` until we fit.
    dropped = 0
    while rest and estimate_messages_tokens(prefix + rest) > budget_tokens:
        dropped_msg = rest.pop(0)
        dropped += 1
        logger.debug(
            "Emergency truncation: dropped %s message (~%d tokens)",
            dropped_msg.get("role", "?"),
            estimate_message_tokens(dropped_msg),
        )

    final = prefix + rest
    if dropped:
        logger.warning(
            "Emergency truncation: %d -> %d messages after dropping %d "
            "(~%d tokens remaining)",
            len(messages),
            len(final),
            dropped,
            estimate_messages_tokens(final),
        )
    return final


def get_model_context_window(model: str) -> int:
    """Return the estimated context window (tokens) for a known model.

    Falls back to 64 000 tokens for unrecognised model strings.

    Args:
        model: LiteLLM-style model identifier, e.g.
            ``"openai/gpt-4o"`` or ``"anthropic/claude-sonnet-4-20250514"``.

    Returns:
        Context window size in tokens.

    Examples:
        >>> get_model_context_window("openai/gpt-4o")
        128000
        >>> get_model_context_window("unknown/model")
        64000
    """
    return MODEL_CONTEXT_WINDOWS.get(model, 64_000)

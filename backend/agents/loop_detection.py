# -*- coding: utf-8 -*-
"""Tool call loop detection -- prevents agents from getting stuck.

Ported from OpenClaw's tool-loop-detection.ts.
Three detectors + global circuit breaker with sliding window history.

Usage pattern::

    state = LoopDetectionState()
    config = LoopDetectionConfig()

    # Before each tool call:
    result = detect_tool_loop(state, tool_name, params, config)
    if result.stuck:
        return result.message  # inject into agent context

    record_tool_call(state, tool_name, params, tool_call_id=call_id)

    # Execute tool ...
    outcome = run_tool(tool_name, params)

    # After each tool call:
    record_tool_outcome(state, tool_name, params, result=outcome)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

HISTORY_SIZE = 30
WARNING_THRESHOLD = 10
CRITICAL_THRESHOLD = 20
CIRCUIT_BREAKER_THRESHOLD = 30

# Known polling-style tools that legitimately repeat the same call while
# waiting for an async process to complete.
KNOWN_POLL_TOOLS = frozenset({"code_execute", "execute_file"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LoopDetectionConfig:
    """Configuration for loop detection."""

    enabled: bool = True
    history_size: int = HISTORY_SIZE
    warning_threshold: int = WARNING_THRESHOLD
    critical_threshold: int = CRITICAL_THRESHOLD
    circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD
    detect_generic_repeat: bool = True
    detect_poll_no_progress: bool = True
    detect_ping_pong: bool = True


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ToolCallRecord:
    """A single tool call captured in the sliding-window history."""

    tool_name: str
    args_hash: str
    result_hash: Optional[str] = None
    tool_call_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class LoopDetectionState:
    """Mutable per-agent state that tracks tool call history."""

    history: List[ToolCallRecord] = field(default_factory=list)


@dataclass
class LoopDetectionResult:
    """Result returned by :func:`detect_tool_loop`."""

    stuck: bool = False
    level: Optional[str] = None        # "warning" | "critical"
    detector: Optional[str] = None     # which detector fired
    count: int = 0
    message: str = ""
    warning_key: Optional[str] = None  # stable dedup key for upstream filtering


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def _stable_json(value: Any) -> str:
    """Produce deterministic JSON for any Python value.

    dict keys are sorted so that ``{"b": 1, "a": 2}`` and ``{"a": 2, "b": 1}``
    hash identically.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        # bool must come before int because bool is a subclass of int.
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable_json(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value.keys())
        pairs = [f"{json.dumps(str(k))}:{_stable_json(value[k])}" for k in keys]
        return "{" + ",".join(pairs) + "}"
    # Fallback: stringify unknown types so they still produce a stable hash.
    return json.dumps(str(value))


def hash_tool_call(tool_name: str, params: Any) -> str:
    """Return a short, stable hash that identifies a (tool, params) pair.

    The 16-character hex prefix is enough entropy for loop-detection purposes
    while keeping logs readable.
    """
    serialized = _stable_json(params)
    digest = hashlib.sha256(serialized.encode()).hexdigest()[:16]
    return f"{tool_name}:{digest}"


def _hash_outcome(result: Any, error: Any = None) -> Optional[str]:
    """Hash a tool result for no-progress detection.

    Returns ``None`` when there is no result to hash (so callers can skip
    recording the outcome rather than storing an ambiguous sentinel).

    Very long results are truncated symmetrically (head + tail) to keep
    hashing fast without losing boundary information.
    """
    if error is not None:
        err_str = error if isinstance(error, str) else str(error)
        digest = hashlib.sha256(err_str.encode()).hexdigest()[:16]
        return f"error:{digest}"

    if result is None:
        return None

    result_str = result if isinstance(result, str) else _stable_json(result)

    max_len = 10_000
    if len(result_str) > max_len:
        half = max_len // 2
        result_str = result_str[:half] + result_str[-half:]

    return hashlib.sha256(result_str.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _is_poll_tool(tool_name: str) -> bool:
    """Return True if *tool_name* is a known polling-style tool."""
    return tool_name in KNOWN_POLL_TOOLS


def _get_no_progress_streak(
    history: List[ToolCallRecord],
    tool_name: str,
    args_hash: str,
) -> Tuple[int, Optional[str]]:
    """Count consecutive same-tool, same-args calls that produced an identical result.

    Walks the history from newest to oldest, stopping as soon as a different
    result hash is encountered or a non-matching record breaks the run.

    Returns:
        (streak_count, latest_result_hash) -- streak_count is 0 when no
        recorded outcomes exist yet.
    """
    streak = 0
    anchor_hash: Optional[str] = None

    for record in reversed(history):
        if record.tool_name != tool_name or record.args_hash != args_hash:
            # A different tool/args call interrupts the streak.
            break
        if not record.result_hash:
            # Outcome not yet recorded; skip without breaking streak.
            continue
        if anchor_hash is None:
            anchor_hash = record.result_hash
            streak = 1
        elif record.result_hash == anchor_hash:
            streak += 1
        else:
            # Result changed -- there WAS progress at some earlier point.
            break

    return streak, anchor_hash


def _get_ping_pong_streak(
    history: List[ToolCallRecord],
    current_hash: str,
) -> Tuple[int, Optional[str], bool]:
    """Detect an A -> B -> A -> B alternating pattern at the tail of history.

    The algorithm:
    1. Identify the most recent call in history (call it A).
    2. Find the most recent call in history that has a *different* args_hash
       (call it B).
    3. Walk backwards confirming the tail alternates strictly between A and B.
    4. If the *current* incoming call continues that pattern (matches B's hash),
       return the streak length.
    5. Check whether all observed outcomes for A are identical AND all observed
       outcomes for B are identical (no-progress evidence).

    Returns:
        (alternating_count, paired_tool_name, no_progress_evidence)
    """
    if not history:
        return 0, None, False

    last = history[-1]

    # Step 2: find the "other" signature.
    other_hash: Optional[str] = None
    other_tool: Optional[str] = None
    for record in reversed(history[:-1]):
        if record.args_hash != last.args_hash:
            other_hash = record.args_hash
            other_tool = record.tool_name
            break

    if other_hash is None or other_tool is None:
        return 0, None, False

    # Step 3: count alternating tail.
    alt_count = 0
    for i in range(len(history) - 1, -1, -1):
        record = history[i]
        # Even positions (0, 2, ...) should match last.args_hash, odd match other_hash.
        expected = last.args_hash if (alt_count % 2 == 0) else other_hash
        if record.args_hash != expected:
            break
        alt_count += 1

    if alt_count < 2:
        return 0, None, False

    # Step 4: does the current call continue the pattern?
    # After 'alt_count' entries ending on last.args_hash, the next expected
    # entry is other_hash.
    if current_hash != other_hash:
        return 0, None, False

    # Step 5: no-progress evidence.
    tail_start = max(0, len(history) - alt_count)
    first_hash_a: Optional[str] = None
    first_hash_b: Optional[str] = None
    no_progress = True

    for i in range(tail_start, len(history)):
        record = history[i]
        if not record.result_hash:
            no_progress = False
            break
        if record.args_hash == last.args_hash:
            if first_hash_a is None:
                first_hash_a = record.result_hash
            elif first_hash_a != record.result_hash:
                no_progress = False
                break
        elif record.args_hash == other_hash:
            if first_hash_b is None:
                first_hash_b = record.result_hash
            elif first_hash_b != record.result_hash:
                no_progress = False
                break

    # Both sides must have at least one observed outcome.
    if not first_hash_a or not first_hash_b:
        no_progress = False

    return alt_count + 1, last.tool_name, no_progress


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_tool_loop(
    state: LoopDetectionState,
    tool_name: str,
    params: Any,
    config: Optional[LoopDetectionConfig] = None,
) -> LoopDetectionResult:
    """Check whether the agent is stuck in a loop before executing a tool.

    Call this **before** :func:`record_tool_call` and before running the tool.
    If the returned result has ``stuck=True``, inject ``result.message`` into
    the agent's context instead of (or in addition to) running the tool.

    Detection order (highest priority first):

    1. Global circuit breaker -- any tool repeated ≥30 times with no progress.
    2. Known-poll critical -- poll tool ≥20 no-progress repeats.
    3. Known-poll warning  -- poll tool ≥10 no-progress repeats.
    4. Ping-pong critical  -- A↔B alternation ≥20 with no progress.
    5. Ping-pong warning   -- A↔B alternation ≥10.
    6. Generic repeat warning -- non-poll tool called ≥10 times with same args.

    Args:
        state:     Per-agent mutable state containing call history.
        tool_name: Name of the tool about to be called.
        params:    Tool parameters (any JSON-serialisable value).
        config:    Detection configuration; defaults to ``LoopDetectionConfig()``.

    Returns:
        :class:`LoopDetectionResult` -- ``stuck=False`` means the call looks safe.
    """
    cfg = config or LoopDetectionConfig()
    if not cfg.enabled:
        return LoopDetectionResult()

    history = state.history
    current_hash = hash_tool_call(tool_name, params)
    is_poll = _is_poll_tool(tool_name)

    no_progress_streak, _latest_result = _get_no_progress_streak(
        history, tool_name, current_hash
    )
    ping_pong_count, _paired_tool, pp_no_progress = _get_ping_pong_streak(
        history, current_hash
    )

    # ------------------------------------------------------------------
    # 1. Global circuit breaker
    # ------------------------------------------------------------------
    if no_progress_streak >= cfg.circuit_breaker_threshold:
        logger.error(
            "Loop circuit breaker: %s repeated %d times with no progress",
            tool_name,
            no_progress_streak,
        )
        return LoopDetectionResult(
            stuck=True,
            level="critical",
            detector="global_circuit_breaker",
            count=no_progress_streak,
            message=(
                f"CRITICAL: {tool_name} has repeated identical no-progress outcomes "
                f"{no_progress_streak} times. Execution blocked to prevent runaway loops. "
                f"Stop using this tool and try a different approach or report the task as failed."
            ),
            warning_key=f"global:{tool_name}:{current_hash}",
        )

    # ------------------------------------------------------------------
    # 2 & 3. Known-poll no-progress (critical then warning)
    # ------------------------------------------------------------------
    if is_poll and cfg.detect_poll_no_progress:
        if no_progress_streak >= cfg.critical_threshold:
            logger.error(
                "Critical polling loop: %s repeated %d times with no progress",
                tool_name,
                no_progress_streak,
            )
            return LoopDetectionResult(
                stuck=True,
                level="critical",
                detector="known_poll_no_progress",
                count=no_progress_streak,
                message=(
                    f"CRITICAL: Called {tool_name} with identical arguments and no progress "
                    f"{no_progress_streak} times. This appears to be a stuck polling loop. "
                    f"Stop calling this tool and report the task status."
                ),
                warning_key=f"poll:{tool_name}:{current_hash}",
            )

        if no_progress_streak >= cfg.warning_threshold:
            logger.warning(
                "Polling loop warning: %s repeated %d times with no progress",
                tool_name,
                no_progress_streak,
            )
            return LoopDetectionResult(
                stuck=True,
                level="warning",
                detector="known_poll_no_progress",
                count=no_progress_streak,
                message=(
                    f"WARNING: You have called {tool_name} {no_progress_streak} times with "
                    f"identical arguments and no progress. Stop polling and either wait longer "
                    f"or report the task as failed."
                ),
                warning_key=f"poll:{tool_name}:{current_hash}",
            )

    # ------------------------------------------------------------------
    # 4 & 5. Ping-pong (critical then warning)
    # ------------------------------------------------------------------
    if cfg.detect_ping_pong:
        if ping_pong_count >= cfg.critical_threshold and pp_no_progress:
            logger.error(
                "Critical ping-pong loop: %d alternating calls detected",
                ping_pong_count,
            )
            return LoopDetectionResult(
                stuck=True,
                level="critical",
                detector="ping_pong",
                count=ping_pong_count,
                message=(
                    f"CRITICAL: You are alternating between repeated tool-call patterns "
                    f"({ping_pong_count} consecutive calls) with no progress. "
                    f"Execution blocked. Try a completely different approach."
                ),
                warning_key=f"pingpong:{tool_name}:{current_hash}",
            )

        if ping_pong_count >= cfg.warning_threshold:
            logger.warning(
                "Ping-pong loop warning: %d alternating calls detected",
                ping_pong_count,
            )
            return LoopDetectionResult(
                stuck=True,
                level="warning",
                detector="ping_pong",
                count=ping_pong_count,
                message=(
                    f"WARNING: You are alternating between repeated tool-call patterns "
                    f"({ping_pong_count} consecutive calls). This looks like a ping-pong loop. "
                    f"Stop retrying and try a different approach."
                ),
                warning_key=f"pingpong:{tool_name}:{current_hash}",
            )

    # ------------------------------------------------------------------
    # 6. Generic repeat (warning only; poll tools handled above)
    # ------------------------------------------------------------------
    if not is_poll and cfg.detect_generic_repeat:
        recent_count = sum(
            1 for h in history
            if h.tool_name == tool_name and h.args_hash == current_hash
        )
        if recent_count >= cfg.warning_threshold:
            logger.warning(
                "Loop warning: %s called %d times with identical args",
                tool_name,
                recent_count,
            )
            return LoopDetectionResult(
                stuck=True,
                level="warning",
                detector="generic_repeat",
                count=recent_count,
                message=(
                    f"WARNING: You have called {tool_name} {recent_count} times with "
                    f"identical arguments. If this is not making progress, stop retrying "
                    f"and try a different approach."
                ),
                warning_key=f"generic:{tool_name}:{current_hash}",
            )

    return LoopDetectionResult()


def record_tool_call(
    state: LoopDetectionState,
    tool_name: str,
    params: Any,
    tool_call_id: Optional[str] = None,
    config: Optional[LoopDetectionConfig] = None,
) -> None:
    """Append a tool call to the sliding-window history.

    Call this **after** :func:`detect_tool_loop` returns ``stuck=False`` and
    **before** executing the tool.

    The sliding window is capped at ``config.history_size`` (default 30).
    When the window is full the oldest entry is dropped.

    Args:
        state:        Per-agent mutable state.
        tool_name:    Name of the tool being called.
        params:       Tool parameters.
        tool_call_id: Optional opaque ID used to correlate the outcome later.
        config:       Detection configuration; defaults to ``LoopDetectionConfig()``.
    """
    cfg = config or LoopDetectionConfig()
    state.history.append(
        ToolCallRecord(
            tool_name=tool_name,
            args_hash=hash_tool_call(tool_name, params),
            tool_call_id=tool_call_id,
            timestamp=time.time(),
        )
    )
    # Maintain sliding window -- pop from the front (oldest entry).
    if len(state.history) > cfg.history_size:
        state.history.pop(0)


def record_tool_outcome(
    state: LoopDetectionState,
    tool_name: str,
    params: Any,
    result: Any = None,
    error: Any = None,
    tool_call_id: Optional[str] = None,
) -> None:
    """Attach a result hash to the most recent matching call record.

    Call this **after** the tool has finished executing (success or error).
    The outcome hash is used by :func:`detect_tool_loop` to determine whether
    repeated calls are making progress.

    Matching priority:
    1. ``tool_call_id`` exact match (when provided).
    2. Most-recent unresolved record with matching ``tool_name`` + ``args_hash``.

    If no matching record is found a new terminal-only record is appended so
    that outcome data is never silently discarded.

    Args:
        state:        Per-agent mutable state.
        tool_name:    Name of the tool that was called.
        params:       Tool parameters (must be identical to those passed to
                      :func:`record_tool_call`).
        result:       Tool output on success; ``None`` if the call failed.
        error:        Exception or error string; ``None`` on success.
        tool_call_id: Optional ID previously passed to :func:`record_tool_call`.
    """
    result_hash = _hash_outcome(result, error)
    if result_hash is None:
        # Nothing to record (result is None and no error).
        return

    args_hash = hash_tool_call(tool_name, params)

    # Walk from newest to oldest looking for an unresolved matching record.
    for record in reversed(state.history):
        if tool_call_id is not None and record.tool_call_id != tool_call_id:
            continue
        if record.tool_name != tool_name or record.args_hash != args_hash:
            continue
        if record.result_hash is not None:
            # Already has an outcome -- keep looking for an unresolved one.
            continue
        record.result_hash = result_hash
        return

    # No match found: append a synthetic record so the outcome isn't lost.
    state.history.append(
        ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            result_hash=result_hash,
            tool_call_id=tool_call_id,
        )
    )


def get_tool_stats(state: LoopDetectionState) -> Dict[str, Any]:
    """Return a summary of tool call activity for monitoring / debug logging.

    Example output::

        {
            "total_calls": 12,
            "unique_patterns": 4,
            "most_frequent": {"tool_name": "code_execute", "count": 7},
        }

    Args:
        state: Per-agent mutable state.

    Returns:
        Dictionary with aggregate statistics over the current history window.
    """
    patterns: Dict[str, Dict[str, Any]] = {}

    for call in state.history:
        key = call.args_hash
        if key in patterns:
            patterns[key]["count"] += 1
        else:
            patterns[key] = {"tool_name": call.tool_name, "count": 1}

    most_frequent: Optional[Dict[str, Any]] = None
    for pattern in patterns.values():
        if most_frequent is None or pattern["count"] > most_frequent["count"]:
            most_frequent = pattern

    return {
        "total_calls": len(state.history),
        "unique_patterns": len(patterns),
        "most_frequent": most_frequent,
    }

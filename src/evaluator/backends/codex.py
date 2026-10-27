"""OpenAI Codex CLI backend."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from evaluator import quota, toolcalls
from evaluator.usage import RequestUsage, UsageSummary

from .agentic import AgenticBackend
from .base import (
    detect_firewall_hosts,
    has_aws_bedrock_bearer_token,
    has_aws_env_credentials,
    has_aws_region,
    has_aws_shared_credentials,
    needs_aws_shared_credentials,
)
from .codex_usage_wrapper import (
    CODEX_CHILD_USAGE_EVENT,
    CODEX_CHILD_USAGE_START_EVENT,
    CODEX_CHILD_USAGE_VERSION,
)

DEFAULT_MODEL = "gpt-5.5"

# ChatGPT's hard usage cap surfaces as an `error` / `turn.failed` event whose
# message reads e.g. "You've hit your usage limit. ... try again at 7:24 PM."
_USAGE_LIMIT_RE = re.compile(r"usage limit", re.IGNORECASE)
_RETRY_AT_RE = re.compile(r"try again at\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])")

# detect_quota_block runs host-side (after the agent container exits) where the
# repo and ~/.codex are available, so it can reuse the usage probe's precise reset.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_CODEX_USAGE_SOURCE = "codex_cli_turn_completed"
_CODEX_CHILD_USAGE_SOURCE = "codex_rollout_child_token_count"
_CODEX_CHILD_USAGE_COMPATIBLE_VERSIONS = frozenset({3, 4, CODEX_CHILD_USAGE_VERSION})
_MODEL_ACTIVITY_ITEM_TYPES = frozenset(
    {
        "agent_message",
        "reasoning",
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "collab_tool_call",
        "web_search",
        "todo_list",
    }
)
# Item types that are a tool call rather than the model thinking out loud.
_TOOL_ITEM_TYPES = frozenset(
    {"command_execution", "file_change", "mcp_tool_call", "collab_tool_call", "todo_list", "web_search"}
)
_STREAM_LAG_RE = re.compile(r"event stream lagged; dropped\s+\d+\s+events?", re.IGNORECASE)


@dataclass(frozen=True)
class _CodexTerminalUsage:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int | None
    cache_write_input_tokens: int | None
    reasoning_output_tokens: int | None
    incomplete: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _CodexChildUsageAudit:
    root_thread_id: str
    child_count: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_write_input_tokens: int
    reasoning_output_tokens: int
    requests: tuple[RequestUsage, ...]
    complete: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _CodexChildToolAudit:
    root_thread_id: str
    tool_calls: toolcalls.ToolCallSummary


@dataclass(frozen=True)
class _ParsedCodexRun:
    transcript: str
    usage: UsageSummary


def _strict_token(value: object) -> int | None:
    """Validate a native Codex token field without coercion."""

    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_terminal_usage(event: dict[str, Any]) -> tuple[_CodexTerminalUsage | None, tuple[str, ...]]:
    raw_usage = event.get("usage")
    if not isinstance(raw_usage, dict):
        return None, ("Codex turn.completed event has no usage object",)

    input_tokens = _strict_token(raw_usage.get("input_tokens"))
    output_tokens = _strict_token(raw_usage.get("output_tokens"))
    core_errors = []
    if input_tokens is None:
        core_errors.append("input_tokens")
    if output_tokens is None:
        core_errors.append("output_tokens")
    if core_errors:
        return None, (f"Codex turn.completed has invalid core fields: {', '.join(core_errors)}",)

    if input_tokens == 0 and output_tokens == 0:
        # Codex's JSONL event processor uses Usage::default() when it never
        # received a native token update, so this shape is not proof of a free run.
        return None, ("Codex reported synthesized-looking all-zero terminal usage",)

    warnings: list[str] = []
    incomplete = False

    def optional_subset(name: str) -> int | None:
        nonlocal incomplete
        if name not in raw_usage:
            warnings.append(f"Codex turn.completed is missing {name}")
            incomplete = True
            return None
        value = _strict_token(raw_usage[name])
        if value is None:
            warnings.append(f"Codex turn.completed has invalid {name}")
            incomplete = True
        return value

    cached_input_tokens = optional_subset("cached_input_tokens")
    cache_write_input_tokens = optional_subset("cache_write_input_tokens")
    reasoning_output_tokens = optional_subset("reasoning_output_tokens")
    if (
        cached_input_tokens is not None
        and cache_write_input_tokens is not None
        and cached_input_tokens + cache_write_input_tokens > input_tokens
    ):
        warnings.append("Codex cache read and write input tokens exceed total input tokens")
        cached_input_tokens = None
        cache_write_input_tokens = None
        incomplete = True
    elif cached_input_tokens is not None and cached_input_tokens > input_tokens:
        warnings.append("Codex cached input tokens exceed total input tokens")
        cached_input_tokens = None
        incomplete = True
    elif cache_write_input_tokens is not None and cache_write_input_tokens > input_tokens:
        warnings.append("Codex cache-write input tokens exceed total input tokens")
        cache_write_input_tokens = None
        incomplete = True
    if reasoning_output_tokens is not None and reasoning_output_tokens > output_tokens:
        warnings.append("Codex reasoning output tokens exceed total output tokens")
        reasoning_output_tokens = None
        incomplete = True

    return (
        _CodexTerminalUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            incomplete=incomplete,
            warnings=tuple(warnings),
        ),
        (),
    )


def _parse_child_usage_audit(
    event: dict[str, Any],
) -> tuple[_CodexChildUsageAudit | None, tuple[str, ...]]:
    version = event.get("version")
    # Later versions add independent tool-call data, but retain the v3 usage
    # payload so archived usage audits remain readable.
    if type(version) is not int or version not in _CODEX_CHILD_USAGE_COMPATIBLE_VERSIONS:
        return None, ("Codex child-usage audit has an unsupported version",)

    root_thread_id = event.get("root_thread_id")
    if not isinstance(root_thread_id, str) or not root_thread_id:
        return None, ("Codex child-usage audit has no root thread ID",)

    raw_complete = event.get("complete")
    raw_warning_codes = event.get("warning_codes", [])
    if (
        type(raw_complete) is not bool
        or not isinstance(raw_warning_codes, list)
        or any(not isinstance(code, str) or not code or len(code) > 80 for code in raw_warning_codes)
    ):
        return None, ("Codex child-usage audit has invalid status metadata",)

    child_count = _strict_token(event.get("child_count"))
    input_tokens = _strict_token(event.get("input_tokens"))
    cached_input_tokens = _strict_token(event.get("cached_input_tokens"))
    output_tokens = _strict_token(event.get("output_tokens"))
    reasoning_output_tokens = _strict_token(event.get("reasoning_output_tokens"))
    cache_write_input_tokens = _strict_token(event.get("cache_write_input_tokens"))
    if (
        child_count is None
        or input_tokens is None
        or cached_input_tokens is None
        or output_tokens is None
        or reasoning_output_tokens is None
        or cache_write_input_tokens is None
        or cached_input_tokens + cache_write_input_tokens > input_tokens
        or reasoning_output_tokens > output_tokens
        or (child_count == 0 and (input_tokens > 0 or output_tokens > 0))
    ):
        return None, ("Codex child-usage audit has invalid aggregate usage",)

    warning_codes = tuple(dict.fromkeys(raw_warning_codes))
    warnings: tuple[str, ...] = ()
    if warning_codes:
        warnings += (f"Codex child-usage audit is incomplete ({', '.join(warning_codes)})",)
    elif not raw_complete:
        warnings += ("Codex child-usage audit is incomplete",)
    requests: tuple[RequestUsage, ...]
    requests_valid = True
    raw_requests = event.get("requests")
    parsed_requests: list[RequestUsage] = []
    if not isinstance(raw_requests, list):
        requests_valid = False
    else:
        for raw_request in raw_requests:
            if not isinstance(raw_request, dict):
                requests_valid = False
                continue
            request_input = _strict_token(raw_request.get("input_tokens"))
            request_cache_read = _strict_token(raw_request.get("cached_input_tokens"))
            request_cache_write = _strict_token(raw_request.get("cache_write_input_tokens"))
            request_output = _strict_token(raw_request.get("output_tokens"))
            request_reasoning = _strict_token(raw_request.get("reasoning_output_tokens"))
            model = raw_request.get("model")
            provider = raw_request.get("provider")
            if (
                request_input is None
                or request_cache_read is None
                or request_cache_write is None
                or request_output is None
                or request_reasoning is None
                or request_cache_read + request_cache_write > request_input
                or request_reasoning > request_output
                or not isinstance(model, str)
                or not model.strip()
                or not isinstance(provider, str)
                or not provider.strip()
            ):
                requests_valid = False
                continue
            parsed_requests.append(
                RequestUsage(
                    input_tokens=request_input,
                    output_tokens=request_output,
                    cache_read_input_tokens=request_cache_read,
                    cache_write_input_tokens=request_cache_write,
                    reasoning_output_tokens=request_reasoning,
                    resolved_model=model,
                    provider=provider,
                )
            )
    requests = tuple(parsed_requests)
    if not requests_valid:
        warnings += ("Codex child-usage audit has invalid per-request usage",)

    return (
        _CodexChildUsageAudit(
            root_thread_id=root_thread_id,
            child_count=child_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            requests=requests,
            complete=raw_complete and not warning_codes and requests_valid,
            warnings=warnings,
        ),
        (),
    )


def _parse_child_tool_audit(
    event: dict[str, Any],
) -> tuple[_CodexChildToolAudit | None, tuple[str, ...]]:
    """Validate the tool-only, privacy-preserving session-tree audit."""

    version = event.get("version")
    if type(version) is not int or version != CODEX_CHILD_USAGE_VERSION:
        return None, ("Codex child tool-call audit has an unsupported version",)
    if event.get("tool_calls_scope") != "session_tree":
        return None, ("Codex tool-call audit has an invalid scope",)
    root_thread_id = event.get("root_thread_id")
    if not isinstance(root_thread_id, str) or not root_thread_id:
        return None, ("Codex child tool-call audit has no root thread ID",)
    raw_summary = event.get("tool_calls")
    summary = toolcalls.ToolCallSummary.from_dict(raw_summary)
    if not isinstance(raw_summary, dict) or not summary.available:
        return None, ("Codex child tool-call audit is missing or invalid",)
    return _CodexChildToolAudit(root_thread_id=root_thread_id, tool_calls=summary), ()


def _request_token_totals(requests: tuple[RequestUsage, ...]) -> tuple[int, int, int, int, int]:
    return (
        sum(request.input_tokens or 0 for request in requests),
        sum(request.cache_read_input_tokens or 0 for request in requests),
        sum(request.cache_write_input_tokens or 0 for request in requests),
        sum(request.output_tokens or 0 for request in requests),
        sum(request.reasoning_output_tokens or 0 for request in requests),
    )


def _append_transcript_event(lines: list[str], event: dict[str, Any]) -> None:
    etype = event.get("type")
    if etype == "item.completed":
        item = event.get("item")
        if not isinstance(item, dict):
            return
        itype = item.get("type")
        if itype == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text:
                lines.extend((f"[AGENT] {text}", ""))
        elif itype == "command_execution":
            command = item.get("command", "")
            output = item.get("aggregated_output", "")
            lines.append(f"[CMD] {command}")
            if output:
                output = str(output)
                if len(output) > 3000:
                    output = output[:1500] + "\n... (truncated) ...\n" + output[-1500:]
                lines.append(output.rstrip())
            if item.get("exit_code") is not None:
                lines.append(f"[EXIT {item['exit_code']}]")
            lines.append("")
        elif itype == "file_change":
            changes = item.get("changes")
            if isinstance(changes, list):
                paths = [change.get("path") for change in changes if isinstance(change, dict)]
                lines.extend((f"[EDIT] {', '.join(path for path in paths if isinstance(path, str))}", ""))
        elif itype == "error":
            lines.extend((f"[WARNING] {item.get('message', '')}", ""))
    elif etype == "error":
        lines.extend((f"[ERROR] {event.get('message', '')}", ""))


def _retry_may_duplicate_model_work(jsonl_path: str) -> bool:
    """Detect native activity or a stream too incomplete to retry safely."""

    saw_turn_started = False
    saw_turn_failed = False
    failure_payload_invalid = False
    failure_messages: list[str] = []
    try:
        with open(jsonl_path) as f:
            for raw in f:
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return True
                if not isinstance(event, dict):
                    return True
                event_type = event.get("type")
                if not isinstance(event_type, str):
                    return True
                if event_type == CODEX_CHILD_USAGE_EVENT:
                    audit, audit_warnings = _parse_child_usage_audit(event)
                    if (
                        audit is None
                        or audit_warnings
                        or not audit.complete
                        or bool(audit.requests)
                        or audit.input_tokens > 0
                        or audit.output_tokens > 0
                    ):
                        return True
                    continue
                if event_type == "turn.started":
                    saw_turn_started = True
                elif event_type == "turn.completed":
                    return True
                elif event_type == "turn.failed":
                    saw_turn_failed = True
                    error = event.get("error")
                    message = error.get("message") if isinstance(error, dict) else None
                    if isinstance(message, str):
                        failure_messages.append(message)
                    else:
                        failure_payload_invalid = True
                elif event_type == "error":
                    message = event.get("message")
                    if isinstance(message, str):
                        failure_messages.append(message)
                    else:
                        failure_payload_invalid = True
                item = event.get("item")
                if not event_type.startswith("item.") or not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if isinstance(item_type, str) and item_type in _MODEL_ACTIVITY_ITEM_TYPES:
                    return True
                if item_type == "error":
                    message = item.get("message")
                    if isinstance(message, str) and _STREAM_LAG_RE.search(message):
                        # This warning is not itself model work, but events that
                        # would prove work may be among those dropped. Retrying
                        # such a launch could silently duplicate paid work.
                        return True
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError):
        return True

    if saw_turn_failed and not saw_turn_started:
        # A terminal failure without its required start event is a damaged
        # lifecycle, so it cannot prove that dispatch never happened.
        return True
    if not saw_turn_started:
        return False
    # The explicit provider cap is a rejection, not an interrupted generation.
    # It owns a separate wait-and-retry path in the runner. Every other started
    # failure may have reached the provider before its first item event arrived.
    return not (
        saw_turn_failed
        and not failure_payload_invalid
        and failure_messages
        and all(_USAGE_LIMIT_RE.search(message) for message in failure_messages)
    )


def _parse_codex_run(jsonl_path: str) -> _ParsedCodexRun:
    lines: list[str] = []
    terminal_events: list[dict[str, Any]] = []
    terminal_usages: list[_CodexTerminalUsage] = []
    child_audit_events = 0
    child_audits: list[_CodexChildUsageAudit] = []
    saw_child_audit_start = False
    root_thread_ids: list[str] = []
    warnings: list[str] = []
    malformed_lines = 0
    failed_turns = 0
    saw_multi_agent_activity = False
    saw_stream_lag = False
    saw_model_reroute = False

    try:
        with open(jsonl_path) as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    malformed_lines += 1
                    continue
                if not isinstance(event, dict):
                    malformed_lines += 1
                    continue
                _append_transcript_event(lines, event)
                event_type = event.get("type")
                item = event.get("item")
                if event_type == "thread.started":
                    thread_id = event.get("thread_id")
                    if isinstance(thread_id, str) and thread_id:
                        root_thread_ids.append(thread_id)
                elif event_type == CODEX_CHILD_USAGE_START_EVENT:
                    saw_child_audit_start = True
                elif event_type == CODEX_CHILD_USAGE_EVENT:
                    child_audit_events += 1
                    child_audit, audit_warnings = _parse_child_usage_audit(event)
                    warnings.extend(audit_warnings)
                    if child_audit is not None:
                        child_audits.append(child_audit)
                if isinstance(event_type, str) and event_type.startswith("item.") and isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "collab_tool_call":
                        saw_multi_agent_activity = True
                    elif item_type == "error":
                        message = item.get("message")
                        if isinstance(message, str):
                            if _STREAM_LAG_RE.search(message):
                                saw_stream_lag = True
                            if message.startswith("model rerouted: "):
                                saw_model_reroute = True
                if event_type == "turn.completed":
                    terminal_events.append(event)
                    terminal_usage, terminal_warnings = _parse_terminal_usage(event)
                    warnings.extend(terminal_warnings)
                    if terminal_usage is not None:
                        terminal_usages.append(terminal_usage)
                elif event_type == "turn.failed":
                    failed_turns += 1
    except (OSError, UnicodeError) as exc:
        return _ParsedCodexRun(
            transcript="\n".join(lines),
            usage=UsageSummary(
                sources=("codex_cli_jsonl",),
                available=False,
                warnings=(f"Codex JSONL output unavailable: {type(exc).__name__}",),
            ),
        )

    if malformed_lines:
        warnings.append(f"Codex JSONL contains {malformed_lines} malformed nonempty line(s)")
    if saw_stream_lag:
        warnings.append("Codex reported dropped JSONL events; model activity and usage may be incomplete")
    if child_audit_events > 1:
        warnings.append("Codex JSONL contains multiple child-usage audits; ignoring ambiguous child totals")
    child_audit = child_audits[0] if child_audit_events == 1 and len(child_audits) == 1 else None
    child_audit_matches_root = (
        child_audit is not None and len(root_thread_ids) == 1 and root_thread_ids[0] == child_audit.root_thread_id
    )
    if not terminal_usages:
        if not terminal_events:
            warnings.append("Codex turn.completed usage is unavailable")
        if failed_turns:
            warnings.append("Codex turn failed before terminal usage was emitted")
        if child_audit is not None and not child_audit_matches_root:
            warnings.append("Codex child-usage audit does not match one primary thread")
        if (
            child_audit is not None
            and child_audit_matches_root
            and (child_audit.input_tokens > 0 or child_audit.output_tokens > 0)
        ):
            warnings.extend(child_audit.warnings)
            warnings.append("Codex totals include child usage only because primary-thread usage is unavailable")
            return _ParsedCodexRun(
                transcript="\n".join(lines),
                usage=UsageSummary(
                    input_tokens=child_audit.input_tokens,
                    output_tokens=child_audit.output_tokens,
                    cache_read_input_tokens=child_audit.cache_read_input_tokens,
                    cache_write_input_tokens=child_audit.cache_write_input_tokens,
                    reasoning_output_tokens=child_audit.reasoning_output_tokens,
                    model_requests=None,
                    model_time_secs=None,
                    costs=(),
                    requests=(),
                    sources=(_CODEX_CHILD_USAGE_SOURCE,),
                    available=True,
                    complete=False,
                    is_lower_bound=True,
                    warnings=tuple(dict.fromkeys(warnings)),
                ),
            )
        return _ParsedCodexRun(
            transcript="\n".join(lines),
            usage=UsageSummary(
                sources=("codex_cli_jsonl",),
                available=False,
                warnings=tuple(dict.fromkeys(warnings)),
            ),
        )

    selected = terminal_usages[-1]
    warnings.extend(selected.warnings)
    lower_bound = False
    if len(terminal_events) > 1:
        warnings.append("Codex JSONL contains multiple turn.completed events; using the last usable aggregate")
        lower_bound = True
    if child_audit_events > 1:
        lower_bound = True
    if malformed_lines:
        lower_bound = True
    if failed_turns:
        warnings.append("Codex JSONL contains both failed and completed turn events")
        lower_bound = True
    if saw_model_reroute:
        warnings.append("Codex used a rerouted model; requested-model pricing is unsafe")
        lower_bound = True
    if child_audit is not None:
        warnings.extend(child_audit.warnings)
        if not child_audit_matches_root:
            warnings.append("Codex child-usage audit does not match one primary thread")
            lower_bound = True
        if not child_audit.complete:
            lower_bound = True
    elif child_audit_events == 1:
        warnings.append("Codex child-usage audit is unusable")
        lower_bound = True
    elif saw_child_audit_start:
        warnings.append("Codex child-usage audit did not finish")
        lower_bound = True
    elif saw_multi_agent_activity:
        warnings.append(
            "Codex JSONL contains multi-agent activity without a child-usage audit; "
            "the terminal aggregate covers only the parent thread"
        )
        lower_bound = True
    if saw_stream_lag:
        lower_bound = True

    usable_child_audit = child_audit if child_audit_matches_root else None
    child_input_tokens = usable_child_audit.input_tokens if usable_child_audit is not None else 0
    child_output_tokens = usable_child_audit.output_tokens if usable_child_audit is not None else 0
    cache_read_input_tokens = selected.cache_read_input_tokens
    cache_write_input_tokens = selected.cache_write_input_tokens
    reasoning_output_tokens = selected.reasoning_output_tokens
    if usable_child_audit is not None:
        if cache_read_input_tokens is not None:
            cache_read_input_tokens += usable_child_audit.cache_read_input_tokens
        if cache_write_input_tokens is not None:
            cache_write_input_tokens += usable_child_audit.cache_write_input_tokens
        if reasoning_output_tokens is not None:
            reasoning_output_tokens += usable_child_audit.reasoning_output_tokens

    requests: tuple[RequestUsage, ...] = ()
    model_requests: int | None = None
    if (
        usable_child_audit is not None
        and usable_child_audit.complete
        and not selected.incomplete
        and cache_read_input_tokens is not None
        and cache_write_input_tokens is not None
        and reasoning_output_tokens is not None
    ):
        expected_request_totals = (
            selected.input_tokens + child_input_tokens,
            cache_read_input_tokens,
            cache_write_input_tokens,
            selected.output_tokens + child_output_tokens,
            reasoning_output_tokens,
        )
        if _request_token_totals(usable_child_audit.requests) != expected_request_totals:
            warnings.append("Codex v3 per-request usage does not match terminal and child aggregate totals")
            lower_bound = True
        elif not lower_bound:
            requests = usable_child_audit.requests
            model_requests = len(requests)

    sources = [_CODEX_USAGE_SOURCE]
    if usable_child_audit is not None and usable_child_audit.child_count:
        sources.append(_CODEX_CHILD_USAGE_SOURCE)

    return _ParsedCodexRun(
        transcript="\n".join(lines),
        usage=UsageSummary(
            input_tokens=selected.input_tokens + child_input_tokens,
            output_tokens=selected.output_tokens + child_output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_write_input_tokens=cache_write_input_tokens,
            reasoning_output_tokens=reasoning_output_tokens,
            model_requests=model_requests,
            model_time_secs=None,
            costs=(),
            requests=requests,
            sources=tuple(sources),
            available=True,
            complete=not lower_bound and not selected.incomplete,
            is_lower_bound=lower_bound,
            warnings=tuple(dict.fromkeys(warnings)),
        ),
    )


def _tool_command(item: dict[str, Any]) -> str | None:
    if item.get("type") == "mcp_tool_call":
        return toolcalls.blocking_proof_check_command(
            item.get("tool"), item.get("arguments"), f"mcp__{item.get('server')}"
        )
    command = item.get("command")
    return command if item.get("type") == "command_execution" and isinstance(command, str) else None


def _same_tool_item(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("type") == right.get("type") and _tool_command(left) == _tool_command(right)


def _parse_tool_calls(jsonl_path: str) -> toolcalls.ToolCallSummary:
    """Use the rollout session-tree audit, with CLI root events as fallback."""

    evidence = toolcalls.EventStreamEvidence()
    starts: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    updates: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    completions: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    anonymous_starts: list[tuple[int, dict[str, Any]]] = []
    anonymous_updates: list[tuple[int, dict[str, Any]]] = []
    anonymous_completions: list[tuple[int, dict[str, Any]]] = []
    root_thread_ids: list[str | None] = []
    root_thread_indexes: list[int] = []
    turn_started_indexes: list[int] = []
    terminals: list[tuple[int, str]] = []
    trailing_root_activity = False
    saw_stream_lag = False
    saw_multi_agent_activity = False
    child_audit_starts = 0
    child_audit_start_indexes: list[int] = []
    child_audit_start_versions: list[object] = []
    child_audit_events = 0
    child_audit_indexes: list[int] = []
    child_audits: list[_CodexChildToolAudit] = []
    warnings: list[str] = []

    for index, event in enumerate(toolcalls.iter_events(jsonl_path, evidence)):
        event_type = event.get("type")
        if terminals and event_type in {"turn.started", "turn.completed", "turn.failed"}:
            trailing_root_activity = True
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            root_thread_ids.append(thread_id if isinstance(thread_id, str) and thread_id else None)
            root_thread_indexes.append(index)
        elif event_type == "turn.started":
            turn_started_indexes.append(index)
        elif event_type in {"turn.completed", "turn.failed"}:
            terminals.append((index, event_type))
        elif event_type == CODEX_CHILD_USAGE_START_EVENT:
            child_audit_starts += 1
            child_audit_start_indexes.append(index)
            child_audit_start_versions.append(event.get("version"))
        elif event_type == CODEX_CHILD_USAGE_EVENT:
            child_audit_events += 1
            child_audit_indexes.append(index)
            audit, audit_warnings = _parse_child_tool_audit(event)
            warnings.extend(audit_warnings)
            if audit is not None:
                child_audits.append(audit)

        item = event.get("item")
        if not event_type.startswith("item."):
            continue
        if not isinstance(item, dict):
            evidence.warn("Codex item event has an invalid item object")
            continue
        if terminals and index > terminals[-1][0]:
            trailing_root_activity = True
        item_type = item.get("type")
        if not isinstance(item_type, str):
            evidence.warn("Codex item event has a missing or invalid item type")
            continue
        if item_type == "collab_tool_call":
            saw_multi_agent_activity = True
        elif item_type == "error":
            message = item.get("message")
            if isinstance(message, str) and _STREAM_LAG_RE.search(message):
                saw_stream_lag = True
        if item_type not in _TOOL_ITEM_TYPES or event_type not in {
            "item.started",
            "item.updated",
            "item.completed",
        }:
            continue
        item_id = item.get("id")
        if event_type == "item.started":
            target, anonymous = starts, anonymous_starts
        elif event_type == "item.updated":
            target, anonymous = updates, anonymous_updates
        else:
            target, anonymous = completions, anonymous_completions
        if isinstance(item_id, str) and item_id:
            target.setdefault(item_id, []).append((index, item))
        else:
            anonymous.append((index, item))

    lifecycle_complete = True
    if saw_stream_lag:
        evidence.warn("Codex reported dropped JSONL events; tool-call totals may be incomplete")
    if len(root_thread_ids) != 1 or root_thread_ids[0] is None:
        warnings.append("Codex tool-call stream does not identify exactly one primary thread")
        lifecycle_complete = False
    if len(turn_started_indexes) != 1:
        warnings.append("Codex tool-call stream does not contain exactly one turn.started event")
        lifecycle_complete = False
    if len(terminals) != 1 or terminals[0][1] not in {"turn.completed", "turn.failed"}:
        warnings.append("Codex tool-call stream did not end in one terminal turn event")
        lifecycle_complete = False
    if trailing_root_activity:
        warnings.append("Codex tool-call stream contains item activity after its terminal event")
        lifecycle_complete = False
    if (
        len(root_thread_indexes) == 1
        and len(turn_started_indexes) == 1
        and len(terminals) == 1
        and not (root_thread_indexes[0] < turn_started_indexes[0] < terminals[0][0])
    ):
        warnings.append("Codex tool-call stream has an invalid thread/turn event order")
        lifecycle_complete = False

    tool_item_indexes = [
        index
        for entries in (
            *starts.values(),
            *updates.values(),
            *completions.values(),
            anonymous_starts,
            anonymous_updates,
            anonymous_completions,
        )
        for index, _item in entries
    ]
    if (
        tool_item_indexes
        and len(turn_started_indexes) == 1
        and len(terminals) == 1
        and any(not (turn_started_indexes[0] < index < terminals[0][0]) for index in tool_item_indexes)
    ):
        warnings.append("Codex tool-call stream contains tool activity outside its active turn")
        lifecycle_complete = False

    observed: list[tuple[int, str | None]] = []
    all_item_ids = set(starts) | set(updates) | set(completions)
    todo_ids = {
        item_id
        for item_id in all_item_ids
        if any(
            item.get("type") == "todo_list"
            for entries in (starts.get(item_id, ()), updates.get(item_id, ()), completions.get(item_id, ()))
            for _index, item in entries
        )
    }
    for item_id in sorted(
        todo_ids,
        key=lambda candidate: min(
            index
            for entries in (starts.get(candidate, ()), updates.get(candidate, ()), completions.get(candidate, ()))
            for index, _item in entries
        ),
    ):
        started = starts.get(item_id, [])
        updated = updates.get(item_id, [])
        completed = completions.get(item_id, [])
        all_entries = [*started, *updated, *completed]
        if started:
            observed.append((started[0][0], _tool_command(started[0][1])))
        todo_updates = [(index, item) for index, item in updated if item.get("type") == "todo_list"]
        observed.extend((index, None) for index, _item in todo_updates)
        if not started and not todo_updates and completed:
            observed.append((completed[0][0], _tool_command(completed[0][1])))

        if any(item.get("type") != "todo_list" for _index, item in all_entries):
            warnings.append(f"Codex todo item {item_id} conflicts with another tool item type")
            lifecycle_complete = False
        if len(started) != 1:
            warning = "has no started event" if not started else "has duplicate started events"
            warnings.append(f"Codex todo item {item_id} {warning}")
            lifecycle_complete = False
        if len(completed) != 1:
            warning = "did not complete" if not completed else "has duplicate completed events"
            warnings.append(f"Codex todo item {item_id} {warning}")
            lifecycle_complete = False
        if started and completed:
            start_index = started[0][0]
            completion_index = completed[0][0]
            if completion_index <= start_index or any(
                not (start_index < update_index < completion_index) for update_index, _item in updated
            ):
                warnings.append(f"Codex todo item {item_id} has an invalid update lifecycle")
                lifecycle_complete = False

    for item_id, entries in starts.items():
        if item_id in todo_ids:
            continue
        first_index, first_item = entries[0]
        observed.append((first_index, _tool_command(first_item)))
        if len(entries) > 1:
            warnings.append(f"Codex tool item {item_id} has duplicate started events")
            lifecycle_complete = False
        if any(not _same_tool_item(first_item, item) for _, item in entries[1:]):
            warnings.append(f"Codex tool item {item_id} has conflicting started events")
            lifecycle_complete = False
        completed = completions.get(item_id, [])
        if not completed:
            warnings.append(f"Codex tool item {item_id} started but did not complete")
            lifecycle_complete = False
        else:
            if len(completed) > 1:
                warnings.append(f"Codex tool item {item_id} has duplicate completed events")
                lifecycle_complete = False
            if any(index <= first_index or not _same_tool_item(first_item, item) for index, item in completed):
                warnings.append(f"Codex tool item {item_id} has an inconsistent completed event")
                lifecycle_complete = False
            first_completed = completed[0][1]
            if any(not _same_tool_item(first_completed, item) for _, item in completed[1:]):
                warnings.append(f"Codex tool item {item_id} has conflicting completed events")
                lifecycle_complete = False
    for item_id, entries in completions.items():
        if item_id in starts or item_id in todo_ids:
            continue
        first_index, first_item = entries[0]
        observed.append((first_index, _tool_command(first_item)))
        warnings.append(f"Codex tool item {item_id} completed without a recorded start")
        lifecycle_complete = False
        if len(entries) > 1:
            warnings.append(f"Codex tool item {item_id} has duplicate completed events")
        if any(not _same_tool_item(first_item, item) for _, item in entries[1:]):
            warnings.append(f"Codex tool item {item_id} has conflicting completed events")
    for item_id, entries in updates.items():
        if item_id in todo_ids:
            continue
        warnings.append(f"Codex tool item {item_id} has an unexpected updated event")
        lifecycle_complete = False
        if item_id not in starts and item_id not in completions:
            first_index, first_item = entries[0]
            observed.append((first_index, _tool_command(first_item)))
    # Without IDs, repeated lifecycle records cannot be distinguished from
    # repeated calls.  Keep one positive dispatch witness per signature so the
    # degraded result remains a genuine lower bound instead of over-counting a
    # replayed start or completion.
    anonymous_witnesses = [*anonymous_starts, *anonymous_updates, *anonymous_completions]
    if anonymous_witnesses and not starts and not updates and not completions:
        index, item = min(anonymous_witnesses, key=lambda entry: entry[0])
        observed.append((index, _tool_command(item)))
    if anonymous_starts or anonymous_updates or anonymous_completions:
        warnings.append("Codex tool-call stream contains tool items without IDs")
        lifecycle_complete = False

    observed.sort(key=lambda entry: entry[0])
    summary = toolcalls.summarize(
        (command for _, command in observed),
        evidence,
        lifecycle_complete=lifecycle_complete,
        warnings=warnings,
    )

    def invalid_session_tree_audit(*audit_warnings: str) -> toolcalls.ToolCallSummary:
        return toolcalls.ToolCallSummary.from_commands(
            (),
            available=True,
            complete=False,
            warnings=(*summary.warnings, *warnings, *audit_warnings),
        )

    if child_audit_starts == 0:
        if child_audit_events:
            return invalid_session_tree_audit("Codex child tool-call audit appeared without its start sentinel")
        if saw_multi_agent_activity:
            return summary.merge(
                toolcalls.ToolCallSummary.from_commands(
                    (),
                    available=True,
                    complete=False,
                    warnings=("Codex multi-agent activity has no child tool-call audit",),
                )
            )
        return summary

    if (
        child_audit_starts != 1
        or child_audit_start_versions != [CODEX_CHILD_USAGE_VERSION]
        or child_audit_events != 1
        or len(child_audits) != 1
    ):
        return invalid_session_tree_audit("Codex child tool-call audit is missing or ambiguous")
    if child_audit_start_indexes != [0] or child_audit_indexes != [evidence.event_count - 1]:
        return invalid_session_tree_audit("Codex child tool-call audit has an invalid stream position")
    child_audit = child_audits[0]
    if len(root_thread_ids) != 1 or root_thread_ids[0] != child_audit.root_thread_id:
        return invalid_session_tree_audit("Codex child tool-call audit does not match the primary thread")
    return child_audit.tool_calls


class CodexBackend(AgenticBackend):
    name = "codex"
    requires_public_pricing = True
    install_script = "install-codex.sh"
    session_state_dir = "/root/.codex"
    project_skills_dir = ".agents/skills"
    env_keys = [
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_HOST",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
    ]
    credential_mounts = ["codex"]
    reasoning_effort_values = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL

    def build_command(self, workspace: str, result_dir: str) -> list[str]:
        last_msg_path = os.path.join(result_dir, "codex_last_message.txt")
        wrapper = (
            ["python3", "/opt/codex_usage_wrapper.py"]
            if workspace == "/workspace"
            else [sys.executable, os.path.join(os.path.dirname(__file__), "codex_usage_wrapper.py")]
        )
        # Invoke the `codex` binary directly (it must be on PATH). Going through
        # `npx codex` is wrong: npm has no top-level `codex` package (OpenAI's is
        # `@openai/codex`), so `npx codex` resolves to an unrelated bogus package.
        cmd = [
            *wrapper,
            "--proof-check-workspace",
            workspace,
            "--",
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            workspace,
            "-m",
            self.model,
            "-c",
            "web_search=disabled",
            "--json",
            "-o",
            last_msg_path,
        ]
        if self.reasoning_effort is not None:
            cmd.extend(["-c", f"model_reasoning_effort={self.reasoning_effort}"])
        if self._uses_bedrock():
            cmd.extend(["-c", 'model_provider="amazon-bedrock"'])
        return cmd

    def get_credential_mounts(self) -> list[str]:
        mounts = []
        if self._uses_bedrock() or not self._has_api_key_auth():
            mounts.append("codex")
        if self._uses_bedrock() and needs_aws_shared_credentials():
            mounts.append("aws")
        return mounts

    @staticmethod
    def _has_api_key_auth() -> bool:
        return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY"))

    def _uses_bedrock(self) -> bool:
        if self.model.startswith("openai."):
            return True
        return self._host_config_uses_bedrock()

    @staticmethod
    def _host_config_uses_bedrock() -> bool:
        config_path = Path.home() / ".codex" / "config.toml"
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
        except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
            return False
        return config.get("model_provider") == "amazon-bedrock"

    @staticmethod
    def _host_config_has_bedrock_region() -> bool:
        config_path = Path.home() / ".codex" / "config.toml"
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
        except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
            return False
        provider = config.get("model_providers", {}).get("amazon-bedrock", {})
        aws = provider.get("aws", {}) if isinstance(provider, dict) else {}
        region = aws.get("region") if isinstance(aws, dict) else None
        return isinstance(region, str) and bool(region)

    @staticmethod
    def public_pricing_configuration_error() -> str | None:
        """Reject host-side Codex service tiers the price library cannot value."""

        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        try:
            with open(codex_home / "config.toml", "rb") as f:
                service_tier = tomllib.load(f).get("service_tier", "default")
        except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
            return None
        if service_tier in {"default", "standard"}:
            return None
        return f"Codex service tier {service_tier!r} has no reliable public price"

    def check_auth(self) -> str | None:
        if self._uses_bedrock():
            if has_aws_bedrock_bearer_token():
                if not (has_aws_region() or self._host_config_has_bedrock_region()):
                    return "codex: AWS_REGION or AWS_DEFAULT_REGION required for Bedrock bearer-token auth"
                return None
            if has_aws_env_credentials():
                if not (has_aws_region() or self._host_config_has_bedrock_region()):
                    return "codex: AWS_REGION or AWS_DEFAULT_REGION required for Bedrock AWS env auth"
                return None
            if has_aws_shared_credentials():
                return None
            return "codex: Bedrock selected but no AWS credentials detected"
        # Fast paths: an env var is set (direct OpenAI or Azure routing).
        if os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY"):
            return None
        # Slow path: ask codex itself whether it's logged in (OAuth/ChatGPT).
        # This is a local read of ~/.codex state, no API call, no session.
        try:
            r = subprocess.run(
                ["codex", "login", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0 and "Logged in" in (r.stdout + r.stderr):
                return None
        except FileNotFoundError:
            return "codex: `codex` CLI not found on PATH"
        except Exception:
            pass
        return "codex: no auth detected. Set OPENAI_API_KEY or AZURE_OPENAI_API_KEY, or run `codex login`."

    def firewall_hosts(self) -> list[str]:
        return detect_firewall_hosts(self.model)

    def usage_script(self) -> str | None:
        return "scripts/usage/codex.sh"

    def default_quota(self) -> tuple[float, float]:
        return (95.0, 95.0)

    def detect_quota_block(self, jsonl_path: str) -> int | None:
        """Detect ChatGPT's hard 'usage limit' cap and return seconds to wait.

        The percentage gate cannot see this: once capped, codex's turns fail
        instantly with no `usage` event, so the rolling utilization the gate reads
        goes stale/low and never trips — every subsequent task fails in ~3s and is
        misgraded as FAIL. We scan the run's own events for the explicit usage-limit
        error and sleep until the stated reset instead. Returns None if no cap.
        """
        msg = None
        saw_completed_turn = False
        try:
            with open(jsonl_path) as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    t = ev.get("type", "")
                    if t == "turn.completed":
                        saw_completed_turn = True
                        continue
                    if t == "error":
                        candidate = ev.get("message")
                        m = candidate if isinstance(candidate, str) else ""
                    elif t == "turn.failed":
                        error = ev.get("error")
                        candidate = error.get("message") if isinstance(error, dict) else None
                        m = candidate if isinstance(candidate, str) else ""
                    else:
                        continue
                    if m and _USAGE_LIMIT_RE.search(m):
                        msg = m  # keep the last occurrence
        except (OSError, UnicodeError):
            return None
        if msg is None or saw_completed_turn:
            return None
        # Prefer the precise reset epoch codex records in its session rollout (what
        # the usage probe reads) over parsing the human "try again at 7:24 PM"
        # string, which is timezone- and boundary-fragile. Fall back to the prose
        # time only when the probe has no data.
        reset_at = self._reset_at_from_probe()
        when = reset_at if reset_at is not None else self._parse_retry_time(msg)
        return quota.secs_until_reset(when, clamp_hi=6 * 3600, fallback=1800)

    def _reset_at_from_probe(self) -> str | None:
        """The reset time (ISO) of the window that hit its cap, from the codex
        usage probe — or None.

        Codex records a structured ``resets_at`` epoch per window in its session
        rollout, far more reliable than the human time in the cap message. The
        binding window is the one at its cap (utilization >= 100); when both the 5h
        and weekly windows are capped we wait for the later reset, so a weekly cap
        with a fresh 5h window doesn't make us retry-thrash until the 5h resets.
        Falls back to the most-utilized window, then to None (prose time) when the
        probe can't be read (no repo script, no ~/.codex, API-key auth).
        """
        rel = self.usage_script()
        if not rel:
            return None
        usage = quota.fetch_usage(os.path.join(_REPO_ROOT, rel))
        if not usage:
            return None
        raw_windows = (usage.get("five_hour"), usage.get("seven_day"))
        windows = [window for window in raw_windows if isinstance(window, dict)]

        def utilization(window: dict[str, object]) -> int | float:
            value = window.get("utilization")
            if isinstance(value, int) and not isinstance(value, bool):
                return value if value >= 0 else 0
            if isinstance(value, float) and value >= 0 and math.isfinite(value):
                return value
            return 0

        def has_reset(window: dict[str, object]) -> bool:
            value = window.get("resets_at")
            return isinstance(value, str) and bool(value)

        capped = [window for window in windows if utilization(window) >= 100 and has_reset(window)]
        if capped:
            return max(str(window["resets_at"]) for window in capped)  # wait past the last-clearing cap
        with_reset = [window for window in windows if has_reset(window)]
        if not with_reset:
            return None
        return str(max(with_reset, key=utilization)["resets_at"])

    @staticmethod
    def _parse_retry_time(msg: str) -> datetime | None:
        """Parse 'try again at 7:24 PM' from a usage-limit message into a datetime
        (today, or tomorrow if that time already passed), or None if absent. Waking
        too early (timezone skew) is self-correcting: the retry re-hits the cap and
        re-sleeps on the fresh error.
        """
        m = _RETRY_AT_RE.search(msg)
        if not m:
            return None
        try:
            hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
            if ap == "PM" and hh != 12:
                hh += 12
            elif ap == "AM" and hh == 12:
                hh = 0
            now = datetime.now()
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target
        except Exception:
            return None

    def parse_run_metadata(self, jsonl_path: str) -> dict[str, object]:
        return {"tool_calls": _parse_tool_calls(jsonl_path).to_dict()}

    def parse_output(self, jsonl_path: str) -> tuple[str, int, int]:
        parsed = _parse_codex_run(jsonl_path)
        return parsed.transcript, parsed.usage.legacy_input_tokens, parsed.usage.legacy_output_tokens

    def parse_usage(self, jsonl_path: str, *, input_tokens: int, output_tokens: int) -> UsageSummary:
        # The legacy counts are produced by this same parser. Read the native
        # terminal aggregate again so structured and compatibility fields share
        # one protocol interpretation and can never double-count intermediates.
        del input_tokens, output_tokens
        return _parse_codex_run(jsonl_path).usage

    def retry_may_duplicate_model_work(self, jsonl_path: str) -> bool:
        # A failed turn has no native token aggregate. Known model-driven item
        # types prove activity; a stream-lag warning means such proof may have
        # been dropped. Both make an automatic replacement unsafe without
        # fabricating request or token counts.
        return _retry_may_duplicate_model_work(jsonl_path)

    def attempt_output_files(self) -> tuple[str, ...]:
        # `-o` is only written after a final response. Without isolating it, a
        # later failed retry can leave an earlier launch's message looking final.
        return ("codex_last_message.txt",)

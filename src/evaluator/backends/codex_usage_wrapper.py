"""Stream ``codex exec`` JSONL and append a sanitized rollout-tree audit.

Codex's public ``turn.completed`` event reports only the primary thread. Rollout
files persist native cumulative token counters for the full session tree, so this
wrapper emits child token aggregates, session-tree tool calls, and sanitized
per-request metadata. Prompts and rollout content never leave the state directory.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

if __package__:
    from evaluator import toolcalls as _toolcalls
else:
    # Local evaluator runs execute this file by path, so Python otherwise adds
    # only ``.../backends`` to sys.path while the shared module lives one level up.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import toolcalls as _toolcalls

CODEX_CHILD_USAGE_EVENT = "tlaps.codex_child_usage"
CODEX_CHILD_USAGE_START_EVENT = "tlaps.codex_child_usage.started"
CODEX_CHILD_USAGE_VERSION = 5

_TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
_TURN_STARTED_TYPES = frozenset({"task_started", "turn_started"})
_TURN_COMPLETED_TYPES = frozenset({"task_complete", "turn_complete"})
_JAVASCRIPT_LANGUAGE = Language(tree_sitter_javascript.language())


@dataclass(frozen=True)
class _TokenTotals:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    def __add__(self, other: _TokenTotals) -> _TokenTotals:
        return _TokenTotals(  # type: ignore[arg-type]
            **{field: getattr(self, field) + getattr(other, field) for field in _TOKEN_FIELDS}
        )

    def delta_from(self, baseline: _TokenTotals) -> _TokenTotals | None:
        values = {field: getattr(self, field) - getattr(baseline, field) for field in _TOKEN_FIELDS}
        if any(value < 0 for value in values.values()):
            return None
        return _TokenTotals(**values)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in _TOKEN_FIELDS}


@dataclass(frozen=True)
class _TimelineItem:
    index: int
    kind: str
    turn_id: str | None = None
    totals: _TokenTotals | None = None
    model: str | None = None
    tool_id: str | None = None
    command: str | None = None


@dataclass(frozen=True)
class _RolloutMeta:
    session_id: str
    thread_id: str
    parent_thread_id: str | None
    forked_from_id: str | None
    model_provider: str | None


@dataclass(frozen=True)
class _SanitizedRequest:
    usage: _TokenTotals
    model: str | None
    provider: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            **self.usage.to_dict(),
            "model": self.model,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class _UsageRollout:
    meta: _RolloutMeta
    timeline: tuple[_TimelineItem, ...]
    referenced_child_ids: frozenset[str]
    invalid_indexes: tuple[int, ...]
    tool_invalid_indexes: tuple[int, ...]
    unsupported_service_tier: bool

    @property
    def turn_ids(self) -> frozenset[str]:
        return frozenset(item.turn_id for item in self.timeline if item.kind == "started" and item.turn_id)

    @property
    def structurally_complete(self) -> bool:
        return not self.invalid_indexes

    @property
    def tool_structurally_complete(self) -> bool:
        return not self.tool_invalid_indexes


def _strict_token(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_totals(value: object) -> _TokenTotals | None:
    if not isinstance(value, dict):
        return None
    parsed = {field: _strict_token(value.get(field)) for field in _TOKEN_FIELDS}
    if any(token is None for token in parsed.values()):
        return None
    totals = _TokenTotals(**parsed)  # type: ignore[arg-type]
    if totals.cached_input_tokens + totals.cache_write_input_tokens > totals.input_tokens:
        return None
    if totals.reasoning_output_tokens > totals.output_tokens:
        return None
    return totals


def _parse_meta_record(value: object) -> _RolloutMeta | None:
    if not isinstance(value, dict) or value.get("type") != "session_meta":
        return None
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id")
    thread_id = payload.get("id")
    parent_thread_id = payload.get("parent_thread_id")
    forked_from_id = payload.get("forked_from_id")
    raw_model_provider = payload.get("model_provider")
    model_provider = raw_model_provider if isinstance(raw_model_provider, str) and raw_model_provider.strip() else None
    if not isinstance(session_id, str) or not session_id or not isinstance(thread_id, str) or not thread_id:
        return None
    if parent_thread_id is not None and (not isinstance(parent_thread_id, str) or not parent_thread_id):
        return None
    if forked_from_id is not None and (not isinstance(forked_from_id, str) or not forked_from_id):
        return None
    return _RolloutMeta(
        session_id=session_id,
        thread_id=thread_id,
        parent_thread_id=parent_thread_id,
        forked_from_id=forked_from_id,
        model_provider=model_provider,
    )


def _call_arguments(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _shell_command(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        return shlex.join(value)
    return None


def _javascript_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _javascript_nodes(root: Node) -> Iterable[Node]:
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.named_children))


def _javascript_static_string(source: bytes, node: Node) -> str | None:
    if node.type != "string":
        return None
    raw = _javascript_text(source, node)
    try:
        value = json.loads(raw) if raw.startswith('"') else ast.literal_eval(raw)
    except (json.JSONDecodeError, SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _javascript_object_command(source: bytes, node: Node) -> str | None:
    """Return one unambiguous literal ``cmd`` property from an object."""

    command: str | None = None
    for child in node.named_children:
        # Spreads, computed properties, and methods can override ``cmd`` at
        # runtime. Keep those objects conservative instead of guessing.
        if child.type != "pair":
            return None
        key = child.child_by_field_name("key")
        value = child.child_by_field_name("value")
        if key is None or value is None:
            return None
        key_name = (
            _javascript_text(source, key)
            if key.type in {"identifier", "property_identifier"}
            else _javascript_static_string(source, key)
        )
        if key_name is None:
            return None
        if key_name != "cmd":
            continue
        if command is not None:
            return None
        command = _javascript_static_string(source, value)
        if command is None:
            return None
    return command


def _code_mode_shell_commands(value: object) -> tuple[str, ...]:
    """Extract literal ``tools.exec_command`` commands from one code-mode call."""

    if not isinstance(value, str):
        return ()
    source = value.encode("utf-8", errors="replace")
    tree = Parser(_JAVASCRIPT_LANGUAGE).parse(source)
    if tree.root_node.has_error:
        return ()

    commands: list[str] = []
    for node in _javascript_nodes(tree.root_node):
        if node.type != "call_expression":
            continue
        function = node.child_by_field_name("function")
        if function is None or _javascript_text(source, function) != "tools.exec_command":
            continue
        arguments = node.child_by_field_name("arguments")
        if arguments is None or not arguments.named_children:
            continue
        options = arguments.named_children[0]
        if options.type != "object":
            continue
        command = _javascript_object_command(source, options)
        if command is not None:
            commands.append(command)
    return tuple(commands)


def _tool_dispatch(payload: dict[str, object]) -> tuple[str | None, str | None] | None:
    """Extract one sanitized outer rollout dispatch."""

    item_type = payload.get("type")
    if item_type == "function_call":
        name = payload.get("name")
        call_id = payload.get("call_id")
        command = None
        if name in {"exec_command", "shell_command"}:
            arguments = _call_arguments(payload.get("arguments"))
            if arguments is not None:
                command_key = "cmd" if name == "exec_command" else "command"
                command = _shell_command(arguments.get(command_key))
        else:
            command = _toolcalls.blocking_proof_check_command(
                name, _call_arguments(payload.get("arguments")), payload.get("namespace")
            )
        return (call_id if isinstance(call_id, str) and call_id else None, command)
    if item_type == "custom_tool_call":
        name = payload.get("name")
        call_id = payload.get("call_id")
        commands = _code_mode_shell_commands(payload.get("input")) if name == "exec" else ()
        command = "\n".join(commands) if commands else None
        return (call_id if isinstance(call_id, str) and call_id else None, command)
    if item_type == "local_shell_call":
        raw_call_id = payload.get("call_id")
        item_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id else payload.get("id")
        action = payload.get("action")
        command = _shell_command(action.get("command")) if isinstance(action, dict) else None
        return (item_id if isinstance(item_id, str) and item_id else None, command)
    if item_type in {
        "computer_call",
        "image_generation_call",
        "mcp_tool_call",
        "tool_search_call",
        "web_search_call",
    }:
        raw_call_id = payload.get("call_id")
        item_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id else payload.get("id")
        return (item_id if isinstance(item_id, str) and item_id else None, None)
    return None


def _read_usage_rollout(path: Path) -> _UsageRollout | None:
    meta: _RolloutMeta | None = None
    timeline: list[_TimelineItem] = []
    referenced_child_ids: set[str] = set()
    invalid_indexes: list[int] = []
    tool_invalid_indexes: list[int] = []
    unsupported_service_tier = False
    try:
        with path.open("rb") as rollout:
            for index, raw_bytes in enumerate(rollout):
                try:
                    raw = raw_bytes.decode("utf-8")
                except UnicodeError:
                    if index == 0:
                        return None
                    invalid_indexes.append(index)
                    tool_invalid_indexes.append(index)
                    continue
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    if index == 0:
                        return None
                    invalid_indexes.append(index)
                    tool_invalid_indexes.append(index)
                    continue
                if not isinstance(record, dict):
                    if index == 0:
                        return None
                    invalid_indexes.append(index)
                    tool_invalid_indexes.append(index)
                    continue
                if index == 0:
                    meta = _parse_meta_record(record)
                    if meta is None:
                        return None
                    continue
                record_type = record.get("type")
                if not isinstance(record_type, str):
                    invalid_indexes.append(index)
                    tool_invalid_indexes.append(index)
                    continue
                if record_type == "turn_context":
                    payload = record.get("payload")
                    turn_id = payload.get("turn_id") if isinstance(payload, dict) else None
                    model = payload.get("model") if isinstance(payload, dict) else None
                    if isinstance(turn_id, str) and turn_id and isinstance(model, str) and model.strip():
                        timeline.append(_TimelineItem(index=index, kind="context", turn_id=turn_id, model=model))
                    else:
                        invalid_indexes.append(index)
                    continue
                if record_type == "response_item":
                    payload = record.get("payload")
                    if not isinstance(payload, dict):
                        invalid_indexes.append(index)
                        tool_invalid_indexes.append(index)
                        continue
                    if not isinstance(payload.get("type"), str):
                        invalid_indexes.append(index)
                        tool_invalid_indexes.append(index)
                        continue
                    dispatch = _tool_dispatch(payload)
                    if dispatch is not None:
                        tool_id, command = dispatch
                        timeline.append(_TimelineItem(index=index, kind="tool", tool_id=tool_id, command=command))
                    continue
                if record_type != "event_msg":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    invalid_indexes.append(index)
                    tool_invalid_indexes.append(index)
                    continue
                event_type = payload.get("type")
                if not isinstance(event_type, str):
                    invalid_indexes.append(index)
                    tool_invalid_indexes.append(index)
                    continue
                if event_type == "thread_settings_applied":
                    settings = payload.get("thread_settings")
                    if not isinstance(settings, dict):
                        invalid_indexes.append(index)
                        continue
                    service_tier = settings.get("service_tier")
                    if service_tier is not None and (
                        not isinstance(service_tier, str) or service_tier not in {"default", "standard"}
                    ):
                        unsupported_service_tier = True
                elif event_type == "token_count":
                    info = payload.get("info")
                    if info is None:
                        continue
                    totals = _parse_totals(info.get("total_token_usage") if isinstance(info, dict) else None)
                    if totals is None:
                        invalid_indexes.append(index)
                    else:
                        timeline.append(_TimelineItem(index=index, kind="tokens", totals=totals))
                elif event_type in _TURN_STARTED_TYPES:
                    turn_id = payload.get("turn_id")
                    if isinstance(turn_id, str) and turn_id:
                        timeline.append(_TimelineItem(index=index, kind="started", turn_id=turn_id))
                    else:
                        invalid_indexes.append(index)
                        tool_invalid_indexes.append(index)
                elif event_type in _TURN_COMPLETED_TYPES:
                    turn_id = payload.get("turn_id")
                    if isinstance(turn_id, str) and turn_id:
                        timeline.append(_TimelineItem(index=index, kind="completed", turn_id=turn_id))
                    else:
                        invalid_indexes.append(index)
                        tool_invalid_indexes.append(index)
                elif event_type == "turn_aborted":
                    turn_id = payload.get("turn_id")
                    if turn_id is None or (isinstance(turn_id, str) and turn_id):
                        timeline.append(_TimelineItem(index=index, kind="aborted", turn_id=turn_id))
                    else:
                        invalid_indexes.append(index)
                        tool_invalid_indexes.append(index)
                elif event_type == "sub_agent_activity":
                    child_thread_id = payload.get("agent_thread_id")
                    if isinstance(child_thread_id, str) and child_thread_id:
                        referenced_child_ids.add(child_thread_id)
                    else:
                        invalid_indexes.append(index)
                        tool_invalid_indexes.append(index)
    except OSError:
        invalid_indexes.append(len(timeline) + 1)
        tool_invalid_indexes.append(len(timeline) + 1)
    if meta is None:
        return None
    return _UsageRollout(
        meta=meta,
        timeline=tuple(timeline),
        referenced_child_ids=frozenset(referenced_child_ids),
        invalid_indexes=tuple(invalid_indexes),
        tool_invalid_indexes=tuple(tool_invalid_indexes),
        unsupported_service_tier=unsupported_service_tier,
    )


def _analyze_rollout(
    rollout: _UsageRollout,
    parent: _UsageRollout | None,
    *,
    allow_empty: bool,
) -> tuple[_TokenTotals, tuple[_SanitizedRequest, ...], set[str]]:
    warning_codes: set[str] = set()
    if rollout.unsupported_service_tier:
        warning_codes.add("unsupported_service_tier")
    inherited_turn_ids: frozenset[str] = frozenset()
    forked = rollout.meta.forked_from_id is not None
    if forked:
        if (
            parent is None
            or not parent.structurally_complete
            or rollout.meta.forked_from_id != rollout.meta.parent_thread_id
        ):
            return (
                _TokenTotals(),
                (),
                {"fork_baseline_unavailable"},
            )
        inherited_turn_ids = parent.turn_ids

    own_starts = [
        item for item in rollout.timeline if item.kind == "started" and item.turn_id not in inherited_turn_ids
    ]

    boundary = own_starts[0].index if own_starts else 0
    baselines = [
        item for item in rollout.timeline if item.kind == "tokens" and item.index < boundary and item.totals is not None
    ]
    baseline = baselines[-1].totals if baselines else _TokenTotals()
    assert baseline is not None
    inherited_counter_invalid = False
    previous_inherited = _TokenTotals()
    for item in baselines:
        assert item.totals is not None
        if item.totals.delta_from(previous_inherited) is None:
            inherited_counter_invalid = True
            break
        previous_inherited = item.totals
    if forked and not own_starts:
        if inherited_counter_invalid:
            warning_codes.add("fork_baseline_unavailable")
        if not rollout.structurally_complete:
            warning_codes.add("rollout_invalid")
        return _TokenTotals(), (), warning_codes
    if forked and (inherited_counter_invalid or any(index < boundary for index in rollout.invalid_indexes)):
        warning_codes.add("fork_baseline_unavailable")
        if not rollout.structurally_complete:
            warning_codes.add("rollout_invalid")
        return _TokenTotals(), (), warning_codes

    active_turns: set[str] = set()
    finished_turns: set[str] = set()
    turns_with_usage: set[str] = set()
    turn_models: dict[str, str] = {}
    conflicted_turns: set[str] = set()
    requests: list[_SanitizedRequest] = []
    previous = baseline
    counter_valid = True
    for item in rollout.timeline:
        if item.index < boundary or item.turn_id in inherited_turn_ids:
            continue
        if item.kind == "started" and item.turn_id:
            if active_turns or item.turn_id in finished_turns:
                warning_codes.add("child_lifecycle_invalid")
            active_turns.add(item.turn_id)
        elif item.kind == "context" and item.turn_id and item.model:
            if item.turn_id not in active_turns:
                warning_codes.add("child_lifecycle_invalid")
            previous_model = turn_models.get(item.turn_id)
            if previous_model is None:
                turn_models[item.turn_id] = item.model
            elif previous_model != item.model:
                conflicted_turns.add(item.turn_id)
                warning_codes.add("request_model_conflict")
        elif item.kind == "tokens" and item.totals is not None and counter_valid:
            delta = item.totals.delta_from(previous)
            if delta is None:
                warning_codes.add("child_usage_counter_invalid")
                counter_valid = False
                continue
            if item.totals == previous:
                continue
            previous = item.totals
            turn_id = next(iter(active_turns)) if len(active_turns) == 1 else None
            if turn_id is None:
                warning_codes.add("child_lifecycle_invalid")
            else:
                turns_with_usage.add(turn_id)
            model = turn_models.get(turn_id) if turn_id is not None and turn_id not in conflicted_turns else None
            if model is None:
                warning_codes.add("request_model_missing")
            provider = rollout.meta.model_provider
            if provider is None:
                warning_codes.add("request_provider_missing")
            requests.append(_SanitizedRequest(usage=delta, model=model, provider=provider))
        elif item.kind == "completed" and item.turn_id:
            if item.turn_id not in active_turns:
                warning_codes.add("child_lifecycle_invalid")
            elif item.turn_id not in turns_with_usage:
                warning_codes.add("child_usage_missing")
            active_turns.discard(item.turn_id)
            finished_turns.add(item.turn_id)
        elif item.kind == "aborted":
            warning_codes.add("child_lifecycle_invalid")
            if item.turn_id:
                active_turns.discard(item.turn_id)
    if active_turns or (not own_starts and not forked and not allow_empty):
        warning_codes.add("child_lifecycle_invalid")
    if not rollout.structurally_complete:
        warning_codes.add("rollout_invalid")

    safe_delta = previous.delta_from(baseline) or _TokenTotals()

    request_totals = _TokenTotals()
    for request in requests:
        request_totals += request.usage
    if request_totals != safe_delta:
        warning_codes.add("request_totals_mismatch")

    return safe_delta, tuple(requests), warning_codes


def _analyze_tool_rollout(
    rollout: _UsageRollout,
    parent: _UsageRollout | None,
    *,
    allow_empty: bool,
) -> tuple[list[str | None], set[str]]:
    """Return this rollout's own dispatches, excluding inherited fork history."""

    warning_codes: set[str] = set()
    inherited_turn_ids: frozenset[str] = frozenset()
    forked = rollout.meta.forked_from_id is not None
    if forked:
        if (
            parent is None
            or not parent.tool_structurally_complete
            or rollout.meta.forked_from_id != rollout.meta.parent_thread_id
        ):
            return [], {"child_tool_boundary_unavailable"}
        inherited_turn_ids = parent.turn_ids

    own_starts = [
        item for item in rollout.timeline if item.kind == "started" and item.turn_id not in inherited_turn_ids
    ]
    # Only forked rollouts contain an inherited parent prefix. A direct child
    # may be truncated before its first task_started record; keep any earlier
    # tool evidence so it cannot be published as an exact zero.
    boundary = own_starts[0].index if forked and own_starts else 0
    if forked and not own_starts:
        if not rollout.tool_structurally_complete:
            warning_codes.add("child_tool_stream_invalid")
        if not allow_empty:
            warning_codes.add("child_tool_lifecycle_invalid")
    if forked and own_starts and any(index < boundary for index in rollout.tool_invalid_indexes):
        return [], {"child_tool_boundary_unavailable"}

    prefix_tool_indexes_to_skip: set[int] = set()
    if forked:
        assert parent is not None
        parent_tool_pairs = {
            (item.tool_id, item.command) for item in parent.timeline if item.kind == "tool" and item.tool_id is not None
        }
        parent_tool_ids = {tool_id for tool_id, _command in parent_tool_pairs}
        for item in rollout.timeline:
            if item.kind != "tool" or (own_starts and item.index >= boundary):
                continue
            if item.tool_id is not None and (item.tool_id, item.command) in parent_tool_pairs:
                prefix_tool_indexes_to_skip.add(item.index)
                continue
            warning_codes.add("child_tool_boundary_unavailable")
            # An ID-less record, or an ID whose payload conflicts with the
            # parent, may be a replay of inherited history. Do not double-count
            # it. A new stable ID is independent positive child evidence.
            if item.tool_id is None or item.tool_id in parent_tool_ids:
                prefix_tool_indexes_to_skip.add(item.index)

    commands: list[str | None] = []
    active_turns: set[str] = set()
    finished_turns: set[str] = set()
    seen_tools: dict[str, str | None] = {}
    seen_tool_indexes: dict[str, int] = {}
    anonymous_tool_observed = False
    anonymous_command_index: int | None = None
    for item in rollout.timeline:
        if item.turn_id in inherited_turn_ids:
            continue
        if (
            forked
            and (not own_starts or item.index < boundary)
            and (item.kind != "tool" or item.index in prefix_tool_indexes_to_skip)
        ):
            continue
        if item.kind == "started" and item.turn_id:
            if active_turns or item.turn_id in finished_turns:
                warning_codes.add("child_tool_lifecycle_invalid")
            active_turns.add(item.turn_id)
        elif item.kind == "completed" and item.turn_id:
            if item.turn_id not in active_turns:
                warning_codes.add("child_tool_lifecycle_invalid")
            active_turns.discard(item.turn_id)
            finished_turns.add(item.turn_id)
        elif item.kind == "aborted":
            # Aborted is still an explicit terminal for dispatch enumeration;
            # failure status alone does not imply that earlier tool records are
            # missing. Orphan/ambiguous aborts remain lifecycle gaps.
            if item.turn_id and item.turn_id in active_turns:
                active_turns.discard(item.turn_id)
                finished_turns.add(item.turn_id)
            else:
                warning_codes.add("child_tool_lifecycle_invalid")
        elif item.kind == "tool":
            if len(active_turns) != 1:
                warning_codes.add("child_tool_lifecycle_invalid")
            if item.tool_id is None:
                # ID-less records cannot prove whether repeated payloads are
                # separate dispatches. Keep one witness so the degraded count
                # remains a genuine lower bound.
                if not anonymous_tool_observed:
                    anonymous_command_index = len(commands)
                    commands.append(item.command)
                    anonymous_tool_observed = True
                warning_codes.add("child_tool_id_invalid")
            elif item.tool_id not in seen_tools:
                seen_tools[item.tool_id] = item.command
                seen_tool_indexes[item.tool_id] = len(commands)
                commands.append(item.command)
            else:
                warning_codes.add("child_tool_id_duplicate")
                if seen_tools[item.tool_id] != item.command:
                    commands[seen_tool_indexes[item.tool_id]] = None
                    warning_codes.add("child_tool_id_conflict")
    if seen_tools and anonymous_command_index is not None:
        commands.pop(anonymous_command_index)
    if active_turns or (not own_starts and not allow_empty):
        warning_codes.add("child_tool_lifecycle_invalid")
    if not rollout.tool_structurally_complete:
        warning_codes.add("child_tool_stream_invalid")
    return commands, warning_codes


def _belongs_to_tree(thread_id: str, root_thread_id: str, by_thread: dict[str, _UsageRollout]) -> bool:
    seen: set[str] = set()
    while thread_id != root_thread_id:
        if thread_id in seen:
            return False
        seen.add(thread_id)
        rollout = by_thread.get(thread_id)
        if rollout is None or rollout.meta.parent_thread_id is None:
            return False
        thread_id = rollout.meta.parent_thread_id
    return True


def collect_child_usage(root_thread_id: str, candidate_paths: Iterable[Path]) -> dict[str, object]:
    """Build a sanitized usage and tool-call audit for one Codex session tree."""

    warning_codes: set[str] = set()
    tool_warning_codes: set[str] = set()
    by_thread: dict[str, _UsageRollout] = {}
    duplicate_thread_ids: set[str] = set()
    for path in sorted(candidate_paths):
        rollout = _read_usage_rollout(path)
        if rollout is None:
            warning_codes.add("new_rollout_metadata_invalid")
            tool_warning_codes.add("new_rollout_metadata_invalid")
        elif rollout.meta.session_id != root_thread_id or rollout.meta.thread_id in duplicate_thread_ids:
            continue
        elif rollout.meta.thread_id in by_thread:
            warning_codes.add("duplicate_thread_rollout")
            tool_warning_codes.add("duplicate_thread_rollout")
            by_thread.pop(rollout.meta.thread_id)
            duplicate_thread_ids.add(rollout.meta.thread_id)
        else:
            by_thread[rollout.meta.thread_id] = rollout

    root = by_thread.get(root_thread_id)
    root_is_primary = (
        root is not None
        and root.meta.session_id == root.meta.thread_id
        and root.meta.parent_thread_id is None
        and root.meta.forked_from_id is None
    )
    requests: list[_SanitizedRequest] = []
    session_commands: list[str | None] = []
    if not root_is_primary:
        warning_codes.add("root_rollout_missing")
        tool_warning_codes.add("root_rollout_missing")
    else:
        assert root is not None
        _root_totals, root_requests, root_warnings = _analyze_rollout(root, None, allow_empty=True)
        requests.extend(root_requests)
        warning_codes.update(root_warnings)
        root_commands, root_tool_warnings = _analyze_tool_rollout(root, None, allow_empty=True)
        session_commands.extend(root_commands)
        tool_warning_codes.update(root_tool_warnings)

    known_thread_ids = set(by_thread)
    if any(rollout.referenced_child_ids - known_thread_ids for rollout in by_thread.values()):
        warning_codes.add("referenced_child_rollout_missing")
        tool_warning_codes.add("referenced_child_rollout_missing")

    child_count = 0
    totals = _TokenTotals()
    for thread_id, rollout in sorted(by_thread.items()):
        if thread_id == root_thread_id:
            continue
        child_count += 1
        if not _belongs_to_tree(thread_id, root_thread_id, by_thread):
            warning_codes.add("thread_tree_invalid")
            tool_warning_codes.add("thread_tree_invalid")
            continue
        parent_thread_id = rollout.meta.parent_thread_id
        child_totals, child_requests, child_warnings = _analyze_rollout(
            rollout,
            by_thread.get(parent_thread_id) if parent_thread_id else None,
            allow_empty=False,
        )
        totals += child_totals
        requests.extend(child_requests)
        warning_codes.update(child_warnings)
        rollout_commands, rollout_tool_warnings = _analyze_tool_rollout(
            rollout,
            by_thread.get(parent_thread_id) if parent_thread_id else None,
            allow_empty=False,
        )
        session_commands.extend(rollout_commands)
        tool_warning_codes.update(rollout_tool_warnings)

    tool_warnings = (
        (f"Codex session-tree tool-call audit is incomplete ({', '.join(sorted(tool_warning_codes))})",)
        if tool_warning_codes
        else ()
    )
    session_tool_calls = _toolcalls.ToolCallSummary.from_commands(
        session_commands,
        available=True,
        complete=not tool_warning_codes,
        warnings=tool_warnings,
    )

    return {
        "type": CODEX_CHILD_USAGE_EVENT,
        "version": CODEX_CHILD_USAGE_VERSION,
        "tool_calls_scope": "session_tree",
        "root_thread_id": root_thread_id,
        "child_count": child_count,
        **totals.to_dict(),
        "requests": [request.to_dict() for request in requests],
        "complete": not warning_codes,
        "warning_codes": sorted(warning_codes),
        "tool_calls": session_tool_calls.to_dict(),
    }


def _dates_between(first: date, last: date) -> Iterable[date]:
    current = first
    while current <= last:
        yield current
        current += timedelta(days=1)


def _rollout_paths(sessions_dir: Path, first: date, last: date) -> set[Path]:
    paths: set[Path] = set()
    for day in _dates_between(first, last):
        day_dir = sessions_dir / str(day.year) / f"{day.month:02d}" / f"{day.day:02d}"
        paths.update(day_dir.glob("rollout-*.jsonl"))
    return paths


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured) if configured else Path.home() / ".codex"


def _stream_codex(command: Sequence[str]) -> tuple[int, str | None, bool]:
    try:
        process = subprocess.Popen(
            command,
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        print(f"failed to launch Codex: {type(exc).__name__}", file=sys.stderr)
        return 127, None, False

    root_thread_id: str | None = None
    conflicting_root = False
    ended_with_newline = True
    assert process.stdout is not None
    for raw in process.stdout:
        sys.stdout.write(raw)
        sys.stdout.flush()
        ended_with_newline = raw.endswith("\n")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "thread.started":
            continue
        candidate = event.get("thread_id")
        if not isinstance(candidate, str) or not candidate:
            continue
        if root_thread_id is None:
            root_thread_id = candidate
        elif candidate != root_thread_id:
            conflicting_root = True
    return_code = process.wait()
    if not ended_with_newline:
        sys.stdout.write("\n")
    return return_code, root_thread_id, conflicting_root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-check-workspace")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a Codex command is required after --")

    if args.proof_check_workspace:
        if __package__:
            from evaluator.backends.codex_proof_check import configure_codex
        else:
            from codex_proof_check import configure_codex

        try:
            command = configure_codex(command, args.proof_check_workspace)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"cannot configure blocking proof tool: {exc}", file=sys.stderr)
            return 1

    sessions_dir = _codex_home() / "sessions"
    started = datetime.now().astimezone()
    existing_paths = _rollout_paths(sessions_dir, started.date(), started.date())
    print(
        json.dumps(
            {"type": CODEX_CHILD_USAGE_START_EVENT, "version": CODEX_CHILD_USAGE_VERSION},
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )
    return_code, root_thread_id, conflicting_root = _stream_codex(command)
    ended = datetime.now().astimezone()

    if root_thread_id is not None:
        try:
            candidate_paths = _rollout_paths(sessions_dir, started.date(), ended.date()) - existing_paths
            audit = collect_child_usage(root_thread_id, candidate_paths)
            if conflicting_root:
                audit["complete"] = False
                warning_codes = audit.get("warning_codes")
                if isinstance(warning_codes, list):
                    warning_codes.append("root_thread_id_conflict")
                    warning_codes.sort()
        except Exception:
            audit = {
                "type": CODEX_CHILD_USAGE_EVENT,
                "version": CODEX_CHILD_USAGE_VERSION,
                "tool_calls_scope": "session_tree",
                "root_thread_id": root_thread_id,
                "child_count": 0,
                **_TokenTotals().to_dict(),
                "requests": [],
                "complete": False,
                "warning_codes": ["audit_failed"],
                "tool_calls": _toolcalls.ToolCallSummary.from_commands(
                    (),
                    available=True,
                    complete=False,
                    warnings=("Codex child tool-call audit failed",),
                ).to_dict(),
            }
        print(json.dumps(audit, separators=(",", ":"), sort_keys=True), flush=True)
    return return_code if return_code >= 0 else 128 - return_code


if __name__ == "__main__":
    raise SystemExit(main())

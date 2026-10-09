"""Anthropic Claude Code CLI backend."""

from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from evaluator import toolcalls
from evaluator.cost import calculate_model_aggregate_cost_usd
from evaluator.usage import RequestUsage, UsageCost, UsageSummary, nonnegative_float, nonnegative_int

from .agentic import AgenticBackend
from .base import (
    detect_firewall_hosts,
    has_aws_bedrock_bearer_token,
    has_aws_env_credentials,
    has_aws_region,
    has_aws_shared_credentials,
    needs_aws_shared_credentials,
)

DEFAULT_MODEL = "claude-opus-4-8"
PROVIDER = "anthropic"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _message_usage(usage: object) -> tuple[int | None, int | None, int | None, int | None]:
    """Return ``(input, cache_read, cache_write, output)`` for one message.

    Anthropic reports cache reads/creations as buckets *beside* ``input_tokens``,
    but the shared usage contract treats them as classifications *within* input
    usage. Fold them in exactly once so ``input_tokens`` is the full billable
    input and the cache fields only classify part of it.
    """

    if not isinstance(usage, dict):
        return None, None, None, None
    base_input = nonnegative_int(usage.get("input_tokens"))
    cache_write = nonnegative_int(usage.get("cache_creation_input_tokens"))
    cache_read = nonnegative_int(usage.get("cache_read_input_tokens"))
    known_input = [value for value in (base_input, cache_write, cache_read) if value is not None]
    total_input = sum(known_input) if known_input else None
    return total_input, cache_read, cache_write, nonnegative_int(usage.get("output_tokens"))


def _streamed_request(
    message: dict[str, Any],
    requested_model: str | None,
    *,
    provider: str,
    provider_request_id: str | None,
    trust_output: bool,
) -> RequestUsage:
    """One per-request record from a deduplicated ``assistant`` event.

    A streamed message's input and cache counts are final, but its
    ``output_tokens`` is only the partial known at message start, so it is kept
    only when no authoritative ``result`` total is available.
    """

    total_input, cache_read, cache_write, output = _message_usage(message.get("usage"))
    stop_reason = _optional_str(message.get("stop_reason"))
    return RequestUsage(
        input_tokens=total_input,
        output_tokens=output if trust_output else None,
        cache_read_input_tokens=cache_read,
        cache_write_input_tokens=cache_write,
        requested_model=requested_model,
        resolved_model=_optional_str(message.get("model")),
        provider=provider,
        finish_reasons=((stop_reason,) if stop_reason is not None else ()),
        request_id=_optional_str(message.get("id")),
        provider_request_id=provider_request_id,
    )


def _model_usage_aggregate(
    value: object,
    *,
    provider: str,
) -> tuple[dict[str, int], float | None, tuple[RequestUsage, ...], tuple[str, ...]] | None:
    """Normalize Claude Code's authoritative per-model session aggregate.

    ``result.usage`` can cover only the primary model while ``modelUsage`` also
    includes helper and sub-agent models whose costs are already part of
    ``total_cost_usd``.
    """

    if not isinstance(value, dict) or not value:
        return None
    entries = [
        (model, usage) for model, usage in value.items() if isinstance(model, str) and model and isinstance(usage, dict)
    ]
    if not entries:
        return None
    warnings: list[str] = []
    if len(entries) != len(value):
        warnings.append("Claude Code modelUsage contains malformed model entries")

    field_names = {
        "base_input_tokens": "inputTokens",
        "cache_read_input_tokens": "cacheReadInputTokens",
        "cache_write_input_tokens": "cacheCreationInputTokens",
        "output_tokens": "outputTokens",
    }
    components: dict[str, list[int | None]] = {
        field: [nonnegative_int(usage.get(provider_field)) for _model, usage in entries]
        for field, provider_field in field_names.items()
    }
    for field, values in components.items():
        if any(value is None for value in values):
            warnings.append(f"Claude Code modelUsage {field} is missing for some models")

    totals: dict[str, int] = {}
    for field in ("cache_read_input_tokens", "cache_write_input_tokens", "output_tokens"):
        known = [value for value in components[field] if value is not None]
        if known:
            totals[field] = sum(known)
    known_input = [
        value
        for field in ("base_input_tokens", "cache_read_input_tokens", "cache_write_input_tokens")
        for value in components[field]
        if value is not None
    ]
    if known_input:
        totals["input_tokens"] = sum(known_input)

    costs = [nonnegative_float(usage.get("costUSD")) for _model, usage in entries]
    if any(cost is None for cost in costs):
        warnings.append("Claude Code modelUsage costUSD is missing for some models")
    aggregate_cost = sum(costs) if all(cost is not None for cost in costs) else None
    model_aggregates: list[RequestUsage] = []
    for index, (model, _usage) in enumerate(entries):
        input_parts = [
            components["base_input_tokens"][index],
            components["cache_read_input_tokens"][index],
            components["cache_write_input_tokens"][index],
        ]
        model_aggregates.append(
            RequestUsage(
                input_tokens=sum(input_parts) if all(part is not None for part in input_parts) else None,
                output_tokens=components["output_tokens"][index],
                cache_read_input_tokens=components["cache_read_input_tokens"][index],
                cache_write_input_tokens=components["cache_write_input_tokens"][index],
                resolved_model=model,
                provider=provider,
            )
        )
    return totals, aggregate_cost, tuple(model_aggregates), tuple(warnings)


@dataclass
class _ResultStream:
    """Recognize one run, including indexed background-task follow-up turns.

    Older CLIs emit a single unindexed result. Multiple results need stronger
    evidence: one session and contiguous delivery indices starting at zero.
    Activity after an intermediate result is valid only if another result
    closes it. Session resets/concatenated runs are deliberately unsupported.
    """

    results: list[dict[str, Any]] = dataclass_field(default_factory=list)
    session_ids: set[str] = dataclass_field(default_factory=set)
    warnings: list[str] = dataclass_field(default_factory=list)
    activity_after_result: bool = False

    def observe(self, event: dict[str, Any]) -> None:
        session_id = _optional_str(event.get("session_id"))
        if session_id is not None:
            self.session_ids.add(session_id)
        elif "session_id" in event:
            self.warnings.append("Claude Code stream contains an invalid session_id")
        event_type = event.get("type")
        if not isinstance(event_type, str):
            self.warnings.append("Claude Code stream contains an event without a string type")
        elif event_type == "result":
            self.results.append(event)
            self.activity_after_result = False
        elif event_type in {"assistant", "user", "system", "stream_event", "error"}:
            self.activity_after_result = bool(self.results)
            if event_type == "error" or event.get("subtype") == "conversation_reset":
                self.warnings.append("Claude Code stream contains an error or conversation reset")

    def identity_warnings(self) -> tuple[str, ...]:
        warnings = list(self.warnings)
        if len(self.session_ids) > 1:
            warnings.append("Claude Code stream contains multiple session IDs")
        indexed = len(self.results) > 1 or any("result_index" in result for result in self.results)
        if indexed:
            for index, result in enumerate(self.results):
                result_index = result.get("result_index")
                if type(result_index) is not int or result_index != index:
                    warnings.append("Claude Code result_index sequence is missing, duplicated, or out of order")
                if _optional_str(result.get("session_id")) is None:
                    warnings.append("Claude Code indexed result is missing its session_id")
        return tuple(dict.fromkeys(warnings))

    def final_warnings(self) -> tuple[str, ...]:
        warnings = list(self.identity_warnings())
        if not self.results or self.activity_after_result:
            warnings.append("Claude Code stream has no final result after its last activity")
        return tuple(warnings)


def _cumulative_result_warnings(results: list[dict[str, Any]]) -> tuple[str, ...]:
    """Validate only running totals; usage and num_turns are per-result."""

    previous: dict[tuple[str, ...], float] = {}
    warnings: list[str] = []
    for result in results:
        current: dict[tuple[str, ...], float] = {}
        for name in ("total_cost_usd", "duration_api_ms"):
            value = nonnegative_float(result.get(name))
            # Batched background notifications emit empty zero-turn results
            # with duration_api_ms=0, while cost/model totals remain cumulative.
            if name == "duration_api_ms" and value == 0 and result.get("num_turns") == 0:
                value = previous.get((name,))
            if value is not None:
                current[(name,)] = value
        model_usage = result.get("modelUsage")
        if isinstance(model_usage, dict):
            for model, usage in model_usage.items():
                if not isinstance(model, str) or not isinstance(usage, dict):
                    continue
                for name in (
                    "inputTokens",
                    "cacheReadInputTokens",
                    "cacheCreationInputTokens",
                    "outputTokens",
                    "costUSD",
                ):
                    value = nonnegative_float(usage.get(name))
                    if value is not None:
                        current[("modelUsage", model, name)] = value
        for key, value in previous.items():
            if key not in current or current[key] < value:
                warnings.append(f"Claude Code cumulative {'.'.join(key)} disappeared or decreased")
        previous.update(current)
    return tuple(dict.fromkeys(warnings))


def parse_claude_code_usage(
    jsonl_path: str,
    *,
    requested_model: str | None = None,
    provider: str = PROVIDER,
) -> UsageSummary | None:
    """Parse Claude Code stream-json usage into an authoritative usage record.

    Streamed ``assistant`` input/cache are final, but streamed ``output_tokens``
    is a message-start partial, so the settled output and USD cost are taken from
    the last ``result`` event's cumulative ``modelUsage``. Indexed results can
    follow background-task notifications: sum their turn-local ``usage`` only,
    never their cumulative cost/model totals. Incomplete streams retain lower
    bounds from the observed messages and result snapshots.
    """

    streamed: list[tuple[dict[str, Any], str | None]] = []
    warnings: list[str] = []
    result_stream = _ResultStream()
    malformed_json = False
    result_error = False
    result_totals: dict[str, int | None] = {}
    result_cost: UsageCost | None = None
    model_usage_totals: dict[str, int] | None = None
    model_usage_cost: float | None = None
    model_usage_aggregates: tuple[RequestUsage, ...] = ()
    model_usage_warnings: tuple[str, ...] = ()
    model_time_secs: float | None = None
    num_turns: int | None = None
    # One `assistant` event is streamed per content block, each repeating the
    # turn's whole usage, so collapse to the first event per message id.
    seen_messages: dict[str, dict[str, Any]] = {}

    try:
        with open(jsonl_path) as stream:
            for raw in stream:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    malformed_json = True
                    continue
                if not isinstance(event, dict):
                    malformed_json = True
                    continue
                result_stream.observe(event)
                etype = event.get("type", "")

                if etype == "assistant":
                    message = event.get("message")
                    if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                        continue
                    message_id = _optional_str(message.get("id"))
                    if message_id is not None:
                        previous = seen_messages.get(message_id)
                        if previous is not None:
                            if any(previous.get(name) != message.get(name) for name in ("usage", "model")):
                                result_stream.warnings.append("Claude Code assistant message ID has conflicting usage")
                            continue
                        seen_messages[message_id] = message
                    streamed.append((message, _optional_str(event.get("request_id"))))

                elif etype == "result":
                    result_error |= event.get("is_error") is True or str(event.get("subtype", "")).startswith("error")
                    total_input, cache_read, cache_write, output = _message_usage(event.get("usage"))
                    result_totals = {
                        "input_tokens": total_input,
                        "output_tokens": output,
                        "cache_read_input_tokens": cache_read,
                        "cache_write_input_tokens": cache_write,
                    }
                    num_turns = nonnegative_int(event.get("num_turns"))
                    total_cost = nonnegative_float(event.get("total_cost_usd"))
                    result_cost = (
                        UsageCost(total_cost, "usd", "claude_code.total_cost_usd") if total_cost is not None else None
                    )
                    model_usage_totals = None
                    model_usage_cost = None
                    model_usage_aggregates = ()
                    model_usage_warnings = ()
                    raw_model_usage = event.get("modelUsage")
                    model_aggregate = _model_usage_aggregate(
                        raw_model_usage,
                        provider=provider,
                    )
                    if model_aggregate is not None:
                        (
                            model_usage_totals,
                            model_usage_cost,
                            model_usage_aggregates,
                            model_usage_warnings,
                        ) = model_aggregate
                    elif raw_model_usage is not None:
                        model_usage_warnings = ("Claude Code modelUsage is malformed",)
                    api_ms = nonnegative_float(event.get("duration_api_ms"))
                    if api_ms is not None:
                        model_time_secs = max(model_time_secs or 0, api_ms / 1000)
    except FileNotFoundError:
        return None

    result_count = len(result_stream.results)
    if not streamed and result_count == 0:
        return None

    if malformed_json:
        warnings.append("Claude Code stream contains malformed JSON")
    lifecycle_warnings = result_stream.final_warnings()
    cumulative_warnings = _cumulative_result_warnings(result_stream.results)
    warnings.extend(lifecycle_warnings)
    warnings.extend(cumulative_warnings)
    result_stream_valid = bool(result_count) and not (malformed_json or lifecycle_warnings or cumulative_warnings)
    partial_turn_usage = False
    if result_count > 1 and not result_stream.identity_warnings():
        turn_totals = [_message_usage(result.get("usage")) for result in result_stream.results]
        for index, name in enumerate(
            ("input_tokens", "cache_read_input_tokens", "cache_write_input_tokens", "output_tokens")
        ):
            values = [turn[index] for turn in turn_totals]
            known = [value for value in values if value is not None]
            result_totals[name] = sum(known) if known else None
            if known and len(known) != len(values):
                partial_turn_usage = True
                warnings.append(f"Claude Code {name} is missing from some result turns")
        turns = [nonnegative_int(result.get("num_turns")) for result in result_stream.results]
        num_turns = sum(turns) if all(turn is not None for turn in turns) else None

    requests = [
        _streamed_request(
            message,
            requested_model,
            provider=provider,
            provider_request_id=provider_request_id,
            trust_output=not result_stream_valid,
        )
        for message, provider_request_id in streamed
    ]

    totals: dict[str, object] = {}
    token_discrepancy = False
    cost_discrepancy = False
    request_count_lower_bound = False
    missing_core_totals: list[str] = []
    if result_count:
        authoritative_totals: dict[str, int | None] = (
            {**result_totals, **model_usage_totals} if model_usage_totals is not None else result_totals
        )
        for field, value in authoritative_totals.items():
            if value is not None:
                totals[field] = value
        if model_usage_totals is not None:
            # The session aggregate includes the primary turns. Even an
            # incomplete primary sum is a floor it cannot legitimately undercut.
            for name, primary_total in result_totals.items():
                aggregate_total = model_usage_totals.get(name)
                if primary_total is not None and aggregate_total is not None and aggregate_total < primary_total:
                    token_discrepancy = True
                    totals[name] = primary_total
                    warnings.append(
                        f"Claude Code modelUsage {name} total {aggregate_total} "
                        f"is smaller than result usage {primary_total}"
                    )

        authoritative_cost = result_cost if result_stream_valid else None
        if authoritative_cost is None and model_usage_cost is not None:
            authoritative_cost = (
                UsageCost(model_usage_cost, "usd", "claude_code.modelUsage.costUSD") if result_stream_valid else None
            )
        public_price_cost, public_price_warning = (
            calculate_model_aggregate_cost_usd(model_usage_aggregates, provider)
            if (
                result_stream_valid
                and not token_discrepancy
                and model_usage_aggregates
                and all(
                    warning == "Claude Code modelUsage costUSD is missing for some models"
                    for warning in model_usage_warnings
                )
            )
            else (None, None)
        )
        costs = [authoritative_cost] if authoritative_cost is not None else []
        if public_price_cost is not None:
            costs.append(
                UsageCost(
                    public_price_cost,
                    "usd",
                    "claude_code.modelUsage.public_price",
                )
            )
        if costs:
            totals["costs"] = tuple(costs)
        elif not result_stream_valid:
            warnings.append("Claude Code cost ignored because the terminal stream is invalid")
        else:
            warnings.append("Claude Code result event did not report total_cost_usd or modelUsage costUSD")
            if public_price_warning is not None:
                warnings.append(f"Claude Code modelUsage public-price fallback failed: {public_price_warning}")
        if (
            result_stream_valid
            and result_cost is not None
            and model_usage_cost is not None
            and not math.isclose(result_cost.amount, model_usage_cost, rel_tol=1e-9, abs_tol=1e-12)
        ):
            cost_discrepancy = True
            warnings.append(
                f"Claude Code total_cost_usd {result_cost.amount} differs from modelUsage costUSD {model_usage_cost}"
            )
        warnings.extend(model_usage_warnings)
        missing_core_totals = [field for field in ("input_tokens", "output_tokens") if field not in totals]
        warnings.extend(f"Claude Code result {field} is unavailable" for field in missing_core_totals)
        if model_time_secs is not None:
            totals["model_time_secs"] = model_time_secs

        streamed_count = len(requests)
        known_request_floor = streamed_count
        if streamed_count:
            if num_turns is not None and num_turns != streamed_count:
                request_count_lower_bound = True
                warnings.append(
                    f"Claude Code num_turns {num_turns} differs from {streamed_count} streamed model request(s); "
                    "model_requests is a lower bound"
                )
            streamed_models = {request.resolved_model for request in requests if request.resolved_model is not None}
            unstreamed_models = {
                aggregate.resolved_model for aggregate in model_usage_aggregates if aggregate.resolved_model is not None
            } - streamed_models
            if unstreamed_models:
                request_count_lower_bound = True
                known_request_floor += len(unstreamed_models)
                warnings.append(
                    "Claude Code modelUsage includes model(s) without streamed request events "
                    f"({', '.join(sorted(unstreamed_models))}); model_requests is a lower bound"
                )
            elif (
                result_stream_valid
                and not partial_turn_usage
                and model_usage_totals is not None
                and all(
                    nonnegative_int(message["usage"].get(name)) is not None
                    for message, _request_id in streamed
                    for name in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
                )
                and any(
                    model_usage_totals.get(name, 0) > sum(getattr(request, name) for request in requests)
                    for name in ("input_tokens", "cache_read_input_tokens", "cache_write_input_tokens")
                    if all(getattr(request, name) is not None for request in requests)
                )
            ):
                # Helper calls can use the same model as the primary stream, so
                # a model-name set alone cannot prove per-request coverage. Only
                # add a request witness when reliable streamed totals are lower;
                # partial input buckets or visible helpers may already explain
                # the difference from modelUsage.
                request_count_lower_bound = True
                known_request_floor += 1
                warnings.append(
                    "Claude Code modelUsage includes usage without streamed request events; "
                    "model_requests is a lower bound"
                )
        elif model_usage_aggregates:
            known_request_floor = len(model_usage_aggregates)
            if len(model_usage_aggregates) > 1:
                request_count_lower_bound = True
                warnings.append(
                    "Claude Code cross-model usage has no per-request events; model_requests is a lower bound"
                )
            elif num_turns is None:
                request_count_lower_bound = True
                warnings.append(
                    "Claude Code result did not report request-count evidence; model_requests is a lower bound"
                )
            elif num_turns < known_request_floor:
                request_count_lower_bound = True
                warnings.append(
                    f"Claude Code num_turns {num_turns} is smaller than the modelUsage request floor "
                    f"{known_request_floor}; model_requests is a lower bound"
                )
        elif num_turns is None:
            # A terminal result proves that at least one model request occurred,
            # but without streamed events or num_turns its exact count is lost.
            request_count_lower_bound = True
            known_request_floor = max(known_request_floor, 1)
            warnings.append("Claude Code result did not report request-count evidence; model_requests is a lower bound")

        if num_turns is not None or known_request_floor != streamed_count:
            totals["model_requests"] = max(known_request_floor, num_turns or 0)

        # Input and cache are reliable per message, so a mismatch against the
        # same-scope result.usage totals means streamed turns were lost.
        # modelUsage can legitimately be larger because it includes helper
        # models whose individual events are not part of this stream.
        for field in ("input_tokens", "cache_read_input_tokens", "cache_write_input_tokens"):
            summary_total = result_totals.get(field)
            observed = sum(getattr(request, field) for request in requests if getattr(request, field) is not None)
            if streamed and summary_total is not None and observed != summary_total:
                token_discrepancy = True
                warnings.append(
                    f"Claude Code {field} result total {summary_total} differs from streamed total {observed}"
                )
    else:
        warnings.append("Claude Code result event missing; usage is a lower bound")

    if not result_stream_valid:
        # A trailing unfinished turn or a zeroed crash result must not erase
        # the usage already observed. Maxima are lower bounds, never sums of
        # cumulative snapshots (which would count the same work repeatedly).
        for result in result_stream.results:
            for name, value in zip(
                ("input_tokens", "cache_read_input_tokens", "cache_write_input_tokens", "output_tokens"),
                _message_usage(result.get("usage")),
                strict=True,
            ):
                if value is not None:
                    totals[name] = max(totals.get(name, 0), value)
            aggregate = _model_usage_aggregate(result.get("modelUsage"), provider=provider)
            if aggregate is not None:
                for name, value in aggregate[0].items():
                    totals[name] = max(totals.get(name, 0), value)
        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_write_input_tokens"):
            values = [getattr(request, name) for request in requests if getattr(request, name) is not None]
            if values:
                totals[name] = max(totals.get(name, 0), sum(values))

    complete = (
        result_count > 0
        and not result_error
        and not token_discrepancy
        and not cost_discrepancy
        and not request_count_lower_bound
        and result_stream_valid
        and not model_usage_warnings
        and not missing_core_totals
        and not partial_turn_usage
        and "costs" in totals
    )
    return UsageSummary.from_requests(
        requests,
        source="claude_code_stream_json",
        complete=complete,
        is_lower_bound=not complete,
        warnings=tuple(dict.fromkeys(warnings)),
        totals=totals,
    )


def _tool_call_summary(jsonl_path: str) -> toolcalls.ToolCallSummary:
    """Count dispatched ``tool_use`` blocks across a closed result sequence."""

    evidence = toolcalls.EventStreamEvidence()
    commands: list[str | None] = []
    seen_calls: dict[str, tuple[int, dict[str, Any]]] = {}
    completed_ids: dict[str, int] = {}
    anonymous_call_observed = False
    anonymous_call_command: str | None = None
    anonymous_result_observed = False
    identity_valid = True
    warnings: list[str] = []
    result_stream = _ResultStream()
    for event_index, event in enumerate(toolcalls.iter_events(jsonl_path, evidence)):
        result_stream.observe(event)
        event_type = event.get("type")
        if event_type not in {"assistant", "user"}:
            continue
        message = event.get("message")
        if not isinstance(message, dict):
            evidence.warn(f"Claude Code {event_type} event has an invalid message object")
            continue
        content = message.get("content")
        if not isinstance(content, list):
            evidence.warn(f"Claude Code {event_type} event has invalid message content")
            continue
        for block in content:
            if not isinstance(block, dict):
                evidence.warn(f"Claude Code {event_type} content contains a malformed block")
                continue
            block_type = block.get("type")
            if not isinstance(block_type, str):
                evidence.warn(f"Claude Code {event_type} content block has an invalid type")
                continue
            if event_type == "user":
                if block_type != "tool_result":
                    continue
                raw_result_id = block.get("tool_use_id")
                result_id = raw_result_id if isinstance(raw_result_id, str) and raw_result_id else None
                if result_id is None:
                    identity_valid = False
                    anonymous_result_observed = True
                    warnings.append("Claude Code tool_result has a missing or invalid tool_use_id")
                elif result_id in completed_ids:
                    identity_valid = False
                    warnings.append("Claude Code tool-call stream contains a duplicate tool_result ID")
                else:
                    completed_ids[result_id] = event_index
                continue
            if block_type != "tool_use":
                continue
            record_anonymous_call = False
            call_id = block.get("id")
            if isinstance(call_id, str) and call_id:
                previous = seen_calls.get(call_id)
                if previous is not None:
                    identity_valid = False
                    warning = (
                        "Claude Code tool-call stream contains a conflicting tool_use ID"
                        if previous[1] != block
                        else "Claude Code tool-call stream contains a duplicate tool_use ID"
                    )
                    warnings.append(warning)
                    continue
                seen_calls[call_id] = (event_index, block)
            else:
                identity_valid = False
                warnings.append("Claude Code tool_use has a missing or invalid ID")
                # Without a native ID, repeated payloads cannot prove distinct
                # calls. Keep one positive witness for a genuine lower bound.
                if anonymous_call_observed:
                    continue
                anonymous_call_observed = True
                record_anonymous_call = True
            tool_input = block.get("input")
            command = (
                tool_input.get("command") if block.get("name") == "Bash" and isinstance(tool_input, dict) else None
            )
            command = command if isinstance(command, str) else None
            if record_anonymous_call:
                anonymous_call_command = command
            else:
                commands.append(command)

    missing_results = set(seen_calls) - set(completed_ids)
    orphan_results = set(completed_ids) - set(seen_calls)
    out_of_order = sum(
        completed_ids[call_id] <= seen_calls[call_id][0] for call_id in set(seen_calls) & set(completed_ids)
    )
    if missing_results:
        identity_valid = False
        warnings.append(f"Claude Code tool-call stream has {len(missing_results)} unfinished tool call(s)")
    if orphan_results:
        identity_valid = False
        commands.extend(None for _ in orphan_results)
        warnings.append(f"Claude Code tool-call stream has {len(orphan_results)} orphan tool result(s)")
    if out_of_order:
        identity_valid = False
        warnings.append(f"Claude Code tool-call stream has {out_of_order} result(s) before their tool use")
    if not seen_calls and not completed_ids:
        if anonymous_call_observed:
            commands.append(anonymous_call_command)
        elif anonymous_result_observed:
            commands.append(None)

    lifecycle_warnings = result_stream.final_warnings()
    lifecycle_complete = not lifecycle_warnings and identity_valid
    warnings.extend(lifecycle_warnings)
    return toolcalls.summarize(commands, evidence, lifecycle_complete=lifecycle_complete, warnings=warnings)


class ClaudeCodeBackend(AgenticBackend):
    name = "claude_code"
    requires_public_pricing = True
    install_script = "install-claudecode.sh"
    session_state_dir = "/root/.claude"
    project_skills_dir = ".claude/skills"
    env_keys = [
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_MANTLE",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_AWS_BASE_URL",
        "ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION",
        "DISABLE_PROMPT_CACHING",
    ]
    reasoning_effort_values = ("low", "medium", "high", "xhigh", "max")

    # Tools the agent is allowed to use (mirrors SREGym's whitelist).
    # Using --allowedTools instead of --dangerously-skip-permissions
    # because the latter is blocked when running as root in containers.
    ALLOWED_TOOLS = [
        "Bash",
        "Edit",
        "Write",
        "Read",
        "Glob",
        "Grep",
        "LS",
        "NotebookEdit",
        "NotebookRead",
        "TodoRead",
        "TodoWrite",
        "Agent",
        "Skill",
        "SlashCommand",
        "Task",
    ]

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL
        self.provider = "amazon-bedrock" if self._uses_aws_provider() else PROVIDER

    def get_credential_mounts(self) -> list[str]:
        if self._uses_aws_provider() and needs_aws_shared_credentials():
            return ["aws"]
        if not self._uses_aws_provider() and self._needs_claude_credentials():
            return ["claude"]
        return []

    @staticmethod
    def _uses_aws_provider() -> bool:
        return (
            os.environ.get("CLAUDE_CODE_USE_BEDROCK", "").strip() == "1"
            or os.environ.get("CLAUDE_CODE_USE_MANTLE", "").strip() == "1"
        )

    @staticmethod
    def _needs_claude_credentials() -> bool:
        return not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))

    def build_command(self, workspace: str, result_dir: str) -> list[str]:
        return [
            "claude",
            "--print",
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--verbose",
            "--effort",
            self.reasoning_effort if self.reasoning_effort is not None else "max",
            "--model",
            self.model,
            "--allowedTools",
        ] + self.ALLOWED_TOOLS

    def check_auth(self) -> str | None:
        if self._uses_aws_provider():
            if has_aws_bedrock_bearer_token():
                if not has_aws_region():
                    return "claude_code: AWS_REGION or AWS_DEFAULT_REGION required for Bedrock bearer-token auth"
                return None
            if has_aws_env_credentials():
                if not has_aws_region():
                    return "claude_code: AWS_REGION or AWS_DEFAULT_REGION required for Bedrock AWS env auth"
                return None
            if has_aws_shared_credentials():
                return None
            return "claude_code: Bedrock/Mantle selected but no AWS credentials detected"
        # Fast path: env var present.
        if not self._needs_claude_credentials():
            return None
        # Slow path: probe the CLI with --no-session-persistence so the
        # probe doesn't pollute the user's resume history. This makes one
        # tiny API call but covers OAuth / subscription auth that env-var
        # checks can't see.
        # Keep this credential-only probe cheap without changing the experiment's
        # effort or the parent environment (the model preflight checks those).
        try:
            r = subprocess.run(
                ["claude", "--print", "--no-session-persistence", "--output-format", "text", "ok"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "CLAUDE_CODE_EFFORT_LEVEL": "low"},
            )
            if r.returncode == 0:
                return None
            stderr = (r.stderr or r.stdout or "").strip()
            if len(stderr) > 300:
                stderr = stderr[:300] + "..."
            return f"claude_code: auth probe failed (exit {r.returncode}): {stderr}"
        except subprocess.TimeoutExpired:
            return "claude_code: auth probe timed out (>30s)"
        except FileNotFoundError:
            return "claude_code: `claude` CLI not found on PATH"
        except Exception as e:
            return f"claude_code: auth probe error: {e}"

    def firewall_hosts(self) -> list[str]:
        return detect_firewall_hosts(self.model)

    def usage_script(self) -> str | None:
        return "scripts/usage/claude.sh"

    def default_quota(self) -> tuple[float, float]:
        return (80.0, 95.0)

    def parse_output(self, jsonl_path: str) -> tuple[str, int, int]:
        lines: list[str] = []

        try:
            with open(jsonl_path) as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue

                    etype = event.get("type", "")

                    if etype == "assistant":
                        message = event.get("message", {})
                        if not isinstance(message, dict):
                            continue
                        content = message.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                btype = block.get("type", "")
                                if btype == "text":
                                    text = block.get("text", "")
                                    if text:
                                        lines.append(f"[AGENT] {text}")
                                        lines.append("")
                                elif btype == "tool_use":
                                    tname = block.get("name", "")
                                    tinput = block.get("input", {})
                                    try:
                                        tinput_str = json.dumps(tinput, ensure_ascii=False)
                                    except (TypeError, ValueError):
                                        tinput_str = str(tinput)
                                    if len(tinput_str) > 1500:
                                        tinput_str = tinput_str[:1500] + " ...(truncated)"
                                    lines.append(f"[TOOL] {tname} {tinput_str}")
                                    lines.append("")
                    elif etype == "user":
                        message = event.get("message", {})
                        if not isinstance(message, dict):
                            continue
                        content = message.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                if block.get("type") == "tool_result":
                                    result_content = block.get("content", "")
                                    if isinstance(result_content, list):
                                        result_content = "\n".join(
                                            c.get("text", "") if isinstance(c, dict) else str(c) for c in result_content
                                        )
                                    result_content = str(result_content)
                                    if len(result_content) > 3000:
                                        result_content = (
                                            result_content[:1500] + "\n... (truncated) ...\n" + result_content[-1500:]
                                        )
                                    lines.append(f"[TOOL_RESULT] {result_content.rstrip()}")
                                    lines.append("")

                    elif etype == "result":
                        subtype = event.get("subtype", "")
                        result_text = event.get("result", "")
                        if result_text:
                            lines.append(f"[RESULT/{subtype}] {result_text}")
                            lines.append("")
                        elif subtype:
                            lines.append(f"[RESULT/{subtype}]")
                            lines.append("")

                    elif etype == "system":
                        # Skip init noise; nothing useful for the transcript.
                        continue
        except FileNotFoundError:
            pass

        usage = parse_claude_code_usage(jsonl_path, requested_model=self.model, provider=self.provider)
        return (
            "\n".join(lines),
            usage.legacy_input_tokens if usage is not None else 0,
            usage.legacy_output_tokens if usage is not None else 0,
        )

    def parse_usage(self, jsonl_path: str, *, input_tokens: int, output_tokens: int) -> UsageSummary:
        usage = parse_claude_code_usage(jsonl_path, requested_model=self.model, provider=self.provider)
        if usage is not None:
            return usage
        if input_tokens or output_tokens:
            return UsageSummary(
                input_tokens=nonnegative_int(input_tokens) if input_tokens else None,
                output_tokens=nonnegative_int(output_tokens) if output_tokens else None,
                sources=("claude_code_stream_json",),
                available=True,
                complete=False,
                is_lower_bound=True,
                warnings=("Claude Code usage events unavailable; token usage is incomplete",),
            )
        return UsageSummary(
            sources=("claude_code_stream_json",),
            available=False,
            complete=False,
            warnings=("Claude Code usage events unavailable",),
        )

    def parse_run_metadata(self, jsonl_path: str) -> dict[str, object]:
        return {"tool_calls": _tool_call_summary(jsonl_path).to_dict()}

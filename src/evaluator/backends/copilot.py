"""GitHub Copilot CLI backend."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from typing import Any

from evaluator import toolcalls
from evaluator.usage import RequestUsage, UsageCost, UsageSummary, nonnegative_float, nonnegative_int

from .agentic import AgenticBackend
from .base import detect_firewall_hosts

DEFAULT_MODEL = "claude-opus-4.8"
COPILOT_OTEL_FILENAME = "copilot-otel.jsonl"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _finish_reasons(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if not isinstance(value, list):
        return ()
    return tuple(reason for reason in value if isinstance(reason, str) and reason)


def _span_duration_secs(span: dict[str, Any]) -> float | None:
    def timestamp(value: object) -> float | None:
        if not isinstance(value, list) or len(value) != 2:
            return None
        seconds = nonnegative_float(value[0])
        nanos = nonnegative_float(value[1])
        if seconds is None or nanos is None:
            return None
        return seconds + nanos / 1_000_000_000

    start = timestamp(span.get("startTime"))
    end = timestamp(span.get("endTime"))
    if start is None or end is None or end < start:
        return None
    return end - start


def _copilot_costs(attributes: dict[str, Any]) -> tuple[UsageCost, ...]:
    costs: list[UsageCost] = []
    model_multiplier = nonnegative_float(attributes.get("github.copilot.cost"))
    if model_multiplier is not None:
        # The corresponding SDK assistant.usage field is documented as the
        # model multiplier cost for billing; it is not a currency amount.
        costs.append(UsageCost(model_multiplier, "model_multiplier", "github.copilot.cost"))
    aiu = nonnegative_float(attributes.get("github.copilot.aiu"))
    if aiu is not None:
        costs.append(UsageCost(aiu, "aiu", "github.copilot.aiu"))
    nano_aiu = nonnegative_float(attributes.get("github.copilot.nano_aiu"))
    if nano_aiu is not None:
        costs.append(UsageCost(nano_aiu, "nano_aiu", "github.copilot.nano_aiu"))
    return tuple(costs)


def _iter_otel_spans(path: str) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    spans: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as stream:
            for line_number, raw in enumerate(stream, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    warnings.append(f"ignored malformed OTel line {line_number}")
                    continue
                if not isinstance(event, dict) or event.get("type") != "span":
                    continue
                trace_id = _optional_str(event.get("traceId"))
                span_id = _optional_str(event.get("spanId"))
                if trace_id is None or span_id is None:
                    warnings.append(f"ignored OTel span without trace/span id on line {line_number}")
                    continue
                key = (trace_id, span_id)
                if key in seen:
                    continue
                seen.add(key)
                spans.append(event)
    except OSError:
        return [], ()
    return spans, tuple(dict.fromkeys(warnings))


def _request_from_chat_span(span: dict[str, Any]) -> RequestUsage:
    attributes = span.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    return RequestUsage(
        input_tokens=nonnegative_int(attributes.get("gen_ai.usage.input_tokens")),
        output_tokens=nonnegative_int(attributes.get("gen_ai.usage.output_tokens")),
        cache_read_input_tokens=nonnegative_int(attributes.get("gen_ai.usage.cache_read.input_tokens")),
        cache_write_input_tokens=nonnegative_int(attributes.get("gen_ai.usage.cache_creation.input_tokens")),
        reasoning_output_tokens=nonnegative_int(attributes.get("gen_ai.usage.reasoning.output_tokens")),
        requested_model=_optional_str(attributes.get("gen_ai.request.model")),
        resolved_model=_optional_str(attributes.get("gen_ai.response.model")),
        provider=_optional_str(attributes.get("gen_ai.provider.name")),
        duration_secs=_span_duration_secs(span),
        server_duration=nonnegative_float(attributes.get("github.copilot.server_duration")),
        finish_reasons=_finish_reasons(attributes.get("gen_ai.response.finish_reasons")),
        request_id=_optional_str(attributes.get("gen_ai.response.id")),
        interaction_id=_optional_str(attributes.get("github.copilot.interaction_id")),
        turn_id=_optional_str(attributes.get("github.copilot.turn_id")),
        trace_id=_optional_str(span.get("traceId")),
        span_id=_optional_str(span.get("spanId")),
        costs=_copilot_costs(attributes),
    )


def _cost_map(attributes: object) -> dict[tuple[str, str], float]:
    if not isinstance(attributes, dict):
        return {}
    return {(cost.unit, cost.source): cost.amount for cost in _copilot_costs(attributes)}


def _authoritative_costs(
    roots: list[dict[str, Any]], chat_spans: list[dict[str, Any]]
) -> tuple[tuple[UsageCost, ...], tuple[str, ...]]:
    """Aggregate every agent invocation, preferring each local root total."""

    totals: dict[tuple[str, str], float] = {}
    observed_keys = {key for span in (*roots, *chat_spans) for key in _cost_map(span.get("attributes"))}
    incomplete_keys: set[tuple[str, str]] = set()
    accounted_chats: set[str] = set()
    for root in roots:
        root_id = _optional_str(root.get("spanId"))
        if root_id is None:
            continue
        root_costs = _cost_map(root.get("attributes"))
        child_costs: list[dict[tuple[str, str], float]] = []
        for chat in chat_spans:
            if chat.get("parentSpanId") != root_id:
                continue
            chat_id = _optional_str(chat.get("spanId"))
            if chat_id is not None:
                accounted_chats.add(chat_id)
            child_costs.append(_cost_map(chat.get("attributes")))
        for key in observed_keys:
            if key in root_costs:
                totals[key] = totals.get(key, 0.0) + root_costs[key]
                continue
            known = [costs[key] for costs in child_costs if key in costs]
            if known:
                totals[key] = totals.get(key, 0.0) + sum(known)
            if child_costs and len(known) != len(child_costs):
                incomplete_keys.add(key)

    # A timeout can flush completed chat spans without their invoke_agent root.
    for chat in chat_spans:
        chat_id = _optional_str(chat.get("spanId"))
        if chat_id in accounted_chats:
            continue
        costs = _cost_map(chat.get("attributes"))
        for key in observed_keys:
            if key in costs:
                totals[key] = totals.get(key, 0.0) + costs[key]
            else:
                incomplete_keys.add(key)
    return (
        tuple(UsageCost(amount=amount, unit=unit, source=source) for (unit, source), amount in sorted(totals.items())),
        tuple(source for _unit, source in sorted(incomplete_keys)),
    )


def _runtime_versions(spans: list[dict[str, Any]]) -> tuple[str, ...]:
    versions: list[str] = []
    for span in spans:
        resource = span.get("resource")
        attributes = resource.get("attributes") if isinstance(resource, dict) else None
        if not isinstance(attributes, dict):
            continue
        version = _optional_str(attributes.get("service.version"))
        if version:
            versions.append(version)
    return tuple(dict.fromkeys(versions))


def _trace_usage(spans: list[dict[str, Any]]) -> UsageSummary | None:
    """Summarize one trace from chats and validate it against invocation roots."""

    chat_spans = [
        span
        for span in spans
        if isinstance(span.get("attributes"), dict) and span["attributes"].get("gen_ai.operation.name") == "chat"
    ]
    roots = [
        span
        for span in spans
        if isinstance(span.get("attributes"), dict)
        and span["attributes"].get("gen_ai.operation.name") == "invoke_agent"
    ]
    top_roots = [root for root in roots if not root.get("parentSpanId")]
    requests = [_request_from_chat_span(span) for span in chat_spans]
    warnings: list[str] = []
    cost_is_lower_bound = False
    cost_is_unavailable = False
    token_usage_is_lower_bound = False

    totals: dict[str, object] | None = None
    if top_roots:
        totals = {}
        authoritative_costs, incomplete_cost_sources = _authoritative_costs(roots, chat_spans)
        if authoritative_costs:
            totals["costs"] = authoritative_costs
        else:
            cost_is_unavailable = True
            warnings.append("Copilot OTel did not report cost or AIU")
        if incomplete_cost_sources:
            cost_is_lower_bound = True
            warnings.append("Copilot OTel cost is a lower bound; missing " + ", ".join(incomplete_cost_sources))

        for root in roots:
            root_id = _optional_str(root.get("spanId"))
            if root_id is None:
                continue
            child_requests = [
                _request_from_chat_span(span) for span in chat_spans if span.get("parentSpanId") == root_id
            ]
            comparisons = {
                "input_tokens": sum(
                    request.input_tokens for request in child_requests if request.input_tokens is not None
                ),
                "output_tokens": sum(
                    request.output_tokens for request in child_requests if request.output_tokens is not None
                ),
                "cache_read_input_tokens": sum(
                    request.cache_read_input_tokens
                    for request in child_requests
                    if request.cache_read_input_tokens is not None
                ),
                "cache_write_input_tokens": sum(
                    request.cache_write_input_tokens
                    for request in child_requests
                    if request.cache_write_input_tokens is not None
                ),
                "reasoning_output_tokens": sum(
                    request.reasoning_output_tokens
                    for request in child_requests
                    if request.reasoning_output_tokens is not None
                ),
                "model_requests": len(child_requests),
            }
            root_fields = {
                "input_tokens": "gen_ai.usage.input_tokens",
                "output_tokens": "gen_ai.usage.output_tokens",
                "cache_read_input_tokens": "gen_ai.usage.cache_read.input_tokens",
                "cache_write_input_tokens": "gen_ai.usage.cache_creation.input_tokens",
                "reasoning_output_tokens": "gen_ai.usage.reasoning.output_tokens",
                "model_requests": "github.copilot.turn_count",
            }
            attributes = root.get("attributes")
            if not isinstance(attributes, dict):
                continue
            for field, attribute in root_fields.items():
                root_total = nonnegative_int(attributes.get(attribute))
                if root_total is not None and comparisons[field] != root_total:
                    token_usage_is_lower_bound = True
                    warnings.append(
                        f"Copilot OTel {field} invoke_agent total {root_total} "
                        f"differs from direct chat total {comparisons[field]}"
                    )
    elif requests:
        warnings.append("Copilot OTel root span missing; usage is a lower bound")
    else:
        return None

    return UsageSummary.from_requests(
        requests,
        source="copilot_cli_otel",
        complete=(
            bool(top_roots) and not token_usage_is_lower_bound and not cost_is_lower_bound and not cost_is_unavailable
        ),
        is_lower_bound=not top_roots or token_usage_is_lower_bound or cost_is_lower_bound,
        runtime_versions=_runtime_versions(spans),
        warnings=tuple(dict.fromkeys(warnings)),
        totals=totals,
    )


def parse_copilot_otel(path: str) -> UsageSummary | None:
    """Parse official Copilot CLI OTel JSONL without counting root + children."""

    spans, parse_warnings = _iter_otel_spans(path)
    if not spans:
        return None

    by_trace: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        trace_id = _optional_str(span.get("traceId"))
        if trace_id is not None:
            by_trace.setdefault(trace_id, []).append(span)
    summaries = [usage for trace_spans in by_trace.values() if (usage := _trace_usage(trace_spans)) is not None]
    if not summaries:
        return None

    usage = summaries[0]
    for summary in summaries[1:]:
        usage = usage.merge(summary)
    if parse_warnings:
        usage = replace(
            usage,
            complete=False,
            is_lower_bound=True,
            warnings=tuple(dict.fromkeys((*usage.warnings, *parse_warnings))),
        )
    return usage


_COPILOT_ACTIVITY_EVENTS = frozenset(
    {
        "assistant.message",
        "assistant.turn_start",
        "tool.execution_start",
        "tool.execution_complete",
        "tool.execution_partial_result",
    }
)


def _stream_proves_model_activity(jsonl_path: str) -> bool:
    """Detect native response/tool activity when Copilot OTel is incomplete."""

    try:
        with open(jsonl_path, encoding="utf-8") as stream:
            for raw in stream:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type in {
                    "tool.execution_start",
                    "tool.execution_complete",
                    "tool.execution_partial_result",
                }:
                    return True
                if event_type != "assistant.message":
                    continue
                data = event.get("data")
                if not isinstance(data, dict):
                    continue
                content = data.get("content")
                if isinstance(content, str) and content:
                    return True
                if isinstance(content, list) and content:
                    return True
                requests = data.get("toolRequests")
                if isinstance(requests, list) and requests:
                    return True
                output_tokens = nonnegative_int(data.get("outputTokens"))
                if output_tokens:
                    return True
    except (OSError, UnicodeError):
        return False
    return False


def _copilot_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _copilot_call(data: dict[str, Any], *, name_key: str) -> tuple[str | None, str | None]:
    raw_name = data.get(name_key)
    name = raw_name if isinstance(raw_name, str) and raw_name else None
    arguments = data.get("arguments")
    command = arguments.get("command") if name == "bash" and isinstance(arguments, dict) else None
    return name, command if isinstance(command, str) else None


def _same_copilot_call(left: tuple[object, str | None], right: tuple[object, str | None]) -> bool:
    left_name, left_command = left
    right_name, right_command = right
    return left_name == right_name and (left_command is None or right_command is None or left_command == right_command)


def _copilot_shutdown_type(event: dict[str, Any]) -> object:
    return event.get("shutdownType", _copilot_data(event).get("shutdownType"))


def _tool_call_summary(jsonl_path: str) -> toolcalls.ToolCallSummary:
    """Count announced tool requests and require a final clean lifecycle envelope."""

    evidence = toolcalls.EventStreamEvidence()
    requests: dict[str, tuple[object, str | None]] = {}
    starts: dict[str, tuple[object, str | None]] = {}
    completions: set[str] = set()
    request_indexes: dict[str, int] = {}
    start_indexes: dict[str, int] = {}
    completion_indexes: dict[str, int] = {}
    partials: set[str] = set()
    anonymous_witnesses: list[str | None] = []
    lifecycle_valid = True
    clean_terminals = 0
    hard_terminal = False
    activity_after_clean_terminal = False
    warnings: list[str] = []

    for event_index, event in enumerate(toolcalls.iter_events(jsonl_path, evidence)):
        event_type = event.get("type")
        if clean_terminals and event_type in _COPILOT_ACTIVITY_EVENTS:
            activity_after_clean_terminal = True

        if event_type == "result":
            clean_terminals += 1
        elif event_type == "session.shutdown":
            if _copilot_shutdown_type(event) == "routine":
                clean_terminals += 1
            else:
                hard_terminal = True
        elif event_type == "abort" or (event_type == "session.error" and clean_terminals):
            hard_terminal = True

        if event_type == "assistant.message":
            raw_data = event.get("data")
            if not isinstance(raw_data, dict):
                evidence.warn("Copilot assistant message has an invalid data object")
                continue
            data = raw_data
            raw_requests = data.get("toolRequests", [])
            if not isinstance(raw_requests, list):
                lifecycle_valid = False
                warnings.append("Copilot assistant message has invalid toolRequests")
                continue
            for request in raw_requests:
                if not isinstance(request, dict):
                    if not anonymous_witnesses:
                        anonymous_witnesses.append(None)
                    lifecycle_valid = False
                    warnings.append("Copilot tool request is malformed")
                    continue
                call = _copilot_call(request, name_key="name")
                if call[0] is None:
                    lifecycle_valid = False
                    warnings.append("Copilot tool request has a missing or invalid name")
                raw_call_id = request.get("toolCallId")
                call_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id else None
                if call_id is None:
                    if not anonymous_witnesses:
                        anonymous_witnesses.append(call[1])
                    lifecycle_valid = False
                    warnings.append("Copilot tool request has a missing or invalid toolCallId")
                    continue
                previous = requests.get(call_id)
                if previous is not None:
                    lifecycle_valid = False
                    warning = (
                        "Copilot tool-call stream contains a conflicting toolCallId"
                        if not _same_copilot_call(previous, call)
                        else "Copilot tool-call stream contains a duplicate toolCallId"
                    )
                    warnings.append(warning)
                    continue
                requests[call_id] = call
                request_indexes[call_id] = event_index
            continue

        if event_type not in {
            "tool.execution_start",
            "tool.execution_partial_result",
            "tool.execution_complete",
        }:
            continue

        data = _copilot_data(event)
        raw_call_id = data.get("toolCallId")
        call_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id else None
        if call_id is None:
            if not anonymous_witnesses:
                anonymous_witnesses.append(None)
            lifecycle_valid = False
            warnings.append(f"Copilot {event_type} has a missing or invalid toolCallId")
            continue

        if event_type == "tool.execution_partial_result":
            partials.add(call_id)
            continue

        if event_type == "tool.execution_start":
            call = _copilot_call(data, name_key="toolName")
            if call[0] is None:
                lifecycle_valid = False
                warnings.append("Copilot execution start has a missing or invalid toolName")
            previous = starts.get(call_id)
            if previous is not None:
                lifecycle_valid = False
                warning = (
                    "Copilot tool-call stream contains a conflicting execution start"
                    if not _same_copilot_call(previous, call)
                    else "Copilot tool-call stream contains a duplicate execution start"
                )
                warnings.append(warning)
            else:
                starts[call_id] = call
                start_indexes[call_id] = event_index
            continue

        if call_id in completions:
            lifecycle_valid = False
            warnings.append("Copilot tool-call stream contains a duplicate execution completion")
            continue
        completions.add(call_id)
        completion_indexes[call_id] = event_index

    commands: list[str | None] = []
    all_call_ids = set(requests) | set(starts) | completions | partials
    missing_requests = 0
    missing_starts = 0
    unfinished = 0
    conflicts = 0
    ordering_conflicts = 0
    for call_id in all_call_ids:
        request = requests.get(call_id)
        start = starts.get(call_id)
        call = request if request is not None else start
        commands.append(call[1] if call is not None else None)
        if request is None:
            missing_requests += 1
        if start is None:
            missing_starts += 1
        if call_id not in completions:
            unfinished += 1
        if request is not None and start is not None and not _same_copilot_call(request, start):
            conflicts += 1
        if request is not None and start is not None and call_id in completions:
            if not (request_indexes[call_id] < start_indexes[call_id] < completion_indexes[call_id]):
                ordering_conflicts += 1
    if missing_requests:
        lifecycle_valid = False
        warnings.append(f"Copilot tool-call stream has {missing_requests} execution(s) without a tool request")
    if missing_starts:
        lifecycle_valid = False
        warnings.append(f"Copilot tool-call stream has {missing_starts} execution(s) without a start event")
    if unfinished:
        lifecycle_valid = False
        warnings.append(f"Copilot tool-call stream ended with {unfinished} unfinished tool execution(s)")
    if conflicts:
        lifecycle_valid = False
        warnings.append(f"Copilot tool-call stream has {conflicts} request/start conflict(s)")
    if ordering_conflicts:
        lifecycle_valid = False
        warnings.append(f"Copilot tool-call stream has {ordering_conflicts} out-of-order tool lifecycle(s)")
    if not all_call_ids:
        commands.extend(anonymous_witnesses)
    if clean_terminals != 1:
        warnings.append("Copilot tool-call stream has no unique clean terminal event")
    if hard_terminal:
        warnings.append("Copilot tool-call stream contains a terminal abort or error shutdown")
    if activity_after_clean_terminal:
        warnings.append("Copilot tool-call stream contains run activity after a clean terminal event")

    lifecycle_complete = (
        clean_terminals == 1 and not hard_terminal and not activity_after_clean_terminal and lifecycle_valid
    )
    return toolcalls.summarize(
        commands,
        evidence,
        lifecycle_complete=lifecycle_complete,
        warnings=warnings,
    )


class CopilotBackend(AgenticBackend):
    name = "copilot"
    requires_public_pricing = True
    install_script = "install-copilot.sh"
    session_state_dir = "/root/.copilot"
    project_skills_dir = ".github/skills"
    env_keys = [
        "COPILOT_GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "COPILOT_PROVIDER_BASE_URL",
        "COPILOT_PROVIDER_API_KEY",
        "COPILOT_PROVIDER_TYPE",
        "COPILOT_MODEL",
    ]
    reasoning_effort_values = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL

    def build_command(self, workspace: str, result_dir: str) -> list[str]:
        # --allow-all is required for non-interactive tool use (no approvals).
        # --output-format json emits JSONL (one event per line) to stdout.
        # --disable-builtin-mcps drops the GitHub MCP server: it needs no
        # network beyond the model API and prevents data leakage from
        # github.com lookups (matching the firewalled codex/claude runs).
        # --no-custom-instructions keeps runs reproducible across machines.
        # --no-auto-update stops the CLI from hitting api.github.com for a
        # release check, so the *only* host it needs is the Copilot
        # inference API (no GitHub repo/web access — anti-cheating parity
        # with the firewalled codex/claude runs).
        # The existing max effort remains the default unless explicitly overridden.
        return [
            "copilot",
            "--allow-all",
            "-C",
            workspace,
            "--output-format",
            "json",
            "--model",
            self.model,
            "--effort",
            self.reasoning_effort if self.reasoning_effort is not None else "max",
            "--log-level",
            "none",
            "--no-color",
            "--disable-builtin-mcps",
            "--no-custom-instructions",
            "--no-auto-update",
            "--excluded-tools",
            "web_fetch",
        ]

    def prepare_invocation(self, command: list[str], prompt: str) -> tuple[list[str], str | None]:
        # Copilot CLI only instruments its documented non-interactive scripting
        # path. Feeding an initial prompt to the interactive mode through stdin
        # can exit successfully without flushing any OTel spans.
        return [*command, "-p", prompt], None

    def execution_environment(self, result_dir: str) -> dict[str, str]:
        return {
            "COPILOT_OTEL_ENABLED": "true",
            # A host-level otlp-http selection otherwise wins over the file
            # path and silently sends no per-task artifact to the result dir.
            "COPILOT_OTEL_EXPORTER_TYPE": "file",
            "COPILOT_OTEL_FILE_EXPORTER_PATH": os.path.join(result_dir, COPILOT_OTEL_FILENAME),
            # Never put benchmark prompts, model responses, or tool payloads in
            # the telemetry artifact, even if the host enables content capture.
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
        }

    def attempt_output_files(self) -> tuple[str, ...]:
        return (COPILOT_OTEL_FILENAME,)

    def check_auth(self) -> str | None:
        # BYOK mode: provider env vars are set
        if os.environ.get("COPILOT_PROVIDER_BASE_URL"):
            return None
        # Fast path: a token env var is set (headless auth).
        if os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
            return None
        # Slow path: probe the CLI with a trivial prompt. This covers OAuth
        # (`copilot login`) / credential-store auth that env-var checks can't
        # see. --disable-builtin-mcps keeps the probe fast and offline-safe.
        try:
            r = subprocess.run(
                [
                    "copilot",
                    "--allow-all",
                    "--disable-builtin-mcps",
                    "--no-color",
                    "--no-auto-update",
                    "--output-format",
                    "text",
                    "-p",
                    "ok",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode == 0:
                return None
            stderr = (r.stderr or r.stdout or "").strip()
            if len(stderr) > 300:
                stderr = stderr[:300] + "..."
            return f"copilot: auth probe failed (exit {r.returncode}): {stderr}"
        except subprocess.TimeoutExpired:
            return "copilot: auth probe timed out (>60s)"
        except FileNotFoundError:
            return "copilot: `copilot` CLI not found on PATH"
        except Exception as e:
            return f"copilot: auth probe error: {e}"

    def firewall_hosts(self) -> list[str]:
        # GitHub Copilot validates/exchanges the GITHUB token at api.github.com
        # (/copilot_internal/user + /copilot_internal/v2/token) BEFORE it can
        # reach the inference API at api.githubcopilot.com. Unlike codex/claude —
        # whose auth host and inference host are the same already-allowlisted
        # provider domain — Copilot's auth host is distinct, so it must be added
        # explicitly. Without it the firewall drops the auth request and the CLI
        # exits before any model call (0 tokens). The agent's own tools still
        # can't reach it: the GitHub MCP server is off (--disable-builtin-mcps)
        # and web_fetch is excluded, so this only enables the auth handshake.
        return detect_firewall_hosts(self.model) + ["api.github.com"]

    def parse_run_metadata(self, jsonl_path: str) -> dict[str, object]:
        return {"tool_calls": _tool_call_summary(jsonl_path).to_dict()}

    def retry_may_duplicate_model_work(self, jsonl_path: str) -> bool:
        # Copilot may lose its terminal OTel/token totals when the native event
        # stream is cut off after a response or edit. Those events still prove
        # that replaying the launch could duplicate real model work.
        return _stream_proves_model_activity(jsonl_path)

    def parse_output(self, jsonl_path: str) -> tuple[str, int, int]:
        lines: list[str] = []
        in_tok = 0
        out_tok = 0
        # toolCallId -> tool name, so execution_complete results can be labelled.
        tool_names: dict[str, str] = {}

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

                    etype = event.get("type", "")
                    data = event.get("data", {}) or {}

                    if etype == "assistant.message":
                        text = data.get("content", "")
                        if text:
                            lines.append(f"[AGENT] {text}")
                            lines.append("")
                        for req in data.get("toolRequests", []) or []:
                            if not isinstance(req, dict):
                                continue
                            tname = req.get("name", "")
                            tid = req.get("toolCallId", "")
                            if tid:
                                tool_names[tid] = tname
                            targs = req.get("arguments", {})
                            try:
                                targs_str = json.dumps(targs, ensure_ascii=False)
                            except (TypeError, ValueError):
                                targs_str = str(targs)
                            if len(targs_str) > 1500:
                                targs_str = targs_str[:1500] + " ...(truncated)"
                            lines.append(f"[TOOL] {tname} {targs_str}")
                            lines.append("")
                        # copilot exposes per-message output tokens only; there
                        # is no input-token field in the JSONL stream.
                        out_tok += data.get("outputTokens", 0) or 0

                    elif etype == "tool.execution_start":
                        tid = data.get("toolCallId", "")
                        if tid:
                            tool_names[tid] = data.get("toolName", tool_names.get(tid, ""))

                    elif etype == "tool.execution_complete":
                        tid = data.get("toolCallId", "")
                        tname = tool_names.get(tid, "")
                        success = data.get("success", True)
                        result = data.get("result", {}) or {}
                        content = result.get("content", "") or result.get("detailedContent", "")
                        content = str(content)
                        if len(content) > 3000:
                            content = content[:1500] + "\n... (truncated) ...\n" + content[-1500:]
                        status = "ok" if success else "fail"
                        label = f"[TOOL_RESULT/{status}] {tname}".rstrip()
                        lines.append(label)
                        if content:
                            lines.append(content.rstrip())
                        lines.append("")

                    elif etype == "result":
                        exit_code = event.get("exitCode", "")
                        usage = event.get("usage", {}) or {}
                        prem = usage.get("premiumRequests")
                        summary = f"[RESULT exit={exit_code}]"
                        if prem is not None:
                            summary += f" premiumRequests={prem}"
                        lines.append(summary)
                        lines.append("")

        except FileNotFoundError:
            pass

        return "\n".join(lines), in_tok, out_tok

    def parse_usage(self, jsonl_path: str, *, input_tokens: int, output_tokens: int) -> UsageSummary:
        usage = parse_copilot_otel(os.path.join(os.path.dirname(jsonl_path), COPILOT_OTEL_FILENAME))
        if usage is not None:
            if usage.output_tokens is not None and output_tokens and usage.output_tokens != output_tokens:
                usage = replace(
                    usage,
                    complete=False,
                    is_lower_bound=True,
                    warnings=tuple(
                        dict.fromkeys(
                            (
                                *usage.warnings,
                                "Copilot OTel output total differs from the CLI event stream",
                            )
                        )
                    ),
                )
            return usage
        if input_tokens or output_tokens:
            return UsageSummary(
                input_tokens=nonnegative_int(input_tokens) if input_tokens else None,
                output_tokens=nonnegative_int(output_tokens) if output_tokens else None,
                sources=("copilot_cli_jsonl",),
                available=True,
                complete=False,
                is_lower_bound=True,
                warnings=("Copilot OTel telemetry unavailable; token usage is incomplete",),
            )
        return UsageSummary(
            sources=("copilot_cli_otel",),
            available=False,
            complete=False,
            warnings=("Copilot OTel telemetry unavailable",),
        )

"""Official Copilot CLI OpenTelemetry usage parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluator.backends.copilot import (
    COPILOT_OTEL_FILENAME,
    CopilotBackend,
    parse_copilot_otel,
)
from evaluator.cost import calculate_equivalent_cost_usd


def _span(
    trace_id: str,
    span_id: str,
    operation: str,
    attributes: dict[str, object],
    *,
    parent_span_id: str | None = None,
    start_nanos: int = 0,
    end_nanos: int = 100_000_000,
) -> dict[str, object]:
    event: dict[str, object] = {
        "type": "span",
        "traceId": trace_id,
        "spanId": span_id,
        "name": operation,
        "kind": 2,
        "startTime": [100, start_nanos],
        "endTime": [100, end_nanos],
        "attributes": {"gen_ai.operation.name": operation, **attributes},
        "status": {"code": 0},
        "events": [],
        "resource": {"attributes": {"service.name": "github-copilot", "service.version": "1.0.71"}},
        "instrumentationScope": {"name": "github.copilot", "version": "1.0.71"},
    }
    if parent_span_id is not None:
        event["parentSpanId"] = parent_span_id
    return event


def _chat(
    trace_id: str,
    span_id: str,
    parent_span_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_write: int,
    reasoning: int,
    cost: float,
    aiu: float,
) -> dict[str, object]:
    return _span(
        trace_id,
        span_id,
        "chat",
        {
            "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": "claude-opus-4.8",
            "gen_ai.response.model": "claude-opus-4-8-20260701",
            "gen_ai.response.finish_reasons": ["stop"],
            "gen_ai.response.id": f"response-{span_id}",
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.usage.cache_read.input_tokens": cache_read,
            "gen_ai.usage.cache_creation.input_tokens": cache_write,
            "gen_ai.usage.reasoning.output_tokens": reasoning,
            "github.copilot.cost": cost,
            "github.copilot.aiu": aiu,
            "github.copilot.server_duration": 0.08,
            "github.copilot.turn_id": span_id,
            "github.copilot.interaction_id": f"interaction-{span_id}",
        },
        parent_span_id=parent_span_id,
    )


def _write_jsonl(path: Path, *events: object, malformed_tail: bool = False) -> None:
    text = "".join(json.dumps(event) + "\n" for event in events)
    if malformed_tail:
        text += '{"type":"span"'
    path.write_text(text)


def test_all_chat_spans_include_nested_subagent_usage_without_root_double_counting(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    root = _span(
        "trace-1",
        "root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 300,
            "gen_ai.usage.output_tokens": 30,
            "gen_ai.usage.cache_read.input_tokens": 100,
            "gen_ai.usage.cache_creation.input_tokens": 20,
            "gen_ai.usage.reasoning.output_tokens": 8,
            "github.copilot.turn_count": 2,
            "github.copilot.cost": 0.3,
            "github.copilot.aiu": 30,
        },
    )
    first = _chat(
        "trace-1",
        "chat-1",
        "root",
        input_tokens=100,
        output_tokens=10,
        cache_read=40,
        cache_write=10,
        reasoning=3,
        cost=0.1,
        aiu=10,
    )
    second = _chat(
        "trace-1",
        "chat-2",
        "root",
        input_tokens=200,
        output_tokens=20,
        cache_read=60,
        cache_write=10,
        reasoning=5,
        cost=0.2,
        aiu=20,
    )
    nested_chat = _chat(
        "trace-1",
        "subagent-chat",
        "subagent-root",
        input_tokens=50,
        output_tokens=5,
        cache_read=15,
        cache_write=2,
        reasoning=1,
        cost=0.05,
        aiu=5,
    )
    # Each invoke_agent root covers only that agent's direct chat requests.
    nested_root = _span(
        "trace-1",
        "subagent-root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 50,
            "gen_ai.usage.output_tokens": 5,
            "gen_ai.usage.cache_read.input_tokens": 15,
            "gen_ai.usage.cache_creation.input_tokens": 2,
            "gen_ai.usage.reasoning.output_tokens": 1,
            "github.copilot.turn_count": 1,
        },
        parent_span_id="tool-call",
    )
    _write_jsonl(path, first, first, second, nested_chat, nested_root, root)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert usage.status == "complete"
    assert (usage.input_tokens, usage.output_tokens) == (350, 35)
    assert usage.cache_read_input_tokens == 115
    assert usage.cache_write_input_tokens == 22
    assert usage.reasoning_output_tokens == 9
    assert usage.model_requests == 3
    assert len(usage.requests) == 3
    assert usage.model_time_secs == pytest.approx(0.3)
    assert usage.runtime_versions == ("1.0.71",)
    assert [cost.to_dict() for cost in usage.costs] == [
        {"amount": 35.0, "unit": "aiu", "source": "github.copilot.aiu"},
        {
            "amount": 0.35,
            "unit": "model_multiplier",
            "source": "github.copilot.cost",
        },
    ]
    assert usage.requests[0].resolved_model == "claude-opus-4-8-20260701"
    assert usage.requests[0].interaction_id == "interaction-chat-1"
    equivalent_cost, warning = calculate_equivalent_cost_usd(usage, "claude-opus-4.8")
    assert equivalent_cost is not None
    assert equivalent_cost > 0
    assert warning is None


def test_root_chat_mismatch_marks_observed_usage_as_a_lower_bound(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    root = _span(
        "trace-damaged",
        "root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 300,
            "gen_ai.usage.output_tokens": 30,
            "github.copilot.turn_count": 2,
            "github.copilot.cost": 0.3,
        },
    )
    surviving_chat = _chat(
        "trace-damaged",
        "chat-1",
        "root",
        input_tokens=100,
        output_tokens=10,
        cache_read=40,
        cache_write=10,
        reasoning=3,
        cost=0.1,
        aiu=10,
    )
    _write_jsonl(path, surviving_chat, root)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens, usage.model_requests) == (100, 10, 1)
    assert any("input_tokens invoke_agent total 300" in warning for warning in usage.warnings)
    assert any("model_requests invoke_agent total 2" in warning for warning in usage.warnings)


def test_malformed_otel_downgrades_otherwise_complete_usage(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    root = _span(
        "trace-malformed",
        "root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 10,
            "gen_ai.usage.cache_read.input_tokens": 20,
            "gen_ai.usage.cache_creation.input_tokens": 0,
            "gen_ai.usage.reasoning.output_tokens": 2,
            "github.copilot.turn_count": 1,
            "github.copilot.cost": 0.1,
            "github.copilot.aiu": 10,
        },
    )
    chat = _chat(
        "trace-malformed",
        "chat",
        "root",
        input_tokens=100,
        output_tokens=10,
        cache_read=20,
        cache_write=0,
        reasoning=2,
        cost=0.1,
        aiu=10,
    )
    _write_jsonl(path, chat, root, malformed_tail=True)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert usage.status == "lower_bound"
    assert usage.complete is False
    assert usage.is_lower_bound is True
    assert "ignored malformed OTel line 3" in usage.warnings


def test_native_nano_aiu_and_missing_subagent_cost_are_reported_as_a_lower_bound(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    top_chat = _span(
        "trace-native",
        "top-chat",
        "chat",
        {
            "gen_ai.usage.input_tokens": 400,
            "gen_ai.usage.output_tokens": 40,
            "gen_ai.usage.cache_read.input_tokens": 80,
            "gen_ai.usage.reasoning.output_tokens": 4,
            "github.copilot.cost": 4.0,
            "github.copilot.nano_aiu": 400.0,
        },
        parent_span_id="top-root",
    )
    top_root = _span(
        "trace-native",
        "top-root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 400,
            "gen_ai.usage.output_tokens": 40,
            "gen_ai.usage.cache_read.input_tokens": 80,
            "gen_ai.usage.reasoning.output_tokens": 4,
            "github.copilot.cost": 4.0,
            "github.copilot.nano_aiu": 400.0,
            "github.copilot.turn_count": 1,
        },
    )
    nested_chat = _span(
        "trace-native",
        "nested-chat",
        "chat",
        {
            "gen_ai.usage.input_tokens": 200,
            "gen_ai.usage.output_tokens": 20,
            "gen_ai.usage.cache_read.input_tokens": 40,
            "gen_ai.usage.reasoning.output_tokens": 2,
        },
        parent_span_id="nested-root",
    )
    nested_root = _span(
        "trace-native",
        "nested-root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 200,
            "gen_ai.usage.output_tokens": 20,
            "gen_ai.usage.cache_read.input_tokens": 40,
            "gen_ai.usage.reasoning.output_tokens": 2,
        },
        parent_span_id="tool-call",
    )
    _write_jsonl(path, nested_chat, nested_root, top_chat, top_root)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (600, 60)
    assert usage.model_requests == 2
    assert [cost.to_dict() for cost in usage.costs] == [
        {
            "amount": 4.0,
            "unit": "model_multiplier",
            "source": "github.copilot.cost",
        },
        {"amount": 400.0, "unit": "nano_aiu", "source": "github.copilot.nano_aiu"},
    ]
    assert any("github.copilot.cost" in warning for warning in usage.warnings)
    assert any("github.copilot.nano_aiu" in warning for warning in usage.warnings)


def test_missing_root_reports_only_completed_chat_spans_as_lower_bound(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    first = _chat(
        "trace-timeout",
        "chat-1",
        "missing-root",
        input_tokens=101,
        output_tokens=11,
        cache_read=21,
        cache_write=0,
        reasoning=4,
        cost=0.1,
        aiu=10,
    )
    second = _chat(
        "trace-timeout",
        "chat-2",
        "missing-root",
        input_tokens=202,
        output_tokens=22,
        cache_read=42,
        cache_write=5,
        reasoning=6,
        cost=0.2,
        aiu=20,
    )
    _write_jsonl(path, first, second, malformed_tail=True)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert usage.status == "lower_bound"
    assert usage.complete is False
    assert usage.is_lower_bound is True
    assert (usage.input_tokens, usage.output_tokens) == (303, 33)
    assert usage.cache_read_input_tokens == 63
    assert usage.cache_write_input_tokens == 5
    assert usage.reasoning_output_tokens == 10
    assert "Copilot OTel root span missing; usage is a lower bound" in usage.warnings
    assert "ignored malformed OTel line 3" in usage.warnings


def test_root_cost_fields_are_authoritative_without_hiding_other_chat_units(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    root = _span(
        "trace-cost",
        "root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 10,
            "github.copilot.turn_count": 1,
            "github.copilot.cost": 0.5,
        },
    )
    chat = _chat(
        "trace-cost",
        "chat",
        "root",
        input_tokens=100,
        output_tokens=10,
        cache_read=20,
        cache_write=0,
        reasoning=2,
        cost=0.1,
        aiu=10,
    )
    _write_jsonl(path, chat, root)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert [cost.to_dict() for cost in usage.costs] == [
        {"amount": 10.0, "unit": "aiu", "source": "github.copilot.aiu"},
        {
            "amount": 0.5,
            "unit": "model_multiplier",
            "source": "github.copilot.cost",
        },
    ]


def test_complete_and_interrupted_traces_are_aggregated_without_hiding_the_lower_bound(tmp_path):
    path = tmp_path / COPILOT_OTEL_FILENAME
    complete_chat = _chat(
        "trace-complete",
        "chat-complete",
        "root-complete",
        input_tokens=100,
        output_tokens=10,
        cache_read=20,
        cache_write=0,
        reasoning=2,
        cost=0.1,
        aiu=10,
    )
    complete_root = _span(
        "trace-complete",
        "root-complete",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 10,
            "gen_ai.usage.cache_read.input_tokens": 20,
            "gen_ai.usage.reasoning.output_tokens": 2,
            "github.copilot.turn_count": 1,
        },
    )
    interrupted_chat = _chat(
        "trace-interrupted",
        "chat-interrupted",
        "missing-root",
        input_tokens=50,
        output_tokens=5,
        cache_read=10,
        cache_write=0,
        reasoning=1,
        cost=0.05,
        aiu=5,
    )
    _write_jsonl(path, complete_chat, complete_root, interrupted_chat)

    usage = parse_copilot_otel(str(path))

    assert usage is not None
    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (150, 15)
    assert usage.model_requests == 2
    assert len(usage.requests) == 2


def test_backend_falls_back_to_cli_output_as_incomplete_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    output.write_text("")
    backend = CopilotBackend()

    usage = backend.parse_usage(str(output), input_tokens=0, output_tokens=7)

    assert usage.status == "lower_bound"
    assert usage.input_tokens is None
    assert usage.output_tokens == 7
    assert usage.costs == ()


def test_backend_marks_missing_telemetry_without_activity_unavailable(tmp_path):
    backend = CopilotBackend()

    usage = backend.parse_usage(str(tmp_path / "output.jsonl"), input_tokens=0, output_tokens=0)

    assert usage.status == "unavailable"
    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_copilot_retry_detection_distinguishes_activity_from_an_unreadable_stream(tmp_path):
    activity = tmp_path / "activity.jsonl"
    _write_jsonl(
        activity,
        {
            "type": "assistant.message",
            "data": {
                "content": "working",
                "toolRequests": [{"toolCallId": "edit-1", "name": "edit"}],
            },
        },
    )
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("not json\n")
    backend = CopilotBackend()

    assert backend.retry_may_duplicate_model_work(str(activity)) is True
    assert backend.retry_may_duplicate_model_work(str(malformed)) is False
    assert backend.retry_may_duplicate_model_work(str(tmp_path / "missing.jsonl")) is False


def test_cli_otel_output_mismatch_downgrades_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    output.write_text("")
    root = _span(
        "trace-mismatch",
        "root",
        "invoke_agent",
        {
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 10,
            "gen_ai.usage.cache_read.input_tokens": 20,
            "gen_ai.usage.cache_creation.input_tokens": 0,
            "gen_ai.usage.reasoning.output_tokens": 2,
            "github.copilot.turn_count": 1,
            "github.copilot.cost": 0.1,
            "github.copilot.aiu": 10,
        },
    )
    chat = _chat(
        "trace-mismatch",
        "chat",
        "root",
        input_tokens=100,
        output_tokens=10,
        cache_read=20,
        cache_write=0,
        reasoning=2,
        cost=0.1,
        aiu=10,
    )
    _write_jsonl(tmp_path / COPILOT_OTEL_FILENAME, chat, root)

    usage = CopilotBackend().parse_usage(str(output), input_tokens=0, output_tokens=11)

    assert usage.status == "lower_bound"
    assert usage.complete is False
    assert usage.is_lower_bound is True
    assert "Copilot OTel output total differs from the CLI event stream" in usage.warnings


def test_each_execution_gets_an_isolated_official_otel_file(tmp_path):
    backend = CopilotBackend()
    first = backend.execution_environment(str(tmp_path / "task-a"))
    second = backend.execution_environment(str(tmp_path / "task-b"))

    assert first == {
        "COPILOT_OTEL_ENABLED": "true",
        "COPILOT_OTEL_EXPORTER_TYPE": "file",
        "COPILOT_OTEL_FILE_EXPORTER_PATH": str(tmp_path / "task-a" / COPILOT_OTEL_FILENAME),
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
    }
    assert second["COPILOT_OTEL_FILE_EXPORTER_PATH"] != first["COPILOT_OTEL_FILE_EXPORTER_PATH"]
    assert backend.attempt_output_files() == (COPILOT_OTEL_FILENAME,)


def test_execution_environment_overrides_host_otel_exporter(tmp_path):
    backend = CopilotBackend()
    merged = {
        "COPILOT_OTEL_ENABLED": "false",
        "COPILOT_OTEL_EXPORTER_TYPE": "otlp-http",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example",
    }

    merged.update(backend.execution_environment(str(tmp_path)))

    assert merged["COPILOT_OTEL_ENABLED"] == "true"
    assert merged["COPILOT_OTEL_EXPORTER_TYPE"] == "file"
    assert merged["COPILOT_OTEL_FILE_EXPORTER_PATH"] == str(tmp_path / COPILOT_OTEL_FILENAME)


def test_copilot_uses_documented_prompt_flag_without_stdin(tmp_path):
    backend = CopilotBackend(model="test-model")
    command = backend.build_command(str(tmp_path), str(tmp_path / "results"))

    invocation, stdin_data = backend.prepare_invocation(command, "EXACT PROMPT")

    assert invocation == [*command, "-p", "EXACT PROMPT"]
    assert stdin_data is None


def test_copilot_cli_install_uses_latest_release():
    script = Path("docker/install-scripts/install-copilot.sh").read_text()

    assert "npm install -g @github/copilot --cache" in script

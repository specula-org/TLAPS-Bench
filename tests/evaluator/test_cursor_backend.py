"""Focused tests for the Cursor backend."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from evaluator.backends.cursor import CursorBackend
from evaluator.cost import calculate_equivalent_cost_usd


def _write_jsonl(path, *events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events))


def test_cursor_terminal_usage_drives_structured_tokens_and_cost(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"taskToolCall": {"args": {"description": "delegate"}}},
        },
        {
            "type": "result",
            "subtype": "success",
            "result": "Done",
            "duration_ms": 2500,
            "duration_api_ms": 2500,
            "usage": {
                "inputTokens": 100,
                "outputTokens": 40,
                "cacheReadTokens": 60,
                "cacheWriteTokens": 10,
            },
        },
    )
    backend = CursorBackend()

    transcript, input_tokens, output_tokens = backend.parse_output(str(output))
    usage = backend.parse_usage(str(output), input_tokens=input_tokens, output_tokens=output_tokens)

    assert transcript.endswith("[RESULT/success] Done\n")
    assert (input_tokens, output_tokens) == (170, 40)
    assert usage.status == "complete"
    assert usage.input_tokens == 170
    assert usage.output_tokens == 40
    assert usage.cache_read_input_tokens == 60
    assert usage.cache_write_input_tokens == 10
    assert usage.model_time_secs is None
    assert usage.requests == ()
    assert usage.costs == ()
    assert usage.sources == ("cursor_cli_result",)
    assert calculate_equivalent_cost_usd(usage, backend.model) == (pytest.approx(0.0009555), None)


def test_cursor_missing_terminal_usage_is_unavailable(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(output, {"type": "result", "subtype": "success", "result": "Done"})
    backend = CursorBackend(model="gpt-5.2")

    _transcript, input_tokens, output_tokens = backend.parse_output(str(output))
    usage = backend.parse_usage(str(output), input_tokens=input_tokens, output_tokens=output_tokens)

    assert (input_tokens, output_tokens) == (0, 0)
    assert usage.status == "unavailable"
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert calculate_equivalent_cost_usd(usage, backend.model) == (
        None,
        "aggregate token usage is incomplete",
    )


def test_cursor_trusts_zero_terminal_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "result",
            "subtype": "success",
            "usage": {
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheReadTokens": 0,
                "cacheWriteTokens": 0,
            },
        },
    )

    usage = CursorBackend().parse_usage(str(output), input_tokens=0, output_tokens=0)

    assert usage.status == "complete"
    assert (usage.input_tokens, usage.output_tokens) == (0, 0)


def test_cursor_retry_detection_distinguishes_activity_from_an_unreadable_stream(tmp_path):
    activity = tmp_path / "activity.jsonl"
    _write_jsonl(
        activity,
        {
            "type": "tool_call",
            "subtype": "completed",
            "call_id": "edit-1",
            "tool_call": {"editToolCall": {"args": {"path": "Task.tla"}}},
        },
    )
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("not json\n")
    backend = CursorBackend()

    assert backend.retry_may_duplicate_model_work(str(activity)) is True
    assert backend.retry_may_duplicate_model_work(str(malformed)) is False
    assert backend.retry_may_duplicate_model_work(str(tmp_path / "missing.jsonl")) is False


def test_cursor_transcript_uses_the_tool_field_among_metadata(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "tool_call",
            "subtype": "started",
            "call_id": "outer-call",
            "tool_call": {
                "toolCallId": "native-call",
                "startedAtMs": "123",
                "shellToolCall": {"args": {"command": "tlapm --version"}},
            },
        },
        {
            "type": "tool_call",
            "subtype": "completed",
            "call_id": "outer-call",
            "tool_call": {
                "shellToolCall": {
                    "args": {"command": "tlapm --version"},
                    "result": "TLAPM version",
                },
                "completedAtMs": "456",
                "toolCallId": "native-call",
            },
        },
    )

    transcript, _input_tokens, _output_tokens = CursorBackend().parse_output(str(output))

    assert "[TOOL] shellToolCall tlapm --version" in transcript
    assert "[TOOL_RESULT] TLAPM version" in transcript
    assert "toolCallId" not in transcript


def test_cursor_uses_dynamic_firewall_with_default_runtime_hosts(monkeypatch):
    monkeypatch.delenv("CURSOR_API_ENDPOINT", raising=False)
    backend = CursorBackend()

    assert backend.dynamic_firewall is True
    assert backend.firewall_hosts() == [
        "api2.cursor.sh",
        "api2direct.cursor.sh",
        "api5.cursor.sh",
        "authenticate.cursor.sh",
        "authenticator.cursor.sh",
        "authentication.cursor.sh",
        "repo42.cursor.sh",
    ]


@pytest.mark.parametrize(
    ("endpoint", "hostname"),
    [
        ("https://cursor-gateway.example.com", "cursor-gateway.example.com"),
        ("https://CURSOR-GATEWAY.EXAMPLE.COM:443/v1", "cursor-gateway.example.com"),
        ("https://bücher.example/v1", "xn--bcher-kva.example"),
        ("https://cursor-gateway.example.com./v1", "cursor-gateway.example.com"),
    ],
)
def test_cursor_firewall_uses_configured_https_endpoint(monkeypatch, endpoint, hostname):
    monkeypatch.setenv("CURSOR_API_ENDPOINT", endpoint)
    backend = CursorBackend()

    assert backend.dynamic_firewall is False
    assert backend.firewall_hosts() == [hostname]


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "api2.cursor.sh",
        "http://api2.cursor.sh",
        "https:///missing-host",
        "https://api2.cursor.sh:8443",
        "https://api2.cursor.sh:not-a-port",
        "https://user@example.com",
        "https://bad_host.example.com",
        "https://127.0.0.1",
        "https://[::1]",
    ],
)
def test_cursor_firewall_rejects_endpoint_it_cannot_enforce(monkeypatch, endpoint):
    monkeypatch.setenv("CURSOR_API_ENDPOINT", endpoint)

    with pytest.raises(ValueError, match="CURSOR_API_ENDPOINT"):
        CursorBackend().firewall_hosts()

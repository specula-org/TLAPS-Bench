"""Claude Code stream-json usage and native USD cost parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluator.backends.claude_code import ClaudeCodeBackend, parse_claude_code_usage
from evaluator.cost import calculate_equivalent_cost_usd


def _assistant(
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read: int | None = None,
    cache_write: int | None = None,
    model: str = "claude-opus-4-8",
    message_id: str = "msg_1",
    provider_request_id: str | None = None,
    stop_reason: str | None = "end_turn",
) -> dict[str, object]:
    usage: dict[str, object] = {}
    if input_tokens is not None:
        usage["input_tokens"] = input_tokens
    if output_tokens is not None:
        usage["output_tokens"] = output_tokens
    if cache_read is not None:
        usage["cache_read_input_tokens"] = cache_read
    if cache_write is not None:
        usage["cache_creation_input_tokens"] = cache_write
    event: dict[str, object] = {
        "type": "assistant",
        "message": {
            "id": message_id,
            "model": model,
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": "working"}],
            "usage": usage,
        },
    }
    if provider_request_id is not None:
        event["request_id"] = provider_request_id
    return event


def _result(
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read: int | None = None,
    cache_write: int | None = None,
    total_cost_usd: float | None = None,
    duration_api_ms: int | None = None,
    is_error: bool = False,
    subtype: str = "success",
    num_turns: int | None = None,
    model_usage: dict[str, object] | None = None,
) -> dict[str, object]:
    usage: dict[str, object] = {}
    if input_tokens is not None:
        usage["input_tokens"] = input_tokens
    if output_tokens is not None:
        usage["output_tokens"] = output_tokens
    if cache_read is not None:
        usage["cache_read_input_tokens"] = cache_read
    if cache_write is not None:
        usage["cache_creation_input_tokens"] = cache_write
    event: dict[str, object] = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "result": "done",
        "usage": usage,
    }
    if total_cost_usd is not None:
        event["total_cost_usd"] = total_cost_usd
    if duration_api_ms is not None:
        event["duration_api_ms"] = duration_api_ms
    if num_turns is not None:
        event["num_turns"] = num_turns
    if model_usage is not None:
        event["modelUsage"] = model_usage
    return event


def _write(path: Path, *events: dict[str, object]) -> str:
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return str(path)


def test_cache_tokens_classify_input_without_double_counting(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10, cache_read=40, cache_write=20),
        _result(
            input_tokens=100,
            output_tokens=10,
            cache_read=40,
            cache_write=20,
            total_cost_usd=0.0125,
            duration_api_ms=2500,
        ),
    )

    usage = parse_claude_code_usage(path, requested_model="claude-opus-4-8")

    assert usage is not None
    # Anthropic reports cache buckets beside input_tokens; the shared contract
    # folds them in exactly once (100 + 40 + 20).
    assert usage.input_tokens == 160
    assert usage.output_tokens == 10
    assert usage.cache_read_input_tokens == 40
    assert usage.cache_write_input_tokens == 20
    assert usage.model_requests == 1
    assert usage.model_time_secs == 2.5
    assert usage.status == "complete"
    assert usage.costs == tuple(usage.costs)
    assert [cost.to_dict() for cost in usage.costs] == [
        {"amount": 0.0125, "unit": "usd", "source": "claude_code.total_cost_usd"}
    ]
    cost, warning = calculate_equivalent_cost_usd(usage, "claude-opus-4-8")
    assert cost == 0.0125
    assert warning is not None
    assert "differs from token-priced cost" in warning


def test_native_usd_cost_is_recorded_in_its_own_unit(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=5),
        _result(input_tokens=10, output_tokens=5, total_cost_usd=0.42),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert [cost.to_dict() for cost in usage.costs] == [
        {"amount": 0.42, "unit": "usd", "source": "claude_code.total_cost_usd"}
    ]


def test_per_request_evidence_is_preserved(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10, message_id="msg_a", stop_reason="tool_use"),
        _assistant(input_tokens=60, output_tokens=20, message_id="msg_b", stop_reason="end_turn"),
        _result(input_tokens=160, output_tokens=30, total_cost_usd=0.01),
    )

    usage = parse_claude_code_usage(path, requested_model="claude-opus-4-8")

    assert usage is not None
    assert usage.model_requests == 2
    assert [request.request_id for request in usage.requests] == ["msg_a", "msg_b"]
    assert [request.finish_reasons for request in usage.requests] == [("tool_use",), ("end_turn",)]
    assert usage.requests[0].requested_model == "claude-opus-4-8"
    assert usage.requests[0].provider == "anthropic"
    assert usage.status == "complete"


@pytest.mark.parametrize("provider_flag", ["CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_MANTLE"])
def test_aws_provider_is_preserved_for_public_price_fallback(provider_flag, monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_MANTLE", raising=False)
    monkeypatch.setenv(provider_flag, "1")
    backend = ClaudeCodeBackend(model="claude-opus-4-8")
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=1_000, output_tokens=10, cache_read=0, cache_write=0),
        _result(input_tokens=1_000, output_tokens=100, cache_read=0, cache_write=0),
    )

    usage = backend.parse_usage(path, input_tokens=0, output_tokens=0)
    cost, warning = calculate_equivalent_cost_usd(usage, backend.model, backend.provider)

    assert backend.provider == "amazon-bedrock"
    assert usage.requests[0].provider == "amazon-bedrock"
    assert cost == pytest.approx(0.00825)
    assert warning is None


def test_provider_request_id_is_preserved_separately_from_message_id(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(
            input_tokens=10,
            output_tokens=5,
            message_id="msg_a",
            provider_request_id="req_abc",
        ),
        _result(input_tokens=10, output_tokens=5, total_cost_usd=0.01),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.requests[0].request_id == "msg_a"
    assert usage.requests[0].provider_request_id == "req_abc"


def test_model_usage_supplies_cross_model_authoritative_totals(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2, model="claude-opus-4-8", message_id="msg_a"),
        _result(
            input_tokens=10,
            output_tokens=20,
            total_cost_usd=0.11,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 10,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                    "costUSD": 0.1,
                },
                "claude-haiku-4-5": {
                    "inputTokens": 5,
                    "cacheReadInputTokens": 3,
                    "cacheCreationInputTokens": 2,
                    "outputTokens": 4,
                    "costUSD": 0.01,
                },
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.input_tokens == 20
    assert usage.output_tokens == 24
    assert usage.cache_read_input_tokens == 3
    assert usage.cache_write_input_tokens == 2
    costs = {cost.source: cost.amount for cost in usage.costs}
    assert costs["claude_code.total_cost_usd"] == 0.11
    assert costs["claude_code.modelUsage.public_price"] == pytest.approx(0.0005778)
    # modelUsage is the exact cross-model aggregate. Per-request evidence can
    # cover only the primary-model stream, so the token/cost totals are exact
    # while the model-request count remains a lower bound.
    assert usage.model_requests == 2
    assert usage.status == "lower_bound"
    assert any("without streamed request events" in warning for warning in usage.warnings)


def test_model_usage_cost_is_used_when_total_cost_is_absent(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2),
        _result(
            input_tokens=10,
            output_tokens=20,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 10,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                    "costUSD": 0.1,
                }
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "complete"
    costs = {cost.source: cost.amount for cost in usage.costs}
    assert costs["claude_code.modelUsage.costUSD"] == 0.1
    assert costs["claude_code.modelUsage.public_price"] == pytest.approx(0.00055)


def test_cross_model_tokens_are_priced_when_native_usd_is_absent(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2, model="claude-opus-4-8"),
        _result(
            input_tokens=10,
            output_tokens=20,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 10,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                },
                "claude-haiku-4-5": {
                    "inputTokens": 5,
                    "cacheReadInputTokens": 3,
                    "cacheCreationInputTokens": 2,
                    "outputTokens": 4,
                },
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    cost, warning = calculate_equivalent_cost_usd(usage, "claude-opus-4-8", "anthropic")
    assert cost == pytest.approx(0.0005778)
    assert warning is None


@pytest.mark.parametrize(
    "helper_usage",
    [
        {
            "inputTokens": 5,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
            "outputTokens": 4,
        },
        {
            "inputTokens": 5,
            "cacheReadInputTokens": 0,
            "outputTokens": 4,
        },
    ],
)
def test_unpriceable_cross_model_helper_keeps_cost_blank(tmp_path, helper_usage):
    helper_model = "unknown-helper" if "cacheCreationInputTokens" in helper_usage else "claude-haiku-4-5"
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2, model="claude-opus-4-8"),
        _result(
            input_tokens=10,
            output_tokens=20,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 10,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                },
                helper_model: helper_usage,
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    cost, warning = calculate_equivalent_cost_usd(usage, "claude-opus-4-8", "anthropic")
    assert cost is None
    assert warning is not None


def test_terminal_turn_count_and_hidden_helper_set_request_floor(tmp_path):
    streamed = [
        _assistant(
            input_tokens=10,
            output_tokens=2,
            model="claude-opus-4-8",
            message_id=f"msg_{index}",
        )
        for index in range(6)
    ]
    path = _write(
        tmp_path / "output.jsonl",
        *streamed,
        _result(
            input_tokens=60,
            output_tokens=20,
            total_cost_usd=0.11,
            num_turns=7,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 60,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                    "costUSD": 0.1,
                },
                "claude-haiku-4-5": {
                    "inputTokens": 5,
                    "cacheReadInputTokens": 3,
                    "cacheCreationInputTokens": 2,
                    "outputTokens": 4,
                    "costUSD": 0.01,
                },
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.model_requests == 7
    assert usage.status == "lower_bound"
    assert any("num_turns 7 differs from 6" in warning for warning in usage.warnings)
    assert any("claude-haiku-4-5" in warning for warning in usage.warnings)


def test_same_model_hidden_usage_still_makes_request_count_a_lower_bound(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2, cache_read=0, cache_write=0, model="claude-opus-4-8"),
        _result(
            input_tokens=10,
            output_tokens=20,
            total_cost_usd=0.1,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 15,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 24,
                    "costUSD": 0.1,
                }
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.model_requests == 2
    assert usage.status == "lower_bound"
    assert any("usage without streamed request events" in warning for warning in usage.warnings)


def test_terminal_turn_disagreement_without_helper_is_a_lower_bound(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2, message_id="msg_1"),
        _assistant(input_tokens=10, output_tokens=2, message_id="msg_2"),
        _result(input_tokens=20, output_tokens=10, total_cost_usd=0.1, num_turns=3),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.model_requests == 3
    assert usage.status == "lower_bound"
    assert any("num_turns 3 differs from 2" in warning for warning in usage.warnings)


def test_model_usage_cost_mismatch_is_a_lower_bound(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2),
        _result(
            input_tokens=10,
            output_tokens=20,
            total_cost_usd=0.2,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 10,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                    "costUSD": 0.1,
                }
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "lower_bound"
    assert any("total_cost_usd 0.2 differs" in warning for warning in usage.warnings)


def test_malformed_model_usage_is_not_silently_ignored(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2),
        _result(
            input_tokens=10,
            output_tokens=20,
            total_cost_usd=0.1,
            model_usage={"claude-opus-4-8": "invalid"},
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "lower_bound"
    assert "Claude Code modelUsage is malformed" in usage.warnings


def test_malformed_json_invalidates_terminal_cost(tmp_path):
    path = tmp_path / "output.jsonl"
    path.write_text(
        json.dumps(_assistant(input_tokens=10, output_tokens=2))
        + "\n{not-json}\n"
        + json.dumps(_result(input_tokens=10, output_tokens=20, total_cost_usd=0.1))
        + "\n"
    )

    usage = parse_claude_code_usage(str(path))

    assert usage is not None
    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert "Claude Code stream contains malformed JSON" in usage.warnings


def test_non_object_json_invalidates_terminal_cost(tmp_path):
    path = tmp_path / "output.jsonl"
    path.write_text(
        json.dumps(_assistant(input_tokens=10, output_tokens=2))
        + "\n[]\n"
        + json.dumps(_result(input_tokens=10, output_tokens=20, total_cost_usd=0.1))
        + "\n"
    )

    usage = parse_claude_code_usage(str(path))

    assert usage is not None
    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert "Claude Code stream contains malformed JSON" in usage.warnings


def test_unidentified_multiple_results_invalidate_cost(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2),
        _result(input_tokens=10, output_tokens=20, total_cost_usd=0.1),
        _result(input_tokens=10, output_tokens=20, total_cost_usd=0.1),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert "Claude Code result_index sequence is missing, duplicated, or out of order" in usage.warnings


def test_partially_malformed_model_usage_cannot_silently_omit_a_model(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, output_tokens=2),
        _result(
            input_tokens=10,
            output_tokens=20,
            total_cost_usd=0.1,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 10,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "outputTokens": 20,
                    "costUSD": 0.1,
                },
                "unknown-helper": "invalid",
            },
        ),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "lower_bound"
    assert "Claude Code modelUsage contains malformed model entries" in usage.warnings
    assert [cost.source for cost in usage.costs] == ["claude_code.total_cost_usd"]
    assert calculate_equivalent_cost_usd(usage, "claude-opus-4-8") == (0.1, None)


def test_summary_mismatch_against_messages_is_a_lower_bound(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10),
        _result(input_tokens=999, output_tokens=10, total_cost_usd=0.01),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "lower_bound"
    assert any("result total 999" in warning for warning in usage.warnings)


def test_missing_result_event_is_a_lower_bound(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "lower_bound"
    assert usage.input_tokens == 100
    assert any("result event missing" in warning for warning in usage.warnings)


def test_error_result_is_not_complete(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10),
        _result(input_tokens=100, output_tokens=10, total_cost_usd=0.01, is_error=True, subtype="error"),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.status == "lower_bound"


def test_missing_cost_is_flagged_rather_than_assumed_zero(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10),
        _result(input_tokens=100, output_tokens=10),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert any("total_cost_usd or modelUsage costUSD" in warning for warning in usage.warnings)


def test_unreported_tokens_stay_null_not_zero(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(output_tokens=10),
        _result(output_tokens=10, total_cost_usd=0.01),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.input_tokens is None
    assert usage.to_dict()["input_tokens"] is None
    assert usage.output_tokens == 10
    assert usage.status == "lower_bound"
    assert "Claude Code result input_tokens is unavailable" in usage.warnings


def test_explicit_zero_stays_an_exact_zero(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=0, output_tokens=0),
        _result(input_tokens=0, output_tokens=0, total_cost_usd=0.0),
    )

    usage = parse_claude_code_usage(path)

    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.status == "complete"


def test_backend_falls_back_to_legacy_tokens_when_events_are_absent(tmp_path):
    backend = ClaudeCodeBackend(model="claude-opus-4-8")
    path = str(tmp_path / "missing.jsonl")

    usage = backend.parse_usage(path, input_tokens=12, output_tokens=3)

    assert usage.input_tokens == 12
    assert usage.output_tokens == 3
    assert usage.status == "lower_bound"


def test_backend_reports_unavailable_when_nothing_was_produced(tmp_path):
    backend = ClaudeCodeBackend(model="claude-opus-4-8")
    path = str(tmp_path / "missing.jsonl")

    usage = backend.parse_usage(path, input_tokens=0, output_tokens=0)

    assert usage.status == "unavailable"
    assert usage.input_tokens is None


def test_streamed_partial_output_does_not_falsely_flag_a_complete_run(tmp_path):
    """Regression for a real multi-turn run: each streamed assistant
    output_tokens is a message-start partial that sums well below the settled
    total in the result event (24 vs 673 across six turns). The output total
    must come from the result event, and the streamed output must never drive a
    false lower bound."""

    path = _write(
        tmp_path / "output.jsonl",
        # Six turns; input/cache are exact per message, output is a partial.
        _assistant(input_tokens=10, output_tokens=3, cache_read=14364, cache_write=7163, message_id="m0"),
        _assistant(input_tokens=5, output_tokens=4, cache_read=18674, cache_write=2799, message_id="m1"),
        _assistant(input_tokens=5, output_tokens=4, cache_read=21473, cache_write=225, message_id="m2"),
        _assistant(input_tokens=5, output_tokens=4, cache_read=21698, cache_write=116, message_id="m3"),
        _assistant(input_tokens=6, output_tokens=4, cache_read=21814, cache_write=95, message_id="m4"),
        _assistant(input_tokens=5, output_tokens=5, cache_read=21909, cache_write=190, message_id="m5"),
        _result(
            input_tokens=36,
            output_tokens=673,
            cache_read=119932,
            cache_write=10588,
            total_cost_usd=0.0372752,
            duration_api_ms=8000,
            num_turns=6,
        ),
    )

    usage = parse_claude_code_usage(path, requested_model="claude-haiku-4-5")

    assert usage is not None
    assert usage.status == "complete"
    assert usage.warnings == ()
    # Settled output total from the result event, not the summed partials (24).
    assert usage.output_tokens == 673
    assert usage.input_tokens == 36 + 119932 + 10588
    assert usage.model_requests == 6
    # Per-request output is unknown on success, so it is null rather than the
    # misleading streamed partial; the settled total lives on the summary.
    assert [request.output_tokens for request in usage.requests] == [None] * 6
    assert [request.request_id for request in usage.requests] == ["m0", "m1", "m2", "m3", "m4", "m5"]
    assert [cost.to_dict() for cost in usage.costs] == [
        {"amount": 0.0372752, "unit": "usd", "source": "claude_code.total_cost_usd"}
    ]


def test_per_request_input_and_cache_evidence_is_preserved_on_success(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=10, cache_read=14364, cache_write=7266, output_tokens=1, message_id="m0"),
        _assistant(input_tokens=5, cache_read=18674, cache_write=2799, output_tokens=1, message_id="m1"),
        _result(input_tokens=15, output_tokens=90, cache_read=33038, cache_write=10065, total_cost_usd=0.02),
    )

    usage = parse_claude_code_usage(path, requested_model="claude-haiku-4-5")

    assert usage.status == "complete"
    # Input/cache are final per message and are kept as per-request evidence.
    assert [request.input_tokens for request in usage.requests] == [10 + 14364 + 7266, 5 + 18674 + 2799]
    assert [request.cache_read_input_tokens for request in usage.requests] == [14364, 18674]
    assert usage.output_tokens == 90


def test_streamed_input_mismatch_against_result_is_a_lower_bound(tmp_path):
    """Input/cache are reliable per message, so a mismatch means lost turns."""

    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=1, message_id="m0"),
        _result(input_tokens=999, output_tokens=250, total_cost_usd=0.01),
    )

    usage = parse_claude_code_usage(path)

    assert usage.status == "lower_bound"
    assert any("input_tokens result total 999" in warning for warning in usage.warnings)


def test_model_requests_falls_back_to_num_turns_without_streamed_events(tmp_path):
    path = _write(
        tmp_path / "output.jsonl",
        _result(input_tokens=30, output_tokens=90, total_cost_usd=0.02, num_turns=4),
    )

    usage = parse_claude_code_usage(path)

    assert usage.status == "complete"
    assert usage.model_requests == 4
    assert usage.output_tokens == 90


def _assistant_block(message_id: str, usage: dict[str, int], *, block_index: int) -> dict[str, object]:
    """One content-block event of a multi-block turn, echoing the turn usage."""

    return {
        "type": "assistant",
        "message": {
            "id": message_id,
            "model": "claude-haiku-4-5",
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "name": f"Bash{block_index}", "input": {}}],
            "usage": usage,
        },
    }


def test_multi_block_turn_is_counted_once_per_message(tmp_path):
    """Claude Code repeats a turn's usage on every content-block event.

    Regression for a real run where 149 block-events across 94 messages
    inflated the input total by ~1.55x. Each message id must count once.
    """

    turn_usage = {
        "input_tokens": 20121,
        "cache_creation_input_tokens": 7310,
        "cache_read_input_tokens": 12802,
        "output_tokens": 4,
    }
    path = _write(
        tmp_path / "output.jsonl",
        _assistant_block("msg_1", turn_usage, block_index=0),
        _assistant_block("msg_1", turn_usage, block_index=1),
        _assistant_block("msg_1", turn_usage, block_index=2),
        _assistant_block("msg_2", {"input_tokens": 6, "output_tokens": 1}, block_index=0),
        _assistant_block("msg_2", {"input_tokens": 6, "output_tokens": 1}, block_index=1),
    )

    usage = parse_claude_code_usage(path, requested_model="claude-haiku-4-5")

    assert usage is not None
    assert usage.model_requests == 2
    # msg_1: 20121 + 7310 + 12802 = 40233 input; msg_2: 6. Not multiplied by blocks.
    assert usage.input_tokens == 40233 + 6
    assert usage.output_tokens == 4 + 1
    assert [request.request_id for request in usage.requests] == ["msg_1", "msg_2"]


def test_legacy_parse_output_dedupes_multi_block_turns(tmp_path):
    """The legacy fallback total must dedupe the same way as the structured one."""

    turn_usage = {"input_tokens": 100, "cache_read_input_tokens": 40, "output_tokens": 10}
    backend = ClaudeCodeBackend(model="claude-haiku-4-5")
    path = _write(
        tmp_path / "output.jsonl",
        _assistant_block("msg_1", turn_usage, block_index=0),
        _assistant_block("msg_1", turn_usage, block_index=1),
    )

    _, legacy_in, legacy_out = backend.parse_output(path)

    assert (legacy_in, legacy_out) == (140, 10)


def test_legacy_parse_output_total_matches_structured_input_total(tmp_path):
    """The structured record must not change the legacy top-level numbers."""

    backend = ClaudeCodeBackend(model="claude-opus-4-8")
    path = _write(
        tmp_path / "output.jsonl",
        _assistant(input_tokens=100, output_tokens=10, cache_read=40, cache_write=20),
        _result(
            input_tokens=100,
            output_tokens=10,
            cache_read=40,
            cache_write=20,
            total_cost_usd=0.01,
        ),
    )

    _, legacy_in, legacy_out = backend.parse_output(path)
    usage = backend.parse_usage(path, input_tokens=legacy_in, output_tokens=legacy_out)

    assert (legacy_in, legacy_out) == (160, 10)
    assert usage.legacy_input_tokens == legacy_in
    assert usage.legacy_output_tokens == legacy_out


def _background_events():
    """Reduced single-session trace with follow-up turns and an empty result.

    result.usage/num_turns are per turn; modelUsage/cost/API duration accumulate.
    See https://code.claude.com/docs/en/agent-sdk/cost-tracking#track-costs-in-streaming-input-mode.
    """
    path = Path(__file__).parent / "fixtures" / "claude_background_results.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("with_model_usage", [True, False])
def test_background_results_count_each_turn_and_cumulative_cost_once(tmp_path, with_model_usage):
    events = _background_events()
    if not with_model_usage:
        for event in events:
            event.pop("modelUsage", None)
    path = _write(tmp_path / "background.jsonl", *events)
    backend = ClaudeCodeBackend()

    usage = parse_claude_code_usage(path)
    _, legacy_in, legacy_out = backend.parse_output(path)
    tools = backend.parse_run_metadata(path)["tool_calls"]

    assert usage.status == "complete"
    assert usage.warnings == ()
    assert (usage.input_tokens, usage.output_tokens) == (27, 42)
    assert (legacy_in, legacy_out) == (27, 42)
    assert (usage.cache_read_input_tokens, usage.cache_write_input_tokens) == (2, 3)
    assert usage.model_requests == 3
    assert usage.model_time_secs == 2.1
    assert [request.output_tokens for request in usage.requests] == [None, None, None]
    assert next(cost.amount for cost in usage.costs if cost.source == "claude_code.total_cost_usd") == 0.21
    assert tools["complete"] is True
    assert (tools["total"], tools["tlaps"], tools["other"]) == (2, 1, 1)


def test_background_results_keep_cross_model_totals_and_request_lower_bound(tmp_path):
    events = _background_events()
    events[-1]["modelUsage"]["claude-haiku-4-5"] = {
        "inputTokens": 4,
        "outputTokens": 6,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0,
        "costUSD": 0.02,
    }
    events[-1]["total_cost_usd"] = 0.23
    path = _write(tmp_path / "mixed-models.jsonl", *events)

    usage = parse_claude_code_usage(path)
    _, legacy_in, legacy_out = ClaudeCodeBackend().parse_output(path)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (31, 48)
    assert (legacy_in, legacy_out) == (31, 48)
    assert usage.model_requests == 4
    assert any("without streamed request events" in warning for warning in usage.warnings)
    assert next(cost.amount for cost in usage.costs if cost.source == "claude_code.total_cost_usd") == 0.23


@pytest.mark.parametrize(
    "damage",
    [
        "mixed-result-session",
        "mixed-assistant-session",
        "missing-session",
        "missing-index",
        "bool-index",
        "gap",
        "duplicate",
        "nonzero-start",
        "reset",
    ],
)
def test_background_results_reject_broken_session_or_delivery_identity(tmp_path, damage):
    events = _background_events()
    if damage == "mixed-result-session":
        events[-1]["session_id"] = "another-session"
    elif damage == "mixed-assistant-session":
        events[-2]["session_id"] = "another-session"
    elif damage == "missing-session":
        del events[-1]["session_id"]
    elif damage == "missing-index":
        del events[-1]["result_index"]
    elif damage == "bool-index":
        events[3]["result_index"] = False
    elif damage == "gap":
        events[-1]["result_index"] = 4
    elif damage == "duplicate":
        events[-1]["result_index"] = 2
    elif damage == "nonzero-start":
        events[3]["result_index"] = 1
    else:
        events.insert(4, {"type": "system", "subtype": "conversation_reset", "session_id": "background-session"})
    path = _write(tmp_path / "invalid-identity.jsonl", *events)

    usage = parse_claude_code_usage(path)
    tools = ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]

    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert tools["is_lower_bound"] is True
    assert tools["total"] == 2


@pytest.mark.parametrize("field", ["total_cost_usd", "duration_api_ms", "outputTokens", "costUSD", "missing-model"])
def test_background_results_reject_cumulative_regressions(tmp_path, field):
    events = _background_events()
    if field in {"total_cost_usd", "duration_api_ms"}:
        events[-1][field] = 0
    elif field == "missing-model":
        events[-1]["modelUsage"] = {}
    else:
        events[-1]["modelUsage"]["claude-opus-4-8"][field] = 0
    path = _write(tmp_path / "invalid-totals.jsonl", *events)

    usage = parse_claude_code_usage(path)

    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert usage.input_tokens >= 27
    assert usage.output_tokens >= 30
    assert any("disappeared or decreased" in warning for warning in usage.warnings)


@pytest.mark.parametrize("tail_type", ["assistant", "stream_event", "error", "malformed", "non-object"])
def test_background_results_do_not_finalize_trailing_activity(tmp_path, tail_type):
    events = _background_events()
    if tail_type == "assistant":
        events.append(
            {**_assistant(input_tokens=9, output_tokens=1, message_id="unfinished"), "session_id": "background-session"}
        )
    elif tail_type in {"stream_event", "error"}:
        events.append({"type": tail_type, "session_id": "background-session"})
    path = _write(tmp_path / "invalid-tail.jsonl", *events)
    if tail_type in {"malformed", "non-object"}:
        with open(path, "a") as stream:
            stream.write("{broken\n" if tail_type == "malformed" else "[]\n")

    usage = parse_claude_code_usage(path)
    tools = ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]

    assert usage.costs == ()
    assert usage.status == "lower_bound"
    assert usage.input_tokens == (36 if tail_type == "assistant" else 27)
    assert usage.output_tokens == 42
    assert tools["is_lower_bound"] is True


def test_background_error_result_keeps_usage_and_does_not_claim_complete(tmp_path):
    events = _background_events()
    events[-1]["is_error"] = True
    events[-1]["subtype"] = "error_max_turns"
    usage = parse_claude_code_usage(_write(tmp_path / "error-result.jsonl", *events))

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (27, 42)
    assert next(cost.amount for cost in usage.costs if cost.source == "claude_code.total_cost_usd") == 0.21


def test_background_unfinished_tool_does_not_discard_settled_cost(tmp_path):
    events = [event for event in _background_events() if event["type"] != "user"]
    path = _write(tmp_path / "unfinished-tools.jsonl", *events)

    usage = parse_claude_code_usage(path)
    tools = ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]

    assert usage.status == "complete"
    assert next(cost.amount for cost in usage.costs if cost.source == "claude_code.total_cost_usd") == 0.21
    assert tools["is_lower_bound"] is True
    assert tools["total"] == 2
    assert any("unfinished tool call" in warning for warning in tools["warnings"])


def test_background_truncated_turn_preserves_completed_output_without_model_usage(tmp_path):
    events = _background_events()
    for event in events:
        event.pop("modelUsage", None)
    events.append(_assistant(input_tokens=9, output_tokens=1, message_id="unfinished"))
    usage = parse_claude_code_usage(_write(tmp_path / "truncated.jsonl", *events))

    assert usage.status == "lower_bound"
    assert usage.costs == ()
    assert (usage.input_tokens, usage.output_tokens) == (36, 42)


def test_background_missing_turn_usage_is_not_silently_exact(tmp_path):
    events = _background_events()
    del events[7]["usage"]
    usage = parse_claude_code_usage(_write(tmp_path / "missing-turn-usage.jsonl", *events))

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (27, 42)
    assert usage.model_requests == 3
    assert any("missing from some result turns" in warning for warning in usage.warnings)


def test_background_conflicting_message_identity_cannot_finalize_cost(tmp_path):
    events = _background_events()
    events[-2]["message"]["id"] = "msg-1"
    usage = parse_claude_code_usage(_write(tmp_path / "conflicting-message.jsonl", *events))

    assert usage.status == "lower_bound"
    assert usage.costs == ()
    assert "Claude Code assistant message ID has conflicting usage" in usage.warnings


def test_indexed_single_result_is_still_complete(tmp_path):
    path = _write(tmp_path / "single-indexed-result.jsonl", *_background_events()[:4])
    usage = parse_claude_code_usage(path)

    assert usage.status == "complete"
    assert (usage.input_tokens, usage.output_tokens, usage.model_requests) == (10, 20, 1)
    assert ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]["complete"] is True


def test_empty_final_background_result_preserves_cumulative_api_duration(tmp_path):
    path = _write(tmp_path / "empty-final-result.jsonl", *_background_events()[:9])
    usage = parse_claude_code_usage(path)

    assert usage.status == "complete"
    assert usage.model_time_secs == 1.5
    assert (usage.input_tokens, usage.output_tokens, usage.model_requests) == (15, 30, 2)
    assert next(cost.amount for cost in usage.costs if cost.source == "claude_code.total_cost_usd") == 0.15


def test_visible_same_model_helper_does_not_invent_an_extra_request(tmp_path):
    path = _write(
        tmp_path / "visible-helper.jsonl",
        _assistant(input_tokens=10, output_tokens=1, message_id="primary"),
        _assistant(input_tokens=5, output_tokens=1, message_id="helper"),
        _result(
            input_tokens=10,
            output_tokens=20,
            total_cost_usd=0.1,
            num_turns=1,
            model_usage={
                "claude-opus-4-8": {
                    "inputTokens": 15,
                    "outputTokens": 24,
                    "cacheReadInputTokens": 0,
                    "cacheCreationInputTokens": 0,
                    "costUSD": 0.1,
                }
            },
        ),
    )
    usage = parse_claude_code_usage(path)

    assert usage.status == "lower_bound"
    assert usage.model_requests == 2
    assert (usage.input_tokens, usage.output_tokens) == (15, 24)
    assert not any("without streamed request events" in warning for warning in usage.warnings)


@pytest.mark.parametrize(
    ("field", "smaller_total", "summary_field", "expected_floor"),
    [
        ("outputTokens", 40, "output_tokens", 42),
        ("inputTokens", 20, "input_tokens", 27),
        ("cacheReadInputTokens", 1, "cache_read_input_tokens", 2),
        ("cacheCreationInputTokens", 2, "cache_write_input_tokens", 3),
    ],
)
def test_monotonic_model_totals_cannot_undercut_primary_usage(
    tmp_path, field, smaller_total, summary_field, expected_floor
):
    events = _background_events()
    events[-1]["modelUsage"]["claude-opus-4-8"][field] = smaller_total
    path = _write(tmp_path / "inconsistent-primary-scope.jsonl", *events)

    usage = parse_claude_code_usage(path)

    assert usage.status == "lower_bound"
    assert getattr(usage, summary_field) == expected_floor
    assert any(f"modelUsage {summary_field}" in warning and "smaller than" in warning for warning in usage.warnings)
    assert [cost.source for cost in usage.costs] == ["claude_code.total_cost_usd"]


@pytest.mark.parametrize("missing_bucket", ["input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"])
@pytest.mark.parametrize("multiple_results", [False, True])
def test_partial_visible_input_cannot_prove_an_extra_hidden_request(tmp_path, missing_bucket, multiple_results):
    events = _background_events() if multiple_results else _background_events()[:4]
    assistant = events[-2]["message"] if multiple_results else events[1]["message"]
    del assistant["usage"][missing_bucket]
    path = _write(tmp_path / "partial-visible-input.jsonl", *events)

    usage = parse_claude_code_usage(path)

    assert usage.model_requests == (3 if multiple_results else 1)
    assert not any("without streamed request events" in warning for warning in usage.warnings)

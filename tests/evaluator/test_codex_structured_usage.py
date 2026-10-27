"""Structured usage parsing for the native Codex CLI JSONL contract."""

import json
import subprocess
from pathlib import Path

import pytest

from evaluator.backends.codex import CodexBackend
from evaluator.backends.codex_usage_wrapper import CODEX_CHILD_USAGE_VERSION
from evaluator.cost import calculate_equivalent_cost_usd


def _write_jsonl(path: Path, *records: object) -> None:
    with path.open("w") as f:
        for record in records:
            if isinstance(record, str):
                f.write(record + "\n")
            else:
                f.write(json.dumps(record) + "\n")


def _completed_usage(**overrides: object) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": 240,
        "cached_input_tokens": 180,
        "cache_write_input_tokens": 20,
        "output_tokens": 60,
        "reasoning_output_tokens": 25,
    }
    usage.update(overrides)
    return {"type": "turn.completed", "usage": usage}


def _audit_request(
    *,
    input_tokens: int,
    cached_input_tokens: int,
    cache_write_input_tokens: int,
    output_tokens: int,
    reasoning_output_tokens: int,
    model: object = "gpt-5.6-sol",
    provider: object = "openai",
) -> dict[str, object]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": cache_write_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "model": model,
        "provider": provider,
    }


def _child_audit(
    *,
    root_thread_id: str = "parent",
    child_count: int = 1,
    complete: bool = True,
    warning_codes: list[str] | None = None,
    requests: list[dict[str, object]] | None = None,
    **usage_overrides: object,
) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": 40 if child_count else 0,
        "cached_input_tokens": 20 if child_count else 0,
        "cache_write_input_tokens": 5 if child_count else 0,
        "output_tokens": 10 if child_count else 0,
        "reasoning_output_tokens": 4 if child_count else 0,
    }
    usage.update(usage_overrides)
    event = {
        "type": "tlaps.codex_child_usage",
        "version": CODEX_CHILD_USAGE_VERSION,
        "root_thread_id": root_thread_id,
        "child_count": child_count,
        **usage,
        "complete": complete,
        "warning_codes": warning_codes or [],
    }
    event["requests"] = (
        requests
        if requests is not None
        else [
            _audit_request(
                input_tokens=240,
                cached_input_tokens=180,
                cache_write_input_tokens=20,
                output_tokens=60,
                reasoning_output_tokens=25,
            ),
            *(
                [
                    _audit_request(
                        input_tokens=40,
                        cached_input_tokens=20,
                        cache_write_input_tokens=5,
                        output_tokens=10,
                        reasoning_output_tokens=4,
                    )
                ]
                if child_count
                else []
            ),
        ]
    )
    return event


def test_complete_terminal_aggregate_maps_without_fabricating_request_or_cost(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Done"},
            # Future intermediate usage must not be added to the terminal total.
            "usage": {"input_tokens": 999, "output_tokens": 999},
        },
        _completed_usage(),
    )
    backend = CodexBackend(model="gpt-5.6-sol")

    transcript, input_tokens, output_tokens = backend.parse_output(str(output))
    usage = backend.parse_usage(str(output), input_tokens=input_tokens, output_tokens=output_tokens)

    assert transcript == "[AGENT] Done\n"
    assert (input_tokens, output_tokens) == (240, 60)
    assert usage.status == "complete"
    assert usage.input_tokens == 240
    assert usage.cache_read_input_tokens == 180
    assert usage.cache_write_input_tokens == 20
    assert usage.output_tokens == 60
    assert usage.reasoning_output_tokens == 25
    assert usage.model_requests is None
    assert usage.model_time_secs is None
    assert usage.requests == ()
    assert usage.costs == ()
    assert usage.sources == ("codex_cli_turn_completed",)
    cost, warning = calculate_equivalent_cost_usd(usage, backend.model)
    assert cost == pytest.approx(0.002215)
    assert warning is None


def test_unknown_well_formed_events_do_not_downgrade_complete_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(output, {"type": "future.event", "data": {"value": 1}}, _completed_usage())

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "complete"
    assert usage.warnings == ()


def test_recovered_top_level_error_trusts_official_completed_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "error", "message": "Reconnecting... 1/5"},
        _completed_usage(),
    )
    backend = CodexBackend(model="gpt-5.6-sol")

    usage = backend.parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "complete"
    cost, warning = calculate_equivalent_cost_usd(usage, backend.model)
    assert cost == pytest.approx(0.002215)
    assert warning is None


def test_model_reroute_fails_closed_instead_of_pricing_requested_model(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "item.completed",
            "item": {
                "type": "error",
                "message": "model rerouted: gpt-5.6-sol -> gpt-5.2 (HighRiskCyberActivity)",
            },
        },
        _completed_usage(),
    )
    backend = CodexBackend(model="gpt-5.6-sol")

    usage = backend.parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert any("rerouted model" in warning for warning in usage.warnings)
    assert calculate_equivalent_cost_usd(usage, backend.model) == (
        None,
        "aggregate token usage is incomplete",
    )


@pytest.mark.parametrize(
    ("event_type", "item_type"),
    [
        ("item.started", "reasoning"),
        ("item.updated", "command_execution"),
        ("item.completed", "agent_message"),
    ],
)
def test_native_item_lifecycle_proves_model_work_without_terminal_usage(tmp_path, event_type, item_type):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": event_type, "item": {"id": "item-1", "type": item_type}},
        {"type": "turn.failed", "error": {"message": "connection lost"}},
    )

    assert CodexBackend().retry_may_duplicate_model_work(str(output)) is True


def test_ambiguous_failed_turn_without_item_activity_is_retry_unsafe(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "error", "message": "connection lost"},
        {"type": "turn.failed", "error": {"message": "connection lost"}},
    )

    assert CodexBackend().retry_may_duplicate_model_work(str(output)) is True


def test_stream_that_never_started_a_turn_remains_retry_safe(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "error", "message": "failed to load local configuration"},
    )

    assert CodexBackend().retry_may_duplicate_model_work(str(output)) is False
    assert CodexBackend().retry_may_duplicate_model_work(str(tmp_path / "missing.jsonl")) is False


def test_damaged_usage_limit_failure_is_not_assumed_safe_to_retry(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "error"},
        {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}},
    )

    assert CodexBackend().retry_may_duplicate_model_work(str(output)) is True


def test_multi_agent_activity_makes_parent_terminal_only_a_lower_bound(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "sender_thread_id": "parent",
                "receiver_thread_ids": ["child"],
                "status": "completed",
            },
        },
        _completed_usage(),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert any("covers only the parent thread" in warning for warning in usage.warnings)


def test_complete_child_audit_aggregates_parent_and_child_native_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "sender_thread_id": "parent",
                "receiver_thread_ids": ["child"],
                "status": "completed",
            },
        },
        _completed_usage(),
        _child_audit(),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=280, output_tokens=70)

    assert usage.status == "complete"
    assert usage.input_tokens == 280
    assert usage.cache_read_input_tokens == 200
    assert usage.cache_write_input_tokens == 25
    assert usage.output_tokens == 70
    assert usage.reasoning_output_tokens == 29
    assert usage.model_requests == 2
    assert len(usage.requests) == 2
    assert [request.resolved_model for request in usage.requests] == ["gpt-5.6-sol", "gpt-5.6-sol"]
    assert [request.provider for request in usage.requests] == ["openai", "openai"]
    assert usage.sources == (
        "codex_cli_turn_completed",
        "codex_rollout_child_token_count",
    )
    assert usage.warnings == ()


@pytest.mark.parametrize("version", (3, 4))
def test_legacy_child_usage_versions_remain_readable(version, tmp_path):
    output = tmp_path / "output.jsonl"
    legacy_audit = _child_audit()
    legacy_audit["version"] = version
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        legacy_audit,
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=280, output_tokens=70)

    assert usage.status == "complete"
    assert (usage.input_tokens, usage.output_tokens) == (280, 70)


def test_v3_prices_two_large_requests_individually_instead_of_one_aggregate_tier(tmp_path):
    output = tmp_path / "output.jsonl"
    requests = [
        _audit_request(
            input_tokens=200_000,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
        ),
        _audit_request(
            input_tokens=200_000,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
        ),
    ]
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(
            input_tokens=400_000,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
        ),
        _child_audit(child_count=0, requests=requests),
    )
    backend = CodexBackend(model="gpt-5.6-sol")

    usage = backend.parse_usage(str(output), input_tokens=400_000, output_tokens=0)
    cost, warning = calculate_equivalent_cost_usd(usage, backend.model)

    assert usage.status == "complete"
    assert usage.model_requests == 2
    assert [request.input_tokens for request in usage.requests] == [200_000, 200_000]
    assert cost == pytest.approx(2.0)
    assert warning is None


def test_v3_request_total_mismatch_discards_per_request_accounting(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(
            input_tokens=400_000,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
        ),
        _child_audit(
            child_count=0,
            requests=[
                _audit_request(
                    input_tokens=399_999,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    output_tokens=0,
                    reasoning_output_tokens=0,
                )
            ],
        ),
    )
    backend = CodexBackend(model="gpt-5.6-sol")

    usage = backend.parse_usage(str(output), input_tokens=400_000, output_tokens=0)
    cost, warning = calculate_equivalent_cost_usd(usage, backend.model)

    assert usage.status == "lower_bound"
    assert usage.model_requests is None
    assert usage.requests == ()
    assert any("does not match terminal and child aggregate totals" in item for item in usage.warnings)
    assert cost is None
    assert warning == "aggregate token usage is incomplete"


def test_v3_invalid_request_metadata_fails_closed(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        _child_audit(
            child_count=0,
            requests=[
                _audit_request(
                    input_tokens=240,
                    cached_input_tokens=180,
                    cache_write_input_tokens=20,
                    output_tokens=60,
                    reasoning_output_tokens=25,
                    model=None,
                )
            ],
        ),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert usage.model_requests is None
    assert usage.requests == ()
    assert any("invalid per-request usage" in warning for warning in usage.warnings)


def test_incomplete_child_audit_retains_known_child_delta_as_lower_bound(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        _child_audit(
            complete=False,
            warning_codes=["child_lifecycle_invalid"],
        ),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=280, output_tokens=70)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (280, 70)
    assert usage.cache_read_input_tokens == 200
    assert usage.cache_write_input_tokens == 25
    assert usage.reasoning_output_tokens == 29
    assert usage.model_requests is None
    assert usage.requests == ()
    assert any("child_lifecycle_invalid" in warning for warning in usage.warnings)


def test_unsupported_service_tier_never_uses_standard_public_price(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        _child_audit(
            complete=False,
            warning_codes=["unsupported_service_tier"],
        ),
    )
    backend = CodexBackend(model="gpt-5.6-sol")

    usage = backend.parse_usage(str(output), input_tokens=280, output_tokens=70)

    assert usage.status == "lower_bound"
    assert calculate_equivalent_cost_usd(usage, backend.model) == (
        None,
        "aggregate token usage is incomplete",
    )


def test_invalid_child_audit_usage_never_changes_parent_totals(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        _child_audit(cached_input_tokens=41),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert usage.sources == ("codex_cli_turn_completed",)
    assert any("invalid aggregate usage" in warning for warning in usage.warnings)


def test_multiple_child_audits_never_select_arbitrary_totals(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        _child_audit(),
        _child_audit(
            input_tokens=4_000,
            cached_input_tokens=2_000,
            output_tokens=1_000,
            reasoning_output_tokens=400,
        ),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert usage.sources == ("codex_cli_turn_completed",)
    assert any("ignoring ambiguous child totals" in warning for warning in usage.warnings)


def test_audit_for_another_root_never_changes_parent_totals(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
        _child_audit(root_thread_id="another-root"),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert usage.sources == ("codex_cli_turn_completed",)
    assert any("does not match" in warning for warning in usage.warnings)


def test_started_but_missing_child_audit_is_a_lower_bound_even_without_visible_collab(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "tlaps.codex_child_usage.started", "version": CODEX_CHILD_USAGE_VERSION},
        {"type": "thread.started", "thread_id": "parent"},
        _completed_usage(),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert any("did not finish" in warning for warning in usage.warnings)


def test_child_native_usage_makes_failed_launch_unsafe_to_retry(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "thread.started", "thread_id": "parent"},
        {"type": "turn.started"},
        {"type": "turn.failed", "error": {"message": "connection lost"}},
        _child_audit(),
    )

    backend = CodexBackend()
    usage = backend.parse_usage(str(output), input_tokens=0, output_tokens=0)

    assert backend.retry_may_duplicate_model_work(str(output)) is True
    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (40, 10)
    assert usage.cache_read_input_tokens == 20
    assert usage.cache_write_input_tokens == 5
    assert usage.reasoning_output_tokens == 4
    assert usage.sources == ("codex_rollout_child_token_count",)
    assert any("primary-thread usage is unavailable" in warning for warning in usage.warnings)


def test_native_stream_lag_warning_downgrades_terminal_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "item.completed",
            "item": {
                "id": "item-warning",
                "type": "error",
                "message": "in-process app-server event stream lagged; dropped 133 events",
            },
        },
        _completed_usage(),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert any("dropped JSONL events" in warning for warning in usage.warnings)


def test_native_stream_lag_makes_failed_launch_unsafe_to_retry(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {
            "type": "item.completed",
            "item": {
                "id": "item-warning",
                "type": "error",
                "message": "in-process app-server event stream lagged; dropped 3 events",
            },
        },
        {"type": "turn.failed", "error": {"message": "connection lost"}},
    )
    backend = CodexBackend()

    usage = backend.parse_usage(str(output), input_tokens=0, output_tokens=0)

    assert backend.retry_may_duplicate_model_work(str(output)) is True
    assert usage.status == "unavailable"
    assert any("dropped JSONL events" in warning for warning in usage.warnings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_tokens", None),
        ("input_tokens", True),
        ("input_tokens", "240"),
        ("input_tokens", 2.5),
        ("input_tokens", -1),
        ("output_tokens", None),
        ("output_tokens", False),
        ("output_tokens", "60"),
        ("output_tokens", 1.5),
        ("output_tokens", -1),
    ],
)
def test_invalid_core_token_field_makes_usage_unavailable(tmp_path, field, value):
    output = tmp_path / "output.jsonl"
    _write_jsonl(output, _completed_usage(**{field: value}))

    usage = CodexBackend().parse_usage(str(output), input_tokens=0, output_tokens=0)

    assert usage.status == "unavailable"
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert any("invalid core fields" in warning for warning in usage.warnings)


def test_missing_optional_subsets_retain_core_totals_as_incomplete(tmp_path):
    output = tmp_path / "output.jsonl"
    terminal = _completed_usage()
    del terminal["usage"]["cached_input_tokens"]  # type: ignore[index]
    del terminal["usage"]["cache_write_input_tokens"]  # type: ignore[index]
    del terminal["usage"]["reasoning_output_tokens"]  # type: ignore[index]
    _write_jsonl(output, terminal)

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "incomplete"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert usage.cache_read_input_tokens is None
    assert usage.cache_write_input_tokens is None
    assert usage.reasoning_output_tokens is None
    assert any("missing cached_input_tokens" in warning for warning in usage.warnings)
    assert any("missing cache_write_input_tokens" in warning for warning in usage.warnings)
    assert any("missing reasoning_output_tokens" in warning for warning in usage.warnings)


def test_impossible_optional_subsets_are_dropped_and_flagged(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        _completed_usage(
            cached_input_tokens=200,
            cache_write_input_tokens=41,
            reasoning_output_tokens=61,
        ),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "incomplete"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert usage.cache_read_input_tokens is None
    assert usage.cache_write_input_tokens is None
    assert usage.reasoning_output_tokens is None
    assert any("cache read and write input tokens exceed" in warning for warning in usage.warnings)
    assert any("reasoning output tokens exceed" in warning for warning in usage.warnings)


def test_all_zero_terminal_is_not_treated_as_explicit_free_usage(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        _completed_usage(
            input_tokens=0,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=0,
            reasoning_output_tokens=0,
        ),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=0, output_tokens=0)

    assert usage.status == "unavailable"
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert any("all-zero" in warning for warning in usage.warnings)


def test_failed_or_truncated_turn_without_terminal_usage_is_unavailable(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "item.completed", "item": {"type": "agent_message", "text": "Partial"}},
        {"type": "turn.failed", "error": {"message": "connection lost"}},
    )

    transcript, input_tokens, output_tokens = CodexBackend().parse_output(str(output))
    usage = CodexBackend().parse_usage(str(output), input_tokens=input_tokens, output_tokens=output_tokens)

    assert transcript == "[AGENT] Partial\n"
    assert (input_tokens, output_tokens) == (0, 0)
    assert usage.status == "unavailable"
    assert usage.input_tokens is None
    assert any("failed before terminal usage" in warning for warning in usage.warnings)


def test_malformed_line_preserves_terminal_totals_only_as_lower_bound(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(output, "not-json", _completed_usage())

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert any("malformed nonempty line" in warning for warning in usage.warnings)


def test_multiple_terminal_aggregates_use_last_without_summing(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        _completed_usage(input_tokens=100, cached_input_tokens=50, output_tokens=20, reasoning_output_tokens=5),
        _completed_usage(input_tokens=240, cached_input_tokens=180, output_tokens=60, reasoning_output_tokens=25),
    )
    backend = CodexBackend()

    _transcript, input_tokens, output_tokens = backend.parse_output(str(output))
    usage = backend.parse_usage(str(output), input_tokens=input_tokens, output_tokens=output_tokens)

    assert (input_tokens, output_tokens) == (240, 60)
    assert usage.status == "lower_bound"
    assert usage.input_tokens == 240
    assert any("multiple turn.completed" in warning for warning in usage.warnings)


def test_failed_and_completed_lifecycle_is_conservatively_a_lower_bound(tmp_path):
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        {"type": "turn.failed", "error": {"message": "first failure"}},
        _completed_usage(),
    )

    usage = CodexBackend().parse_usage(str(output), input_tokens=240, output_tokens=60)

    assert usage.status == "lower_bound"
    assert (usage.input_tokens, usage.output_tokens) == (240, 60)
    assert any("both failed and completed" in warning for warning in usage.warnings)


def test_missing_jsonl_file_is_unavailable(tmp_path):
    missing = tmp_path / "missing.jsonl"
    backend = CodexBackend()

    transcript, input_tokens, output_tokens = backend.parse_output(str(missing))
    usage = backend.parse_usage(str(missing), input_tokens=input_tokens, output_tokens=output_tokens)

    assert transcript == ""
    assert (input_tokens, output_tokens) == (0, 0)
    assert usage.status == "unavailable"
    assert any("JSONL output unavailable" in warning for warning in usage.warnings)


def test_codex_cli_install_uses_latest_release():
    script = Path("docker/install-scripts/install-codex.sh").read_text()

    assert "npm install -g @openai/codex --cache" in script


def test_codex_command_wraps_native_multi_agent_execution_without_disabling_it():
    command = CodexBackend(model="gpt-test").build_command("/workspace", "/result")

    assert command[:6] == [
        "python3",
        "/opt/codex_usage_wrapper.py",
        "--proof-check-workspace",
        "/workspace",
        "--",
        "codex",
    ]
    overrides = {command[index + 1] for index, value in enumerate(command[:-1]) if value == "-c"}
    assert not any("multi_agent" in override or "fanout" in override for override in overrides)

    dockerfile = Path("docker/base.Dockerfile").read_text()
    assert "COPY src/evaluator/backends/codex_usage_wrapper.py /opt/codex_usage_wrapper.py" in dockerfile


def test_codex_local_command_uses_the_installed_usage_wrapper(tmp_path):
    command = CodexBackend(model="gpt-test").build_command(str(tmp_path), str(tmp_path / "result"))

    assert Path(command[1]).resolve() == Path("src/evaluator/backends/codex_usage_wrapper.py").resolve()
    assert command[2:6] == ["--proof-check-workspace", str(tmp_path), "--", "codex"]
    completed = subprocess.run(command[:2] + ["--help"], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr


def test_codex_last_message_is_isolated_across_retries():
    assert CodexBackend().attempt_output_files() == ("codex_last_message.txt",)

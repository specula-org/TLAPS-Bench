"""termination.classify — tag a run as INFRA_ERROR vs OK.

A FAIL is only a capability signal if the agent made a genuine attempt. The
codex rule reads the agent's event stream: a run that ends on a terminal
``turn.failed`` (or errors without ever completing a turn) was cut short by
infrastructure — corrupted/refused request, dropped stream, server overload —
and is tagged INFRA_ERROR; a run that ends with ``turn.completed`` is OK
(genuine, even if its proof didn't verify).

Run: PYTHONPATH=src python3 -m pytest tests/evaluator/test_termination.py
"""

import json
import os

import pytest

from evaluator.backends import get_backend
from evaluator.backends.agentic import AgenticBackend
from evaluator.termination import (
    INFRA_RULES,
    TerminationContext,
    TerminationReason,
    agent_startup_failure,
    classify,
    claude_code_result_error,
    codex_single_turn_contract_error,
    codex_turn_failed,
    copilot_session_error,
    cursor_result_error,
    is_wall_clock_timeout,
    litellm_completion_error,
    one_shot_result_error,
    pi_run_failed,
    startup_error_snippet,
)

# codex stream cut short by a corrupted/refused request (no turn.completed).
INFRA_STREAM = [
    {"type": "thread.started", "thread_id": "t1"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i0", "type": "command_execution"}},
    {"type": "error", "message": '{"type":"error","error":{"type":"invalid_request_error"}}'},
    {"type": "turn.failed", "error": {"message": "invalid_request_error"}},
]

# codex stream that ran to a normal stop (proof may still have failed grading).
GENUINE_STREAM = [
    {"type": "thread.started", "thread_id": "t2"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "couldn't finish"}},
    {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}},
]

# transient error mid-run, then recovered and completed → still OK.
RECOVERED_STREAM = [
    {"type": "turn.started"},
    {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected before completion)"},
    {"type": "item.completed", "item": {"id": "i0", "type": "agent_message"}},
    {"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 5}},
]

# stream truncated after errors with no terminal turn event (killed mid-turn).
ERRORED_NO_TURN_STREAM = [
    {"type": "turn.started"},
    {"type": "error", "message": "stream disconnected before completion"},
]


def _write_jsonl(path, events):
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return str(path)


def _ctx(path, backend="codex", agent_exit=None, error="", approach=None, provider=None):
    if approach is None:
        approach = "one_shot" if backend.endswith("_oneshot") else "agentic"
    if provider is None and approach == "one_shot":
        provider = backend.removesuffix("_oneshot")
    validator = (
        get_backend(backend).validate_request_audit if approach == "one_shot" and backend.endswith("_oneshot") else None
    )
    return TerminationContext(
        backend=backend,
        jsonl_path=path,
        approach=approach,
        provider=provider,
        request_audit_validator=validator,
        agent_exit=agent_exit,
        error=error,
    )


def _strict_audit(provider, requests=1, contract_ok=True, completed_responses=0, **evidence):
    request_url_sha256 = "canonical-url"
    audit = {
        "provider": provider,
        "model_requests": requests,
        "request_attempts": requests,
        "blocked_requests": 0,
        "system_prompt_present": False,
        "tools_present": False,
        "retries_enabled": False,
        "audit_scope": "wire" if provider == "copilot" else "adapter",
        "contract_ok": contract_ok,
    }
    if provider == "copilot":
        audit.update(
            retries_enabled=True,
            retry_scope="incomplete_response",
            max_inference_attempts=6,
            logical_agent_turns=int(requests > 0),
            completed_responses=completed_responses,
            wire_audited=True,
            inference_requests=requests,
            inference_attempts=requests,
            deadline_blocked_requests=0,
            unknown_requests=0,
            system_removed=requests > 0,
            tools_removed=requests > 0,
            inference_request_details=[
                {
                    "attempt": attempt,
                    "endpoint": "/responses",
                    "request_url_sha256": request_url_sha256,
                    "request_sha256": "canonical-request",
                    "stream_completed": False,
                }
                for attempt in range(1, requests + 1)
            ],
        )
        if requests > 0:
            audit.update(
                endpoint="/responses",
                request_url_sha256=request_url_sha256,
                request_sha256="canonical-request",
            )
    else:
        audit.update(
            wire_audited=False,
            litellm_completion_invocations=requests,
            litellm_retries_disabled=True,
            system_supplied=False,
            tools_supplied=False,
        )
    audit.update(evidence)
    return audit


def _pi_message_end(stop_reason="stop", *, error_message=None):
    message = {
        "role": "assistant",
        "content": [],
        "provider": "openai",
        "model": "gpt-test",
        "api": "openai-responses",
        "stopReason": stop_reason,
    }
    if error_message is not None:
        message["errorMessage"] = error_message
    return {"type": "message_end", "message": message}


def test_turn_failed_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "infra.jsonl", INFRA_STREAM)
    assert classify(_ctx(p)) == TerminationReason.INFRA_ERROR


def test_turn_completed_is_ok(tmp_path):
    p = _write_jsonl(tmp_path / "genuine.jsonl", GENUINE_STREAM)
    assert classify(_ctx(p)) == TerminationReason.OK


def test_codex_single_turn_uses_codex_terminal_contract(tmp_path):
    audit_start = {"type": "tlaps.codex_child_usage.started", "version": 5}
    audit = {
        "type": "tlaps.codex_child_usage",
        "version": 5,
        "root_thread_id": "t2",
        "child_count": 0,
        "complete": True,
        "warning_codes": [],
        "requests": [{"input_tokens": 100, "output_tokens": 10}],
        "tool_calls": {
            "total": 0,
            "tlaps": 0,
            "tlc": 0,
            "apalache": 0,
            "other": 0,
            "available": True,
            "complete": True,
            "is_lower_bound": False,
            "warnings": [],
        },
    }
    failed = _write_jsonl(tmp_path / "single-turn-infra.jsonl", [audit_start, *INFRA_STREAM, audit])
    completed = _write_jsonl(tmp_path / "single-turn-genuine.jsonl", [audit_start, *GENUINE_STREAM, audit])

    assert classify(_ctx(failed, backend="codex_single_turn", approach="single_turn_tool_free")) == (
        TerminationReason.INFRA_ERROR
    )
    assert classify(_ctx(completed, backend="codex_single_turn", approach="single_turn_tool_free")) == (
        TerminationReason.OK
    )


def test_codex_single_turn_contract_excludes_multiple_model_requests(tmp_path):
    events = [
        {"type": "tlaps.codex_child_usage.started", "version": 5},
        *GENUINE_STREAM,
        {
            "type": "tlaps.codex_child_usage",
            "version": 5,
            "root_thread_id": "t2",
            "child_count": 0,
            "complete": True,
            "warning_codes": [],
            "requests": [{"input_tokens": 50}, {"input_tokens": 50}],
            "tool_calls": {
                "total": 0,
                "tlaps": 0,
                "tlc": 0,
                "apalache": 0,
                "other": 0,
                "available": True,
                "complete": True,
                "is_lower_bound": False,
                "warnings": [],
            },
        },
    ]
    path = _write_jsonl(tmp_path / "single-turn-retried-request.jsonl", events)
    ctx = _ctx(path, backend="codex_single_turn", approach="single_turn_tool_free")

    assert codex_single_turn_contract_error(ctx) == TerminationReason.INFRA_ERROR
    assert classify(ctx) == TerminationReason.INFRA_ERROR


def test_recovered_midrun_error_is_ok(tmp_path):
    p = _write_jsonl(tmp_path / "recovered.jsonl", RECOVERED_STREAM)
    assert classify(_ctx(p)) == TerminationReason.OK


def test_errored_without_completing_a_turn_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "killed.jsonl", ERRORED_NO_TURN_STREAM)
    assert classify(_ctx(p)) == TerminationReason.INFRA_ERROR


def test_codex_wrapper_marker_does_not_hide_nonzero_startup_failure(tmp_path):
    path = _write_jsonl(
        tmp_path / "codex-wrapper-startup.jsonl",
        [{"type": "tlaps.codex_child_usage.started", "version": 1}],
    )

    assert classify(_ctx(path, agent_exit=127)) == TerminationReason.INFRA_ERROR


def test_codex_nonempty_stream_without_terminal_is_infra_even_after_zero_exit(tmp_path):
    path = _write_jsonl(
        tmp_path / "codex-truncated.jsonl",
        [
            {"type": "tlaps.codex_child_usage.started", "version": 1},
            {"type": "thread.started", "thread_id": "thread-1"},
        ],
    )

    assert classify(_ctx(path, agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_codex_empty_or_missing_stream_is_infra_even_after_zero_exit(tmp_path):
    empty = tmp_path / "codex-empty.jsonl"
    empty.write_text("")

    assert classify(_ctx(str(empty), agent_exit=0)) == TerminationReason.INFRA_ERROR
    assert classify(_ctx(str(tmp_path / "codex-missing.jsonl"), agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_rule_only_applies_to_its_backend(tmp_path):
    # The codex rule keys off codex's event vocabulary and must abstain for any
    # other backend; a backend with no rule of its own classifies OK.
    p = _write_jsonl(tmp_path / "infra.jsonl", INFRA_STREAM)
    assert codex_turn_failed(_ctx(p, backend="claude_code")) is None
    assert classify(_ctx(p, backend="custom")) == TerminationReason.OK


def test_litellm_completion_error_is_infra(tmp_path):
    path = _write_jsonl(
        tmp_path / "litellm-error.jsonl",
        [
            {"type": "error", "message": "reasoning effort is unsupported for this model", "iteration": 1},
            {"type": "usage", "input_tokens": 0, "output_tokens": 0},
        ],
    )

    assert classify(_ctx(path, backend="litellm", agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_litellm_response_after_error_is_ok(tmp_path):
    path = _write_jsonl(
        tmp_path / "litellm-recovered.jsonl",
        [
            {"type": "error", "message": "transient provider error", "iteration": 1},
            {"type": "response", "text": "recovered", "iteration": 2},
            {"type": "usage", "input_tokens": 10, "output_tokens": 2},
        ],
    )

    assert litellm_completion_error(_ctx(path, backend="litellm")) is None
    assert classify(_ctx(path, backend="litellm")) == TerminationReason.OK


def test_pi_session_header_only_startup_failure_is_infra(tmp_path):
    path = _write_jsonl(
        tmp_path / "pi-startup.jsonl",
        [{"type": "session", "version": 3, "id": "session-1"}],
    )

    assert classify(_ctx(path, backend="pi", agent_exit=1)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize("stop_reason", ["error", "aborted"])
def test_pi_settled_terminal_error_is_infra_even_with_zero_exit(tmp_path, stop_reason):
    path = _write_jsonl(
        tmp_path / f"pi-{stop_reason}.jsonl",
        [
            {"type": "session", "version": 3, "id": "session-1"},
            {"type": "agent_start"},
            _pi_message_end(stop_reason, error_message="provider request failed"),
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    )

    assert classify(_ctx(path, backend="pi", agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_pi_recovered_error_uses_final_assistant_outcome(tmp_path):
    path = _write_jsonl(
        tmp_path / "pi-recovered.jsonl",
        [
            {"type": "session", "version": 3, "id": "session-1"},
            {"type": "agent_start"},
            _pi_message_end("error", error_message="transient provider failure"),
            {"type": "agent_end", "messages": [], "willRetry": True},
            {"type": "agent_start"},
            _pi_message_end("stop"),
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    )

    assert pi_run_failed(_ctx(path, backend="pi", agent_exit=0)) is None
    assert classify(_ctx(path, backend="pi", agent_exit=0)) == TerminationReason.OK


def test_pi_success_requires_agent_settled(tmp_path):
    events = [
        {"type": "session", "version": 3, "id": "session-1"},
        {"type": "agent_start"},
        _pi_message_end("stop"),
        {"type": "agent_end", "messages": [], "willRetry": False},
    ]
    truncated = _write_jsonl(tmp_path / "pi-truncated.jsonl", events)
    settled = _write_jsonl(tmp_path / "pi-settled.jsonl", [*events, {"type": "agent_settled"}])

    assert classify(_ctx(truncated, backend="pi", agent_exit=0)) == TerminationReason.INFRA_ERROR
    assert classify(_ctx(settled, backend="pi", agent_exit=0)) == TerminationReason.OK


def test_pi_nonzero_exit_and_activity_after_settlement_are_infra(tmp_path):
    clean_events = [
        {"type": "session", "version": 3, "id": "session-1"},
        {"type": "agent_start"},
        _pi_message_end("stop"),
        {"type": "agent_end", "messages": [], "willRetry": False},
        {"type": "agent_settled"},
    ]
    nonzero = _write_jsonl(tmp_path / "pi-nonzero.jsonl", clean_events)
    trailing = _write_jsonl(tmp_path / "pi-trailing.jsonl", [*clean_events, {"type": "agent_start"}])

    assert classify(_ctx(nonzero, backend="pi", agent_exit=1)) == TerminationReason.INFRA_ERROR
    assert classify(_ctx(trailing, backend="pi", agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_pi_second_lifecycle_after_settlement_stays_infra_after_another_settlement(tmp_path):
    path = _write_jsonl(
        tmp_path / "pi-reopened.jsonl",
        [
            {"type": "session", "version": 3, "id": "session-1"},
            _pi_message_end("stop"),
            {"type": "agent_settled"},
            {"type": "agent_start"},
            _pi_message_end("stop"),
            {"type": "agent_settled"},
        ],
    )

    assert classify(_ctx(path, backend="pi", agent_exit=0)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize("stop_reason", [None, "", "future_reason"])
def test_pi_unknown_final_stop_reason_is_infra(tmp_path, stop_reason):
    path = _write_jsonl(
        tmp_path / "pi-invalid-terminal.jsonl",
        [_pi_message_end(stop_reason), {"type": "agent_settled"}],
    )

    assert classify(_ctx(path, backend="pi", agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_pi_malformed_stream_is_infra_even_with_a_later_terminal(tmp_path):
    path = tmp_path / "pi-malformed.jsonl"
    path.write_text(
        "\n".join(
            [
                "{not-json",
                json.dumps(_pi_message_end("stop")),
                json.dumps({"type": "agent_settled"}),
            ]
        )
        + "\n"
    )

    assert classify(_ctx(str(path), backend="pi", agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_pi_rule_only_applies_to_pi(tmp_path):
    path = _write_jsonl(tmp_path / "pi-error.jsonl", [_pi_message_end("error"), {"type": "agent_settled"}])

    assert pi_run_failed(_ctx(path, backend="custom", agent_exit=0)) is None


def test_missing_stream_is_ok(tmp_path):
    # A backend with no strict stream contract must not crash or invent INFRA.
    assert classify(_ctx(str(tmp_path / "nope.jsonl"), backend="custom")) == TerminationReason.OK


# --- wall-clock timeout: a LIMIT, consistent across backends, never INFRA -----

# A SIGKILLed run leaves a truncated stream (no terminal turn/result) — exactly
# what each INFRA rule would otherwise read as a cut-off — plus the runner's
# agent_exit == -1 and "<backend> timeout after <N>s" error.
TRUNCATED_BY_BACKEND = {
    "codex": [{"type": "thread.started"}, {"type": "turn.started"}],
    "claude_code": [{"type": "system", "subtype": "init"}, {"type": "assistant", "message": {}}],
    "copilot": [{"type": "assistant.message", "data": {"content": "working"}}],
    "cursor": [{"type": "system", "subtype": "init"}, {"type": "assistant", "message": {}}],
    "pi": [{"type": "session", "version": 3, "id": "session-1"}, {"type": "agent_start"}],
}


def test_is_wall_clock_timeout_signal():
    ctx = TerminationContext(backend="codex", jsonl_path=None, agent_exit=-1, error="codex timeout after 7200s")
    assert is_wall_clock_timeout(ctx) is True
    # a non-timeout error, or a clean exit, is not a timeout
    assert is_wall_clock_timeout(TerminationContext("codex", None, agent_exit=1, error="")) is False
    assert (
        is_wall_clock_timeout(TerminationContext("codex", None, agent_exit=-1, error="provider usage limit")) is False
    )


def test_timeout_is_timeout_not_infra_for_every_backend(tmp_path):
    # Same wall-clock timeout, every backend → TIMEOUT (not INFRA, not OK) — the
    # truncated stream alone would read as a cut-off, but the timeout wins.
    for backend, stream in TRUNCATED_BY_BACKEND.items():
        p = _write_jsonl(tmp_path / f"{backend}.jsonl", stream)
        err = f"{backend} timeout after 7200s"
        verdict = classify(_ctx(p, backend=backend, agent_exit=-1, error=err))
        assert verdict == TerminationReason.TIMEOUT, f"{backend}: {verdict}"


def test_same_truncation_without_timeout_is_still_infra(tmp_path):
    # Without the timeout signal, a truncated stream is a genuine cut-off (crash /
    # dropped connection) → INFRA_ERROR. Asserts the timeout precheck is the only
    # thing reclassifying these.
    expected = {
        "codex": TerminationReason.INFRA_ERROR,
        "claude_code": TerminationReason.INFRA_ERROR,
        "copilot": TerminationReason.INFRA_ERROR,
        "cursor": TerminationReason.INFRA_ERROR,
        "pi": TerminationReason.INFRA_ERROR,
    }
    for backend, stream in TRUNCATED_BY_BACKEND.items():
        p = _write_jsonl(tmp_path / f"{backend}.jsonl", stream)
        assert classify(_ctx(p, backend=backend)) == expected[backend], backend


def test_registry_is_the_extension_point():
    # The interface contract: classify() runs INFRA_RULES in order.
    assert codex_turn_failed in INFRA_RULES
    assert codex_single_turn_contract_error in INFRA_RULES
    assert claude_code_result_error in INFRA_RULES
    assert copilot_session_error in INFRA_RULES
    assert cursor_result_error in INFRA_RULES
    assert litellm_completion_error in INFRA_RULES
    assert pi_run_failed in INFRA_RULES
    assert one_shot_result_error in INFRA_RULES
    assert agent_startup_failure in INFRA_RULES


def test_one_shot_provider_error_is_infra(tmp_path):
    stream = [
        {"type": "request_audit", **_strict_audit("copilot", requests=0)},
        {"type": "error", "message": "authentication failed"},
        {"type": "result", "status": "error", "model_requests": 0},
    ]
    path = _write_jsonl(tmp_path / "oneshot-error.jsonl", stream)
    assert classify(_ctx(path, backend="copilot_oneshot", agent_exit=1)) == TerminationReason.INFRA_ERROR


def test_one_shot_provider_deadline_is_timeout(tmp_path):
    stream = [
        {"type": "usage", "input_tokens": 10, "output_tokens": 4, "model_requests": 1},
        {
            "type": "request_audit",
            **_strict_audit("copilot"),
            "wire_audited": True,
            "inference_requests": 1,
            "inference_attempts": 1,
            "blocked_requests": 0,
            "system_removed": True,
            "tools_removed": True,
        },
        {"type": "error", "message": "Copilot request timed out after 37s"},
        {"type": "result", "status": "timeout", "model_requests": 1},
    ]
    path = _write_jsonl(tmp_path / "oneshot-timeout.jsonl", stream)

    assert classify(_ctx(path, backend="copilot_oneshot", agent_exit=1)) == TerminationReason.TIMEOUT


def test_one_shot_response_before_provider_deadline_is_still_timeout(tmp_path):
    stream = [
        {"type": "response", "text": "COMPLETE RESPONSE BEFORE IDLE"},
        {
            "type": "request_audit",
            **_strict_audit("copilot", completed_responses=1),
            "wire_audited": True,
            "inference_requests": 1,
            "inference_attempts": 1,
            "blocked_requests": 0,
            "system_removed": True,
            "tools_removed": True,
        },
        {"type": "error", "message": "Copilot request timed out waiting for session idle"},
        {"type": "result", "status": "timeout", "model_requests": 1},
    ]
    path = _write_jsonl(tmp_path / "oneshot-response-before-timeout.jsonl", stream)

    assert classify(_ctx(path, backend="copilot_oneshot", agent_exit=1)) == TerminationReason.TIMEOUT


@pytest.mark.parametrize(
    ("provider", "requests", "contract_ok"),
    [("wrong", 1, True), ("copilot", 2, False), ("copilot", 1, False)],
)
def test_one_shot_provider_deadline_requires_valid_audit(tmp_path, provider, requests, contract_ok):
    stream = [
        {
            "type": "request_audit",
            **_strict_audit(provider, requests=requests, contract_ok=contract_ok),
            "wire_audited": True,
            "inference_requests": requests,
            "inference_attempts": requests,
            "blocked_requests": 0,
            "system_removed": True,
            "tools_removed": True,
        },
        {"type": "result", "status": "timeout", "model_requests": requests},
    ]
    path = _write_jsonl(tmp_path / f"oneshot-invalid-timeout-{provider}-{requests}.jsonl", stream)

    assert classify(_ctx(path, backend="copilot_oneshot", agent_exit=1)) == TerminationReason.INFRA_ERROR


def test_one_shot_deadline_before_request_is_still_timeout(tmp_path):
    stream = [
        {"type": "request_audit", **_strict_audit("copilot", requests=0)},
        {"type": "error", "message": "benchmark deadline reached during startup"},
        {"type": "result", "status": "timeout", "model_requests": 0},
    ]
    path = _write_jsonl(tmp_path / "oneshot-startup-timeout.jsonl", stream)

    assert classify(_ctx(path, backend="copilot_oneshot", agent_exit=1)) == TerminationReason.TIMEOUT


def test_one_shot_deadline_during_first_request_preparation_is_timeout(tmp_path):
    stream = [
        {
            "type": "request_audit",
            **_strict_audit(
                "copilot",
                requests=0,
                logical_agent_turns=1,
                deadline_closed=True,
                deadline_blocked_requests=1,
                requested_max_output_tokens=64_000,
            ),
        },
        {"type": "error", "message": "Copilot request reached benchmark deadline"},
        {"type": "result", "status": "timeout", "model_requests": 0},
    ]
    path = _write_jsonl(tmp_path / "oneshot-request-preparation-timeout.jsonl", stream)

    assert classify(_ctx(path, backend="copilot_oneshot", agent_exit=1)) == TerminationReason.TIMEOUT


def test_one_shot_clean_response_is_genuine(tmp_path):
    stream = [
        {"type": "response", "text": "not a complete module"},
        {"type": "usage", "input_tokens": 10, "output_tokens": 4, "model_requests": 1},
        {
            "type": "request_audit",
            **_strict_audit("litellm"),
            "litellm_completion_invocations": 1,
            "wire_audited": False,
            "litellm_retries_disabled": True,
            "system_supplied": False,
            "tools_supplied": False,
        },
        {"type": "result", "status": "success", "model_requests": 1},
    ]
    path = _write_jsonl(tmp_path / "oneshot-success.jsonl", stream)
    assert classify(_ctx(path, backend="litellm_oneshot")) == TerminationReason.OK


def test_one_shot_clean_copilot_response_is_genuine(tmp_path):
    stream = [
        {"type": "response", "text": "not a complete module"},
        {
            "type": "request_audit",
            **_strict_audit("copilot", completed_responses=1),
            "wire_audited": True,
            "inference_requests": 1,
            "inference_attempts": 1,
            "blocked_requests": 0,
            "system_removed": True,
            "tools_removed": True,
        },
        {"type": "result", "status": "success", "model_requests": 1},
    ]

    path = _write_jsonl(tmp_path / "copilot-oneshot-success.jsonl", stream)
    assert classify(_ctx(path, backend="copilot_oneshot")) == TerminationReason.OK


@pytest.mark.parametrize(
    "backend,audit",
    [
        (
            "litellm_oneshot",
            {
                **_strict_audit("litellm", contract_ok=True),
                "wire_audited": False,
                "litellm_completion_invocations": 1,
                "litellm_retries_disabled": True,
                "system_supplied": True,
                "tools_supplied": False,
            },
        ),
        (
            "copilot_oneshot",
            {
                **_strict_audit("copilot", contract_ok=True, completed_responses=1),
                "wire_audited": True,
                "inference_requests": 1,
                "inference_attempts": 1,
                "blocked_requests": 0,
                "system_removed": False,
                "tools_removed": True,
            },
        ),
    ],
)
def test_one_shot_context_audit_regression_is_infra(tmp_path, backend, audit):
    stream = [
        {"type": "response", "text": "not a complete module"},
        {"type": "request_audit", **audit},
        {"type": "result", "status": "success", "model_requests": 1},
    ]

    path = _write_jsonl(tmp_path / f"{backend}-context-regression.jsonl", stream)
    assert classify(_ctx(path, backend=backend)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize(
    ("backend", "field", "value"),
    [
        ("litellm_oneshot", "model_requests", True),
        ("litellm_oneshot", "request_attempts", 1.0),
        ("litellm_oneshot", "blocked_requests", False),
        ("litellm_oneshot", "litellm_completion_invocations", True),
        ("copilot_oneshot", "model_requests", 1.0),
        ("copilot_oneshot", "request_attempts", True),
        ("copilot_oneshot", "blocked_requests", 0.0),
        ("copilot_oneshot", "inference_requests", True),
        ("copilot_oneshot", "inference_attempts", 1.0),
        ("copilot_oneshot", "unknown_requests", False),
    ],
)
def test_one_shot_audit_counts_require_exact_integers(tmp_path, backend, field, value):
    provider = backend.removesuffix("_oneshot")
    audit = _strict_audit(provider, completed_responses=int(provider == "copilot"))
    audit[field] = value
    stream = [
        {"type": "response", "text": "candidate"},
        {"type": "request_audit", **audit},
        {"type": "result", "status": "success", "model_requests": 1},
    ]
    path = _write_jsonl(tmp_path / f"{backend}-{field}.jsonl", stream)

    assert classify(_ctx(path, backend=backend)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize("field", ["system_removed", "tools_removed"])
def test_copilot_zero_request_audit_requires_explicit_context_evidence(tmp_path, field):
    audit = _strict_audit("copilot", requests=0)
    audit.pop(field)
    stream = [
        {"type": "request_audit", **audit},
        {"type": "result", "status": "timeout", "model_requests": 0},
    ]
    path = _write_jsonl(tmp_path / f"copilot-missing-{field}.jsonl", stream)

    assert classify(_ctx(path, backend="copilot_oneshot")) == TerminationReason.INFRA_ERROR


def test_one_shot_truncated_stream_is_infra(tmp_path):
    path = _write_jsonl(tmp_path / "oneshot-truncated.jsonl", [{"type": "request_audit"}])
    assert classify(_ctx(path, backend="litellm_oneshot")) == TerminationReason.INFRA_ERROR


def test_one_shot_non_utf8_stream_fails_closed(tmp_path):
    path = tmp_path / "oneshot-invalid-utf8.jsonl"
    path.write_bytes(b'{"type":"response","text":"candidate"}\n\xff\n')

    assert classify(_ctx(str(path), backend="litellm_oneshot")) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize("contents", [None, "", "  \n", "not json\n", "[]\n", "null\n", '"text"\n'])
def test_one_shot_missing_or_corrupt_stream_fails_closed(tmp_path, contents):
    path = tmp_path / "invalid-one-shot.jsonl"
    if contents is not None:
        path.write_text(contents)

    ctx = TerminationContext(
        backend="custom-evaluator",
        jsonl_path=str(path),
        approach="one_shot",
        provider="litellm",
        agent_exit=0,
    )

    assert classify(ctx) == TerminationReason.INFRA_ERROR


def test_one_shot_rejects_junk_mixed_with_valid_contract(tmp_path):
    path = tmp_path / "mixed-one-shot.jsonl"
    valid_events = [
        {"type": "response", "text": "candidate"},
        {"type": "request_audit", **_strict_audit("litellm")},
        {"type": "result", "status": "success", "model_requests": 1},
    ]
    path.write_text("junk\n" + "".join(json.dumps(event) + "\n" for event in valid_events))

    ctx = TerminationContext(
        backend="custom-evaluator",
        jsonl_path=str(path),
        approach="one_shot",
        provider="litellm",
        agent_exit=0,
    )

    assert classify(ctx) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize("event_type", ["response", "request_audit", "result"])
def test_one_shot_duplicate_contract_event_is_infra(tmp_path, event_type):
    stream = [
        {"type": "response", "text": "not a complete module"},
        {
            "type": "request_audit",
            **_strict_audit("litellm"),
            "litellm_completion_invocations": 1,
            "wire_audited": False,
            "litellm_retries_disabled": True,
            "system_supplied": False,
            "tools_supplied": False,
        },
        {"type": "result", "status": "success", "model_requests": 1},
    ]
    stream.append(next(event.copy() for event in stream if event["type"] == event_type))

    path = _write_jsonl(tmp_path / f"oneshot-duplicate-{event_type}.jsonl", stream)
    assert classify(_ctx(path, backend="litellm_oneshot")) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize(
    "backend,audit,expected",
    [
        (
            "litellm_oneshot",
            {
                **_strict_audit("litellm", requests=2, contract_ok=False),
                "litellm_completion_invocations": 2,
                "wire_audited": False,
                "litellm_retries_disabled": True,
                "system_supplied": False,
                "tools_supplied": False,
            },
            TerminationReason.INFRA_ERROR,
        ),
        (
            "copilot_oneshot",
            {
                **_strict_audit("copilot", requests=2, completed_responses=1),
                "wire_audited": True,
                "inference_requests": 2,
                "inference_attempts": 2,
                "blocked_requests": 0,
            },
            TerminationReason.OK,
        ),
    ],
)
def test_one_shot_success_with_two_wire_requests_is_provider_specific(tmp_path, backend, audit, expected):
    stream = [
        {"type": "response", "text": "not a complete module"},
        {"type": "request_audit", **audit},
        {"type": "result", "status": "success", "model_requests": 2},
    ]

    path = _write_jsonl(tmp_path / f"{backend}-two-requests.jsonl", stream)
    assert classify(_ctx(path, backend=backend)) == expected


def test_copilot_retried_turn_rejects_second_complete_response(tmp_path):
    stream = [
        {"type": "response", "text": "first response"},
        {"type": "response", "text": "second response"},
        {
            "type": "request_audit",
            **_strict_audit("copilot", requests=2, completed_responses=1),
        },
        {"type": "result", "status": "success", "model_requests": 2},
    ]

    path = _write_jsonl(tmp_path / "copilot-two-responses.jsonl", stream)
    assert classify(_ctx(path, backend="copilot_oneshot")) == TerminationReason.INFRA_ERROR


def test_copilot_retried_provider_deadline_is_timeout(tmp_path):
    stream = [
        {
            "type": "request_audit",
            **_strict_audit("copilot", requests=2),
        },
        {"type": "error", "message": "Copilot request reached benchmark deadline"},
        {"type": "result", "status": "timeout", "model_requests": 2},
    ]

    path = _write_jsonl(tmp_path / "copilot-retried-timeout.jsonl", stream)
    assert classify(_ctx(path, backend="copilot_oneshot")) == TerminationReason.TIMEOUT


def test_copilot_native_retry_arriving_at_deadline_is_timeout(tmp_path):
    stream = [
        {
            "type": "request_audit",
            **_strict_audit(
                "copilot",
                requests=1,
                deadline_closed=True,
                deadline_blocked_requests=1,
            ),
        },
        {"type": "error", "message": "Copilot request reached benchmark deadline"},
        {"type": "result", "status": "timeout", "model_requests": 1},
    ]

    path = _write_jsonl(tmp_path / "copilot-native-retry-deadline.jsonl", stream)
    assert classify(_ctx(path, backend="copilot_oneshot")) == TerminationReason.TIMEOUT


# --- quota exhaustion: runner-owned, never produced by classify() -----------


def test_quota_exhausted_is_a_distinct_reason():
    # QUOTA_EXHAUSTED is its own category, distinct from OK/INFRA_ERROR/TIMEOUT.
    reasons = {TerminationReason.OK, TerminationReason.INFRA_ERROR, TerminationReason.TIMEOUT}
    assert TerminationReason.QUOTA_EXHAUSTED not in reasons


def test_classify_never_returns_quota_exhausted(tmp_path):
    # The runner sets QUOTA_EXHAUSTED directly (it owns the quota signal); no
    # classify() rule may spontaneously produce it. A quota-blocked run leaves a
    # no-work, truncated stream — classify() reads that as INFRA_ERROR/OK, never
    # QUOTA_EXHAUSTED — which is exactly why the runner tags it before classify().
    for backend, stream in TRUNCATED_BY_BACKEND.items():
        p = _write_jsonl(tmp_path / f"{backend}.jsonl", stream)
        assert classify(_ctx(p, backend=backend)) != TerminationReason.QUOTA_EXHAUSTED


# QUOTA_EXHAUSTED is the one reason the runner sets directly (not classify()), so
# it's only covered by driving run_single_benchmark. Both quota paths short-
# circuit before the AI agent / grader run, so stubbing the quota gate reaches
# them without a real backend, tlapm, or API key.


class _FakeBackend(AgenticBackend):
    name = "codex"

    def build_command(self, workspace, result_dir):
        return ["fake-agent"]

    def parse_output(self, jsonl_path):
        return ("", 0, 0)  # transcript, input_tokens, output_tokens

    def detect_quota_block(self, jsonl_path):
        return None


class _FakeMode:
    name = "proof-completion"

    def __init__(self, bench_dir):
        self._bench_dir = bench_dir

    def benchmark_dir(self):
        return self._bench_dir

    def get_dependencies(self, benchmark_path):
        return []

    def checker_binary_path(self):
        return "/bin/true"

    def build_prompt(self, basename, tlapm_path, tlapm_lib):
        return "prove it"


def _quota_work_item(tmp_path):
    from evaluator.runner import WorkItem

    bench_dir = tmp_path / "bench"
    bench_path = bench_dir / "Foo" / "Bar.tla"
    os.makedirs(bench_path.parent)
    bench_path.write_text("---- MODULE Bar ----\n====\n")
    return WorkItem(
        benchmark_path=str(bench_path),
        output_dir=str(tmp_path / "out"),
        timeout=10,
        check_timeout=10,
        backend=_FakeBackend(),  # ty:ignore[invalid-argument-type]
        mode=_FakeMode(str(bench_dir)),  # ty:ignore[invalid-argument-type]
        tlapm_path="/bin/true",
        tlapm_lib="",
        usage_script="dummy",  # enables the quota gate
        quota_max_waits=1,
    )


def test_runner_prerun_quota_skip_tags_quota_exhausted(tmp_path, monkeypatch):
    # Proactive gate gives up before the agent runs (max waits reached): the
    # early return must carry QUOTA_EXHAUSTED, not the seeded OK default.
    from evaluator import runner

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *a, **k: False)
    result = runner.run_single_benchmark(_quota_work_item(tmp_path))
    assert result["agent_exit"] == -3
    assert result["termination_reason"] == TerminationReason.QUOTA_EXHAUSTED


def test_runner_duringrun_quota_exhausted_tags_quota_exhausted(tmp_path, monkeypatch):
    # Agent runs, then the provider hard-caps us and the retry budget is spent:
    # run_with_quota_retry returns falsy -> quota_exhausted block (agent never
    # actually invoked, grading skipped).
    from evaluator import runner

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *a, **k: True)
    monkeypatch.setattr(runner.quota, "run_with_quota_retry", lambda run, block, **k: False)
    result = runner.run_single_benchmark(_quota_work_item(tmp_path))
    assert result["agent_exit"] == -3
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == TerminationReason.QUOTA_EXHAUSTED


# --- claude_code rule -------------------------------------------------------

# claude_code closes with a `result` event; subtype `success` vs `error_*`.
CC_SUCCESS = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"role": "assistant"}},
    {"type": "result", "subtype": "success", "is_error": False, "result": "done"},
]
CC_EXEC_ERROR = [
    {"type": "system", "subtype": "init"},
    {"type": "result", "subtype": "error_during_execution", "is_error": True},
]
CC_MAX_TURNS = [
    {"type": "system", "subtype": "init"},
    {"type": "result", "subtype": "error_max_turns", "is_error": True},
]
CC_TRUNCATED = [  # stream cut off before the terminal result event
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"role": "assistant"}},
]


def test_cc_success_is_ok(tmp_path):
    p = _write_jsonl(tmp_path / "ok.jsonl", CC_SUCCESS)
    assert classify(_ctx(p, backend="claude_code")) == TerminationReason.OK


def test_cc_exec_error_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "err.jsonl", CC_EXEC_ERROR)
    assert classify(_ctx(p, backend="claude_code")) == TerminationReason.INFRA_ERROR


def test_cc_max_turns_is_not_infra(tmp_path):
    # error_max_turns is a turn-budget LIMIT, not infrastructure — must NOT flag.
    p = _write_jsonl(tmp_path / "maxturns.jsonl", CC_MAX_TURNS)
    assert classify(_ctx(p, backend="claude_code")) == TerminationReason.OK


def test_cc_truncated_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "trunc.jsonl", CC_TRUNCATED)
    assert classify(_ctx(p, backend="claude_code")) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize(
    "activity",
    [
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "call-1"}]}},
        {"type": "system", "subtype": "task_notification"},
        {"type": "stream_event", "event": {"type": "message_start"}},
        {"type": "error", "message": "connection closed"},
    ],
)
@pytest.mark.parametrize("agent_exit", [0, 137])
def test_cc_activity_after_success_requires_another_result(tmp_path, activity, agent_exit):
    p = _write_jsonl(tmp_path / "unfinished-background.jsonl", [*CC_SUCCESS, activity])
    error = "container OOM killed (exit 137)" if agent_exit == 137 else ""
    assert classify(_ctx(p, backend="claude_code", agent_exit=agent_exit, error=error)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize(
    "terminal,expected",
    [
        (CC_SUCCESS[-1], TerminationReason.OK),
        (CC_MAX_TURNS[-1], TerminationReason.OK),
        (CC_EXEC_ERROR[-1], TerminationReason.INFRA_ERROR),
    ],
)
def test_cc_completed_background_sequence_uses_its_final_result(tmp_path, terminal, expected):
    events = [
        *CC_SUCCESS[:-1],
        {**CC_SUCCESS[-1], "session_id": "s1", "result_index": 0},
        {**CC_SUCCESS[-1], "session_id": "s1", "result_index": 1, "num_turns": 0},
        {"type": "system", "subtype": "task_notification", "session_id": "s1"},
        {"type": "assistant", "session_id": "s1", "message": {"role": "assistant"}},
        {**terminal, "session_id": "s1", "result_index": 2},
    ]
    p = _write_jsonl(tmp_path / "background.jsonl", events)
    assert classify(_ctx(p, backend="claude_code", agent_exit=int(terminal["is_error"]))) == expected


@pytest.mark.parametrize("tail", ['{"type":"result",', "[]\n"])
def test_cc_malformed_tail_cannot_reuse_an_earlier_success(tmp_path, tail):
    p = _write_jsonl(tmp_path / "malformed-background.jsonl", CC_SUCCESS)
    with open(p, "a") as stream:
        stream.write(tail)
    assert classify(_ctx(p, backend="claude_code")) == TerminationReason.INFRA_ERROR


def test_cc_runner_timeout_takes_precedence_over_unfinished_background_turn(tmp_path):
    p = _write_jsonl(tmp_path / "timeout-background.jsonl", [*CC_SUCCESS, *CC_TRUNCATED[1:]])
    ctx = _ctx(p, backend="claude_code", agent_exit=-1, error="claude_code timeout after 7200s")
    assert classify(ctx) == TerminationReason.TIMEOUT


def test_cc_rate_limit_telemetry_after_success_does_not_reopen_the_turn(tmp_path):
    p = _write_jsonl(tmp_path / "telemetry.jsonl", [*CC_SUCCESS, {"type": "rate_limit_event"}])
    assert classify(_ctx(p, backend="claude_code")) == TerminationReason.OK


def test_cc_rule_only_applies_to_claude_code(tmp_path):
    # codex stream through the claude rule must abstain.
    p = _write_jsonl(tmp_path / "infra.jsonl", INFRA_STREAM)
    assert claude_code_result_error(_ctx(p, backend="codex")) is None


# --- cursor rule (stream-json contract ends in one clean result) -------------

CURSOR_SUCCESS = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        "session_id": "s1",
    },
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "done",
        "session_id": "s1",
    },
]
CURSOR_TRUNCATED = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    {"type": "assistant", "message": {"role": "assistant", "content": []}, "session_id": "s1"},
]
CURSOR_ERROR = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    {"type": "error", "message": "stream disconnected", "session_id": "s1"},
]


def test_cursor_clean_terminal_success_is_ok(tmp_path):
    path = _write_jsonl(tmp_path / "cursor-success.jsonl", CURSOR_SUCCESS)
    assert classify(_ctx(path, backend="cursor", agent_exit=0)) == TerminationReason.OK


@pytest.mark.parametrize("stream", [CURSOR_TRUNCATED, CURSOR_ERROR])
def test_cursor_nonempty_stream_without_terminal_result_is_infra(tmp_path, stream):
    path = _write_jsonl(tmp_path / "cursor-incomplete.jsonl", stream)
    assert classify(_ctx(path, backend="cursor", agent_exit=1)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize(
    "terminal",
    [
        {"type": "result", "subtype": "error_during_execution", "is_error": True},
        {"type": "result", "subtype": "success", "is_error": True},
        {"type": "result", "subtype": "success"},
    ],
)
def test_cursor_error_or_malformed_terminal_result_is_infra(tmp_path, terminal):
    path = _write_jsonl(
        tmp_path / "cursor-bad-result.jsonl",
        [{"type": "system", "subtype": "init"}, terminal],
    )
    assert classify(_ctx(path, backend="cursor", agent_exit=1)) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize(
    "stream",
    [
        [*CURSOR_SUCCESS, {"type": "assistant", "message": {"content": []}}],
        [*CURSOR_SUCCESS, CURSOR_SUCCESS[-1]],
    ],
)
def test_cursor_result_must_be_unique_and_terminal(tmp_path, stream):
    path = _write_jsonl(tmp_path / "cursor-malformed-terminal.jsonl", stream)
    assert classify(_ctx(path, backend="cursor")) == TerminationReason.INFRA_ERROR


def test_cursor_malformed_event_stream_is_infra(tmp_path):
    path = tmp_path / "cursor-malformed-stream.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init"}),
                "not json",
                json.dumps(CURSOR_SUCCESS[-1]),
            ]
        )
    )
    assert classify(_ctx(str(path), backend="cursor")) == TerminationReason.INFRA_ERROR


@pytest.mark.parametrize("contents", ["", "not json\n"])
def test_cursor_empty_or_wholly_malformed_stream_is_infra_even_after_zero_exit(tmp_path, contents):
    path = tmp_path / "cursor-empty-or-malformed.jsonl"
    path.write_text(contents)
    assert classify(_ctx(str(path), backend="cursor", agent_exit=0)) == TerminationReason.INFRA_ERROR


def test_cursor_rule_only_applies_to_cursor(tmp_path):
    path = _write_jsonl(tmp_path / "cursor-truncated.jsonl", CURSOR_TRUNCATED)
    assert cursor_result_error(_ctx(path, backend="codex")) is None


# --- copilot rule (event vocabulary per Copilot SDK streaming-events docs) ---

# A clean run: per-tool failure is normal (tlapm rejecting a proof), and a
# terminal `result` with a non-zero exitCode can be a genuine proof failure.
CP_COMPLETED = [
    {"type": "assistant.message", "data": {"content": "hi"}},
    {"type": "tool.execution_complete", "data": {"result": {"success": False}}},
    {"type": "result", "exitCode": 1, "usage": {"premiumRequests": 1}},
]
CP_SESSION_ERROR = [  # dedicated infra error event (auth/quota/network)
    {"type": "assistant.message", "data": {"content": "hi"}},
    {"type": "session.error", "errorType": "quota", "message": "rate limited", "statusCode": 429},
]
CP_ABORT = [
    {"type": "assistant.message", "data": {"content": "hi"}},
    {"type": "abort"},
]
CP_SHUTDOWN_ERROR = [
    {"type": "session.shutdown", "data": {"shutdownType": "error", "errorReason": "stream closed"}},
]
CP_SHUTDOWN_OK = [
    {"type": "session.shutdown", "data": {"shutdownType": "routine"}},
]
CP_RECOVERED = [  # intermittent session.error, then recovered to a clean terminal
    {"type": "assistant.message", "data": {"content": "hi"}},
    {"type": "session.error", "errorType": "quota", "message": "transient 429"},
    {"type": "assistant.message", "data": {"content": "retrying"}},
    {"type": "result", "exitCode": 0, "usage": {"premiumRequests": 2}},
]
CP_ERROR_THEN_RESULT = [  # Copilot emits a result envelope after a fatal root error
    {"type": "assistant.message", "data": {"content": "working"}},
    {
        "type": "model.call_failure",
        "data": {"model": "gpt-5.6-sol", "source": "top_level", "errorMessage": "ETIMEDOUT"},
    },
    {"type": "assistant.turn_end", "data": {"turnId": "20"}},
    {
        "type": "session.error",
        "data": {"errorType": "query", "message": "Failed to get response from the AI model"},
    },
    {"type": "assistant.idle", "data": {}},
    {"type": "result", "exitCode": 1, "usage": {"premiumRequests": 0}},
]
CP_SUBAGENT_ERROR_THEN_RESULT = [
    {"type": "assistant.message", "data": {"content": "working"}},
    {
        "type": "session.error",
        "agentId": "call_rubber_duck",
        "data": {"errorType": "query", "message": "subagent ETIMEDOUT"},
    },
    {"type": "subagent.failed", "agentId": "call_rubber_duck", "data": {"error": "No response generated"}},
    {"type": "assistant.message", "data": {"content": "finished without the subagent"}},
    {"type": "assistant.turn_end", "data": {"turnId": "41"}},
    {"type": "result", "exitCode": 1, "usage": {"premiumRequests": 0}},
]
CP_TRUNCATED = [  # cut off before any terminal event
    {"type": "assistant.message", "data": {"content": "working"}},
    {"type": "tool.execution_start", "data": {}},
]


def test_copilot_completed_is_ok(tmp_path):
    p = _write_jsonl(tmp_path / "done.jsonl", CP_COMPLETED)
    assert classify(_ctx(p, backend="copilot", agent_exit=1)) == TerminationReason.OK


def test_copilot_session_error_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "serr.jsonl", CP_SESSION_ERROR)
    assert classify(_ctx(p, backend="copilot")) == TerminationReason.INFRA_ERROR


def test_copilot_abort_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "abort.jsonl", CP_ABORT)
    assert classify(_ctx(p, backend="copilot")) == TerminationReason.INFRA_ERROR


def test_copilot_shutdown_error_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "sd.jsonl", CP_SHUTDOWN_ERROR)
    assert classify(_ctx(p, backend="copilot")) == TerminationReason.INFRA_ERROR


def test_copilot_shutdown_routine_is_ok(tmp_path):
    p = _write_jsonl(tmp_path / "sdok.jsonl", CP_SHUTDOWN_OK)
    assert classify(_ctx(p, backend="copilot")) == TerminationReason.OK


@pytest.mark.parametrize(
    ("shutdown_type", "expected"),
    [("error", TerminationReason.INFRA_ERROR), ("routine", TerminationReason.OK)],
)
def test_copilot_legacy_top_level_shutdown_type_is_supported(tmp_path, shutdown_type, expected):
    p = _write_jsonl(tmp_path / "legacy-shutdown.jsonl", [{"type": "session.shutdown", "shutdownType": shutdown_type}])
    assert classify(_ctx(p, backend="copilot")) == expected


def test_copilot_recovered_session_error_is_ok(tmp_path):
    # Only a WHOLESALE failure counts: a session.error the run recovered from
    # (followed by a clean terminal) must NOT be flagged.
    p = _write_jsonl(tmp_path / "recov.jsonl", CP_RECOVERED)
    assert classify(_ctx(p, backend="copilot")) == TerminationReason.OK


def test_copilot_root_session_error_is_infra_even_with_terminal_result(tmp_path):
    p = _write_jsonl(tmp_path / "root-error-result.jsonl", CP_ERROR_THEN_RESULT)
    assert classify(_ctx(p, backend="copilot", agent_exit=1)) == TerminationReason.INFRA_ERROR


def test_copilot_subagent_error_does_not_poison_completed_root_run(tmp_path):
    p = _write_jsonl(tmp_path / "subagent-error-result.jsonl", CP_SUBAGENT_ERROR_THEN_RESULT)
    assert classify(_ctx(p, backend="copilot", agent_exit=1)) == TerminationReason.OK


def test_copilot_subagent_activity_does_not_recover_root_session_error(tmp_path):
    events = [
        *CP_ERROR_THEN_RESULT[:-1],
        {"type": "assistant.message", "agentId": "call_subagent", "data": {"content": "still working"}},
        CP_ERROR_THEN_RESULT[-1],
    ]
    p = _write_jsonl(tmp_path / "root-error-subagent-activity.jsonl", events)
    assert classify(_ctx(p, backend="copilot", agent_exit=1)) == TerminationReason.INFRA_ERROR


def test_copilot_truncated_is_infra(tmp_path):
    p = _write_jsonl(tmp_path / "trunc.jsonl", CP_TRUNCATED)
    assert classify(_ctx(p, backend="copilot")) == TerminationReason.INFRA_ERROR


def test_copilot_rule_only_applies_to_copilot(tmp_path):
    p = _write_jsonl(tmp_path / "trunc.jsonl", CP_TRUNCATED)
    assert copilot_session_error(_ctx(p, backend="codex")) is None


# --- backend-independent startup rule (empty stream + nonzero exit) ----------

# The observed Copilot startup failures: a 0-byte output.jsonl, agent_exit 1,
# and the real error only in stderr, wrapped in install/firewall noise.
COPILOT_STARTUP_STDERR = """\
added 3 packages in 8s
[firewall] Allowed: api.githubcopilot.com -> 140.82.113.22
Error: Failed to load models

Error: Failed to list models
"""


def _startup_ctx(tmp_path, stderr=None, backend="copilot", agent_exit=1, error=""):
    # A 0-byte event stream, exactly as the observed startup failures left it.
    jsonl = tmp_path / "output.jsonl"
    jsonl.write_text("")
    stderr_path = None
    if stderr is not None:
        p = tmp_path / "stderr.txt"
        p.write_text(stderr)
        stderr_path = str(p)
    return TerminationContext(
        backend=backend, jsonl_path=str(jsonl), agent_exit=agent_exit, error=error, stderr_path=stderr_path
    )


def test_startup_failure_is_infra_for_every_backend(tmp_path):
    # The rule keys on the failure's shape, not a backend's event vocabulary.
    for backend in ("copilot", "codex", "claude_code", "litellm"):
        ctx = _startup_ctx(tmp_path, COPILOT_STARTUP_STDERR, backend=backend)
        assert classify(ctx) == TerminationReason.INFRA_ERROR, backend


def test_startup_error_snippet_quotes_the_real_error(tmp_path):
    # The label is the actual error line from stderr (first line mentioning
    # "error"), skipping the npm/firewall noise around it — no hardcoded
    # signature list to go stale.
    assert startup_error_snippet(_startup_ctx(tmp_path, COPILOT_STARTUP_STDERR)) == "Error: Failed to load models"
    dns_stderr = "[firewall] ERROR: no IPs resolved for host 'q.eu-central-1.amazonaws.com'"
    assert startup_error_snippet(_startup_ctx(tmp_path, dns_stderr)) == dns_stderr
    # No "error" wording anywhere: fall back to the last non-empty line.
    assert (
        startup_error_snippet(_startup_ctx(tmp_path, "added 3 packages in 8s\nAuthentication token rejected\n"))
        == "Authentication token rejected"
    )
    assert startup_error_snippet(_startup_ctx(tmp_path, None)) == "no stderr"


def test_reworded_startup_error_is_still_infra(tmp_path):
    # The snippet labels, it never gates: a reworded CLI error must not
    # silently turn startup failures back into proof FAILs.
    ctx = _startup_ctx(tmp_path, "models are having a bad day\n")
    assert classify(ctx) == TerminationReason.INFRA_ERROR
    assert startup_error_snippet(ctx) == "models are having a bad day"


def test_startup_failure_without_stderr_is_still_infra(tmp_path):
    # No stderr dump at all (e.g. the container died before writing one).
    assert classify(_startup_ctx(tmp_path, None)) == TerminationReason.INFRA_ERROR


def test_clean_exit_with_empty_stream_is_not_startup_failure(tmp_path):
    assert classify(_startup_ctx(tmp_path, COPILOT_STARTUP_STDERR, agent_exit=0)) == TerminationReason.OK


def test_startup_rule_never_overrides_timeout(tmp_path):
    # A SIGKILLed run can also leave an empty stream + nonzero exit; the
    # wall-clock timeout precheck must win.
    ctx = _startup_ctx(tmp_path, None, agent_exit=-1, error="copilot timeout after 300s")
    assert classify(ctx) == TerminationReason.TIMEOUT


def test_noisy_stderr_on_clean_run_is_ok(tmp_path):
    # install/firewall noise on stderr is normal — a run that reached a clean
    # terminal event stays OK regardless of what stderr says.
    p = _write_jsonl(tmp_path / "done.jsonl", CP_COMPLETED)
    sp = tmp_path / "stderr.txt"
    sp.write_text(COPILOT_STARTUP_STDERR)  # worst case: even a scary stderr
    ctx = TerminationContext(backend="copilot", jsonl_path=p, agent_exit=0, stderr_path=str(sp))
    assert classify(ctx) == TerminationReason.OK

"""Classify how an agent run terminated — in particular, whether a benchmark
result is trustworthy or was cut short by INFRA_ERROR.

A benchmark verdict (PASS/FAIL) is a capability signal only if the agent
actually got to make a genuine attempt. When the run is cut short by
infrastructure — a corrupted/refused API request, a dropped stream, a server
overload — the resulting FAIL says nothing about the model. We tag such runs
with ``termination_reason = INFRA_ERROR`` so they can be filtered out (and
auto-retried by the runner when the model did no work) instead of being read
as genuine failures.

:func:`classify` first checks for a wall-clock timeout (a backend-independent
LIMIT — the model was working, it just ran out of time — reported as TIMEOUT,
never INFRA_ERROR), then runs a registry of INFRA RULES (criteria). Each rule
inspects a ``TerminationContext`` and returns a reason if it fires, else
``None``; the first that fires wins. There is one rule per backend
(:func:`codex_turn_failed`, :func:`codex_single_turn_contract_error`, :func:`claude_code_result_error`,
:func:`copilot_session_error`, :func:`cursor_result_error`,
:func:`litellm_completion_error`, :func:`pi_run_failed`), each branching on
``ctx.backend`` to read its own event vocabulary, plus one backend-independent
startup rule (:func:`agent_startup_failure`) for the CLI dying before emitting
a single event. The one-shot rule may also return TIMEOUT for a strictly
audited provider deadline. Add more by appending to :data:`INFRA_RULES`.

This module only CLASSIFIES. Acting on the classification (the runner auto-
retries an INFRA_ERROR run whose model did no work) is left to the caller.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass


class TerminationReason:
    """How an agent run ended.

    Plain string constants so the value serializes verbatim into results.json.
    Extend with e.g. USAGE_LIMIT as new rules are added — keep the values
    stable, downstream filters match on them.
    """

    OK = "OK"
    INFRA_ERROR = "INFRA_ERROR"
    # The runner SIGKILLed the agent for exceeding its wall-clock budget: a time
    # LIMIT (the model was working), NOT infrastructure. Detected the same way
    # for every backend so they agree (see is_wall_clock_timeout / classify).
    TIMEOUT = "TIMEOUT"
    # A provider hard usage cap stopped the run — the proactive gate exhausted
    # its waits, or the reactive retry gave up. The agent did no genuine work;
    # the run is retriable once the quota window resets. Backend-independent, so
    # every backend agrees. Set directly by the runner (which owns the quota
    # signal), not by a classify() rule — distinct from INFRA_ERROR (retry
    # immediately) and TIMEOUT (out of time).
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"


@dataclass
class TerminationContext:
    """The evidence a rule may inspect.

    ``backend`` lets a rule apply only to the backend whose event format it
    understands. ``approach`` and ``provider`` identify cross-provider contracts
    without encoding semantics in a backend-name suffix. ``events()`` lazily parses the backend's JSONL event stream
    (empty list on a missing/unreadable file), so rules that don't need it pay
    nothing. ``agent_exit`` and ``error`` are the runner's already-recorded
    fields, available to rules that key off them instead of the stream.
    ``stderr()`` lazily reads the agent's stderr dump ("" when absent), where a
    startup failure often leaves its only evidence.
    """

    backend: str
    jsonl_path: str | None
    approach: str = "agentic"
    provider: str | None = None
    request_audit_validator: Callable[[dict[str, object], int], bool] | None = None
    agent_exit: int | None = None
    error: str = ""
    stderr_path: str | None = None
    _events: list | None = None
    _event_stream_valid: bool | None = None
    _stderr: str | None = None

    def events(self) -> list:
        if self._events is None:
            self._events, self._event_stream_valid = _read_event_stream(self.jsonl_path)
        return self._events

    def event_stream_valid(self) -> bool:
        if self._events is None:
            self._events, self._event_stream_valid = _read_event_stream(self.jsonl_path)
        return self._event_stream_valid is True

    def stderr(self) -> str:
        if self._stderr is None:
            self._stderr = _read_text(self.stderr_path)
        return self._stderr


def _read_event_stream(path: str | None) -> tuple[list[dict], bool]:
    """Parse JSONL dictionaries and separately retain stream-integrity evidence.

    Agentic rules keep their historical tolerance by consuming only ``events``.
    Strict approaches can fail closed when a non-blank line is malformed, is not
    a JSON object, or the stream cannot be read.
    """

    if not path:
        return [], False
    out: list[dict] = []
    valid = True
    try:
        with open(path) as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    valid = False
                    continue
                if isinstance(event, dict):
                    out.append(event)
                else:
                    valid = False
    except (OSError, UnicodeError):
        return [], False
    return out, valid


def _read_text(path: str | None) -> str:
    """Contents of a text file, tolerantly ("" when unset/absent/unreadable)."""
    if not path:
        return ""
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


# A rule inspects the context and returns a TerminationReason if it fires, else
# None. Rules must be cheap and side-effect free.
Rule = Callable[[TerminationContext], str | None]


def codex_turn_failed(ctx: TerminationContext) -> str | None:
    """codex rule: the run ended on a failed turn rather than a completed one.

    codex emits one ``turn.started`` … ``turn.completed`` per turn. An
    infrastructure error — a corrupted/refused request, a dropped stream, a
    server overload — instead surfaces as ``error`` events and a terminal
    ``turn.failed`` with no following ``turn.completed``. A genuine "I couldn't
    prove it" run, by contrast, ends with ``turn.completed`` (the model ran to
    a normal stop; its proof simply didn't verify).

    We flag INFRA_ERROR when the last terminal turn event is a failure, when the
    stream ends without a terminal, or when the required JSON stream is empty.
    A run that hit a transient error mid-way but recovered and completed a turn
    is NOT flagged.
    """
    if ctx.backend not in {"codex", "codex_single_turn"}:
        return None
    events = ctx.events()
    if not events:
        return TerminationReason.INFRA_ERROR
    last_terminal = None  # "completed" | "failed"
    for ev in events:
        t = ev.get("type")
        if t == "turn.completed":
            last_terminal = "completed"
        elif t == "turn.failed":
            last_terminal = "failed"
    if last_terminal == "failed":
        return TerminationReason.INFRA_ERROR
    if last_terminal is None:
        return TerminationReason.INFRA_ERROR
    return None


def codex_single_turn_contract_error(ctx: TerminationContext) -> str | None:
    """Require one rollout-audited, tool-free request in one Codex turn."""

    if ctx.backend != "codex_single_turn":
        return None
    events = ctx.events()
    if not ctx.event_stream_valid() or not events:
        return TerminationReason.INFRA_ERROR

    starts = [event for event in events if event.get("type") == "tlaps.codex_child_usage.started"]
    audits = [event for event in events if event.get("type") == "tlaps.codex_child_usage"]
    threads = [event.get("thread_id") for event in events if event.get("type") == "thread.started"]
    if len(starts) != 1 or len(audits) != 1 or len(threads) != 1:
        return TerminationReason.INFRA_ERROR
    if events[0] is not starts[0] or events[-1] is not audits[0]:
        return TerminationReason.INFRA_ERROR

    version = starts[0].get("version")
    audit = audits[0]
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0 or audit.get("version") != version:
        return TerminationReason.INFRA_ERROR
    thread_id = threads[0]
    if not isinstance(thread_id, str) or not thread_id or audit.get("root_thread_id") != thread_id:
        return TerminationReason.INFRA_ERROR
    if audit.get("complete") is not True or audit.get("warning_codes") != [] or audit.get("child_count") != 0:
        return TerminationReason.INFRA_ERROR
    requests = audit.get("requests")
    if not isinstance(requests, list) or len(requests) != 1 or not isinstance(requests[0], dict):
        return TerminationReason.INFRA_ERROR

    tool_calls = audit.get("tool_calls")
    if not isinstance(tool_calls, dict):
        return TerminationReason.INFRA_ERROR
    if (
        tool_calls.get("available") is not True
        or tool_calls.get("complete") is not True
        or tool_calls.get("is_lower_bound") is not False
        or tool_calls.get("warnings") != []
        or any(tool_calls.get(field) != 0 for field in ("total", "tlaps", "tlc", "apalache", "other"))
    ):
        return TerminationReason.INFRA_ERROR

    allowed_items = {"agent_message", "reasoning", "error"}
    for event in events:
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type.startswith("item."):
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") not in allowed_items:
            return TerminationReason.INFRA_ERROR
    return None


def claude_code_result_error(ctx: TerminationContext) -> str | None:
    """claude_code rule: the run ended on an execution error (or never emitted a
    terminal result at all).

    Background work can produce several ``result`` events. The final result
    must follow the last conversation activity; an earlier success cannot
    finalize a truncated follow-up turn. Malformed streams and execution-error
    results are INFRA_ERROR. ``error_max_turns`` remains a turn-budget LIMIT,
    not infrastructure, when it closes the stream.
    """
    if ctx.backend != "claude_code":
        return None
    events = ctx.events()
    if not events:
        return None
    if not ctx.event_stream_valid():
        return TerminationReason.INFRA_ERROR
    last_result = None
    for ev in events:
        event_type = ev.get("type")
        if event_type == "result":
            last_result = ev
        elif event_type in ("assistant", "user", "system", "stream_event", "error"):
            last_result = None
    if last_result is None:
        # No result closes the latest activity, including background turns.
        return TerminationReason.INFRA_ERROR
    subtype = last_result.get("subtype", "")
    if subtype.startswith("error") and subtype != "error_max_turns":
        return TerminationReason.INFRA_ERROR
    return None


def _copilot_shutdown_type(event: dict) -> object:
    data = event.get("data")
    nested = data.get("shutdownType") if isinstance(data, dict) else None
    return event.get("shutdownType", nested)


def copilot_session_error(ctx: TerminationContext) -> str | None:
    """copilot rule: the run did not reach a clean terminal.

    The GitHub Copilot CLI ends a clean run with a terminal event — ``result``
    (carrying ``exitCode``) on the stdout JSON stream, or ``session.shutdown``
    with ``shutdownType: "routine"``. Infrastructure problems surface as a
    ``session.error`` event (``errorType`` e.g. ``"authentication"`` /
    ``"quota"``), an ``abort``, or ``session.shutdown`` with
    ``shutdownType == "error"``.

    A ``result`` is only the CLI's terminal envelope: Copilot may emit one with
    ``exitCode: 1`` immediately after an unrecovered root ``session.error``.
    Such a result is not clean. A later root ``assistant.message`` followed by a
    terminal event proves recovery; errors carrying ``agentId`` belong to a
    subagent and do not poison a completed root run. Per-tool failures and a
    non-zero result without a root session error remain genuine attempts.
    """
    if ctx.backend != "copilot":
        return None
    events = ctx.events()
    if not events:
        return None
    reached_clean_terminal = False
    root_error_pending = False
    for ev in events:
        if ev.get("agentId") is not None:
            continue
        t = ev.get("type")
        shutdown_type = _copilot_shutdown_type(ev)
        root_error = t in {"session.error", "abort"} or (t == "session.shutdown" and shutdown_type == "error")
        if root_error:
            reached_clean_terminal = False
            root_error_pending = True
        elif t == "assistant.message":
            root_error_pending = False
        elif not root_error_pending and (t == "result" or (t == "session.shutdown" and shutdown_type != "error")):
            reached_clean_terminal = True
    if reached_clean_terminal:
        return None
    return TerminationReason.INFRA_ERROR


def cursor_result_error(ctx: TerminationContext) -> str | None:
    """Cursor rule: require one clean terminal ``result`` event.

    Cursor's ``stream-json`` contract ends every successful run with exactly one
    terminal ``result`` whose ``subtype`` is ``success`` and ``is_error`` is
    false. On failure, the CLI may exit nonzero after emitting only a partial
    stream, with the error itself written to stderr. A non-empty stream that is
    malformed, lacks that terminal, or ends in an explicit error is therefore
    not a trustworthy model attempt.

    An empty or wholly malformed stream is also infrastructure failure: a clean
    Cursor run cannot exit without the terminal success event.
    """
    if ctx.backend != "cursor":
        return None
    events = ctx.events()
    if not events or not ctx.event_stream_valid():
        return TerminationReason.INFRA_ERROR
    results = [event for event in events if event.get("type") == "result"]
    if len(results) != 1 or events[-1] is not results[0]:
        return TerminationReason.INFRA_ERROR
    terminal = results[0]
    if terminal.get("subtype") != "success" or terminal.get("is_error") is not False:
        return TerminationReason.INFRA_ERROR
    return None


def litellm_completion_error(ctx: TerminationContext) -> str | None:
    """LiteLLM rule: the agent stopped on a completion error.

    The LiteLLM agent emits an ``error`` event and stops its loop when a
    provider rejects the request or inference otherwise fails. A later
    ``response`` would indicate recovery, so only the last response/error
    outcome determines whether the run was cut short.
    """
    if ctx.backend != "litellm":
        return None
    last_outcome = None
    for event in ctx.events():
        event_type = event.get("type")
        if event_type == "response":
            last_outcome = "response"
        elif event_type == "error":
            last_outcome = "error"
    if last_outcome == "error":
        return TerminationReason.INFRA_ERROR
    return None


_PI_RUN_ACTIVITY_EVENTS = frozenset(
    {
        "agent_start",
        "agent_end",
        "turn_start",
        "turn_end",
        "message_start",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
        "compaction_start",
        "compaction_end",
    }
)


def pi_run_failed(ctx: TerminationContext) -> str | None:
    """Pi rule: require a settled run whose final assistant response succeeded.

    Pi writes a ``session`` header before it starts the prompt, so startup
    failures commonly leave a non-empty stream and bypass the generic empty-
    stream rule. JSON mode also exits zero when the provider's final assistant
    message has ``stopReason == "error"`` or ``"aborted"``. ``agent_settled``
    is the definitive end of Pi's automatic retries, compaction, and queued
    continuations; ``agent_end`` alone is not terminal.

    Earlier assistant errors are allowed when a later response recovered. A
    runner wall-clock timeout is checked before this rule by :func:`classify`.
    """

    if ctx.backend != "pi":
        return None

    events = ctx.events()
    if not ctx.event_stream_valid():
        return TerminationReason.INFRA_ERROR
    settled = False
    activity_after_settled = False
    last_assistant_stop_reason: object = None
    saw_assistant_terminal = False

    for event in events:
        event_type = event.get("type")
        if settled and event_type in _PI_RUN_ACTIVITY_EVENTS:
            activity_after_settled = True
        if event_type == "agent_settled":
            settled = True
        elif event_type == "message_end":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                saw_assistant_terminal = True
                last_assistant_stop_reason = message.get("stopReason")

    if ctx.agent_exit not in {None, 0}:
        return TerminationReason.INFRA_ERROR
    if not settled:
        return TerminationReason.INFRA_ERROR
    if activity_after_settled:
        return TerminationReason.INFRA_ERROR
    if not saw_assistant_terminal:
        return TerminationReason.INFRA_ERROR
    if last_assistant_stop_reason not in {"stop", "length", "toolUse"}:
        return TerminationReason.INFRA_ERROR
    return None


def one_shot_result_error(ctx: TerminationContext) -> str | None:
    """One-shot rule: require an audited terminal result and one clean response.

    The shared one-shot driver emits a terminal ``result`` event. Provider,
    authentication, transport, or request-guard failures end with
    ``status == "error"`` and no successful response; grading the untouched
    ``PROOF OBVIOUS`` file would misreport that infrastructure failure as a
    model capability failure.

    A propagated provider deadline ends with ``status == "timeout"`` and is a
    time limit just like the outer runner watchdog, not infrastructure.

    A clean, unique, non-empty response remains a genuine attempt regardless of
    its text: the runner materializes it and leaves TLA+ syntax and semantics to
    the grader. Missing or ambiguous response content is recorded as FAIL without
    grading the untouched placeholder.
    """
    if ctx.approach != "one_shot":
        return None
    events = ctx.events()
    if not ctx.event_stream_valid() or not events:
        return TerminationReason.INFRA_ERROR
    audits = [event for event in events if event.get("type") == "request_audit"]
    results = [event for event in events if event.get("type") == "result"]
    if len(audits) != 1 or len(results) != 1:
        return TerminationReason.INFRA_ERROR

    def is_count(value: object, expected: int) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value == expected

    terminal = results[0]
    request_count = terminal.get("model_requests")
    if not isinstance(request_count, int) or isinstance(request_count, bool) or request_count < 0:
        return TerminationReason.INFRA_ERROR

    audit = audits[0]
    if ctx.request_audit_validator is None or not ctx.request_audit_validator(audit, request_count):
        return TerminationReason.INFRA_ERROR

    responses = [event for event in events if event.get("type") == "response"]
    completed_responses = audit.get("completed_responses")
    if completed_responses is not None and not is_count(completed_responses, len(responses)):
        return TerminationReason.INFRA_ERROR
    if terminal.get("status") == "timeout":
        return TerminationReason.TIMEOUT

    if request_count < 1 or len(responses) != 1:
        return TerminationReason.INFRA_ERROR
    if terminal.get("status") != "success":
        return TerminationReason.INFRA_ERROR
    return None


def agent_startup_failure(ctx: TerminationContext) -> str | None:
    """Backend-independent rule: the CLI died before emitting a single event
    (observed on Copilot: transient model-list/auth/DNS startup failures with a
    0-byte stream, nonzero exit, and the error only on stderr). Keys on that
    shape alone — never on the stderr wording — covering the per-backend rules'
    empty-stream blind spot for every backend. A wall-clock timeout leaves the
    same shape; classify() checks it first.
    """
    if ctx.events():
        return None
    if not ctx.agent_exit:  # 0 or None: clean/unknown exit, not a startup death
        return None
    return TerminationReason.INFRA_ERROR


def startup_error_snippet(ctx: TerminationContext) -> str:
    """Label for ``infra_retry_reasons``: the first stderr line mentioning
    "error", else the last non-empty line. Diagnostic only — never gates a retry."""
    lines = [ln.strip() for ln in ctx.stderr().splitlines() if ln.strip()]
    if not lines:
        return "no stderr"
    return next((ln for ln in lines if "error" in ln.lower()), lines[-1])[:120]


# Registry of INFRA_ERROR criteria. One rule per backend, then the backend-
# independent startup rule as fallback; append more here (other backends, or
# additional patterns for an existing one) — classify() returns the first that
# fires. This list IS the extension point.
INFRA_RULES: list[Rule] = [
    codex_turn_failed,
    codex_single_turn_contract_error,
    claude_code_result_error,
    copilot_session_error,
    cursor_result_error,
    litellm_completion_error,
    pi_run_failed,
    one_shot_result_error,
    agent_startup_failure,
]


def is_wall_clock_timeout(ctx: TerminationContext) -> bool:
    """Whether the runner SIGKILLed the agent for exceeding its wall-clock budget.

    The runner records this identically for every backend — ``agent_exit == -1``
    and ``error`` = ``"<backend> timeout after <N>s"`` — so the check is backend
    independent. This is a time LIMIT, not infrastructure: the model was working,
    it just didn't finish in the budget (TLAPS proofs are slow, so timeouts are
    common). A SIGKILL also leaves a truncated event stream — no terminal turn /
    result — which the per-backend INFRA rules would otherwise read as a cut-off;
    classify() checks this first so a timeout is never mislabeled INFRA_ERROR.
    """
    return ctx.agent_exit == -1 and "timeout after" in (ctx.error or "")


def classify(ctx: TerminationContext) -> str:
    """Return the run's TerminationReason.

    A wall-clock timeout (a LIMIT, backend-independent) takes precedence over the
    per-backend rules, so every backend agrees on it; otherwise the first rule
    that fires wins (including an audited one-shot provider deadline), else OK.
    """
    if is_wall_clock_timeout(ctx):
        return TerminationReason.TIMEOUT
    for rule in INFRA_RULES:
        reason = rule(ctx)
        if reason:
            return reason
    return TerminationReason.OK

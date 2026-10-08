"""Tool-call counting: the classifier, and each backend's event vocabulary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluator import toolcalls
from evaluator.backends.claude_code import ClaudeCodeBackend
from evaluator.backends.codex import CodexBackend
from evaluator.backends.copilot import CopilotBackend
from evaluator.backends.cursor import CursorBackend
from evaluator.backends.litellm import LiteLLMBackend
from evaluator.backends.pi import PiBackend

TLAPM = "/opt/tlapm/bin/tlapm -I /opt/tlapm/lib/tlapm/stdlib -I $COMMUNITY_LIB Foo.tla"
TLC = "java -cp /opt/sany/lib/tla2tools.jar tlc2.TLC -deadlock -config MCFoo.cfg MCFoo.tla"
APALACHE = "apalache-mc check --init=IndInv --inv=IndInv --length=1 APFoo.tla"


def _write_jsonl(path: Path, *events: object) -> str:
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return str(path)


def _summary(*, total, tlaps=0, tlc=0, apalache=0, other=0, complete=True, warnings=()):
    return {
        "total": total,
        "tlaps": tlaps,
        "tlc": tlc,
        "apalache": apalache,
        "other": other,
        "available": True,
        "complete": complete,
        "is_lower_bound": not complete,
        "warnings": list(warnings),
    }


# --- classifier -------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (TLAPM, toolcalls.TLAPS),
        (TLC, toolcalls.TLC),
        (APALACHE, toolcalls.APALACHE),
        ("/opt/apalache/bin/apalache-mc typecheck APFoo.tla", toolcalls.APALACHE),
        ("check_proof_bin /workspace/Foo.tla", toolcalls.TLAPS),
        ("check_proof_bin --sany-only /workspace/Foo.tla", toolcalls.OTHER),
        ("sed -i 's/OBVIOUS/BY DEF Foo/' Foo.tla", toolcalls.OTHER),
        (None, toolcalls.OTHER),  # a non-shell tool: edit, read, web search
        ("", toolcalls.OTHER),
    ],
)
def test_classifier_names_the_tool_a_command_reached_for(command, expected):
    assert toolcalls.classify_command(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        f"cd /workspace && {TLAPM}",  # after a directory change
        f"{TLAPM} 2>&1 | tail -40",  # first stage of a pipeline
        f"timeout 600 {TLAPM}",  # behind a wrapper that takes an operand
        f"TLAPM_CACHE=/tmp {TLAPM}",  # behind an environment assignment
        f"out=$({TLAPM} 2>&1)",  # captured by command substitution
        f"for g in A B; do {TLAPM}; done",  # swept over goals in a loop
        f"/bin/bash -lc {json.dumps(TLAPM)}",  # Codex's real command envelope
    ],
)
def test_classifier_finds_the_prover_wherever_the_line_puts_it(command):
    # Verbatim shapes from recorded runs: agents rarely type a bare command.
    assert toolcalls.classify_command(command) == toolcalls.TLAPS


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (f"time (timeout 200 {TLAPM})", toolcalls.TLAPS),
        (f"TIMEFORMAT=%R; time ({TLC})", toolcalls.TLC),
        (f"time -p ({APALACHE})", toolcalls.APALACHE),
        ("time (check_proof_bin --sany-only Foo.tla)", toolcalls.OTHER),
        ("time (echo tlapm Foo.tla)", toolcalls.OTHER),
        ("echo (tlapm Foo.tla)", toolcalls.OTHER),
        ("foo (tlapm Foo.tla)", toolcalls.OTHER),
        ("X=1 time (tlapm Foo.tla)", toolcalls.OTHER),
        ("2>/dev/null time (tlapm Foo.tla)", toolcalls.OTHER),
        ("/usr/bin/time (tlapm Foo.tla)", toolcalls.OTHER),
        (r"\time (tlapm Foo.tla)", toolcalls.OTHER),
    ],
)
def test_classifier_only_enters_compound_commands_owned_by_the_time_keyword(command, expected):
    assert toolcalls.classify_command(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "grep -n tlapm notes.txt",
        "which apalache-mc check_proof_bin",
        "ls -la /opt/tlapm/bin/tlapm",
        "pkill -f tlapm",
        "command -v check_proof_bin",
        "command -pv tlapm",
        "env -u tlapm echo harmless",
        "sudo -u tlapm echo harmless",
        "stdbuf -o tlapm echo harmless",
        "rg -n 'missing|tlapm|proof' notes.txt",
        "bash --norc tlapm Foo.tla",
        "function prove { tlapm Foo.tla; }",
        "prove() { tlapm Foo.tla; }",
    ],
)
def test_classifier_reads_the_executable_not_the_line(command):
    # Naming a tool is not running it, and these are the most common ways to name one.
    assert toolcalls.classify_command(command) == toolcalls.OTHER


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # tla2tools.jar is four tools in one, so the main class decides.
        ("java -cp /opt/sany/lib/tla2tools.jar tla2sany.SANY Foo.tla", toolcalls.OTHER),
        ("java -cp /opt/sany/lib/tla2tools.jar pcal.trans Foo.tla", toolcalls.OTHER),
        ("java -cp /opt/tlaplus/tla2tools.jar tlc2.tool.impl.SANY -module Foo", toolcalls.OTHER),
        ("java -DTLA-Library=/opt/x -cp /opt/sany/lib/tla2tools.jar tlc2.TLC MCFoo", toolcalls.TLC),
        # No class named: the jar's own entry point is TLC.
        ("java -jar /opt/sany/lib/tla2tools.jar MCFoo.tla", toolcalls.TLC),
        ("java -jar apalache.jar check Foo.tla", toolcalls.APALACHE),
        ("java -cp tla2tools.jar tlc2.TLC ApalacheRegression.tla", toolcalls.TLC),
        ("java -cp tla2tools.jar tlc2.TLC -jar apalache.jar", toolcalls.TLC),
        ("java -cp tla2tools.jar tla2sany.SANY -jar tla2tools.jar", toolcalls.OTHER),
        ("java --add-modules tlc2.TLC com.example.Main", toolcalls.OTHER),
        ("java -m harmless/Main tlc2.TLC", toolcalls.OTHER),
        ("java --module harmless/Main tlc2.TLC", toolcalls.OTHER),
        ("java --describe-module harmless tlc2.TLC", toolcalls.OTHER),
        ("java --dry-run tlc2.TLC", toolcalls.OTHER),
        ("java --show-version tlc2.TLC", toolcalls.TLC),
        ("javac -cp tla2tools.jar Foo.java", toolcalls.OTHER),
        ("java -cp tla2tools.jar tla2sany.SANY Foo.tla; tlapm Foo.tla", toolcalls.TLAPS),
    ],
)
def test_classifier_resolves_java_hosted_tools_by_main_class(command, expected):
    assert toolcalls.classify_command(command) == expected


def test_classifier_survives_an_unparseable_command():
    assert toolcalls.classify_command('echo "unbalanced') == toolcalls.OTHER


def test_classifier_survives_a_pathologically_deep_shell_tree():
    command = "echo $(" * 400 + "tlapm Foo.tla" + ")" * 400

    assert toolcalls.classify_command(command) == toolcalls.OTHER


@pytest.mark.parametrize("shell", ("bash", "sh"))
def test_shell_c_option_after_a_script_operand_is_not_unwrapped(shell):
    assert toolcalls.classify_command(f"{shell} harmless.sh -lc tlapm") == toolcalls.OTHER


@pytest.mark.parametrize(
    "command",
    (
        "bash -c -- 'tlapm Foo.tla'",
        "bash -lc -- 'tlapm Foo.tla'",
        "bash --norc -c -- 'tlapm Foo.tla'",
        "sh -c -- 'tlapm Foo.tla'",
        "sh -lc -- 'tlapm Foo.tla'",
        "dash -c -- 'tlapm Foo.tla'",
        "dash -lc -- 'tlapm Foo.tla'",
    ),
)
def test_shell_c_option_accepts_an_immediate_option_terminator(command):
    assert toolcalls.classify_command(command) == toolcalls.TLAPS


@pytest.mark.parametrize(
    "command",
    (
        "bash -c --",
        "bash -c -- 'echo tlapm Foo.tla'",
        "bash -- -c 'tlapm Foo.tla'",
    ),
)
def test_shell_option_terminator_does_not_invent_a_command_string(command):
    assert toolcalls.classify_command(command) == toolcalls.OTHER


def test_tool_call_summary_rejects_inconsistent_external_evidence():
    invalid_lower_bound = _summary(total=1, other=1, complete=False)
    invalid_lower_bound["is_lower_bound"] = False
    unavailable_with_counts = _summary(total=1, other=1)
    unavailable_with_counts.update(available=False, complete=False, is_lower_bound=False)

    for value in (invalid_lower_bound, unavailable_with_counts):
        summary = toolcalls.ToolCallSummary.from_dict(value)
        assert summary.available is False
        assert summary.total == 0
        assert summary.warnings == ("tool-call summary has inconsistent evidence",)


def test_tool_call_summary_rejects_invalid_field_types():
    with pytest.raises(ValueError, match="evidence fields"):
        toolcalls.ToolCallSummary(available=1, complete=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="warnings"):
        toolcalls.ToolCallSummary(warnings=None)  # type: ignore[arg-type]

    invalid_evidence = _summary(total=0)
    invalid_evidence["available"] = 1
    invalid_warnings = _summary(total=0)
    invalid_warnings["warnings"] = ["valid", 3]
    assert toolcalls.ToolCallSummary.from_dict(invalid_evidence).warnings == ("tool-call summary has invalid evidence",)
    assert toolcalls.ToolCallSummary.from_dict(invalid_warnings).warnings == ("tool-call summary has invalid warnings",)


@pytest.mark.parametrize(
    "command",
    [
        # Embedded Python naming the checker: recorded verbatim from agents trying to
        # take the grader apart. Without ignoring the body, the parenthesized path
        # reads as a bare invocation of it.
        "python3 <<'PY'\nfrom pathlib import Path\np = Path('/usr/local/bin/check_proof_bin')\nPY",
        # A module written to disk, whose text happens to mention the prover.
        "cat > Foo.tla <<EOF\n\\* run with tlapm Foo.tla\n====\nEOF",
    ],
)
def test_classifier_ignores_what_a_heredoc_writes(command):
    # A heredoc body is data the command writes, not commands it runs; if the agent
    # later executes it, that run is a tool call of its own.
    assert toolcalls.classify_command(command) == toolcalls.OTHER


def test_classifier_still_sees_the_command_around_a_heredoc():
    command = f"cat > Foo.tla <<EOF\n---- MODULE Foo ----\n====\nEOF\n{TLAPM}"
    assert toolcalls.classify_command(command) == toolcalls.TLAPS


def test_tally_reports_a_total_and_every_category():
    counts = toolcalls.tally([TLAPM, None, APALACHE, TLC, "ls", TLAPM])
    # All four keys always present: a category at 0 is a fact about the run, and a
    # consumer should never have to distinguish "none" from "not reported".
    assert counts == {"total": 6, "tlaps": 2, "tlc": 1, "apalache": 1, "other": 2}


def test_tally_of_no_calls_is_all_zero():
    assert toolcalls.tally([]) == {"total": 0, "tlaps": 0, "tlc": 0, "apalache": 0, "other": 0}


def test_iter_events_retains_malformed_and_missing_evidence(tmp_path):
    path = tmp_path / "partial.jsonl"
    path.write_text('{"type":"a"}\nnot json\n[1,2]\n{"type":"b"}\n')
    evidence = toolcalls.EventStreamEvidence()
    assert [event["type"] for event in toolcalls.iter_events(str(path), evidence)] == ["a", "b"]
    assert evidence.available is True
    assert evidence.valid is False
    assert evidence.event_count == 2
    assert evidence.final_warnings() == (
        "tool-call event stream contains malformed JSON",
        "tool-call event stream contains a non-object event",
    )

    missing = toolcalls.EventStreamEvidence()
    assert list(toolcalls.iter_events(str(tmp_path / "absent.jsonl"), missing)) == []
    assert missing.available is False
    assert missing.valid is False
    assert missing.final_warnings() == ("tool-call event stream is missing or unreadable",)


def test_iter_events_preserves_a_valid_prefix_before_invalid_utf8(tmp_path):
    path = tmp_path / "invalid-encoding.jsonl"
    path.write_bytes(b'{"type":"result"}\n\xff\n')
    evidence = toolcalls.EventStreamEvidence()

    assert list(toolcalls.iter_events(str(path), evidence)) == [{"type": "result"}]
    assert evidence.available is True
    assert evidence.valid is False
    assert evidence.final_warnings() == ("tool-call event stream contains invalid text encoding",)


@pytest.mark.parametrize(
    "failure",
    (ValueError("integer digit limit"), RecursionError("parser stack limit")),
    ids=("value-error", "recursion-error"),
)
def test_iter_events_treats_json_parser_limits_as_malformed(failure, monkeypatch, tmp_path):
    path = tmp_path / "parser-limit.jsonl"
    path.write_text('parser limit\n{"type":"result"}\n')
    evidence = toolcalls.EventStreamEvidence()
    original_loads = json.loads

    def loads(raw):
        if raw == "parser limit":
            raise failure
        return original_loads(raw)

    monkeypatch.setattr(toolcalls.json, "loads", loads)

    assert list(toolcalls.iter_events(str(path), evidence)) == [{"type": "result"}]
    assert evidence.available is True
    assert evidence.valid is False
    assert evidence.final_warnings() == ("tool-call event stream contains malformed JSON",)


def test_tool_call_summary_merge_preserves_counts_and_evidence():
    first = toolcalls.ToolCallSummary.from_commands([TLAPM], available=True, complete=True)
    partial = toolcalls.ToolCallSummary.from_commands(
        [TLC, None],
        available=True,
        complete=False,
        warnings=("round was truncated",),
    )
    assert first.merge(partial).to_dict() == _summary(
        total=3,
        tlaps=1,
        tlc=1,
        other=1,
        complete=False,
        warnings=("round was truncated",),
    )


def test_missing_stream_is_unavailable_not_an_exact_zero(tmp_path):
    summary = ClaudeCodeBackend().parse_run_metadata(str(tmp_path / "missing.jsonl"))["tool_calls"]
    assert summary == {
        "total": 0,
        "tlaps": 0,
        "tlc": 0,
        "apalache": 0,
        "other": 0,
        "available": False,
        "complete": False,
        "is_lower_bound": False,
        "warnings": [
            "tool-call event stream is missing or unreadable",
            "Claude Code stream has no final result after its last activity",
        ],
    }


def test_malformed_prefix_preserves_observed_calls_as_a_lower_bound(tmp_path):
    path = tmp_path / "claude-partial.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": TLAPM}}]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "call-1"}]},
            }
        )
        + "\nnot-json\n"
        + json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True})
        + "\n"
    )
    summary = ClaudeCodeBackend().parse_run_metadata(str(path))["tool_calls"]
    assert summary["total"] == 1
    assert summary["tlaps"] == 1
    assert summary["available"] is True
    assert summary["complete"] is False
    assert summary["is_lower_bound"] is True
    assert summary["warnings"] == ["tool-call event stream contains malformed JSON"]


def test_terminal_error_can_still_be_a_complete_tool_stream(tmp_path):
    path = _write_jsonl(
        tmp_path / "claude-terminal-error.jsonl",
        {"type": "result", "subtype": "error_during_execution", "is_error": True},
    )
    assert ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"] == _summary(total=0)


@pytest.mark.parametrize(
    ("backend", "terminal"),
    [
        (ClaudeCodeBackend(), {"type": "result", "subtype": "success"}),
        (CursorBackend(), {"type": "result", "subtype": "success", "is_error": False}),
        (LiteLLMBackend(), {"type": "usage"}),
    ],
    ids=("claude_code", "cursor", "litellm"),
)
def test_unknown_valid_event_after_terminal_does_not_create_a_false_gap(backend, terminal, tmp_path):
    path = _write_jsonl(tmp_path / f"{backend.name}-future.jsonl", terminal, {"type": "future.telemetry"})

    assert backend.parse_run_metadata(path)["tool_calls"] == _summary(total=0)


@pytest.mark.parametrize(
    "backend",
    [CursorBackend(), ClaudeCodeBackend(), CodexBackend(), LiteLLMBackend(), CopilotBackend(), PiBackend()],
    ids=["cursor", "claude_code", "codex", "litellm", "copilot", "pi"],
)
def test_non_string_event_type_is_a_lower_bound_not_a_parser_crash(backend, tmp_path):
    path = _write_jsonl(tmp_path / f"{backend.name}-invalid-type.jsonl", {"type": []})

    summary = backend.parse_run_metadata(path)["tool_calls"]

    assert summary["available"] is True
    assert summary["complete"] is False
    assert summary["is_lower_bound"] is True
    assert any("without a string type" in warning for warning in summary["warnings"])


@pytest.mark.parametrize(
    ("backend", "events", "expected_total"),
    [
        (
            ClaudeCodeBackend(),
            ({"type": "assistant", "message": {}}, {"type": "result", "subtype": "success"}),
            0,
        ),
        (
            CodexBackend(),
            (
                {"type": "thread.started", "thread_id": "root"},
                {"type": "turn.started"},
                {"type": "item.started", "item": []},
                {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
            ),
            0,
        ),
        (CopilotBackend(), ({"type": "assistant.message", "data": []}, {"type": "result"}), 0),
    ],
    ids=["claude-message", "codex-item", "copilot-data"],
)
def test_malformed_known_activity_envelope_downgrades_enumeration(backend, events, expected_total, tmp_path):
    path = _write_jsonl(tmp_path / f"{backend.name}-bad-envelope.jsonl", *events)

    summary = backend.parse_run_metadata(path)["tool_calls"]

    assert summary["total"] == expected_total
    assert summary["is_lower_bound"] is True


@pytest.mark.parametrize(
    ("backend", "events", "expected_total"),
    [
        (
            CursorBackend(),
            (
                {
                    "type": "tool_call",
                    "subtype": [],
                    "call_id": "call",
                    "tool_call": {"shellToolCall": {"args": {"command": TLAPM}}},
                },
                {"type": "result"},
            ),
            1,
        ),
        (
            CodexBackend(),
            (
                {"type": "thread.started", "thread_id": "root"},
                {"type": "turn.started"},
                {"type": "item.started", "item": {"id": "call", "type": []}},
                {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
            ),
            0,
        ),
        (
            CopilotBackend(),
            (
                {"type": "tool.execution_start", "data": {"toolCallId": None, "toolName": []}},
                {"type": "result"},
            ),
            1,
        ),
        (
            LiteLLMBackend(),
            (
                {"type": "tool_call", "toolCallId": None, "name": [], "args": {}, "iteration": 1},
                {"type": "tool_result", "toolCallId": None, "name": [], "iteration": 1},
                {"type": "usage"},
            ),
            1,
        ),
        (
            PiBackend(),
            (
                {"type": "tool_execution_start", "toolCallId": None, "toolName": [], "args": {}},
                {"type": "tool_execution_end", "toolCallId": None, "toolName": []},
                {"type": "agent_settled"},
            ),
            1,
        ),
    ],
    ids=["cursor-subtype", "codex-item-type", "copilot-tool-name", "litellm-name", "pi-tool-name"],
)
def test_invalid_nested_discriminator_is_safe_and_conservative(backend, events, expected_total, tmp_path):
    path = _write_jsonl(tmp_path / f"{backend.name}-bad-nested-type.jsonl", *events)

    summary = backend.parse_run_metadata(path)["tool_calls"]

    assert summary["total"] == expected_total
    assert summary["is_lower_bound"] is True


@pytest.mark.parametrize(
    ("backend", "events", "expected_tlaps", "expected_other"),
    [
        (
            ClaudeCodeBackend(),
            (
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "stable",
                                "name": "Bash",
                                "input": {"command": TLAPM},
                            }
                        ]
                    },
                },
                {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
                {"type": "result", "subtype": "success"},
            ),
            1,
            0,
        ),
        (
            CodexBackend(),
            (
                {"type": "thread.started", "thread_id": "root"},
                {"type": "turn.started"},
                {
                    "type": "item.started",
                    "item": {"id": "stable", "type": "command_execution", "command": TLAPM},
                },
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": TLAPM},
                },
                {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
            ),
            1,
            0,
        ),
        (
            CursorBackend(),
            (
                {
                    "type": "tool_call",
                    "subtype": "started",
                    "call_id": "stable",
                    "tool_call": {"shellToolCall": {"args": {"command": TLAPM}}},
                },
                {
                    "type": "tool_call",
                    "subtype": "completed",
                    "tool_call": {"shellToolCall": {"args": {"command": TLAPM}}},
                },
                {"type": "result", "subtype": "success", "is_error": False},
            ),
            1,
            0,
        ),
        (
            LiteLLMBackend(),
            (
                {"type": "tool_call", "name": "bash", "args": {"command": TLAPM}, "iteration": 1},
                {"type": "tool_result", "toolCallId": "stable", "name": "bash", "iteration": 1},
                {"type": "usage"},
            ),
            0,
            1,
        ),
        (
            CopilotBackend(),
            (
                {
                    "type": "assistant.message",
                    "data": {
                        "toolRequests": [
                            {
                                "name": "bash",
                                "toolCallId": "stable",
                                "arguments": {"command": TLAPM},
                            }
                        ]
                    },
                },
                {
                    "type": "tool.execution_start",
                    "data": {"toolName": "bash", "arguments": {"command": TLAPM}},
                },
                {"type": "tool.execution_complete", "data": {"toolCallId": "stable"}},
                {"type": "result", "exitCode": 0},
            ),
            1,
            0,
        ),
        (
            PiBackend(),
            (
                {
                    "type": "tool_execution_start",
                    "toolCallId": "stable",
                    "toolName": "bash",
                    "args": {"command": TLAPM},
                },
                {"type": "tool_execution_end", "toolName": "bash"},
                {"type": "agent_settled"},
            ),
            1,
            0,
        ),
    ],
    ids=["claude_code", "codex", "cursor", "litellm", "copilot", "pi"],
)
def test_stable_ids_dominate_anonymous_lifecycle_witnesses(
    backend,
    events,
    expected_tlaps,
    expected_other,
    tmp_path,
):
    path = _write_jsonl(tmp_path / f"{backend.name}-mixed-identity.jsonl", *events)

    summary = backend.parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["tlaps"], summary["other"]) == (1, expected_tlaps, expected_other)
    assert summary["complete"] is False
    assert summary["is_lower_bound"] is True


# --- per-backend event vocabularies -----------------------------------------


def _cursor_call(
    kind,
    command=None,
    subtype="started",
    call_id=None,
    *,
    metadata=None,
    metadata_first=False,
    include_call_id=True,
):
    args = {"command": command} if command is not None else {}
    body = {"args": args}
    tool = {kind: body}
    metadata = metadata or {}
    raw_call = {**metadata, **tool} if metadata_first else {**tool, **metadata}
    event = {
        "type": "tool_call",
        "subtype": subtype,
        "tool_call": raw_call,
    }
    if include_call_id:
        event["call_id"] = call_id or f"{kind}:{command or ''}"
    return event


def test_cursor_counts_a_started_completed_pair_once(tmp_path):
    path = _write_jsonl(
        tmp_path / "cursor.jsonl",
        {"type": "system", "subtype": "init"},
        _cursor_call("shellToolCall", TLAPM),
        _cursor_call("shellToolCall", TLAPM, subtype="completed"),
        _cursor_call("editToolCall"),
        _cursor_call("editToolCall", subtype="completed"),
        _cursor_call("shellToolCall", APALACHE),
        _cursor_call("shellToolCall", APALACHE, subtype="completed"),
        {"type": "result", "subtype": "success", "is_error": False},
    )
    assert CursorBackend().parse_run_metadata(path) == {"tool_calls": _summary(total=3, tlaps=1, apalache=1, other=1)}


@pytest.mark.parametrize(
    ("started_metadata_first", "completed_metadata_first"),
    [(False, False), (True, True), (True, False), (False, True)],
)
def test_cursor_ignores_tool_call_metadata_in_any_field_order(
    tmp_path,
    started_metadata_first,
    completed_metadata_first,
):
    metadata = {
        "hookAdditionalContexts": [],
        "toolCallId": "native-call",
        "startedAtMs": "123",
    }
    path = _write_jsonl(
        tmp_path / "cursor-metadata.jsonl",
        _cursor_call(
            "shellToolCall",
            "tlapm --version",
            call_id="outer-call",
            metadata=metadata,
            metadata_first=started_metadata_first,
        ),
        _cursor_call(
            "shellToolCall",
            "tlapm --version",
            subtype="completed",
            call_id="outer-call",
            metadata=metadata,
            metadata_first=completed_metadata_first,
        ),
        {"type": "result", "subtype": "success", "is_error": False},
    )

    assert CursorBackend().parse_run_metadata(path)["tool_calls"] == _summary(total=1, tlaps=1)


def test_cursor_ignores_metadata_on_non_shell_tools(tmp_path):
    metadata = {"toolCallId": "native-edit", "completedAtMs": "456"}
    path = _write_jsonl(
        tmp_path / "cursor-edit-metadata.jsonl",
        _cursor_call("editToolCall", call_id="outer-edit", metadata=metadata, metadata_first=True),
        _cursor_call(
            "editToolCall",
            subtype="completed",
            call_id="outer-edit",
            metadata=metadata,
        ),
        {"type": "result", "subtype": "success", "is_error": False},
    )

    assert CursorBackend().parse_run_metadata(path)["tool_calls"] == _summary(total=1, other=1)


@pytest.mark.parametrize(
    "raw_call",
    [
        {"toolCallId": "metadata-only", "startedAtMs": "123"},
        {
            "shellToolCall": {"args": {"command": "tlapm Foo.tla"}},
            "editToolCall": {"args": {"path": "Foo.tla"}},
        },
    ],
    ids=("zero-tool-fields", "two-tool-fields"),
)
def test_cursor_damaged_tool_call_objects_are_not_guessed(raw_call, tmp_path):
    started = {"type": "tool_call", "subtype": "started", "call_id": "damaged", "tool_call": raw_call}
    completed = {"type": "tool_call", "subtype": "completed", "call_id": "damaged", "tool_call": raw_call}
    path = _write_jsonl(
        tmp_path / "cursor-damaged-call.jsonl",
        started,
        completed,
        {"type": "result", "subtype": "success", "is_error": False},
    )

    summary = CursorBackend().parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["other"]) == (1, 1)
    assert summary["is_lower_bound"] is True
    assert any("invalid tool_call object" in warning for warning in summary["warnings"])


def test_cursor_does_not_substitute_inner_tool_id_for_missing_outer_call_id(tmp_path):
    metadata = {"toolCallId": "inner-id", "startedAtMs": "123"}
    path = _write_jsonl(
        tmp_path / "cursor-missing-outer-id.jsonl",
        _cursor_call(
            "shellToolCall",
            TLAPM,
            metadata=metadata,
            metadata_first=True,
            include_call_id=False,
        ),
        _cursor_call(
            "shellToolCall",
            TLAPM,
            subtype="completed",
            metadata=metadata,
            include_call_id=False,
        ),
        {"type": "result", "subtype": "success", "is_error": False},
    )

    summary = CursorBackend().parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True
    assert any("missing or invalid call_id" in warning for warning in summary["warnings"])


def test_cursor_completion_without_start_is_counted_but_not_claimed_exact(tmp_path):
    path = _write_jsonl(
        tmp_path / "cursor-orphan.jsonl",
        _cursor_call("shellToolCall", TLAPM, subtype="completed"),
        {"type": "result", "subtype": "success", "is_error": False},
    )
    assert CursorBackend().parse_run_metadata(path)["tool_calls"] == _summary(
        total=1,
        tlaps=1,
        complete=False,
        warnings=("Cursor tool completion is missing its start event",),
    )


def test_cursor_correlates_out_of_order_lifecycle_by_native_id(tmp_path):
    path = _write_jsonl(
        tmp_path / "cursor-mismatch.jsonl",
        _cursor_call("editToolCall", subtype="started", call_id="edit"),
        _cursor_call("shellToolCall", TLAPM, subtype="completed", call_id="shell"),
        {"type": "result", "subtype": "success", "is_error": False},
    )

    summary = CursorBackend().parse_run_metadata(path)["tool_calls"]
    assert (summary["total"], summary["tlaps"], summary["other"]) == (2, 1, 1)
    assert summary["is_lower_bound"] is True


def test_cursor_invalid_subtype_reuses_its_valid_call_id_witness(tmp_path):
    invalid = _cursor_call("shellToolCall", TLAPM, call_id="same")
    invalid["subtype"] = []
    path = _write_jsonl(
        tmp_path / "cursor-invalid-subtype.jsonl",
        invalid,
        _cursor_call("shellToolCall", TLAPM, subtype="started", call_id="same"),
        _cursor_call("shellToolCall", TLAPM, subtype="completed", call_id="same"),
        {"type": "result"},
    )

    summary = CursorBackend().parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True


def test_claude_code_counts_tool_use_blocks(tmp_path):
    path = _write_jsonl(
        tmp_path / "cc.jsonl",
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "checking"},
                    {"type": "tool_use", "id": "bash-1", "name": "Bash", "input": {"command": TLAPM}},
                    {
                        "type": "tool_use",
                        "id": "edit-1",
                        "name": "Edit",
                        "input": {"file_path": "Foo.tla"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "bash-1"},
                    {"type": "tool_result", "tool_use_id": "edit-1"},
                ]
            },
        },
        {"type": "result", "subtype": "success", "is_error": False},
    )
    assert ClaudeCodeBackend().parse_run_metadata(path) == {"tool_calls": _summary(total=2, tlaps=1, other=1)}


def test_claude_only_classifies_the_native_bash_tool_as_shell(tmp_path):
    path = _write_jsonl(
        tmp_path / "cc-nonshell.jsonl",
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "edit-1",
                        "name": "Edit",
                        "input": {"command": TLAPM},
                    }
                ]
            },
        },
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "edit-1"}]}},
        {"type": "result", "subtype": "success"},
    )

    assert ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"] == _summary(total=1, other=1)


def test_claude_missing_tool_id_preserves_the_call_as_a_lower_bound(tmp_path):
    anonymous_call = {"type": "tool_use", "name": "Bash", "input": {"command": TLAPM}}
    path = _write_jsonl(
        tmp_path / "cc-missing-id.jsonl",
        {
            "type": "assistant",
            "message": {"content": [anonymous_call]},
        },
        # Replaying an ID-less event cannot establish a second distinct call.
        {"type": "assistant", "message": {"content": [anonymous_call]}},
        {"type": "result", "subtype": "success"},
    )

    summary = ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]
    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True


def test_claude_unfinished_and_orphan_tool_lifecycles_are_lower_bounds(tmp_path):
    unfinished = _write_jsonl(
        tmp_path / "cc-unfinished.jsonl",
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": TLAPM}}]},
        },
        {"type": "result", "subtype": "error_during_execution"},
    )
    orphan = _write_jsonl(
        tmp_path / "cc-orphan.jsonl",
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "lost"}]}},
        {"type": "result", "subtype": "success"},
    )

    unfinished_summary = ClaudeCodeBackend().parse_run_metadata(unfinished)["tool_calls"]
    orphan_summary = ClaudeCodeBackend().parse_run_metadata(orphan)["tool_calls"]

    assert (unfinished_summary["total"], unfinished_summary["tlaps"]) == (1, 1)
    assert unfinished_summary["is_lower_bound"] is True
    assert (orphan_summary["total"], orphan_summary["other"]) == (1, 1)
    assert orphan_summary["is_lower_bound"] is True


def test_claude_duplicate_tool_result_id_is_not_double_counted(tmp_path):
    tool_result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "call-1"}]}}
    path = _write_jsonl(
        tmp_path / "cc-duplicate-result.jsonl",
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": TLAPM}}]},
        },
        tool_result,
        tool_result,
        {"type": "result", "subtype": "success"},
    )

    summary = ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True


@pytest.mark.parametrize("result_first", [False, True])
def test_claude_rejects_duplicate_or_out_of_order_native_ids(result_first, tmp_path):
    tool_use = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": TLAPM}}]},
    }
    tool_result = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "call-1"}]}}
    lifecycle = [tool_result, tool_use] if result_first else [tool_use, tool_use, tool_result]
    path = _write_jsonl(
        tmp_path / "cc-invalid-native-id.jsonl",
        *lifecycle,
        {"type": "result", "subtype": "success"},
    )

    summary = ClaudeCodeBackend().parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True


def test_codex_counts_acting_items_not_the_model_talking(tmp_path):
    path = _write_jsonl(
        tmp_path / "codex.jsonl",
        {"type": "thread.started", "thread_id": "root"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "reasoning", "type": "reasoning", "text": "thinking"}},
        {
            "type": "item.completed",
            "item": {"id": "message", "type": "agent_message", "text": "here goes"},
        },
        {"type": "item.started", "item": {"id": "command", "type": "command_execution", "command": TLC}},
        {"type": "item.completed", "item": {"id": "command", "type": "command_execution", "command": TLC}},
        {"type": "item.started", "item": {"id": "edit", "type": "file_change", "path": "Foo.tla"}},
        {"type": "item.completed", "item": {"id": "edit", "type": "file_change", "path": "Foo.tla"}},
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    )
    assert CodexBackend().parse_run_metadata(path) == {"tool_calls": _summary(total=2, tlc=1, other=1)}


def test_litellm_counts_agent_dispatched_calls(tmp_path):
    path = _write_jsonl(
        tmp_path / "litellm.jsonl",
        {"type": "response", "text": "let me check"},
        {"type": "tool_call", "toolCallId": "1", "name": "bash", "args": {"command": TLAPM}, "iteration": 1},
        {"type": "tool_result", "toolCallId": "1", "name": "bash", "result": "proved", "iteration": 1},
        {"type": "tool_call", "toolCallId": "2", "name": "write_file", "args": {"path": "Foo.tla"}, "iteration": 2},
        {"type": "tool_result", "toolCallId": "2", "name": "write_file", "result": "OK", "iteration": 2},
        {"type": "usage"},
    )
    assert LiteLLMBackend().parse_run_metadata(path) == {"tool_calls": _summary(total=2, tlaps=1, other=1)}


def test_copilot_counts_tool_requests_on_the_assistant_message(tmp_path):
    path = _write_jsonl(
        tmp_path / "copilot.jsonl",
        {
            "type": "assistant.message",
            "data": {
                "content": "running the prover",
                "toolRequests": [
                    {"name": "bash", "toolCallId": "1", "arguments": {"command": TLAPM}},
                    {"name": "str_replace", "toolCallId": "2", "arguments": {"path": "Foo.tla"}},
                ],
            },
        },
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "1", "toolName": "bash", "arguments": {"command": TLAPM}},
        },
        {"type": "tool.execution_complete", "data": {"toolCallId": "1", "success": True}},
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "2", "toolName": "str_replace", "arguments": {"path": "Foo.tla"}},
        },
        {"type": "tool.execution_complete", "data": {"toolCallId": "2", "success": True}},
        {"type": "result", "exitCode": 0},
    )
    assert CopilotBackend().parse_run_metadata(path) == {"tool_calls": _summary(total=2, tlaps=1, other=1)}


def test_copilot_deduplicates_repeated_request_ids(tmp_path):
    request = {
        "type": "assistant.message",
        "data": {"toolRequests": [{"name": "bash", "toolCallId": "same", "arguments": {"command": TLAPM}}]},
    }
    path = _write_jsonl(
        tmp_path / "copilot-duplicate.jsonl",
        request,
        request,
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "same", "toolName": "bash", "arguments": {"command": TLAPM}},
        },
        {"type": "tool.execution_complete", "data": {"toolCallId": "same", "success": True}},
        {"type": "result", "exitCode": 1},
    )
    summary = CopilotBackend().parse_run_metadata(path)["tool_calls"]
    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True


def test_copilot_orphan_native_lifecycle_is_counted_as_a_lower_bound(tmp_path):
    path = _write_jsonl(
        tmp_path / "copilot-orphan.jsonl",
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "orphan", "toolName": "bash", "arguments": {"command": TLAPM}},
        },
        {"type": "tool.execution_complete", "data": {"toolCallId": "orphan", "success": True}},
        {"type": "result", "exitCode": 0},
    )

    summary = CopilotBackend().parse_run_metadata(path)["tool_calls"]
    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True


def test_copilot_only_classifies_the_native_bash_tool_as_shell(tmp_path):
    request = {
        "type": "assistant.message",
        "data": {"toolRequests": [{"name": "str_replace", "toolCallId": "edit", "arguments": {"command": TLAPM}}]},
    }
    path = _write_jsonl(
        tmp_path / "copilot-nonshell.jsonl",
        request,
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "edit", "toolName": "str_replace", "arguments": {"command": TLAPM}},
        },
        {"type": "tool.execution_complete", "data": {"toolCallId": "edit", "success": True}},
        {"type": "result", "exitCode": 0},
    )

    assert CopilotBackend().parse_run_metadata(path)["tool_calls"] == _summary(total=1, other=1)


def test_copilot_latches_activity_after_terminal_and_rejects_duplicate_terminals(tmp_path):
    trailing = _write_jsonl(
        tmp_path / "copilot-trailing.jsonl",
        {"type": "result", "exitCode": 0},
        {"type": "assistant.message", "data": {"toolRequests": []}},
        {"type": "session.shutdown", "data": {"shutdownType": "routine"}},
    )
    duplicate = _write_jsonl(
        tmp_path / "copilot-duplicate-terminal.jsonl",
        {"type": "result", "exitCode": 0},
        {"type": "result", "exitCode": 0},
    )

    for path in (trailing, duplicate):
        summary = CopilotBackend().parse_run_metadata(path)["tool_calls"]
        assert summary["complete"] is False
        assert summary["is_lower_bound"] is True


@pytest.mark.parametrize("order", [("start", "request", "complete"), ("request", "complete", "start")])
def test_copilot_rejects_out_of_order_native_lifecycle(order, tmp_path):
    events = {
        "request": {
            "type": "assistant.message",
            "data": {"toolRequests": [{"name": "bash", "toolCallId": "call", "arguments": {"command": TLAPM}}]},
        },
        "start": {
            "type": "tool.execution_start",
            "data": {"toolCallId": "call", "toolName": "bash", "arguments": {"command": TLAPM}},
        },
        "complete": {"type": "tool.execution_complete", "data": {"toolCallId": "call"}},
    }
    path = _write_jsonl(
        tmp_path / "copilot-out-of-order.jsonl",
        *(events[name] for name in order),
        {"type": "result"},
    )

    summary = CopilotBackend().parse_run_metadata(path)["tool_calls"]

    assert (summary["total"], summary["tlaps"]) == (1, 1)
    assert summary["is_lower_bound"] is True
    assert any("out-of-order" in warning for warning in summary["warnings"])


@pytest.mark.parametrize(
    "backend",
    [CursorBackend(), ClaudeCodeBackend(), CodexBackend(), LiteLLMBackend(), CopilotBackend(), PiBackend()],
    ids=["cursor", "claude_code", "codex", "litellm", "copilot", "pi"],
)
def test_an_init_only_stream_reports_zero_as_a_lower_bound(backend, tmp_path):
    path = _write_jsonl(tmp_path / f"{backend.name}-empty.jsonl", {"type": "system", "subtype": "init"})
    summary = backend.parse_run_metadata(path)["tool_calls"]
    assert summary["total"] == 0
    assert summary["complete"] is False
    assert summary["is_lower_bound"] is True


# --- the count reaching the recorded result ---------------------------------


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


def test_the_tally_is_recorded_in_result_json(tmp_path, monkeypatch):
    """End to end through the runner: a real backend's count lands in the result.

    Counting is worth nothing if it stops at the backend, so this drives
    run_single_benchmark with the agent and grader faked out — no container, no CLI —
    and reads the file a consumer would actually receive.
    """
    from evaluator import runner

    bench_path = tmp_path / "bench" / "Foo" / "Bar.tla"
    bench_path.parent.mkdir(parents=True)
    bench_path.write_text("---- MODULE Bar ----\n====\n")
    item = runner.WorkItem(
        benchmark_path=str(bench_path),
        output_dir=str(tmp_path / "out"),
        timeout=10,
        check_timeout=10,
        backend=CursorBackend(),  # ty:ignore[invalid-argument-type]
        mode=_FakeMode(str(tmp_path / "bench")),  # ty:ignore[invalid-argument-type]
        tlapm_path="/bin/true",
        tlapm_lib="",
    )

    def fake_agent(item_, backend_, mode, workspace, agent_dir, agent_jsonl, prompt, result, checker, canonical=None):
        _write_jsonl(
            Path(agent_jsonl),
            {"type": "system", "subtype": "init", "model": "Composer 2.5"},
            _cursor_call("shellToolCall", TLAPM),
            _cursor_call("shellToolCall", TLAPM, subtype="completed"),
            _cursor_call("shellToolCall", APALACHE),
            _cursor_call("shellToolCall", APALACHE, subtype="completed"),
            _cursor_call("editToolCall"),
            _cursor_call("editToolCall", subtype="completed"),
            {"type": "result", "subtype": "success", "is_error": False, "result": "done"},
        )
        result["agent_exit"] = 0

    def fake_grader(item_, workspace, basename, grading_dir, check_result_path, result, canonical_dir=None):
        result["check_verdict"] = "FAIL"

    monkeypatch.setattr(runner, "_run_backend_local", fake_agent)
    monkeypatch.setattr(runner, "_run_grader_local", fake_grader)

    result = runner.run_single_benchmark(item)
    expected = _summary(total=3, tlaps=1, apalache=1, other=1)
    assert result["tool_calls"] == expected

    written = json.loads((Path(item.output_dir) / "Foo" / "Bar" / "result.json").read_text())
    assert written["tool_calls"] == expected

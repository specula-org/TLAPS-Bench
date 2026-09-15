"""Focused tests for the checker’s complete module-task path."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from common import check_proof
from common.proof_from_scratch_module import begin_agent_proof, end_agent_proof
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS
from evaluator.proof_module_result import validate_module_result
from tlacore.model import Loc, Module, Theorem
from tlacore.sany.dump import SanyRun, SanyStatus

UNIT_A = "Suite/Task_A.tla"
UNIT_B = "Suite/Task_B.tla"
HELPER = "helper:Bridge"


def _unit(
    unit_id: str,
    *,
    kind: str = "target",
    theorem_name: str | None = "Target",
    line_start: int = 10,
    line_end: int = 20,
    dependencies: tuple[str, ...] = (),
    admitted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        unit_id=unit_id,
        kind=kind,
        theorem_name=theorem_name,
        line_start=line_start,
        line_end=line_end,
        dependencies=dependencies,
        admitted=admitted,
    )


def _analysis(
    target_units: tuple[SimpleNamespace, ...],
    helper_units: tuple[SimpleNamespace, ...] = (),
) -> SimpleNamespace:
    checked_units = (*target_units, *helper_units)
    return SimpleNamespace(
        target_units=target_units,
        helper_units=helper_units,
        checked_units=checked_units,
        local_dependencies={unit.unit_id: unit.dependencies for unit in checked_units},
        unused_helper_names=(),
    )


def _write_inputs(
    tmp_path,
    *,
    canonical_source: str = "---- MODULE Task ----\n====\n",
    submitted_source: str | None = None,
    context: tuple[tuple[str, str], ...] = (),
):
    workspace = tmp_path / "workspace"
    benchmark = tmp_path / "canonical"
    workspace.mkdir()
    benchmark.mkdir()
    if submitted_source is None:
        submitted_source = canonical_source
    (workspace / "Task.tla").write_text(submitted_source, encoding="utf-8")
    (benchmark / "Task.tla").write_text(canonical_source, encoding="utf-8")
    for name, source in context:
        (benchmark / name).write_text(source, encoding="utf-8")
        (workspace / name).write_text(source, encoding="utf-8")
    return workspace / "Task.tla", benchmark


def _valid_sany() -> SanyRun:
    return SanyRun(SanyStatus.VALID, ("sany",), 0, "", "", "", {})


def _report(lines: list[str]) -> dict[str, object]:
    reports = [
        line.removeprefix(check_proof.MODULE_RESULT_PREFIX)
        for line in lines
        if line.startswith(check_proof.MODULE_RESULT_PREFIX)
    ]
    assert len(reports) == 1
    return json.loads(reports[0])


def _tlapm_responses(responses: dict[int, tuple[str, str, int]], calls: list[list[str]]):
    def run(command, _timeout, _cwd):
        calls.append(command)
        start = int(command[command.index("--toolbox") + 1])
        return responses[start]

    return run


def _patch_common(monkeypatch, analysis, *, run_killgroup):
    monkeypatch.setattr(check_proof, "run_normalized", lambda *_args, **_kwargs: _valid_sany())
    monkeypatch.setattr(check_proof, "analyze_module_submission", lambda **_kwargs: analysis)
    monkeypatch.setattr(check_proof, "find_community_lib", lambda _filepath: None)
    monkeypatch.setattr(check_proof, "run_killgroup", run_killgroup)


def _run_module_check(monkeypatch, tmp_path, analysis, *, responses, context=()):
    filepath, benchmark = _write_inputs(tmp_path, context=context)
    calls: list[list[str]] = []
    _patch_common(monkeypatch, analysis, run_killgroup=_tlapm_responses(responses, calls))
    lines: list[str] = []
    output = tmp_path / "check.result"
    exit_code = check_proof.run_module_task_check(
        filepath=str(filepath),
        benchmark_dir=str(benchmark),
        expected_unit_ids=tuple(unit.unit_id for unit in analysis.target_units),
        tlapm_path="tlapm",
        tlapm_lib="/tlaps/lib",
        timeout=30,
        output_path=str(output),
        import_violations=[],
        emit=lines.append,
    )
    return exit_code, lines, calls


def test_module_check_reports_raw_results_and_dependency_closed_trust(tmp_path, monkeypatch):
    target_a = _unit(UNIT_A, theorem_name="A", line_start=10)
    target_b = _unit(UNIT_B, theorem_name="B", line_start=50, line_end=60, dependencies=(HELPER,))
    helper = _unit(HELPER, kind="helper", theorem_name="Bridge", line_start=30, line_end=40)
    analysis = _analysis((target_a, target_b), (helper,))
    passed = ("[INFO]: All 1 obligation proved.\n", "", 0)

    exit_code, lines, _calls = _run_module_check(
        monkeypatch,
        tmp_path,
        analysis,
        responses={10: passed, 30: passed, 50: passed},
    )

    assert exit_code == 0
    report = _report(lines)
    assert report["proof_unit_ids"] == [UNIT_A, UNIT_B]
    assert report["trusted_unit_ids"] == [UNIT_A, UNIT_B, HELPER]
    assert report["trusted_proof_unit_ids"] == [UNIT_A, UNIT_B]
    assert report["complete"] is True
    units = {unit["unit_id"]: unit for unit in report["units"]}
    assert {unit_id: unit["raw_verdict"] for unit_id, unit in units.items()} == {
        UNIT_A: "PASS",
        UNIT_B: "PASS",
        HELPER: "PASS",
    }
    assert all(unit["trusted"] for unit in units.values())
    assert {unit_id: unit["obligations"] for unit_id, unit in units.items()} == {
        UNIT_A: 1,
        UNIT_B: 1,
        HELPER: 1,
    }
    validate_module_result(report, (UNIT_A, UNIT_B))


def _marked_source(unit_id: str, proof: str = "PROOF OMITTED") -> str:
    return "\n".join(
        (
            "---- MODULE Task ----",
            BEGIN_AGENT_HELPERS,
            END_AGENT_HELPERS,
            "",
            "THEOREM Target == TRUE",
            begin_agent_proof(unit_id),
            proof,
            end_agent_proof(unit_id),
            "====",
            "",
        )
    )


def _module_for_marked_source(source: str, unit_id: str) -> Module:
    lines = source.splitlines()
    statement = lines.index("THEOREM Target == TRUE") + 1
    begin = lines.index(begin_agent_proof(unit_id)) + 1
    end = lines.index(end_agent_proof(unit_id)) + 1
    body = begin + 1
    theorem = Theorem(
        name="Target",
        loc=Loc(statement, 1, end, 1),
        statement_loc=Loc(statement, 1, statement, 22),
        proof_loc=Loc(body, 1, body, len(lines[body - 1]) + 1),
        proof_is_omitted=True,
        references=[],
        statement_references=[],
        shape={},
    )
    return Module(
        name="Task",
        source_file="Task.tla",
        filename="Task.tla",
        line_start=1,
        line_end=len(lines),
        extends=[],
        constants=[],
        variables=[],
        assumes=[],
        instances=[],
        operators=[],
        spec_formulas=[],
        theorems=[theorem],
    )


def test_unchanged_proof_omitted_is_unresolved_and_not_trusted(tmp_path, monkeypatch):
    unit_id = UNIT_A
    source = _marked_source(unit_id)
    filepath, benchmark = _write_inputs(tmp_path, canonical_source=source)
    module = _module_for_marked_source(source, unit_id)
    monkeypatch.setattr(check_proof, "run_normalized", lambda *_args, **_kwargs: _valid_sany())
    monkeypatch.setattr(check_proof.Module, "parse", lambda _raw: module)
    monkeypatch.setattr(check_proof, "find_community_lib", lambda _filepath: None)
    monkeypatch.setattr(
        check_proof,
        "run_killgroup",
        lambda *_args, **_kwargs: pytest.fail("an admitted PROOF OMITTED unit must not invoke TLAPM"),
    )
    lines: list[str] = []

    exit_code = check_proof.run_module_task_check(
        filepath=str(filepath),
        benchmark_dir=str(benchmark),
        expected_unit_ids=(unit_id,),
        tlapm_path="tlapm",
        tlapm_lib="/tlaps/lib",
        timeout=30,
        output_path=str(tmp_path / "check.result"),
        import_violations=[],
        emit=lines.append,
    )

    assert exit_code == 1
    report = _report(lines)
    assert report["units"][0]["raw_verdict"] == "UNRESOLVED"
    assert report["units"][0]["missing_proofs"] == 1
    assert report["units"][0]["trusted"] is False
    assert report["trusted_unit_ids"] == []
    assert report["trusted_proof_unit_ids"] == []
    assert report["complete"] is False
    validate_module_result(report, (unit_id,))


def test_extra_eof_newlines_do_not_fail_module_integrity(tmp_path, monkeypatch):
    unit_id = UNIT_A
    canonical_source = _marked_source(unit_id)
    submitted_source = canonical_source + "\r\n\n"
    filepath, benchmark = _write_inputs(
        tmp_path,
        canonical_source=canonical_source,
        submitted_source=submitted_source,
    )
    module = _module_for_marked_source(submitted_source, unit_id)
    monkeypatch.setattr(check_proof, "run_normalized", lambda *_args, **_kwargs: _valid_sany())
    monkeypatch.setattr(check_proof.Module, "parse", lambda _raw: module)
    monkeypatch.setattr(check_proof, "find_community_lib", lambda _filepath: None)
    monkeypatch.setattr(
        check_proof,
        "run_killgroup",
        lambda *_args, **_kwargs: pytest.fail("an admitted PROOF OMITTED unit must not invoke TLAPM"),
    )
    lines: list[str] = []

    exit_code = check_proof.run_module_task_check(
        filepath=str(filepath),
        benchmark_dir=str(benchmark),
        expected_unit_ids=(unit_id,),
        tlapm_path="tlapm",
        tlapm_lib="/tlaps/lib",
        timeout=30,
        output_path=str(tmp_path / "check.result"),
        import_violations=[],
        emit=lines.append,
    )

    assert exit_code == 1
    report = _report(lines)
    assert "integrity_issues" not in report
    assert report["units"][0]["raw_verdict"] == "UNRESOLVED"
    assert not any(line.startswith("CHEAT-DETECTED:") for line in lines)


@pytest.mark.parametrize(
    "transform",
    [
        lambda source: source.replace("\n", "\r\n"),
        lambda source: source.removesuffix("\n"),
    ],
    ids=("line-ending-style", "missing-final-newline"),
)
def test_newline_only_module_integrity_failure_is_not_cheating(tmp_path, monkeypatch, transform):
    unit_id = UNIT_A
    canonical_source = _marked_source(unit_id)
    submitted_source = transform(canonical_source)
    filepath, benchmark = _write_inputs(
        tmp_path,
        canonical_source=canonical_source,
        submitted_source=submitted_source,
    )
    module = _module_for_marked_source(submitted_source, unit_id)
    monkeypatch.setattr(check_proof, "run_normalized", lambda *_args, **_kwargs: _valid_sany())
    monkeypatch.setattr(check_proof.Module, "parse", lambda _raw: module)
    monkeypatch.setattr(
        check_proof,
        "run_killgroup",
        lambda *_args, **_kwargs: pytest.fail("an integrity failure must stop TLAPM"),
    )
    lines: list[str] = []

    exit_code = check_proof.run_module_task_check(
        filepath=str(filepath),
        benchmark_dir=str(benchmark),
        expected_unit_ids=(unit_id,),
        tlapm_path="tlapm",
        tlapm_lib="/tlaps/lib",
        timeout=30,
        output_path=str(tmp_path / "check.result"),
        import_violations=[],
        emit=lines.append,
    )

    assert exit_code == 1
    report = _report(lines)
    assert [issue["code"] for issue in report["integrity_issues"]] == ["SCAFFOLD_FORMAT_MODIFIED"]
    assert any(line.startswith("FAIL SCAFFOLD_FORMAT_MODIFIED:") for line in lines)
    assert "GATES-FAILED: module_integrity" in lines
    assert not any(line.startswith("CHEAT-DETECTED:") for line in lines)


def test_raw_pass_with_untrusted_dependency_is_blocked(tmp_path, monkeypatch):
    admitted = _unit(UNIT_A, theorem_name="A", line_start=10, admitted=True)
    dependent = _unit(UNIT_B, theorem_name="B", line_start=50, line_end=60, dependencies=(UNIT_A,))
    analysis = _analysis((admitted, dependent))
    passed = ("[INFO]: All 1 obligation proved.\n", "", 0)

    exit_code, lines, calls = _run_module_check(
        monkeypatch,
        tmp_path,
        analysis,
        responses={50: passed},
    )

    assert exit_code == 1
    assert len(calls) == 1
    report = _report(lines)
    units = {unit["unit_id"]: unit for unit in report["units"]}
    assert units[UNIT_A]["raw_verdict"] == "UNRESOLVED"
    assert units[UNIT_B]["raw_verdict"] == "PASS"
    assert units[UNIT_A]["trusted"] is False
    assert units[UNIT_B]["trusted"] is False
    assert report["trusted_unit_ids"] == []
    assert report["trusted_proof_unit_ids"] == []
    assert report["complete"] is False
    validate_module_result(report, (UNIT_A, UNIT_B))


def test_tlapm_exit_eleven_cannot_be_a_raw_module_unit_pass(tmp_path, monkeypatch):
    analysis = _analysis((_unit(UNIT_A, theorem_name="A", line_start=10),))
    admitted_output = (
        "Proof incomplete in module Task: 0 missing, 1 omitted\n",
        "",
        11,
    )

    exit_code, lines, _calls = _run_module_check(
        monkeypatch,
        tmp_path,
        analysis,
        responses={10: admitted_output},
    )

    assert exit_code == 1
    report = _report(lines)
    assert report["units"][0]["raw_verdict"] == "FAIL"
    assert report["units"][0]["tlapm_exit"] == 11
    assert report["units"][0]["trusted"] is False
    assert report["trusted_proof_unit_ids"] == []
    validate_module_result(report, (UNIT_A,))


def test_context_integrity_failure_emits_machine_report_and_exit_one(tmp_path, monkeypatch):
    context_source = "---- MODULE Model ----\n====\n"
    analysis = _analysis((_unit(UNIT_A, line_start=10),))
    filepath, benchmark = _write_inputs(tmp_path, context=(("Model.tla", context_source),))
    (filepath.parent / "Model.tla").write_text(
        "---- MODULE Model ----\nTHEOREM Changed == TRUE\n====\n", encoding="utf-8"
    )
    _patch_common(monkeypatch, analysis, run_killgroup=lambda *_args: pytest.fail("context failure must stop TLAPM"))
    lines: list[str] = []

    exit_code = check_proof.run_module_task_check(
        filepath=str(filepath),
        benchmark_dir=str(benchmark),
        expected_unit_ids=(UNIT_A,),
        tlapm_path="tlapm",
        tlapm_lib="/tlaps/lib",
        timeout=30,
        output_path=str(tmp_path / "check.result"),
        import_violations=[],
        emit=lines.append,
    )

    assert exit_code == 1
    report = _report(lines)
    assert report["units"] == []
    assert report["trusted_unit_ids"] == []
    assert report["trusted_proof_unit_ids"] == []
    assert report["complete"] is False
    assert [issue["code"] for issue in report["integrity_issues"]] == ["CONTEXT_MODIFIED"]
    assert "CHEAT-DETECTED: CONTEXT_MODIFIED" in lines
    validate_module_result(report, (UNIT_A,))


def test_context_hardlink_alias_is_rejected(tmp_path):
    context_source = "---- MODULE Model ----\n====\n"
    filepath, benchmark = _write_inputs(tmp_path, context=(("Model.tla", context_source),))
    workspace_context = filepath.parent / "Model.tla"
    workspace_context.unlink()
    os.link(benchmark / "Model.tla", workspace_context)

    assert check_proof._module_context_issues(str(filepath), str(benchmark)) == [
        ("CONTEXT_MODIFIED", "context file 'Model.tla' aliases the canonical input")
    ]


def test_unreferenced_scratch_tla_is_not_submitted_context(tmp_path):
    context_source = "---- MODULE Model ----\n====\n"
    filepath, benchmark = _write_inputs(tmp_path, context=(("Model.tla", context_source),))
    (filepath.parent / "MCTask.tla").write_text("---- MODULE MCTask ----\nEXTENDS Task\n====\n")
    (filepath.parent / "Task_TTrace_1.tla").write_text("---- MODULE Task_TTrace_1 ----\n====\n")

    assert check_proof._module_context_issues(str(filepath), str(benchmark)) == []


def test_unit_checker_error_emits_machine_report_and_exit_three(tmp_path, monkeypatch):
    unit = _unit(UNIT_A, line_start=10)
    analysis = _analysis((unit,))
    filepath, benchmark = _write_inputs(tmp_path)
    _patch_common(monkeypatch, analysis, run_killgroup=lambda *_args: (_ for _ in ()).throw(OSError("tlapm missing")))
    lines: list[str] = []

    exit_code = check_proof.run_module_task_check(
        filepath=str(filepath),
        benchmark_dir=str(benchmark),
        expected_unit_ids=(UNIT_A,),
        tlapm_path="tlapm",
        tlapm_lib="/tlaps/lib",
        timeout=30,
        output_path=str(tmp_path / "check.result"),
        import_violations=[],
        emit=lines.append,
    )

    assert exit_code == 3
    report = _report(lines)
    assert report["units"][0]["raw_verdict"] == "ERROR"
    assert report["units"][0]["trusted"] is False
    assert report["complete"] is False
    validate_module_result(report, (UNIT_A,))

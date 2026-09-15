"""Focused tests for module checker reports and their runner parser seam."""

from __future__ import annotations

import json

import pytest

from evaluator.proof_module_result import (
    MODULE_RESULT_PREFIX,
    MODULE_RESULT_SCHEMA_VERSION,
    ModuleResultError,
    module_result_from_result,
    parse_module_result_json,
    validate_module_result,
)
from evaluator.runner import _parse_grader_result

UNIT_A = "Suite/Source_A.tla"
UNIT_B = "Suite/Source_B.tla"
HELPER = "helper:Bridge"
EXPECTED_UNITS = (UNIT_A, UNIT_B)


def _unit(
    unit_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    raw_verdict: str = "PASS",
    tlapm_exit: int | None = 0,
    missing_proofs: int | None = 0,
    obligation_failed: bool | None = False,
    obligations: int | None = 3,
    trusted: bool = True,
) -> dict[str, object]:
    kind = "helper" if unit_id.startswith("helper:") else "target"
    return {
        "unit_id": unit_id,
        "kind": kind,
        "theorem_name": unit_id.rsplit("/", 1)[-1].removesuffix(".tla") if kind == "target" else "Bridge",
        "line_start": 10 if unit_id == UNIT_A else 20 if unit_id == HELPER else 30,
        "line_end": 11 if unit_id == UNIT_A else 21 if unit_id == HELPER else 31,
        "dependencies": list(dependencies),
        "raw_verdict": raw_verdict,
        "tlapm_exit": tlapm_exit,
        "missing_proofs": missing_proofs,
        "obligation_failed": obligation_failed,
        "obligations": obligations,
        "trusted": trusted,
    }


def _complete_report() -> dict[str, object]:
    units = [
        _unit(UNIT_A),
        _unit(HELPER, dependencies=(UNIT_A,)),
        _unit(UNIT_B, dependencies=(HELPER,)),
    ]
    return {
        "schema_version": MODULE_RESULT_SCHEMA_VERSION,
        "sany_status": "valid",
        "proof_unit_ids": list(EXPECTED_UNITS),
        "units": units,
        "trusted_unit_ids": sorted((UNIT_A, HELPER, UNIT_B)),
        "trusted_proof_unit_ids": list(EXPECTED_UNITS),
        "complete": True,
    }


def _partial_report() -> dict[str, object]:
    units = [
        _unit(UNIT_A),
        _unit(
            UNIT_B,
            raw_verdict="FAIL",
            tlapm_exit=11,
            missing_proofs=1,
            obligation_failed=False,
            obligations=2,
            trusted=False,
        ),
    ]
    return {
        "schema_version": MODULE_RESULT_SCHEMA_VERSION,
        "sany_status": "valid",
        "proof_unit_ids": list(EXPECTED_UNITS),
        "units": units,
        "trusted_unit_ids": [UNIT_A],
        "trusted_proof_unit_ids": [UNIT_A],
        "complete": False,
    }


def _assert_invalid(report: dict[str, object], message: str | None = None) -> None:
    match = pytest.raises(ModuleResultError, match=message) if message else pytest.raises(ModuleResultError)
    with match:
        validate_module_result(report, EXPECTED_UNITS)


def test_accepts_a_complete_dependency_closed_report() -> None:
    report = _complete_report()

    assert validate_module_result(report, EXPECTED_UNITS) == report


def test_accepts_a_partial_report_with_only_the_first_target_trusted() -> None:
    report = _partial_report()

    assert validate_module_result(report, EXPECTED_UNITS) == report


def test_accepts_a_legacy_v1_report_without_obligation_counts() -> None:
    report = _partial_report()
    report["schema_version"] = 1
    for unit in report["units"]:
        unit.pop("obligations")

    assert validate_module_result(report, EXPECTED_UNITS) == report


def test_rejects_pass_evidence_from_tlapm_exit_eleven() -> None:
    report = _complete_report()
    report["units"][0]["tlapm_exit"] = 11

    _assert_invalid(report, "inconsistent PASS evidence")


def test_accepts_sany_invalid_report_without_proof_data() -> None:
    report = {
        "schema_version": MODULE_RESULT_SCHEMA_VERSION,
        "sany_status": "invalid",
        "proof_unit_ids": list(EXPECTED_UNITS),
        "units": [],
        "trusted_unit_ids": [],
        "trusted_proof_unit_ids": [],
        "complete": False,
    }

    assert validate_module_result(report, EXPECTED_UNITS) == report


def test_module_result_from_result_only_extracts_a_mapping_result() -> None:
    report = _partial_report()

    assert module_result_from_result({"module_result": report}) == report
    assert module_result_from_result({}) is None
    assert module_result_from_result({"module_result": None}) is None
    assert module_result_from_result({"module_result": []}) is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report["trusted_unit_ids"].remove(UNIT_A), "trusted-unit set"),
        (lambda report: report["units"][0].update(trusted=False), "per-unit trust"),
        (
            lambda report: report.update(trusted_proof_unit_ids=[UNIT_B, UNIT_A]),
            "trusted proof-unit IDs|manifest order",
        ),
    ],
)
def test_rejects_inconsistent_trust_evidence(mutate, message: str) -> None:
    report = _complete_report()
    mutate(report)

    _assert_invalid(report, message)


def test_rejects_targets_out_of_manifest_order() -> None:
    report = _complete_report()
    report["units"] = [report["units"][2], report["units"][1], report["units"][0]]

    _assert_invalid(report, "manifest order")


def test_rejects_proof_unit_ids_that_do_not_match_the_selected_task() -> None:
    report = _complete_report()
    report["proof_unit_ids"] = [UNIT_B, UNIT_A]

    _assert_invalid(report, "differ from the selected module task")


@pytest.mark.parametrize(
    ("dependencies", "message"),
    [
        (("helper:Missing",), "unknown local dependencies"),
        ((UNIT_A, UNIT_A), "must not contain duplicates"),
    ],
)
def test_rejects_unknown_or_repeated_dependencies(dependencies: tuple[str, ...], message: str) -> None:
    report = _partial_report()
    report["units"][1]["dependencies"] = list(dependencies)

    _assert_invalid(report, message)


def test_rejects_a_raw_pass_cycle_as_trusted() -> None:
    report = _complete_report()
    report["units"][0]["dependencies"] = [UNIT_B]
    report["units"][2]["dependencies"] = [UNIT_A]

    _assert_invalid(report, "trusted-unit set")


def test_rejects_an_unknown_raw_verdict() -> None:
    report = _partial_report()
    report["units"][1]["raw_verdict"] = "MAYBE"

    _assert_invalid(report, "invalid raw_verdict")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report.pop("units"), "missing or unknown fields"),
        (lambda report: report.update(extra=True), "missing or unknown fields"),
        (lambda report: report.update(schema_version=True), "unsupported"),
        (lambda report: report.update(schema_version=MODULE_RESULT_SCHEMA_VERSION + 1), "unsupported"),
        (lambda report: report.update(sany_status=[]), "sany_status"),
        (lambda report: report.update(sany_status="unknown"), "sany_status"),
    ],
)
def test_rejects_schema_and_status_variants(mutate, message: str) -> None:
    report = _complete_report()
    mutate(report)

    _assert_invalid(report, message)


@pytest.mark.parametrize(
    ("complete", "trusted_targets", "message"),
    [
        (True, [UNIT_A], "trusted proof-unit IDs|trusted proof-unit list"),
        (False, list(EXPECTED_UNITS), "complete flag"),
        (True, [], "trusted proof-unit list"),
    ],
)
def test_rejects_totals_that_disagree_with_trusted_target_coverage(
    complete: bool,
    trusted_targets: list[str],
    message: str,
) -> None:
    report = _complete_report()
    report["complete"] = complete
    report["trusted_proof_unit_ids"] = trusted_targets

    _assert_invalid(report, message)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tlapm_exit", "0"),
        ("missing_proofs", -1),
        ("obligation_failed", "false"),
    ],
)
def test_rejects_malformed_unit_totals(field: str, value: object) -> None:
    report = _partial_report()
    report["units"][0][field] = value

    _assert_invalid(report, f"{field}|invalid|boolean|integer|count")


@pytest.mark.parametrize(("field", "value"), [("kind", []), ("raw_verdict", [])])
def test_rejects_unhashable_unit_enums(field: str, value: object) -> None:
    report = _partial_report()
    report["units"][0][field] = value

    _assert_invalid(report, f"invalid {field}")


def _machine_output(report: dict[str, object], *, status: str = "valid") -> str:
    return f"SANY-STATUS: {status}\n{MODULE_RESULT_PREFIX}{json.dumps(report, separators=(',', ':'))}\n"


def _parse(report: dict[str, object], exit_code: int, *, output: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {}
    _parse_grader_result(
        exit_code,
        _machine_output(report) if output is None else output,
        result,
        expected_module_unit_ids=EXPECTED_UNITS,
    )
    return result


def test_parser_records_complete_report_and_derived_totals() -> None:
    result = _parse(_complete_report(), 0)

    assert result["check_verdict"] == "PASS"
    assert result["proof_unit_count"] == 2
    assert result["trusted_proof_unit_count"] == 2
    assert result["trusted_proof_unit_ids"] == list(EXPECTED_UNITS)
    assert result["obligations"] == 9
    assert result["obligations_complete"] is True


def test_parser_does_not_overwrite_module_obligation_sum_with_last_text_summary() -> None:
    report = _complete_report()
    output = _machine_output(report) + "[INFO]: All 2 obligations proved.\n"

    result = _parse(report, 0, output=output)

    assert result["obligations"] == 9
    assert result["obligations_complete"] is True


def test_parser_records_partial_report_as_fail_with_derived_totals() -> None:
    result = _parse(_partial_report(), 1)

    assert result["check_verdict"] == "FAIL"
    assert result["proof_unit_count"] == 2
    assert result["trusted_proof_unit_count"] == 1
    assert result["trusted_proof_unit_ids"] == [UNIT_A]


def test_parser_reports_known_obligations_as_a_lower_bound_after_unit_timeout() -> None:
    report = _partial_report()
    report["units"][1].update(
        raw_verdict="TIMEOUT",
        tlapm_exit=None,
        missing_proofs=None,
        obligation_failed=None,
        obligations=None,
    )

    result = _parse(report, 3)

    assert result["check_verdict"] == "TIMEOUT"
    assert result["obligations"] == 3
    assert result["obligations_complete"] is False


def test_parser_classifies_an_explicit_pre_result_checker_timeout() -> None:
    result: dict[str, object] = {}

    _parse_grader_result(
        3,
        "SANY-STATUS: unavailable\nCHECK-TIMEOUT: checker budget exhausted\n",
        result,
        expected_module_unit_ids=EXPECTED_UNITS,
    )

    assert result["check_verdict"] == "TIMEOUT"
    assert result["sany_status"] == "unavailable"


def test_parser_keeps_unavailable_sany_without_a_timeout_marker_as_error() -> None:
    result: dict[str, object] = {}

    _parse_grader_result(
        3,
        "SANY-STATUS: unavailable\nERROR: SANY executable missing\n",
        result,
        expected_module_unit_ids=EXPECTED_UNITS,
    )

    assert result["check_verdict"] == "ERROR"


@pytest.mark.parametrize(
    "output",
    [
        "SANY-STATUS: valid\n",
        _machine_output(_partial_report())
        + f"{MODULE_RESULT_PREFIX}{json.dumps(_partial_report(), separators=(',', ':'))}\n",
        f"SANY-STATUS: valid\n{MODULE_RESULT_PREFIX}not-json\n",
        _machine_output(_partial_report()).replace("}\n", "} trailing\n", 1),
    ],
)
def test_parser_requires_exactly_one_valid_machine_result(output: str) -> None:
    result: dict[str, object] = {}
    _parse_grader_result(1, output, result, expected_module_unit_ids=EXPECTED_UNITS)

    assert result["check_verdict"] == "ERROR"
    assert "module" in result["error"]


@pytest.mark.parametrize(
    ("report", "exit_code", "message"),
    [
        (_partial_report(), 0, "exited PASS"),
        (_complete_report(), 1, "exited FAIL"),
    ],
)
def test_parser_rejects_exit_code_and_report_completion_mismatch(
    report: dict[str, object], exit_code: int, message: str
) -> None:
    result = _parse(report, exit_code)

    assert result["check_verdict"] == "ERROR"
    expected_error = (
        f"module grader {message} without trusting every proof unit"
        if exit_code == 0
        else "module grader exited FAIL for a complete trusted module"
    )
    assert result["error"] == expected_error


def test_parser_requires_a_sany_status_marker() -> None:
    result = _parse(_complete_report(), 0, output=f"{MODULE_RESULT_PREFIX}{json.dumps(_complete_report())}\n")

    assert result["check_verdict"] == "ERROR"
    assert result["error"] == "grader did not report a SANY status"


@pytest.mark.parametrize(
    "markers",
    [
        "SANY-STATUS: valid\nSANY-STATUS: valid\n",
        "SANY-STATUS: valid\nSANY-STATUS: invalid\n",
    ],
)
def test_parser_requires_exactly_one_sany_status_marker(markers: str) -> None:
    result: dict[str, object] = {}
    _parse_grader_result(
        1,
        markers + f"{MODULE_RESULT_PREFIX}{json.dumps(_partial_report(), separators=(',', ':'))}\n",
        result,
        expected_module_unit_ids=EXPECTED_UNITS,
    )

    assert result["check_verdict"] == "ERROR"
    assert result["error"] == "grader reported multiple SANY status markers; expected exactly one"


def test_parser_rejects_an_invalid_sany_status_marker() -> None:
    result: dict[str, object] = {}
    _parse_grader_result(
        1,
        f"SANY-STATUS: unknown\n{MODULE_RESULT_PREFIX}{json.dumps(_partial_report(), separators=(',', ':'))}\n",
        result,
        expected_module_unit_ids=EXPECTED_UNITS,
    )

    assert result["check_verdict"] == "ERROR"
    assert result["error"] == "grader reported an invalid SANY status marker: 'unknown'"


def test_parser_requires_module_sany_status_to_match_the_marker() -> None:
    result = _parse(_complete_report(), 0, output=_machine_output(_complete_report(), status="invalid"))

    assert result["check_verdict"] == "ERROR"
    assert result["error"] == "module grader SANY status disagrees with SANY-STATUS marker"


def test_strict_module_result_parser_rejects_duplicate_json_object_keys() -> None:
    report = json.dumps(_partial_report(), separators=(",", ":"))
    duplicate = report[:-1] + ',"complete":false}'

    with pytest.raises(ModuleResultError, match="duplicate JSON key"):
        parse_module_result_json(duplicate, EXPECTED_UNITS)


def test_parser_rejects_duplicate_json_object_keys() -> None:
    report = json.dumps(_partial_report(), separators=(",", ":"))
    duplicate = report[:-1] + ',"complete":false}'
    result: dict[str, object] = {}
    _parse_grader_result(
        1,
        f"SANY-STATUS: valid\n{MODULE_RESULT_PREFIX}{duplicate}\n",
        result,
        expected_module_unit_ids=EXPECTED_UNITS,
    )

    assert result["check_verdict"] == "ERROR"
    assert "invalid result" in result["error"]

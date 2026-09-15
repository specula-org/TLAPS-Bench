"""Focused proof-unit scoring and summary coverage for module tasks."""

from __future__ import annotations

from pathlib import Path

from evaluator import runner
from evaluator.score import (
    SCORERS,
    SPECIFICATION_EQUAL,
    comparison_md,
    proof_unit_rate_line,
    proof_unit_score,
    scorecard_md,
)

UNIT_A = "Suite/Module/A"
UNIT_B = "Suite/Module/B"


def _module_result(unit_ids: tuple[str, ...], trusted_ids: tuple[str, ...]) -> dict[str, object]:
    trusted = set(trusted_ids)
    units = []
    for index, unit_id in enumerate(unit_ids, start=1):
        is_trusted = unit_id in trusted
        units.append(
            {
                "unit_id": unit_id,
                "kind": "target",
                "theorem_name": unit_id.rsplit("/", 1)[-1],
                "line_start": index,
                "line_end": index + 1,
                "dependencies": [],
                "raw_verdict": "PASS" if is_trusted else "FAIL",
                "tlapm_exit": 0 if is_trusted else 1,
                "missing_proofs": 0 if is_trusted else 1,
                "obligation_failed": False,
                "trusted": is_trusted,
            }
        )
    return {
        "schema_version": 1,
        "sany_status": "valid",
        "proof_unit_ids": list(unit_ids),
        "units": units,
        "trusted_unit_ids": list(trusted_ids),
        "trusted_proof_unit_ids": list(trusted_ids),
        "complete": len(trusted_ids) == len(unit_ids),
    }


def _result(
    benchmark: str,
    unit_ids: tuple[str, ...],
    *,
    verdict: str = "FAIL",
    trusted_ids: tuple[str, ...] = (),
    termination_reason: str = "OK",
    module_result: dict[str, object] | None = None,
    continuations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "benchmark": benchmark,
        "module": benchmark.split("/", 1)[0],
        "mode": "proof-from-scratch",
        "check_verdict": verdict,
        "termination_reason": termination_reason,
        "time_secs": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "proof_unit_ids": list(unit_ids),
        "proof_unit_count": len(unit_ids),
        "trusted_proof_unit_count": len(trusted_ids),
        "trusted_proof_unit_ids": list(trusted_ids),
    }
    if module_result is not None:
        result["module_result"] = module_result
    if continuations is not None:
        result["continuations"] = continuations
    return result


def test_first_attempt_uses_validated_module_report_not_persisted_trust_counts() -> None:
    result = _result(
        "Suite/Module.tla",
        (UNIT_A, UNIT_B),
        module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
        trusted_ids=(UNIT_A, UNIT_B),
    )

    score = proof_unit_score([result])

    assert (score.trusted_units, score.total_units) == (1, 2)


def test_with_continuations_uses_latest_available_report_without_a_pass() -> None:
    result = _result(
        "Suite/Module.tla",
        (UNIT_A, UNIT_B),
        module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
        continuations=[
            {
                "check_verdict": "FAIL",
                "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_A,)),
            },
            {
                "check_verdict": "FAIL",
                "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_B,)),
            },
        ],
    )

    score = proof_unit_score([result], with_continuations=True)

    assert (score.trusted_units, score.total_units) == (1, 2)


def test_with_continuations_keeps_the_first_passing_report() -> None:
    result = _result(
        "Suite/Module.tla",
        (UNIT_A, UNIT_B),
        module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
        continuations=[
            {
                "round": 1,
                "check_verdict": "PASS",
                "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_A, UNIT_B)),
            },
            {
                "round": 2,
                "check_verdict": "FAIL",
                "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_A,)),
            },
        ],
    )

    score = proof_unit_score([result], with_continuations=True)

    assert (score.trusted_units, score.total_units) == (2, 2)


def test_errors_and_skips_are_excluded_but_verified_pass_after_interruption_counts() -> None:
    results = [
        _result(
            "Suite/Good.tla",
            (UNIT_A, UNIT_B),
            trusted_ids=(UNIT_A,),
            module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
        ),
        _result("Suite/Error.tla", (UNIT_A, UNIT_B), verdict="ERROR"),
        _result(
            "Suite/Skipped.tla",
            (UNIT_A, UNIT_B),
            verdict="SKIP",
            trusted_ids=(UNIT_A, UNIT_B),
            module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A, UNIT_B)),
        ),
        _result(
            "Suite/Infra.tla",
            (UNIT_A, UNIT_B),
            verdict="PASS",
            termination_reason="INFRA_ERROR",
            trusted_ids=(UNIT_A, UNIT_B),
            module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A, UNIT_B)),
        ),
        {"benchmark": "ordinary.tla", "check_verdict": "PASS"},
    ]

    score = proof_unit_score(results)

    assert (score.trusted_units, score.total_units) == (3, 4)
    assert score.excluded_modules == 2
    continuation_score = proof_unit_score(results, with_continuations=True)
    assert (continuation_score.trusted_units, continuation_score.total_units) == (3, 4)


def test_non_module_results_do_not_contribute_to_proof_unit_score() -> None:
    result = {
        "benchmark": "ordinary.tla",
        "check_verdict": "PASS",
        "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_A, UNIT_B)),
        "trusted_proof_unit_count": 2,
    }

    score = proof_unit_score([result])

    assert (score.trusted_units, score.total_units, score.represented_modules) == (0, 0, 0)
    assert proof_unit_rate_line([result]) is None


def test_summary_reports_proof_unit_totals_and_per_module_trust(tmp_path: Path) -> None:
    results = [
        _result(
            "Suite/First.tla",
            (UNIT_A, UNIT_B),
            trusted_ids=(UNIT_A,),
            module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
        ),
        _result(
            "Suite/Second.tla",
            (UNIT_A,),
            verdict="PASS",
            trusted_ids=(UNIT_A,),
            module_result=_module_result((UNIT_A,), (UNIT_A,)),
        ),
        {"benchmark": "ordinary.tla", "check_verdict": "PASS", "time_secs": 0.0},
    ]

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=3,
        backend_name="copilot",
        mode_name="proof-from-scratch",
        specification_ids={
            ("proof-from-scratch", "Suite/First.tla"): "Suite/First.tla",
            ("proof-from-scratch", "Suite/Second.tla"): "Suite/Second.tla",
        },
    )

    summary = (tmp_path / "summary.md").read_text()
    unit_score = "**Proof-unit score (k/n, pass@1)**: 2/3 (66.7%)"
    strict_completion = "**Specification pass rate (all leaves complete)**"
    assert unit_score in summary
    assert summary.index(unit_score) < summary.index(strict_completion)
    assert "pass@1 trusted 1/2 proof units" in summary
    assert "pass@1 trusted 1/1 proof units" in summary
    assert "ordinary.tla` | ✅ PASS" in summary
    assert "ordinary.tla` | ✅ PASS | 0.0s |  | 0/0 |" not in summary


def test_summary_reports_latest_continuation_proof_unit_trust(tmp_path: Path) -> None:
    results = [
        _result(
            "Suite/Module.tla",
            (UNIT_A, UNIT_B),
            trusted_ids=(UNIT_A,),
            module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
            continuations=[
                {
                    "round": 1,
                    "check_verdict": "FAIL",
                    "trusted_proof_unit_count": 1,
                    "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_A,)),
                },
                {
                    "round": 2,
                    "check_verdict": "PASS",
                    "trusted_proof_unit_count": 2,
                    "module_result": _module_result((UNIT_A, UNIT_B), (UNIT_A, UNIT_B)),
                },
            ],
        )
    ]

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=1,
        backend_name="copilot",
        mode_name="proof-from-scratch",
    )

    summary = (tmp_path / "summary.md").read_text()
    assert "**Proof-unit score (k/n, pass@1)**: 1/2 (50.0%)" in summary
    assert "**Proof-unit score (k/n, with continuations)**: 2/2 (100.0%)" in summary
    assert "pass@1 trusted 1/2 proof units; latest continuation trusted 2/2" in summary


def test_scorecard_and_comparison_use_k_over_n_as_the_module_primary() -> None:
    results = [
        _result(
            "Suite/Module.tla",
            (UNIT_A, UNIT_B),
            trusted_ids=(UNIT_A,),
            module_result=_module_result((UNIT_A, UNIT_B), (UNIT_A,)),
        )
    ]
    run = {
        "path": "results.json",
        "id": "run-one",
        "backend": "codex",
        "mode": "proof-from-scratch",
        "results": results,
    }
    specification_ids = {
        ("proof-from-scratch", "Suite/Module.tla"): "Suite/Module.tla",
    }

    scorecard = scorecard_md(run, SCORERS["equal"], SPECIFICATION_EQUAL, specification_ids)
    unit_score = "**Proof-unit score (k/n, pass@1)**: 1/2 (50.0%)"
    assert scorecard.index(unit_score) < scorecard.index("**Specification pass rate")

    comparison = comparison_md([run], SCORERS["equal"], SPECIFICATION_EQUAL, specification_ids)
    assert "| Proof-unit score (k/n) | Specification pass rate |" in comparison
    assert "| run-one | codex | proof-from-scratch | 1/2 (50.0%) | 0/1 (0.0%) |" in comparison

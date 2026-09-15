"""Scoring from results.json.

A task passes iff check_verdict == "PASS"; CHEATING/FAIL/TIMEOUT count as not
passed, while ERROR is excluded for retry. CHEATING is never shown as its own category. Strict
specification pass rate is primary; task-level and specification-macro scores
remain diagnostics. SKIP is dropped from scoring entirely (neither passed nor
failed) and only reported as a side count.

Run: PYTHONPATH=src python3 -m pytest tests/evaluator/test_score.py
"""

import json
import sys

import pytest

from evaluator.score import (
    SCORERS,
    SPECIFICATION_EQUAL,
    comparison_md,
    continuation_budget,
    continuation_interrupted,
    continuation_passed,
    is_non_genuine,
    is_pass,
    is_pass_with_continuations,
    is_skipped,
    load_run,
    main,
    n_non_genuine,
    n_skipped,
    scope_specification_ids,
    scorecard_md,
    specification_equal_score,
    weighted_score,
)

EQUAL = SCORERS["equal"]


def _r(verdict, module="M", **kw):
    d = {
        "check_verdict": verdict,
        "module": module,
        "input_tokens": 0,
        "output_tokens": 0,
        "agent_time_secs": 0,
        "grading_time_secs": 0,
        "time_secs": 0,
    }
    d.update(kw)
    if "time_secs" in kw and "agent_time_secs" not in kw and "grading_time_secs" not in kw:
        d["agent_time_secs"] = kw["time_secs"]
    return d


def test_is_pass_only_for_PASS():
    assert is_pass(_r("PASS"))
    for v in ["FAIL", "CHEATING", "TIMEOUT", "ERROR"]:
        assert not is_pass(_r(v))


def test_cheating_counts_as_fail():
    results = [_r("PASS"), _r("PASS"), _r("CHEATING"), _r("FAIL")]
    pct, n_pass, n_total = weighted_score(results, EQUAL)
    assert (n_pass, n_total) == (2, 4)
    assert pct == 50.0


def test_equal_weight_is_percent_passed():
    results = [_r("PASS")] * 3 + [_r("FAIL")]
    pct, n_pass, n_total = weighted_score(results, EQUAL)
    assert (n_pass, n_total, pct) == (3, 4, 75.0)


def test_empty_is_zero_not_crash():
    assert weighted_score([], EQUAL) == (0.0, 0, 0)


def test_specification_equal_preserves_partial_credit_without_task_count_bias():
    specification_ids = scope_specification_ids(
        "proof-completion",
        {
            "A/One.tla": "A/A.tla",
            "A/Two.tla": "A/A.tla",
            "B/Only.tla": "B/B.tla",
        },
    )
    results = [
        _r("PASS", mode="proof-completion", benchmark="A/One.tla"),
        _r("FAIL", mode="proof-completion", benchmark="A/Two.tla"),
        _r("PASS", mode="proof-completion", benchmark="B/Only.tla"),
    ]

    score = specification_equal_score(results, specification_ids)

    assert score.specification_pass_pct == 50.0
    assert score.specification_macro_pct == 75.0  # mean(1/2, 1/1)
    assert score.task_micro_pct == pytest.approx(66.6667)
    assert (score.tasks_passed, score.applicable_tasks) == (2, 3)
    assert (score.complete_specifications, score.represented_specifications) == (1, 2)


def test_specification_equal_rejects_an_active_task_without_a_spec_id():
    results = [_r("PASS", mode="proof-completion", benchmark="A/One.tla")]

    with pytest.raises(ValueError, match="missing specification identity"):
        specification_equal_score(results, {("proof-completion", "A/One.tla"): ""})


def test_specification_equal_excludes_non_applicable_and_unscored_results():
    specification_ids = scope_specification_ids(
        "proof-completion",
        {
            "A/Pass.tla": "A/A.tla",
            "A/Skipped.tla": "A/A.tla",
            "B/Infra.tla": "B/B.tla",
        },
    )
    results = [
        _r("PASS", mode="proof-completion", benchmark="A/Pass.tla"),
        _r("SKIP", mode="proof-completion", benchmark="A/Skipped.tla"),
        _r("ERROR", mode="proof-completion", benchmark="B/Infra.tla", termination_reason="INFRA_ERROR"),
        _r("PASS", mode="proof-completion", benchmark="Removed/Old.tla"),
    ]

    score = specification_equal_score(results, specification_ids)

    assert score.specification_macro_pct == 100.0
    assert (score.tasks_passed, score.applicable_tasks) == (1, 1)
    assert (score.complete_specifications, score.represented_specifications) == (1, 2)
    assert score.unresolved_specifications == 1
    assert score.error_affected_specifications == 1
    assert score.non_applicable_results == 1


@pytest.mark.parametrize(
    ("verdicts", "complete", "failed", "unresolved", "resolved", "pass_pct"),
    [
        (("PASS", "ERROR"), 0, 0, 1, 0, 0.0),
        (("FAIL", "ERROR"), 0, 1, 0, 1, 0.0),
        (("PASS", "PASS"), 1, 0, 0, 1, 100.0),
    ],
)
def test_specification_state_is_tristate(verdicts, complete, failed, unresolved, resolved, pass_pct):
    specification_ids = scope_specification_ids(
        "proof-completion",
        {"A/One.tla": "A/A.tla", "A/Two.tla": "A/A.tla"},
    )
    results = [
        _r(verdict, mode="proof-completion", benchmark=task)
        for verdict, task in zip(verdicts, ("A/One.tla", "A/Two.tla"), strict=True)
    ]

    score = specification_equal_score(results, specification_ids)

    assert score.complete_specifications == complete
    assert score.failed_specifications == failed
    assert score.unresolved_specifications == unresolved
    assert score.resolved_specifications == resolved
    assert score.specification_pass_pct == pass_pct
    assert score.error_affected_specifications == (1 if "ERROR" in verdicts else 0)


def test_scorecard_reports_unresolved_and_error_affected_specifications():
    specification_ids = scope_specification_ids(
        "proof-completion",
        {"A/One.tla": "A/A.tla", "A/Two.tla": "A/A.tla"},
    )
    results = [
        _r("PASS", mode="proof-completion", benchmark="A/One.tla"),
        _r("ERROR", mode="proof-completion", benchmark="A/Two.tla"),
    ]
    run = {"path": "x", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    card = scorecard_md(run, EQUAL, SPECIFICATION_EQUAL, specification_ids)

    assert "**Specification pass rate (all leaves complete)**: 0/0 resolved specifications (0.0%)" in card
    assert "**Unresolved specifications**: 1 excluded until their errors are retried" in card
    assert "**Specifications affected by errors**: 1 contain excluded ERROR/interrupted leaves" in card


def test_specification_scorecard_shows_strict_primary_before_secondary_diagnostics():
    specification_ids = scope_specification_ids(
        "proof-completion",
        {
            "A/One.tla": "A/A.tla",
            "A/Two.tla": "A/A.tla",
            "B/Only.tla": "B/B.tla",
        },
    )
    results = [
        _r("PASS", module="A", mode="proof-completion", benchmark="A/One.tla"),
        _r("FAIL", module="A", mode="proof-completion", benchmark="A/Two.tla"),
        _r("PASS", module="B", mode="proof-completion", benchmark="B/Only.tla"),
    ]
    run = {"path": "x", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    md = scorecard_md(run, EQUAL, SPECIFICATION_EQUAL, specification_ids)

    primary = "**Specification pass rate (all leaves complete)**: 1/2 resolved specifications (50.0%)"
    task_level = "**Task-micro pass rate**: 2/3 (66.7%)"
    specification_macro = "**Specification-macro pass rate**: 75.0% across 2 resolved specifications"
    assert primary in md
    assert task_level in md
    assert specification_macro in md
    assert md.index(primary) < md.index(task_level) < md.index(specification_macro)
    assert "## By module (task micro)" in md
    assert "| **Total** | **2** | **3** | **66.7%** |" in md


def test_specification_comparison_shows_primary_and_secondary_scores():
    specification_ids = scope_specification_ids(
        "proof-completion",
        {"A/One.tla": "A/A.tla", "A/Two.tla": "A/A.tla", "B/Only.tla": "B/B.tla"},
    )
    runs = [
        {
            "path": "one",
            "id": "one",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [
                _r("PASS", mode="proof-completion", benchmark="A/One.tla"),
                _r("FAIL", mode="proof-completion", benchmark="A/Two.tla"),
                _r("PASS", mode="proof-completion", benchmark="B/Only.tla"),
            ],
        }
    ]

    md = comparison_md(runs, EQUAL, SPECIFICATION_EQUAL, specification_ids)

    assert "| Run | Backend | Mode | Specification pass rate | Task pass rate | Specification macro |" in md
    assert "| one | codex | proof-completion | 1/2 (50.0%) | 2/3 (66.7%) | 75.0% |" in md


def test_specification_comparison_rejects_different_task_cohorts():
    specification_ids = scope_specification_ids("proof-completion", {"A/One.tla": "A/A.tla", "A/Two.tla": "A/A.tla"})
    runs = [
        {
            "id": "one",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [_r("PASS", mode="proof-completion", benchmark="A/One.tla")],
        },
        {
            "id": "two",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [
                _r("PASS", mode="proof-completion", benchmark="A/One.tla"),
                _r("PASS", mode="proof-completion", benchmark="A/Two.tla"),
            ],
        },
    ]

    with pytest.raises(ValueError, match="different applicable task cohorts"):
        comparison_md(runs, EQUAL, SPECIFICATION_EQUAL, specification_ids)


def test_scorecard_module_breakdown_and_no_cheating_row():
    results = [_r("PASS", module="A"), _r("CHEATING", module="A"), _r("PASS", module="B")]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}
    md = scorecard_md(run, EQUAL, "equal")
    assert "CHEATING" not in md  # a cheat is folded into fail, never its own category
    assert "| A | 1 | 2 | 50.0% |" in md
    assert "| B | 1 | 1 | 100.0% |" in md
    assert "| **Total** | **2** | **3** | **66.7%** |" in md
    assert "**Pass rate**: 2/3 (66.7%)" in md


def test_scorecard_separates_tokens_time_and_equivalent_cost():
    results = [
        _r("PASS", input_tokens=1, output_tokens=2, time_secs=1.25, equivalent_cost_usd=0.125),
        _r("FAIL", input_tokens=4, output_tokens=5, time_secs=2.75, equivalent_cost_usd=0.25),
    ]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    md = scorecard_md(run, EQUAL, "equal")

    assert "**Cost**:" not in md
    assert "**Tokens**: 5 input / 7 output" in md
    assert "**Total agent time**: 4.0s" in md
    assert "**Total grading time**: 0.0s" in md
    assert "**Total task time**: 4.0s" in md
    assert "**Equivalent cost**: $0.375000" in md


def test_scorecard_reports_split_time_without_equivalent_cost():
    results = [_r("PASS", input_tokens=1, output_tokens=2, time_secs=1.25)]
    run = {"path": "x/results.json", "id": "x", "backend": "cursor", "mode": "proof-completion", "results": results}

    md = scorecard_md(run, EQUAL, "equal")

    assert "**Tokens**: 1 input / 2 output" in md
    assert "**Total agent time**: 1.2s" in md
    assert "**Total grading time**: 0.0s" in md
    assert "**Total task time**: 1.2s" in md
    assert "**Equivalent cost**:" not in md


def test_scorecard_does_not_turn_missing_metrics_into_zero():
    results = [_r("PASS", time_secs=1.0, equivalent_cost_usd=0.1), _r("FAIL")]
    results[1].pop("time_secs")
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    md = scorecard_md(run, EQUAL, "equal")

    assert "**Total task time**: unavailable" in md
    assert "**Equivalent cost**: unavailable" in md


def test_scorecard_does_not_render_unavailable_structured_tokens_as_zero():
    result = _r(
        "PASS",
        usage={
            "available": False,
            "complete": False,
            "is_lower_bound": False,
            "input_tokens": None,
            "output_tokens": None,
        },
    )
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": [result]}

    assert "**Tokens**: unavailable" in scorecard_md(run, EQUAL, "equal")


def test_scorecard_preserves_known_exact_zero_metrics():
    results = [_r("PASS", time_secs=0, equivalent_cost_usd=0)]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    md = scorecard_md(run, EQUAL, "equal")

    assert "**Total task time**: 0.0s" in md
    assert "**Equivalent cost**: $0.000000" in md


def test_tiny_positive_cost_is_not_rendered_as_zero():
    results = [_r("PASS", time_secs=1, equivalent_cost_usd=0.0000005)]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    assert "**Equivalent cost**: $5e-07" in scorecard_md(run, EQUAL, "equal")


def test_scorecard_excludes_non_genuine_time_and_cost_and_reports_cost_warning():
    results = [
        _r(
            "PASS",
            input_tokens=10,
            output_tokens=2,
            time_secs=1.5,
            equivalent_cost_usd=0.15,
            benchmark="formal.tla",
            usage={"warnings": ["equivalent cost warning: values differ"]},
        ),
        _r(
            "ERROR",
            input_tokens=999,
            output_tokens=999,
            time_secs=100,
            equivalent_cost_usd=10,
            benchmark="infra.tla",
            termination_reason="INFRA_ERROR",
        ),
        _r(
            "SKIP",
            input_tokens=999,
            output_tokens=999,
            time_secs=100,
            equivalent_cost_usd=10,
            benchmark="skipped.tla",
        ),
    ]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}

    md = scorecard_md(run, EQUAL, "equal")

    # Preserve the legacy token summary; only time and cost use formal rows.
    assert "**Tokens**: 2,008 input / 2,000 output" in md
    assert "**Total task time**: 1.5s" in md
    assert "**Equivalent cost**: $0.150000" in md
    assert "## Cost warnings" in md
    assert "`formal.tla`: equivalent cost warning: values differ" in md


def test_comparison_row_per_run():
    runs = [
        {"id": "r1", "backend": "codex", "mode": "proof-completion", "results": [_r("PASS"), _r("FAIL")]},
        {"id": "r2", "backend": "claude_code", "mode": "proof-completion", "results": [_r("PASS"), _r("PASS")]},
    ]
    md = comparison_md(runs, EQUAL, "equal")
    assert "Comparison — 2 runs" in md
    assert "| r1 | codex | proof-completion | 50.0% | 1/2 |" in md
    assert "| r2 | claude_code | proof-completion | 100.0% | 2/2 |" in md


def test_comparison_reports_equivalent_cost_and_missing_metrics():
    runs = [
        {
            "id": "priced",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [_r("PASS", time_secs=1.25, equivalent_cost_usd=0.125)],
        },
        {
            "id": "legacy",
            "backend": "claude_code",
            "mode": "proof-completion",
            "results": [_r("PASS")],
        },
    ]
    runs[1]["results"][0].pop("time_secs")

    md = comparison_md(runs, EQUAL, "equal")

    assert "| Time | Equivalent cost |" in md
    assert "| priced | codex | proof-completion | 100.0% | 1/1 | 0/0 | 1.2s | $0.125000 |" in md
    assert "| legacy | claude_code | proof-completion | 100.0% | 1/1 | 0/0 | unavailable | unavailable |" in md


def test_comparison_preserves_legacy_columns_without_equivalent_cost():
    runs = [
        {
            "id": "legacy",
            "backend": "cursor",
            "mode": "proof-completion",
            "results": [_r("PASS", time_secs=1.25)],
        }
    ]

    md = comparison_md(runs, EQUAL, "equal")

    assert "| Time |" in md
    assert "Equivalent cost" not in md
    assert "| legacy | cursor | proof-completion | 100.0% | 1/1 | 0/0 | 1.2s |" in md


def test_mixed_comparison_excludes_cursor_infra_accounting():
    runs = [
        {
            "id": "priced",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [_r("PASS", time_secs=1, equivalent_cost_usd=0.1)],
        },
        {
            "id": "deferred",
            "backend": "cursor",
            "mode": "proof-completion",
            "results": [
                _r("PASS", time_secs=2),
                _r("ERROR", time_secs=100, termination_reason="INFRA_ERROR"),
            ],
        },
    ]

    md = comparison_md(runs, EQUAL, "equal")

    assert (
        "| deferred | cursor | proof-completion | 100.0% | 1/1 (+1 error/interrupted) | 0/0 | 2.0s | unavailable |"
    ) in md


def test_load_run_from_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "results.json").write_text(json.dumps([_r("PASS", backend="codex", mode="proof-completion")]))
    run = load_run(str(d))
    assert run["backend"] == "codex"
    assert run["mode"] == "proof-completion"
    assert len(run["results"]) == 1


# --- SKIP is excluded from scoring, not counted as a failure --------------


def test_is_skipped_only_for_SKIP():
    assert is_skipped(_r("SKIP"))
    for v in ["PASS", "FAIL", "CHEATING", "TIMEOUT", "ERROR"]:
        assert not is_skipped(_r(v))


def test_skip_drops_out_of_denominator():
    # 1 PASS + 1 FAIL + 1 SKIP -> 1/2 (50%), NOT 1/3: the skip is excluded.
    results = [_r("PASS"), _r("FAIL"), _r("SKIP")]
    pct, n_pass, n_total = weighted_score(results, EQUAL)
    assert (n_pass, n_total, pct) == (1, 2, 50.0)
    assert n_skipped(results) == 1


def test_all_skip_is_zero_not_crash():
    results = [_r("SKIP"), _r("SKIP")]
    assert weighted_score(results, EQUAL) == (0.0, 0, 0)
    assert n_skipped(results) == 2


def test_verified_pass_after_interruption_counts_but_unresolved_results_do_not():
    results = [
        _r("PASS"),
        _r("FAIL"),
        _r("PASS", termination_reason="INFRA_ERROR"),
        _r("FAIL", termination_reason="INFRA_ERROR"),
        _r("ERROR", termination_reason="QUOTA_EXHAUSTED"),
    ]
    pct, n_pass, n_total = weighted_score(results, EQUAL)
    assert (n_pass, n_total, pct) == (2, 3, pytest.approx(200 / 3))
    assert n_non_genuine(results) == 2


def test_ok_timeout_and_legacy_results_stay_scored():
    # TIMEOUT is a limit (graded on workspace artifacts); a missing
    # termination_reason is a pre-classification run. Both stay scored.
    results = [
        _r("PASS", termination_reason="OK"),
        _r("FAIL", termination_reason="TIMEOUT"),
        _r("FAIL"),
    ]
    pct, n_pass, n_total = weighted_score(results, EQUAL)
    assert (n_pass, n_total) == (1, 3)
    assert n_non_genuine(results) == 0


def test_scorecard_reports_non_genuine_count():
    results = [_r("PASS"), _r("ERROR")]
    run = {"path": "x", "id": "r", "backend": "copilot", "mode": "proof-completion", "results": results}
    card = scorecard_md(run, EQUAL, "equal")
    assert "**Pass rate**: 1/1 (100.0%)" in card
    assert "1 error/interrupted (excluded — re-run)" in card


def test_scorecard_with_no_formal_results_reports_accounting_unavailable():
    results = [
        _r(
            "ERROR",
            termination_reason="INFRA_ERROR",
            time_secs=100,
            equivalent_cost_usd=10,
        )
    ]
    run = {"path": "x", "id": "r", "backend": "copilot", "mode": "proof-completion", "results": results}

    card = scorecard_md(run, EQUAL, "equal")

    assert "**Total task time**: unavailable" in card
    assert "**Equivalent cost**: unavailable" in card


def test_scorecard_excludes_skip_and_reports_it():
    # Module A: PASS + SKIP -> 1/1 (skip gone). Module B: all SKIP -> absent.
    results = [_r("PASS", module="A"), _r("SKIP", module="A"), _r("SKIP", module="B")]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}
    md = scorecard_md(run, EQUAL, "equal")
    assert "**Pass rate**: 1/1 (100.0%) · 2 skipped" in md
    assert "| A | 1 | 1 | 100.0% |" in md  # skip not counted against module A
    assert "| B |" not in md  # a fully-skipped module drops out of the table
    assert "| **Total** | **1** | **1** | **100.0%** |" in md


def test_scorecard_no_skip_has_no_skipped_note():
    results = [_r("PASS"), _r("FAIL")]
    run = {"path": "x/results.json", "id": "x", "backend": "codex", "mode": "proof-completion", "results": results}
    md = scorecard_md(run, EQUAL, "equal")
    assert "**Pass rate**: 1/2 (50.0%)" in md
    assert "skipped" not in md


def test_comparison_discloses_skip_inline():
    runs = [
        {"id": "r1", "backend": "codex", "mode": "proof-completion", "results": [_r("PASS"), _r("FAIL"), _r("SKIP")]},
        {"id": "r2", "backend": "claude_code", "mode": "proof-completion", "results": [_r("PASS"), _r("PASS")]},
    ]
    md = comparison_md(runs, EQUAL, "equal")
    assert "| r1 | codex | proof-completion | 50.0% | 1/2 (+1 skipped) |" in md
    assert "| r2 | claude_code | proof-completion | 100.0% | 2/2 |" in md  # no note when nothing skipped


# --- continuations are a separate metric, never a replacement for pass@1 ---


def _cont(*verdicts):
    return [{"round": i + 1, "check_verdict": v} for i, v in enumerate(verdicts)]


# A chain ended by a non-genuine round (the runner stops continuing on these).
CUT_CHAIN = [{"round": 1, "check_verdict": "ERROR", "termination_reason": "QUOTA_EXHAUSTED"}]


def test_continuation_passed_predicates():
    recovered = _r("FAIL", continuations=_cont("FAIL", "PASS"))
    still_failing = _r("FAIL", continuations=_cont("FAIL"))
    assert continuation_passed(recovered) and is_pass_with_continuations(recovered)
    assert not continuation_passed(still_failing) and not is_pass_with_continuations(still_failing)
    assert not continuation_passed(_r("FAIL"))  # no rounds recorded
    assert is_pass_with_continuations(_r("PASS"))  # first-attempt pass counts too


def test_weighted_score_with_continuations_same_denominator():
    # pass@1 and the continuation rate share the scored set (non-genuine excluded).
    results = [
        _r("PASS"),
        _r("FAIL", continuations=_cont("PASS")),
        _r("FAIL", continuations=_cont("FAIL")),
        _r("FAIL", termination_reason="INFRA_ERROR"),
    ]
    assert weighted_score(results, EQUAL) == (100.0 / 3, 1, 3)
    assert weighted_score(results, EQUAL, passed=is_pass_with_continuations) == (200.0 / 3, 2, 3)


def test_continuation_interrupted_only_for_unresolved_cut_chains():
    # Interrupted = the chain-ending round was infra/quota-cut with no PASS.
    assert continuation_interrupted(_r("FAIL", continuations=CUT_CHAIN))
    # An exhausted budget of genuine rounds is a real continuation failure.
    assert not continuation_interrupted(_r("FAIL", continuations=_cont("FAIL", "FAIL")))
    # A recovered chain resolved, however its stream ended.
    assert not continuation_interrupted(_r("FAIL", continuations=_cont("FAIL", "PASS")))
    assert not continuation_interrupted(_r("FAIL"))  # no rounds recorded


def test_partial_module_progress_after_interruption_requires_retry():
    result = _r(
        "FAIL",
        termination_reason="QUOTA_EXHAUSTED",
        graded_after_interruption=True,
        module_result={"complete": False},
    )

    assert is_non_genuine(result)


def test_invalid_module_submission_after_interruption_requires_retry():
    result = _r(
        "FAIL",
        termination_reason="INFRA_ERROR",
        invalid_submission_after_interruption=True,
    )

    assert is_non_genuine(result)
    assert continuation_interrupted(_r("FAIL", continuations=[{"round": 1, **result}]))


def test_continuation_budget_uniform_or_none():
    assert continuation_budget([_r("FAIL", max_continuations=3), _r("PASS")]) == 3
    assert continuation_budget([_r("FAIL", max_continuations=3), _r("FAIL", max_continuations=5)]) is None
    assert continuation_budget([_r("FAIL")]) is None  # legacy results: no budget recorded


def test_scorecard_reports_continuation_rate_separately():
    results = [_r("FAIL", continuations=_cont("PASS")), _r("FAIL")]
    run = {"path": "x", "id": "r", "backend": "copilot", "mode": "proof-completion", "results": results}
    md = scorecard_md(run, EQUAL, "equal")
    assert "**Pass rate**: 0/2 (0.0%)" in md  # pass@1 stays first-attempt only
    assert "**Task-micro pass rate with continuations**: 1/2 (50.0%) — 1 recovered by continuation" in md


def test_scorecard_labels_continuation_budget_and_excludes_cut_chains():
    # The rate states its budget (≤N), and an interrupted chain is dropped from
    # numerator AND denominator with a disclosed count — never a silent failure.
    results = [
        _r("FAIL", continuations=_cont("PASS"), max_continuations=3),
        _r("FAIL", continuations=CUT_CHAIN, max_continuations=3),
        _r("FAIL"),
    ]
    run = {"path": "x", "id": "r", "backend": "copilot", "mode": "proof-completion", "results": results}
    md = scorecard_md(run, EQUAL, "equal")
    assert "**Pass rate**: 0/3 (0.0%)" in md  # the cut chain's genuine first FAIL stays scored
    assert (
        "**Task-micro pass rate with continuations (≤3)**: 1/2 (50.0%) — 1 recovered by continuation "
        "(pass@1 above is first-attempt only) · 1 chain(s) interrupted (excluded — re-run)"
    ) in md


def test_scorecard_without_continuations_has_no_continuation_line():
    results = [_r("PASS"), _r("FAIL")]
    run = {"path": "x", "id": "r", "backend": "copilot", "mode": "proof-completion", "results": results}
    assert "continuation" not in scorecard_md(run, EQUAL, "equal")


def test_comparison_discloses_continuation_recoveries_inline():
    # The budget is part of the result: +1 recovery out of ≤1 round and out of
    # ≤10 must not render identically. Legacy results without a recorded budget
    # fall back to the unlabeled note.
    runs = [
        {
            "id": "r1",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [_r("PASS"), _r("FAIL", continuations=_cont("PASS"), max_continuations=3)],
        },
        {
            "id": "r2",
            "backend": "copilot",
            "mode": "proof-completion",
            "results": [_r("PASS"), _r("FAIL", continuations=_cont("PASS"))],  # legacy: no budget recorded
        },
        {"id": "r3", "backend": "claude_code", "mode": "proof-completion", "results": [_r("PASS"), _r("FAIL")]},
    ]
    md = comparison_md(runs, EQUAL, "equal")
    assert "| r1 | codex | proof-completion | 50.0% | 1/2 (+1 via ≤3 continuations) |" in md
    assert "| r2 | copilot | proof-completion | 50.0% | 1/2 (+1 via continuation) |" in md
    assert "| r3 | claude_code | proof-completion | 50.0% | 1/2 |" in md  # no note without rounds


def test_comparison_discloses_interrupted_chains_inline():
    # "(+0 via continuation)" alone would hide that the chain was infra/quota-cut
    # rather than genuinely exhausted — the cut count must appear next to it.
    runs = [
        {
            "id": "r1",
            "backend": "codex",
            "mode": "proof-completion",
            "results": [_r("PASS"), _r("FAIL", continuations=CUT_CHAIN)],
        },
    ]
    md = comparison_md(runs, EQUAL, "equal")
    assert "| r1 | codex | proof-completion | 50.0% | 1/2 (+0 via continuation) (+1 chain(s) cut) |" in md


# --- load_run / main entry point ------------------------------------------


def test_load_run_from_file_path(tmp_path):
    f = tmp_path / "results.json"
    f.write_text(json.dumps([_r("PASS", backend="codex", mode="proof-completion")]))
    run = load_run(str(f))
    assert run["path"] == str(f)
    assert run["backend"] == "codex"
    assert run["id"] == tmp_path.name  # id falls back to the containing dir


def _write_run(tmp_path, name, results):
    d = tmp_path / name
    d.mkdir()
    (d / "results.json").write_text(json.dumps(results))
    return str(d)


def test_main_single_prints_scorecard(tmp_path, monkeypatch, capsys):
    results = [
        _r("PASS", backend="codex", mode="proof-completion", benchmark="A/One.tla"),
        _r("FAIL", backend="codex", mode="proof-completion", benchmark="A/Two.tla"),
    ]
    d = _write_run(tmp_path, "run1", results)
    specification_ids = scope_specification_ids("proof-completion", {"A/One.tla": "A/A.tla", "A/Two.tla": "A/A.tla"})
    monkeypatch.setattr("evaluator.score.load_current_specification_ids", lambda _modes: specification_ids)
    monkeypatch.setattr(sys, "argv", ["tlaps-bench score", d])
    assert main() == 0
    out = capsys.readouterr().out
    assert "# Scorecard" in out
    assert "**Specification pass rate (all leaves complete)**: 0/1 resolved specification (0.0%)" in out
    assert "**Specification-macro pass rate**: 50.0% across 1 resolved specification" in out
    assert "**Task-micro pass rate**: 1/2 (50.0%)" in out


def test_main_equal_retains_legacy_task_micro_score(tmp_path, monkeypatch, capsys):
    d = _write_run(tmp_path, "run1", [_r("PASS"), _r("FAIL")])
    monkeypatch.setattr(sys, "argv", ["tlaps-bench score", "--scoring", "equal", d])

    assert main() == 0

    assert "**Pass rate**: 1/2 (50.0%)" in capsys.readouterr().out


def test_main_multiple_prints_comparison(tmp_path, monkeypatch, capsys):
    d1 = _write_run(
        tmp_path,
        "run1",
        [_r("PASS", backend="codex", mode="proof-completion", benchmark="A/One.tla")],
    )
    d2 = _write_run(
        tmp_path,
        "run2",
        [_r("FAIL", backend="codex", mode="proof-completion", benchmark="A/One.tla")],
    )
    specification_ids = scope_specification_ids("proof-completion", {"A/One.tla": "A/A.tla"})
    monkeypatch.setattr("evaluator.score.load_current_specification_ids", lambda _modes: specification_ids)
    monkeypatch.setattr(sys, "argv", ["tlaps-bench score", d1, d2])
    assert main() == 0
    assert "# Comparison — 2 runs" in capsys.readouterr().out


def test_main_reports_mismatched_comparison_cohorts(tmp_path, monkeypatch, capsys):
    d1 = _write_run(
        tmp_path,
        "run1",
        [_r("PASS", backend="codex", mode="proof-completion", benchmark="A/One.tla")],
    )
    d2 = _write_run(
        tmp_path,
        "run2",
        [
            _r("PASS", backend="codex", mode="proof-completion", benchmark="A/One.tla"),
            _r("PASS", backend="codex", mode="proof-completion", benchmark="A/Two.tla"),
        ],
    )
    specification_ids = scope_specification_ids("proof-completion", {"A/One.tla": "A/A.tla", "A/Two.tla": "A/A.tla"})
    monkeypatch.setattr("evaluator.score.load_current_specification_ids", lambda _modes: specification_ids)
    monkeypatch.setattr(sys, "argv", ["tlaps-bench score", d1, d2])

    assert main() == 1
    assert "different applicable task cohorts" in capsys.readouterr().err


def test_main_missing_path_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tlaps-bench score", str(tmp_path / "nope")])
    assert main() == 1
    assert "no results.json" in capsys.readouterr().err

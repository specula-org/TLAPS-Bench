"""Score benchmark results from one or more results.json files.

``tlaps-bench run`` writes a machine-readable ``results.json`` per run. This
reads one or more of them and prints a Markdown scorecard. It is pure and
offline — no network, no API keys — so metrics can be (re)computed cheaply
without re-running the (expensive) agents.

PASS/FAIL: a task counts as passed iff its ``check_verdict`` is exactly
``"PASS"``. FAIL, CHEATING, and TIMEOUT count as not passed. ERROR means the
grader or its infrastructure did not produce a capability result, so it is
excluded and must be retried.

SKIP is one exception: an operator marks a benchmark ``SKIP`` to exclude it from
scoring (e.g. a theorem known to time out for reasons outside the agent's
control). A skipped task is in neither the numerator nor the denominator — it is
dropped from the pass rate entirely, not counted as a failure — and the count is
reported separately so nothing is hidden.

Non-genuine runs are the other exception: ERROR and an unresolved result whose
``termination_reason`` is ``INFRA_ERROR`` or ``QUOTA_EXHAUSTED`` are not
capability signals. These are excluded from the numerator and denominator and
reported as needing a re-run. A verified PASS after an interruption still
counts. Declared agent/checker TIMEOUT is a benchmark limit, so it stays scored.

Continuations (``tlaps-bench run --max-continuations``) are a separate metric,
never a replacement: ``check_verdict`` always holds the FIRST attempt's verdict,
so the pass rate above stays pass@1. When a run recorded continuation rounds
(``result["continuations"]``), a second, clearly-labeled "with continuations"
rate is reported (with the run's ≤N budget), counting a task as passed if any
round reached PASS — the gap between the two is how often a first-attempt
failure was an early stop rather than an inability. A chain cut short by
infrastructure/provider interruption before resolving is not failed: like a non-genuine
first attempt it is excluded from the continuation rate and reported separately
(see ``continuation_interrupted``).

For module-level proof-from-scratch results, the primary score is dependency-
closed proof-unit coverage: a module with k trusted original theorems out of n
scores k/n, preserving theorem-level partial credit. Strict whole-module
completion remains visible as a diagnostic. Other modes retain the strict
specification pass rate as their primary score.

The legacy pluggable task scorer assigns a non-negative weight to each task;
the score of a group of tasks is

    100 * (sum of weights of passed tasks) / (sum of all weights)

The ``equal`` task scorer gives every task weight 1. It remains available via
``--scoring equal`` for compatibility and as the task-micro diagnostic.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from common.proof_from_scratch_manifest import load_module_task_manifest
from common.task_contract import load_manifest_specification_ids
from evaluator.proof_module_result import ModuleResultError, validate_module_result
from evaluator.usage import TokenUsage, aggregate_token_usage, format_token_usage

PASS_VERDICT = "PASS"
SKIP_VERDICT = "SKIP"
NON_GENUINE_TERMINATIONS = {"INFRA_ERROR", "QUOTA_EXHAUSTED"}
COST_TIME_BACKENDS = {
    "codex",
    "claude_code",
    "copilot",
    "copilot_oneshot",
    "cursor",
    "litellm",
    "litellm_oneshot",
    "pi",
}
REPO_ROOT = Path(__file__).resolve().parents[2]
SPECIFICATION_EQUAL = "specification-equal"
SpecificationKey = tuple[str, str]


@dataclass(frozen=True)
class SpecificationScore:
    """Specification pass rate and secondary diagnostics for one cohort."""

    specification_pass_pct: float
    specification_macro_pct: float
    task_micro_pct: float
    tasks_passed: int
    applicable_tasks: int
    complete_specifications: int
    failed_specifications: int
    unresolved_specifications: int
    error_affected_specifications: int
    represented_specifications: int
    non_applicable_results: int

    @property
    def resolved_specifications(self) -> int:
        return self.complete_specifications + self.failed_specifications


@dataclass(frozen=True)
class ProofUnitScore:
    """Dependency-closed target coverage across module-level tasks."""

    trusted_units: int
    total_units: int
    represented_modules: int
    excluded_modules: int

    @property
    def trusted_pct(self) -> float:
        return 100.0 * self.trusted_units / self.total_units if self.total_units else 0.0


def is_pass(result: dict) -> bool:
    """A task passed iff its verdict is exactly PASS (CHEATING/FAIL/... do not)."""
    return result.get("check_verdict") == PASS_VERDICT


def is_skipped(result: dict) -> bool:
    """A task is SKIP iff an operator excluded it from scoring (see module doc)."""
    return result.get("check_verdict") == SKIP_VERDICT


def is_non_genuine(result: dict) -> bool:
    """Whether a result lacks a benchmark capability verdict and needs retry."""

    verdict = result.get("check_verdict")
    if verdict == "ERROR":
        return True
    return result.get("termination_reason") in NON_GENUINE_TERMINATIONS and verdict != PASS_VERDICT


def continuation_passed(result: dict) -> bool:
    """Whether any continuation round (--max-continuations) reached PASS.

    A round's PASS means the grader verified the proof in the workspace, so it
    is ground truth regardless of how that round's event stream terminated."""
    return any(r.get("check_verdict") == PASS_VERDICT for r in result.get("continuations") or [])


def is_pass_with_continuations(result: dict) -> bool:
    """PASS on the first attempt or on any continuation round — the predicate
    behind the separate "with continuations" rate (pass@1 uses is_pass)."""
    return is_pass(result) or continuation_passed(result)


def continuation_interrupted(result: dict) -> bool:
    """Whether the continuation chain was cut short by infra/quota before it
    could resolve: no round passed and the chain-ending round is non-genuine.

    Like a non-genuine first attempt, the outcome is indeterminate — neither a
    recovery nor an exhausted budget — so the continuation rate excludes it and
    reports it separately (rerun the benchmark with --resume)."""
    rounds = result.get("continuations") or []
    return bool(rounds) and is_non_genuine(rounds[-1]) and not continuation_passed(result)


def continuation_budget(results: list[dict]) -> int | None:
    """The run's --max-continuations budget, when recorded and uniform across
    results. Mixed budgets (e.g. a run resumed with a different flag) yield
    None and reports omit the ≤N label."""
    budgets = {r["max_continuations"] for r in results if r.get("max_continuations")}
    return budgets.pop() if len(budgets) == 1 else None


def continuation_rate_line(results: list[dict], weight: Callable[[dict], float], n_pass: int) -> str | None:
    """The "with continuations" pass-rate line shared by summary.md and the
    scorecard, or None when no continuation rounds were recorded. Interrupted
    chains are excluded from the rate and disclosed; ``n_pass`` is the pass@1
    count the recovery delta is measured against."""
    if not any(r.get("continuations") for r in results):
        return None
    resolved = [r for r in results if not continuation_interrupted(r)]
    cpct, cn_pass, cn_total = weighted_score(resolved, weight, passed=is_pass_with_continuations)
    budget = continuation_budget(results)
    label = f" (≤{budget})" if budget else ""
    line = (
        f"**Task-micro pass rate with continuations{label}**: {cn_pass}/{cn_total} ({cpct:.1f}%) — "
        f"{cn_pass - n_pass} recovered by continuation (pass@1 above is first-attempt only)"
    )
    n_cut = sum(1 for r in results if continuation_interrupted(r))
    if n_cut:
        line += f" · {n_cut} chain(s) interrupted (excluded — re-run)"
    return line


def _module_proof_unit_ids(result: Mapping[str, object]) -> tuple[str, ...] | None:
    value = result.get("proof_unit_ids")
    if type(value) is not list or not value or any(type(unit_id) is not str or not unit_id for unit_id in value):
        return None
    if len(value) != len(set(value)):
        return None
    return tuple(value)


def _effective_module_attempt(result: dict, *, with_continuations: bool) -> Mapping[str, object]:
    if not with_continuations:
        return result
    attempts = [result, *(attempt for attempt in (result.get("continuations") or []) if isinstance(attempt, Mapping))]
    passing = [
        attempt
        for attempt in attempts
        if attempt.get("check_verdict") == PASS_VERDICT and isinstance(attempt.get("module_result"), dict)
    ]
    if passing:
        return passing[0]
    graded = [attempt for attempt in attempts if isinstance(attempt.get("module_result"), dict)]
    return graded[-1] if graded else result


def proof_unit_score(results: list[dict], *, with_continuations: bool = False) -> ProofUnitScore:
    """Return proof-unit micro coverage without trusting persisted derived counts."""

    trusted = 0
    total = 0
    represented = 0
    excluded = 0
    for result in results:
        unit_ids = _module_proof_unit_ids(result)
        if unit_ids is None:
            continue
        represented += 1
        if is_skipped(result) or is_non_genuine(result) or (with_continuations and continuation_interrupted(result)):
            excluded += 1
            continue
        total += len(unit_ids)
        attempt = _effective_module_attempt(result, with_continuations=with_continuations)
        raw_report = attempt.get("module_result")
        if not isinstance(raw_report, dict):
            continue
        try:
            report = validate_module_result(raw_report, unit_ids)
        except ModuleResultError:
            continue
        trusted += len(report["trusted_proof_unit_ids"])
    return ProofUnitScore(
        trusted_units=trusted,
        total_units=total,
        represented_modules=represented,
        excluded_modules=excluded,
    )


def proof_unit_rate_line(results: list[dict], *, with_continuations: bool = False) -> str | None:
    score = proof_unit_score(results, with_continuations=with_continuations)
    if not score.represented_modules:
        return None
    qualifier = "with continuations" if with_continuations else "pass@1"
    line = (
        f"**Proof-unit score (k/n, {qualifier})**: {score.trusted_units}/{score.total_units} ({score.trusted_pct:.1f}%)"
    )
    if score.excluded_modules:
        line += f" · {score.excluded_modules} module(s) skipped or interrupted (excluded — re-run)"
    return line


def n_skipped(results: list[dict]) -> int:
    """How many tasks were operator-excluded from scoring."""
    return sum(1 for r in results if is_skipped(r))


def n_non_genuine(results: list[dict]) -> int:
    """How many results are excluded as non-genuine (need a re-run)."""
    return sum(1 for r in results if is_non_genuine(r))


def scope_specification_ids(mode: str, task_specification_ids: Mapping[str, str]) -> dict[SpecificationKey, str]:
    """Scope manifest task IDs by mode, since task paths can occur in both suites."""

    return {(mode, task_id): spec_id for task_id, spec_id in task_specification_ids.items()}


def _validate_specification_ids(specification_ids: Mapping[SpecificationKey, str]) -> None:
    for key, spec_id in specification_ids.items():
        if not isinstance(key, tuple) or len(key) != 2 or not all(isinstance(part, str) and part for part in key):
            raise ValueError(f"invalid specification mapping key: {key!r}")
        if not isinstance(spec_id, str) or not spec_id:
            raise ValueError(f"missing specification identity for {key[0]}/{key[1]}")


def _result_specification_key(result: dict) -> SpecificationKey | None:
    mode = result.get("mode")
    task_id = result.get("benchmark")
    if not isinstance(mode, str) or not mode or not isinstance(task_id, str) or not task_id:
        return None
    return mode, task_id


def specification_equal_score(
    results: list[dict],
    specification_ids: Mapping[SpecificationKey, str],
    passed: Callable[[dict], bool] = is_pass,
) -> SpecificationScore:
    """Score selected, applicable tasks at specification and task levels.

    A result is applicable when its ``(mode, benchmark)`` identity exists in the
    active versioned manifest. Results for tasks removed from a later manifest
    are excluded and counted as non-applicable. Active manifest entries without
    a specification identity are invalid and fail before any score is returned.
    SKIP and non-genuine results are excluded by the existing score policy.
    """

    _validate_specification_ids(specification_ids)
    by_specification: dict[SpecificationKey, list[dict]] = defaultdict(list)
    non_applicable = 0

    for result in results:
        key = _result_specification_key(result)
        if key is None or key not in specification_ids:
            non_applicable += 1
            continue
        if is_skipped(result):
            continue
        by_specification[(key[0], specification_ids[key])].append(result)

    applicable = [result for grouped in by_specification.values() for result in grouped if not is_non_genuine(result)]
    tasks_passed = sum(1 for result in applicable if passed(result))
    applicable_tasks = len(applicable)
    task_micro_pct = 100.0 * tasks_passed / applicable_tasks if applicable_tasks else 0.0

    complete_specifications = 0
    failed_specifications = 0
    unresolved_specifications = 0
    error_affected_specifications = 0
    spec_fractions: list[float] = []
    for grouped in by_specification.values():
        resolved = [result for result in grouped if not is_non_genuine(result)]
        affected = len(resolved) != len(grouped)
        if affected:
            error_affected_specifications += 1
        if any(not passed(result) for result in resolved):
            failed_specifications += 1
            spec_fractions.append(sum(1 for result in resolved if passed(result)) / len(resolved))
        elif affected:
            unresolved_specifications += 1
        else:
            complete_specifications += 1
            spec_fractions.append(1.0)

    represented_specifications = len(by_specification)
    resolved_specifications = complete_specifications + failed_specifications
    specification_macro_pct = 100.0 * sum(spec_fractions) / resolved_specifications if resolved_specifications else 0.0
    specification_pass_pct = (
        100.0 * complete_specifications / resolved_specifications if resolved_specifications else 0.0
    )
    return SpecificationScore(
        specification_pass_pct=specification_pass_pct,
        specification_macro_pct=specification_macro_pct,
        task_micro_pct=task_micro_pct,
        tasks_passed=tasks_passed,
        applicable_tasks=applicable_tasks,
        complete_specifications=complete_specifications,
        failed_specifications=failed_specifications,
        unresolved_specifications=unresolved_specifications,
        error_affected_specifications=error_affected_specifications,
        represented_specifications=represented_specifications,
        non_applicable_results=non_applicable,
    )


def applicable_manifest_results(
    results: Iterable[dict], specification_ids: Mapping[SpecificationKey, str]
) -> list[dict]:
    """Return results whose task identity is present in the active manifests."""

    return [result for result in results if _result_specification_key(result) in specification_ids]


def specification_score_lines(
    results: list[dict], specification_ids: Mapping[SpecificationKey, str]
) -> tuple[list[str], SpecificationScore]:
    """Format the shared primary/secondary score lines for reports."""

    score = specification_equal_score(results, specification_ids)
    task_line = f"**Task-micro pass rate**: {score.tasks_passed}/{score.applicable_tasks} ({score.task_micro_pct:.1f}%)"
    mapped_results = applicable_manifest_results(results, specification_ids)
    skipped = n_skipped(mapped_results)
    non_genuine = n_non_genuine(mapped_results)
    if skipped:
        task_line += f" · {skipped} skipped"
    if non_genuine:
        task_line += f" · {non_genuine} error/interrupted (excluded — re-run)"

    resolved_word = "specification" if score.resolved_specifications == 1 else "specifications"
    lines = [
        f"**Specification pass rate (all leaves complete)**: "
        f"{score.complete_specifications}/{score.resolved_specifications} resolved "
        f"{resolved_word} ({score.specification_pass_pct:.1f}%)",
        task_line,
        f"**Specification-macro pass rate**: {score.specification_macro_pct:.1f}% "
        f"across {score.resolved_specifications} resolved {resolved_word}",
    ]
    if score.unresolved_specifications:
        lines.append(
            f"**Unresolved specifications**: {score.unresolved_specifications} excluded until their errors are retried"
        )
    if score.error_affected_specifications:
        lines.append(
            f"**Specifications affected by errors**: {score.error_affected_specifications} contain excluded "
            "ERROR/interrupted leaves"
        )
    if score.non_applicable_results:
        lines.append(
            f"**Non-applicable results**: {score.non_applicable_results} not present in the active manifest (excluded)"
        )
    return lines, score


def load_current_specification_ids(
    modes: Iterable[str], benchmark_root: Path | None = None
) -> dict[SpecificationKey, str]:
    """Load stable identities from the current versioned manifests."""

    root = benchmark_root or REPO_ROOT / "benchmark"
    supported_modes = {"proof-completion", "proof-from-scratch"}
    specification_ids: dict[SpecificationKey, str] = {}
    for mode in sorted(set(modes)):
        if mode not in supported_modes:
            raise ValueError(f"cannot load specification identities for unknown mode {mode!r}")
        if mode == "proof-from-scratch":
            manifest = load_module_task_manifest(
                root / "proof-from-scratch-module",
                corpus_manifest_path=root / "proof-from-scratch" / "manifest.json",
            )
            task_specification_ids = {entry.spec.task_id: entry.spec.task_id for entry in manifest.entries}
        else:
            task_specification_ids = load_manifest_specification_ids(root / mode, suite_name=mode)
        specification_ids.update(scope_specification_ids(mode, task_specification_ids))
    return specification_ids


# A scorer maps one task result to a non-negative weight; the group score is the
# weighted pass fraction. Add an entry here to define a new scheme, then select
# it with --scoring.
SCORERS: dict[str, Callable[[dict], float]] = {
    "equal": lambda r: 1.0,  # every task counts the same; score = % passed
}


def weighted_score(
    results: list[dict], weight: Callable[[dict], float], passed: Callable[[dict], bool] = is_pass
) -> tuple[float, int, int]:
    """Return (score_percent, n_passed, n_total) over the scored tasks.

    SKIP and non-genuine tasks are dropped first, so ``n_total`` is the number
    of *scored* tasks (excluded ones count toward neither the pass count nor the
    denominator). ``passed`` is the pass predicate: the default scores pass@1;
    the "with continuations" rate passes ``is_pass_with_continuations`` after
    also dropping interrupted chains (see continuation_rate_line).
    """
    scored = [r for r in results if not is_skipped(r) and not is_non_genuine(r)]
    n_total = len(scored)
    n_pass = sum(1 for r in scored if passed(r))
    total_w = sum(max(weight(r), 0.0) for r in scored)
    pass_w = sum(max(weight(r), 0.0) for r in scored if passed(r))
    pct = (100.0 * pass_w / total_w) if total_w > 0 else 0.0
    return pct, n_pass, n_total


def load_run(path: str) -> dict:
    """Load a results.json (``path`` may be the file itself or its run dir).

    Returns {"path", "id", "backend", "mode", "results"}.
    """
    json_path = os.path.join(path, "results.json") if os.path.isdir(path) else path
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"no results.json at {path}")
    with open(json_path) as f:
        results = json.load(f)
    backends = sorted({r.get("backend") for r in results if r.get("backend")})
    modes = sorted({r.get("mode") for r in results if r.get("mode")})
    run_dir = os.path.dirname(os.path.abspath(json_path))
    return {
        "path": json_path,
        "id": os.path.basename(run_dir) or run_dir,
        "backend": "+".join(backends) or "?",
        "mode": "+".join(modes) or "?",
        "results": results,
    }


def _sum_metric(results: list[dict], field: str) -> float | None:
    """Sum a required non-negative metric without turning missing data into zero."""

    if not results:
        return None
    values: list[float] = []
    for result in results:
        value = result.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (OverflowError, ValueError):
            return None
        if parsed < 0 or not math.isfinite(parsed):
            return None
        values.append(parsed)
    return sum(values)


def _has_equivalent_cost(results: list[dict]) -> bool:
    return any("equivalent_cost_usd" in result for result in results)


def _totals(
    results: list[dict],
) -> tuple[TokenUsage, float | None, float | None, float | None, float | None]:
    tokens = aggregate_token_usage(results)
    formal = [result for result in results if not is_skipped(result) and not is_non_genuine(result)]
    agent_secs = _sum_metric(formal, "agent_time_secs")
    grading_secs = _sum_metric(formal, "grading_time_secs")
    total_secs = _sum_metric(formal, "time_secs")
    equivalent_cost_usd = _sum_metric(formal, "equivalent_cost_usd") if _has_equivalent_cost(results) else None
    return tokens, agent_secs, grading_secs, total_secs, equivalent_cost_usd


def _cost_warnings(results: list[dict]) -> list[tuple[str, str]]:
    warnings: list[tuple[str, str]] = []
    for result in results:
        if is_skipped(result) or is_non_genuine(result):
            continue
        usage = result.get("usage")
        raw_warnings = usage.get("warnings") if isinstance(usage, dict) else None
        if not isinstance(raw_warnings, list):
            continue
        benchmark = str(result.get("benchmark", "?"))
        warnings.extend(
            (benchmark, warning)
            for warning in raw_warnings
            if isinstance(warning, str) and warning.startswith("equivalent cost ")
        )
    return warnings


def _format_time(secs: float | None) -> str:
    return "unavailable" if secs is None else f"{secs:,.1f}s"


def _format_cost(cost_usd: float | None) -> str:
    if cost_usd is None:
        return "unavailable"
    if cost_usd == 0 or cost_usd >= 0.000001:
        return f"${cost_usd:,.6f}"
    return f"${cost_usd:.6g}"


def scorecard_md(
    run: dict,
    weight: Callable[[dict], float],
    scoring_name: str,
    specification_ids: Mapping[SpecificationKey, str] | None = None,
) -> str:
    """Markdown scorecard for a single run: overall score + per-module table."""
    results = run["results"]
    scoring_results = results if specification_ids is None else applicable_manifest_results(results, specification_ids)
    pct, n_pass, n_total = weighted_score(scoring_results, weight)
    tokens, agent_secs, grading_secs, secs, equivalent_cost_usd = _totals(results)
    has_equivalent_cost = _has_equivalent_cost(results)

    lines = [
        f"# Scorecard — {run['backend']} / {run['mode']}",
        "",
        f"**Source**: {run['path']}",
    ]
    unit_line = proof_unit_rate_line(scoring_results)
    if unit_line:
        # Issue #132 defines one module's score as k/n trusted theorems. Keep
        # this ahead of strict whole-module completion diagnostics.
        lines.append(unit_line)
    if specification_ids is None:
        skipped = n_skipped(results)
        non_genuine = n_non_genuine(results)
        pass_line = f"**Pass rate**: {n_pass}/{n_total} ({pct:.1f}%)"
        if skipped:
            pass_line += f" · {skipped} skipped"
        if non_genuine:
            pass_line += f" · {non_genuine} error/interrupted (excluded — re-run)"
        lines.append(pass_line)
    else:
        score_lines, specification_score = specification_score_lines(results, specification_ids)
        lines.extend(score_lines)
        n_pass = specification_score.tasks_passed

    # Separate, clearly-labeled metric — the pass rate above stays pass@1.
    cont_line = continuation_rate_line(scoring_results, weight, n_pass)
    if cont_line:
        lines.append(cont_line)
    continuation_unit_line = proof_unit_rate_line(scoring_results, with_continuations=True)
    if continuation_unit_line and any(result.get("continuations") for result in scoring_results):
        lines.append(continuation_unit_line)
    lines.append(f"**Tokens**: {format_token_usage(tokens, verbose=True)}")
    lines.append(f"**Total agent time**: {_format_time(agent_secs)}")
    lines.append(f"**Total grading time**: {_format_time(grading_secs)}")
    lines.append(f"**Total task time**: {_format_time(secs)}")
    if has_equivalent_cost:
        lines.append(f"**Equivalent cost**: {_format_cost(equivalent_cost_usd)}")
    if scoring_name not in {"equal", SPECIFICATION_EQUAL}:
        lines.append(f"**Scoring**: {scoring_name} (weighted)")

    by_module: dict[str, list[dict]] = defaultdict(list)
    for r in scoring_results:
        if is_skipped(r) or is_non_genuine(r):
            continue  # fully-excluded modules drop out of the table entirely
        by_module[r.get("module") or "?"].append(r)

    module_heading = "## By module (task micro)" if specification_ids is not None else "## By module"
    lines += [
        "",
        module_heading,
        "",
        "| Module | Passed | Total | Pass % |",
        "|--------|-------:|------:|-------:|",
    ]
    for module in sorted(by_module):
        mpct, mp, mt = weighted_score(by_module[module], weight)
        lines.append(f"| {module} | {mp} | {mt} | {mpct:.1f}% |")
    lines.append(f"| **Total** | **{n_pass}** | **{n_total}** | **{pct:.1f}%** |")
    lines.append("")
    cost_warnings = _cost_warnings(results) if has_equivalent_cost else []
    if cost_warnings:
        lines += ["## Cost warnings", ""]
        lines.extend(f"- `{benchmark}`: {warning}" for benchmark, warning in cost_warnings)
        lines.append("")
    return "\n".join(lines)


def comparison_md(
    runs: list[dict],
    weight: Callable[[dict], float],
    scoring_name: str,
    specification_ids: Mapping[SpecificationKey, str] | None = None,
) -> str:
    """Markdown comparison table across several runs (one row per run)."""
    if specification_ids is not None and runs:
        reference = {
            key for result in runs[0]["results"] if (key := _result_specification_key(result)) in specification_ids
        }
        for run in runs[1:]:
            cohort = {
                key for result in run["results"] if (key := _result_specification_key(result)) in specification_ids
            }
            if cohort != reference:
                raise ValueError(
                    "cannot compare runs with different applicable task cohorts: "
                    f"{runs[0]['id']} has {len(reference)} task IDs, {run['id']} has {len(cohort)}"
                )

    lines = [f"# Comparison — {len(runs)} runs", ""]
    if scoring_name not in {"equal", SPECIFICATION_EQUAL}:
        lines += [f"**Scoring**: {scoring_name} (weighted)", ""]
    show_equivalent_cost = any(_has_equivalent_cost(run["results"]) for run in runs)
    show_proof_units = any(
        proof_unit_score(
            run["results"]
            if specification_ids is None
            else applicable_manifest_results(run["results"], specification_ids)
        ).represented_modules
        for run in runs
    )
    score_columns = (
        "Specification pass rate | Task pass rate | Specification macro"
        if specification_ids is not None
        else "Pass % | Passed/Total"
    )
    score_alignment = (
        "--------------------:|-----------:|--------------------:"
        if specification_ids is not None
        else "-------:|-------------:"
    )
    if show_proof_units:
        score_columns = "Proof-unit score (k/n) | " + score_columns
        score_alignment = "----------------------:|" + score_alignment
    if show_equivalent_cost:
        lines += [
            f"| Run | Backend | Mode | {score_columns} | Tokens (in/out) | Time | Equivalent cost |",
            f"|-----|---------|------|{score_alignment}|-----------------|-----:|----------------:|",
        ]
    else:
        lines += [
            f"| Run | Backend | Mode | {score_columns} | Tokens (in/out) | Time |",
            f"|-----|---------|------|{score_alignment}|-----------------|-----:|",
        ]
    for run in runs:
        results = run["results"]
        scoring_results = (
            results if specification_ids is None else applicable_manifest_results(results, specification_ids)
        )
        pct, n_pass, n_total = weighted_score(scoring_results, weight)
        if specification_ids is not None:
            specification_score = specification_equal_score(results, specification_ids)
        tokens, _agent_secs, _grading_secs, secs, equivalent_cost_usd = _totals(run["results"])
        run_has_equivalent_cost = _has_equivalent_cost(run["results"])
        if show_equivalent_cost and not run_has_equivalent_cost and run["backend"] in COST_TIME_BACKENDS:
            formal = [result for result in run["results"] if not is_skipped(result) and not is_non_genuine(result)]
            secs = _sum_metric(formal, "time_secs")
        score_notes = ""
        skipped = n_skipped(scoring_results)
        if skipped:
            score_notes += f" (+{skipped} skipped)"
        non_genuine = n_non_genuine(scoring_results)
        if non_genuine:
            score_notes += f" (+{non_genuine} error/interrupted)"
        if any(r.get("continuations") for r in scoring_results):
            _, cn_pass, _ = weighted_score(scoring_results, weight, passed=is_pass_with_continuations)
            # Name the budget: +1 recovery out of ≤1 round and out of ≤10 are
            # different results, and rows in this table exist to be compared.
            budget = continuation_budget(scoring_results)
            if budget:
                score_notes += f" (+{cn_pass - n_pass} via ≤{budget} continuations)"
            else:
                score_notes += f" (+{cn_pass - n_pass} via continuation)"
            n_cut = sum(1 for r in scoring_results if continuation_interrupted(r))
            if n_cut:
                score_notes += f" (+{n_cut} chain(s) cut)"
        passed_total = f"{n_pass}/{n_total}{score_notes}"
        if specification_ids is None:
            score_cells = f"{pct:.1f}% | {passed_total}"
        else:
            if specification_score.non_applicable_results:
                score_notes += f" (+{specification_score.non_applicable_results} non-applicable)"
            score_cells = (
                f"{specification_score.complete_specifications}/"
                f"{specification_score.resolved_specifications} "
                f"({specification_score.specification_pass_pct:.1f}%) | "
                f"{n_pass}/{n_total} ({specification_score.task_micro_pct:.1f}%){score_notes} | "
                f"{specification_score.specification_macro_pct:.1f}%"
            )
            if specification_score.unresolved_specifications:
                score_cells += f" (+{specification_score.unresolved_specifications} unresolved specification(s))"
        if show_proof_units:
            unit_score = proof_unit_score(scoring_results)
            unit_cell = (
                f"{unit_score.trusted_units}/{unit_score.total_units} ({unit_score.trusted_pct:.1f}%)"
                if unit_score.represented_modules
                else "—"
            )
            if unit_score.excluded_modules:
                unit_cell += f" (+{unit_score.excluded_modules} excluded)"
            score_cells = f"{unit_cell} | {score_cells}"
        row = f"| {run['id']} | {run['backend']} | {run['mode']} | {score_cells} | {format_token_usage(tokens)} | "
        if show_equivalent_cost:
            time_text = _format_time(secs)
            row += f"{time_text} | {_format_cost(equivalent_cost_usd)} |"
        else:
            row += f"{_format_time(secs)} |"
        lines.append(row)
    lines.append("")
    warnings = [
        (run["id"], benchmark, warning) for run in runs for benchmark, warning in _cost_warnings(run["results"])
    ]
    if warnings:
        lines += ["## Cost warnings", ""]
        lines.extend(f"- `{run_id}` / `{benchmark}`: {warning}" for run_id, benchmark, warning in warnings)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tlaps-bench score",
        description=(
            "Score benchmark results (proof-unit k/n for module tasks; strict specification completion otherwise) "
            "from results.json."
        ),
    )
    parser.add_argument("paths", nargs="+", help="One or more results.json files or run directories")
    parser.add_argument(
        "--scoring",
        default=SPECIFICATION_EQUAL,
        choices=[SPECIFICATION_EQUAL, *sorted(SCORERS)],
        help=(
            "Scoring scheme (default: proof-unit k/n for module tasks and specification-equal otherwise; "
            "'equal' retains legacy task-level scoring)"
        ),
    )
    args = parser.parse_args()

    weight = SCORERS["equal"] if args.scoring == SPECIFICATION_EQUAL else SCORERS[args.scoring]
    runs = []
    for p in args.paths:
        try:
            runs.append(load_run(p))
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            sys.stderr.write(f"tlaps-bench score: {e}\n")
            return 1

    specification_ids = None
    if args.scoring == SPECIFICATION_EQUAL:
        modes = {result.get("mode") for run in runs for result in run["results"]}
        try:
            specification_ids = load_current_specification_ids(mode for mode in modes if isinstance(mode, str))
        except (ValueError, OSError) as e:
            sys.stderr.write(f"tlaps-bench score: {e}\n")
            return 1

    try:
        rendered = (
            scorecard_md(runs[0], weight, args.scoring, specification_ids)
            if len(runs) == 1
            else comparison_md(runs, weight, args.scoring, specification_ids)
        )
    except ValueError as e:
        sys.stderr.write(f"tlaps-bench score: {e}\n")
        return 1
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())

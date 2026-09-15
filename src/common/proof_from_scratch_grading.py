"""Pure semantic analysis for one submitted proof-from-scratch module."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from common.proof_from_scratch_module import (
    ModuleTaskContractError,
    ModuleTaskRegions,
    parse_module_task_regions,
)
from common.task_contract import FixedSegmentStatus, compare_fixed_segments
from common.tla_modules import mask_comments_and_strings
from tlacore.model import Module, Theorem

HELPER_UNIT_PREFIX = "helper:"
_OMITTED_KEYWORD = re.compile(r"\bOMITTED\b")
_SMT_KEYWORD = re.compile(r"(?<![A-Za-z0-9_])SMT(?![A-Za-z0-9_])")
_SMTT_KEYWORD = re.compile(r"(?<![A-Za-z0-9_])SMTT(?![A-Za-z0-9_])")
_SMTT_FORM = re.compile(r'SMTT\s*\(\s*"r(?P<round>[0-9]+)"\s*\)(?![A-Za-z0-9_])')


class ModuleSubmissionError(ValueError):
    """A submitted module cannot be graded under the module-task contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LocalProofUnit:
    """One original proof unit or reachable submitted helper theorem."""

    unit_id: str
    kind: str
    theorem_name: str | None
    line_start: int
    line_end: int
    dependencies: tuple[str, ...]
    admitted: bool


@dataclass(frozen=True)
class ModuleSubmissionAnalysis:
    """Validated local theorem graph extracted only from the submission."""

    target_units: tuple[LocalProofUnit, ...]
    helper_units: tuple[LocalProofUnit, ...]
    unused_helper_names: tuple[str, ...]

    @property
    def checked_units(self) -> tuple[LocalProofUnit, ...]:
        return (*self.target_units, *self.helper_units)

    @property
    def local_dependencies(self) -> dict[str, tuple[str, ...]]:
        return {unit.unit_id: unit.dependencies for unit in self.checked_units}


def proof_unit_ids_from_markers(source: str) -> tuple[str, ...]:
    """Read ordered proof-unit IDs from module marker lines."""

    prefix = "\\* BEGIN AGENT PROOF "
    unit_ids = tuple(line.removeprefix(prefix) for line in source.splitlines() if line.startswith(prefix))
    if not unit_ids:
        raise ModuleSubmissionError("MODULE_MARKERS_INVALID", "module task contains no identified proof regions")
    return unit_ids


def _parse_regions(source: str, expected_unit_ids: Iterable[str], *, label: str) -> ModuleTaskRegions:
    try:
        return parse_module_task_regions(source, expected_unit_ids)
    except ModuleTaskContractError as exc:
        raise ModuleSubmissionError(
            "MODULE_MARKERS_INVALID", f"{label} module task has invalid editable regions: {exc}"
        ) from exc


def _theorem_in_range(theorems: tuple[Theorem, ...], start: int, end: int, *, unit_id: str) -> Theorem:
    matches = [theorem for theorem in theorems if theorem.loc is not None and start <= theorem.loc.line_start <= end]
    if len(matches) != 1:
        raise ModuleSubmissionError(
            "PROOF_UNIT_MAPPING_INVALID",
            f"proof unit {unit_id!r} must map to exactly one top-level theorem, found {len(matches)}",
        )
    return matches[0]


def _target_theorems(
    module: Module,
    regions: ModuleTaskRegions,
) -> tuple[tuple[str, Theorem], ...]:
    theorems = tuple(module.theorems)
    result: list[tuple[str, Theorem]] = []
    previous_closing_marker = regions.helper_line_bounds[1] + 1
    for proof in regions.proofs:
        opening_marker = proof.line_bounds[0] - 1
        theorem = _theorem_in_range(
            theorems,
            previous_closing_marker + 1,
            opening_marker - 1,
            unit_id=proof.task_id,
        )
        statement_end = opening_marker - 1
        if theorem.statement_loc is None or not (
            previous_closing_marker + 1 <= theorem.statement_loc.line_start
            and theorem.statement_loc.line_end <= statement_end
        ):
            raise ModuleSubmissionError(
                "TARGET_STATEMENT_MODIFIED",
                f"statement for proof unit {proof.task_id!r} extends into an editable region",
            )
        if theorem.proof_loc is not None and not (
            proof.line_bounds[0] <= theorem.proof_loc.line_start <= proof.line_bounds[1]
        ):
            raise ModuleSubmissionError(
                "PROOF_OUTSIDE_REGION",
                f"proof for unit {proof.task_id!r} is outside its editable proof region",
            )
        result.append((proof.task_id, theorem))
        previous_closing_marker = proof.line_bounds[1] + 1
    return tuple(result)


def _helper_theorems(module: Module, regions: ModuleTaskRegions) -> tuple[Theorem, ...]:
    start, end = regions.helper_line_bounds
    helpers = tuple(
        theorem for theorem in module.theorems if theorem.loc is not None and start <= theorem.loc.line_start <= end
    )
    for theorem in helpers:
        if not theorem.name:
            raise ModuleSubmissionError("HELPER_NAME_REQUIRED", "every submitted helper theorem must be named")
        if theorem.proof_loc is not None and not (start <= theorem.proof_loc.line_start <= end):
            raise ModuleSubmissionError(
                "HELPER_PROOF_OUTSIDE_REGION",
                f"proof for helper theorem {theorem.name!r} is outside the helper region",
            )
    return helpers


def _reject_added_omitted_proofs(
    canonical_regions: ModuleTaskRegions,
    submitted_regions: ModuleTaskRegions,
) -> None:
    """Reject admissions added inside editable regions.

    An unchanged canonical ``PROOF OMITTED`` remains an unresolved target so a
    partially solved module can still earn credit. Any newly introduced
    ``OMITTED`` token, including one buried in a hierarchical proof, admits an
    obligation and must fail before TLAPM can mistake exit 11 for a raw pass.
    """

    if _OMITTED_KEYWORD.search(mask_comments_and_strings(submitted_regions.helpers)):
        raise ModuleSubmissionError(
            "PROOF_OMITTED_ADDED",
            "helper region contains an admitted proof",
        )

    for canonical, submitted in zip(canonical_regions.proofs, submitted_regions.proofs, strict=True):
        if submitted.text == canonical.text:
            continue
        if _OMITTED_KEYWORD.search(mask_comments_and_strings(submitted.text)):
            raise ModuleSubmissionError(
                "PROOF_OMITTED_ADDED",
                f"proof region {submitted.task_id!r} contains an admitted proof",
            )


def _reject_invalid_smt_budgets(regions: ModuleTaskRegions) -> None:
    """Require deterministic, bounded SMT calls in editable proof text."""

    editable_regions = [("helper region", regions.helpers)]
    editable_regions.extend((f"proof region {proof.task_id!r}", proof.text) for proof in regions.proofs)
    for label, source in editable_regions:
        code = mask_comments_and_strings(source)
        if _SMT_KEYWORD.search(code) is not None:
            raise ModuleSubmissionError(
                "SMT_BUDGET_INVALID",
                f'{label} uses standalone SMT; use SMTT("rN") with 1 <= N <= 30',
            )
        for match in _SMTT_KEYWORD.finditer(code):
            form = _SMTT_FORM.match(source, match.start())
            if form is None:
                raise ModuleSubmissionError(
                    "SMT_BUDGET_INVALID",
                    f'{label} uses invalid SMTT form; use SMTT("rN") with 1 <= N <= 30',
                )
            digits = form.group("round").lstrip("0")
            if not digits or len(digits) > 2 or int(digits) > 30:
                raise ModuleSubmissionError(
                    "SMT_BUDGET_INVALID",
                    f'{label} uses invalid SMTT form; use SMTT("rN") with 1 <= N <= 30',
                )


def _reject_forbidden_editable_declarations(module: Module, regions: ModuleTaskRegions) -> None:
    helper_start, helper_end = regions.helper_line_bounds

    def in_helpers(loc) -> bool:
        return loc is not None and helper_start <= loc.line_start <= helper_end

    def proof_unit_at(loc) -> str | None:
        if loc is None:
            return None
        for proof in regions.proofs:
            start, end = proof.line_bounds
            if start <= loc.line_start <= end:
                return proof.task_id
        return None

    forbidden: list[str] = []
    forbidden.extend(f"CONSTANT {symbol.name}" for symbol in module.constants if in_helpers(symbol.loc))
    forbidden.extend(f"VARIABLE {symbol.name}" for symbol in module.variables if in_helpers(symbol.loc))
    forbidden.extend(
        f"{'AXIOM' if assumption.is_axiom else 'ASSUME'} {assumption.name or '<unnamed>'}"
        for assumption in module.assumes
        if in_helpers(assumption.loc)
    )
    forbidden.extend(
        f"nested MODULE {module_symbol.name}" for module_symbol in module.inner_modules if in_helpers(module_symbol.loc)
    )
    forbidden.extend(f"top-level {node.kind}" for node in module.other_top_levels if in_helpers(node.loc))
    if forbidden:
        raise ModuleSubmissionError(
            "FORBIDDEN_HELPER_DECLARATION",
            "helper region contains forbidden declarations: " + ", ".join(forbidden),
        )

    bad_directives = [
        directive.kind
        for directive in module.directives
        if in_helpers(directive.loc) and not directive.definitions_only
    ]
    if bad_directives:
        raise ModuleSubmissionError(
            "FORBIDDEN_HELPER_DIRECTIVE",
            "helper region contains a non-definition USE/HIDE directive",
        )

    proof_region_nodes: list[tuple[str, object]] = []
    proof_region_nodes.extend((f"CONSTANT {value.name}", value.loc) for value in module.constants)
    proof_region_nodes.extend((f"VARIABLE {value.name}", value.loc) for value in module.variables)
    proof_region_nodes.extend(
        (f"{'AXIOM' if value.is_axiom else 'ASSUME'} {value.name or '<unnamed>'}", value.loc)
        for value in module.assumes
    )
    proof_region_nodes.extend(
        (f"INSTANCE {value.name or value.module or '<unnamed>'}", value.loc) for value in module.instances
    )
    proof_region_nodes.extend((f"operator {value.name}", value.loc) for value in module.operators)
    proof_region_nodes.extend((f"nested MODULE {value.name}", value.loc) for value in module.inner_modules)
    proof_region_nodes.extend((f"module directive {value.kind}", value.loc) for value in module.directives)
    proof_region_nodes.extend((f"top-level {value.kind}", value.loc) for value in module.other_top_levels)
    proof_region_nodes.extend((f"theorem {value.name or '<unnamed>'}", value.loc) for value in module.theorems)
    unexpected = [
        (description, unit_id) for description, loc in proof_region_nodes if (unit_id := proof_unit_at(loc)) is not None
    ]
    if unexpected:
        description, unit_id = unexpected[0]
        raise ModuleSubmissionError(
            "TOP_LEVEL_DECLARATION_IN_PROOF",
            f"proof region {unit_id!r} contains an extra {description}; target regions may contain only proofs",
        )


def _reachable_helpers(
    target_units: tuple[LocalProofUnit, ...],
    helpers_by_id: dict[str, LocalProofUnit],
) -> set[str]:
    reachable: set[str] = set()
    pending = [dependency for unit in target_units for dependency in unit.dependencies if dependency in helpers_by_id]
    while pending:
        unit_id = pending.pop()
        if unit_id in reachable:
            continue
        reachable.add(unit_id)
        pending.extend(
            dependency
            for dependency in helpers_by_id[unit_id].dependencies
            if dependency in helpers_by_id and dependency not in reachable
        )
    return reachable


def analyze_module_submission(
    *,
    canonical_source: str,
    submitted_source: str,
    expected_unit_ids: Iterable[str],
    module: Module,
    expected_extends: Iterable[str] | None = None,
) -> ModuleSubmissionAnalysis:
    """Validate immutable regions and derive the submitted local dependency graph."""

    expected = tuple(expected_unit_ids)
    canonical_regions = _parse_regions(canonical_source, expected, label="canonical")
    submitted_regions = _parse_regions(submitted_source, expected, label="submitted")
    fixed_segment_status = compare_fixed_segments(canonical_regions.fixed_segments, submitted_regions.fixed_segments)
    if fixed_segment_status is FixedSegmentStatus.FORMAT_MODIFIED:
        raise ModuleSubmissionError(
            "SCAFFOLD_FORMAT_MODIFIED",
            "fixed module task scaffold differs only in line endings or the final newline",
        )
    if fixed_segment_status is FixedSegmentStatus.MODIFIED:
        raise ModuleSubmissionError(
            "SCAFFOLD_MODIFIED",
            "fixed module task scaffold outside editable regions was modified",
        )

    if expected_extends is not None and tuple(module.extends) != tuple(expected_extends):
        raise ModuleSubmissionError(
            "MODULE_EXTENDS_MODIFIED",
            "submitted module changes the canonical EXTENDS imports through an editable region",
        )

    _reject_invalid_smt_budgets(submitted_regions)
    _reject_forbidden_editable_declarations(module, submitted_regions)
    _reject_added_omitted_proofs(canonical_regions, submitted_regions)
    target_theorems = _target_theorems(module, submitted_regions)
    helper_theorems = _helper_theorems(module, submitted_regions)

    named: dict[str, str] = {}
    for unit_id, theorem in target_theorems:
        if theorem.name:
            if theorem.name in named:
                raise ModuleSubmissionError("LOCAL_NAME_COLLISION", f"local theorem name {theorem.name!r} is repeated")
            named[theorem.name] = unit_id
    for theorem in helper_theorems:
        assert theorem.name is not None
        if theorem.name in named:
            raise ModuleSubmissionError("LOCAL_NAME_COLLISION", f"local theorem name {theorem.name!r} is repeated")
        named[theorem.name] = HELPER_UNIT_PREFIX + theorem.name

    def local_dependencies(theorem: Theorem) -> tuple[str, ...]:
        return tuple(sorted({named[reference] for reference in theorem.references if reference in named}))

    target_units = tuple(
        LocalProofUnit(
            unit_id=unit_id,
            kind="target",
            theorem_name=theorem.name,
            line_start=theorem.loc.line_start if theorem.loc else 0,
            line_end=theorem.loc.line_end if theorem.loc else 0,
            dependencies=local_dependencies(theorem),
            admitted=theorem.is_admitted,
        )
        for unit_id, theorem in target_theorems
    )
    all_helpers = tuple(
        LocalProofUnit(
            unit_id=HELPER_UNIT_PREFIX + (theorem.name or ""),
            kind="helper",
            theorem_name=theorem.name,
            line_start=theorem.loc.line_start if theorem.loc else 0,
            line_end=theorem.loc.line_end if theorem.loc else 0,
            dependencies=local_dependencies(theorem),
            admitted=theorem.is_admitted,
        )
        for theorem in helper_theorems
    )
    helpers_by_id = {unit.unit_id: unit for unit in all_helpers}
    reachable = _reachable_helpers(target_units, helpers_by_id)
    helper_units = tuple(unit for unit in all_helpers if unit.unit_id in reachable)

    checked = {unit.unit_id for unit in (*target_units, *helper_units)}
    target_units = tuple(
        replace(unit, dependencies=tuple(dependency for dependency in unit.dependencies if dependency in checked))
        for unit in target_units
    )
    helper_units = tuple(
        replace(unit, dependencies=tuple(dependency for dependency in unit.dependencies if dependency in checked))
        for unit in helper_units
    )
    unused_helper_names = tuple(unit.theorem_name or "" for unit in all_helpers if unit.unit_id not in reachable)
    return ModuleSubmissionAnalysis(
        target_units=target_units,
        helper_units=helper_units,
        unused_helper_names=unused_helper_names,
    )


__all__ = [
    "HELPER_UNIT_PREFIX",
    "LocalProofUnit",
    "ModuleSubmissionAnalysis",
    "ModuleSubmissionError",
    "analyze_module_submission",
    "proof_unit_ids_from_markers",
]

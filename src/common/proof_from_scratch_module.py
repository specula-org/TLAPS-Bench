"""Shared contract for module-level proof-from-scratch tasks.

The generated corpus groups existing theorem target IDs into one editable proof
module per source specification. This module fixes the boundary shared by the
generator and evaluator: strict metadata, identified proof regions, fixed
scaffold extraction, and dependency-closed trust. It deliberately performs no
SANY or TLAPM work.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from common.task_contract import BEGIN_AGENT_HELPERS, BEGIN_AGENT_PROOF, END_AGENT_HELPERS, END_AGENT_PROOF

MODULE_TASK_FORMAT_VERSION = 1

BEGIN_AGENT_PROOF_PREFIX = BEGIN_AGENT_PROOF + " "
END_AGENT_PROOF_PREFIX = END_AGENT_PROOF + " "

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ModuleTaskContractError(ValueError):
    """Module-task metadata or editable regions violate the shared contract."""


@dataclass(frozen=True)
class ModuleProofUnit:
    """One existing theorem target scored inside a module task."""

    task_id: str
    statement_sha256: str


@dataclass(frozen=True)
class ModuleTaskSpec:
    """Immutable identity and ordered proof units for one module task."""

    format_version: int
    task_id: str
    source_sha256: str
    proof_units: tuple[ModuleProofUnit, ...]

    @property
    def proof_unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.task_id for unit in self.proof_units)


@dataclass(frozen=True)
class ModuleProofRegion:
    """One submitted proof body, identified by its existing theorem task ID."""

    task_id: str
    text: str
    line_bounds: tuple[int, int]


@dataclass(frozen=True)
class ModuleTaskRegions:
    """One helper body, ordered proof bodies, and their immutable separators."""

    fixed_segments: tuple[str, ...]
    helpers: str
    helper_line_bounds: tuple[int, int]
    proofs: tuple[ModuleProofRegion, ...]

    @property
    def proof_unit_ids(self) -> tuple[str, ...]:
        return tuple(proof.task_id for proof in self.proofs)

    def render(
        self,
        *,
        helpers: str | None = None,
        proofs: Mapping[str, str] | None = None,
    ) -> str:
        """Rebuild the task while replacing only identified editable bodies."""

        replacements = proofs or {}
        unknown = set(replacements) - set(self.proof_unit_ids)
        if unknown:
            raise ModuleTaskContractError(f"replacement proofs contain unknown task IDs: {sorted(unknown)}")

        editable = [self.helpers if helpers is None else helpers]
        editable.extend(replacements.get(proof.task_id, proof.text) for proof in self.proofs)
        editable = [body if not body or body.endswith(("\n", "\r")) else body + "\n" for body in editable]
        parts: list[str] = []
        for fixed, body in zip(self.fixed_segments[:-1], editable, strict=True):
            parts.extend((fixed, body))
        parts.append(self.fixed_segments[-1])
        return "".join(parts)


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ModuleTaskContractError(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def _exact_object(value: object, keys: set[str], *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        expected = ", ".join(sorted(keys))
        raise ModuleTaskContractError(f"{label} must contain exactly: {expected}")
    return value


def _canonical_tla_path(value: object, *, label: str) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise ModuleTaskContractError(f"{label} must be a non-empty canonical relative .tla path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise ModuleTaskContractError(f"{label} must be a canonical relative path: {value!r}")
    if path.suffix != ".tla":
        raise ModuleTaskContractError(f"{label} must name a .tla file: {value!r}")
    return value


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ModuleTaskContractError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def validate_module_task_spec_data(raw: object) -> ModuleTaskSpec:
    """Validate one exact future module-task manifest entry."""

    root = _exact_object(
        raw,
        {"format_version", "task_id", "source_sha256", "proof_units"},
        label="module task spec",
    )
    if type(root["format_version"]) is not int or root["format_version"] != MODULE_TASK_FORMAT_VERSION:
        raise ModuleTaskContractError(
            f"unsupported module task format_version {root['format_version']!r}; expected {MODULE_TASK_FORMAT_VERSION}"
        )
    task_id = _canonical_tla_path(root["task_id"], label="module task_id")
    source_sha256 = _sha256(root["source_sha256"], label="module source_sha256")
    raw_units = root["proof_units"]
    if type(raw_units) is not list or not raw_units:
        raise ModuleTaskContractError("module proof_units must be a non-empty list")

    proof_units: list[ModuleProofUnit] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_units):
        entry = _exact_object(value, {"task_id", "statement_sha256"}, label=f"proof unit {index}")
        unit_id = _canonical_tla_path(entry["task_id"], label=f"proof unit {index} task_id")
        if unit_id in seen:
            raise ModuleTaskContractError(f"module repeats proof unit task ID {unit_id!r}")
        seen.add(unit_id)
        proof_units.append(
            ModuleProofUnit(
                task_id=unit_id,
                statement_sha256=_sha256(
                    entry["statement_sha256"],
                    label=f"proof unit {unit_id!r} statement_sha256",
                ),
            )
        )

    return ModuleTaskSpec(
        format_version=MODULE_TASK_FORMAT_VERSION,
        task_id=task_id,
        source_sha256=source_sha256,
        proof_units=tuple(proof_units),
    )


def load_module_task_spec(path: Path) -> ModuleTaskSpec:
    """Load one strict module-task spec without fallback or inferred fields."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ModuleTaskContractError(f"cannot read module task spec {path}: {exc}") from exc
    try:
        raw = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except ModuleTaskContractError as exc:
        raise ModuleTaskContractError(f"invalid module task spec {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModuleTaskContractError(
            f"invalid JSON in module task spec {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return validate_module_task_spec_data(raw)


def statement_sha256(statement: str) -> str:
    """Hash the exact canonical statement bytes recorded for one proof unit."""

    if type(statement) is not str:
        raise ModuleTaskContractError("statement must be a string")
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def begin_agent_proof(task_id: str) -> str:
    """Canonical opening marker for one existing theorem task ID."""

    return BEGIN_AGENT_PROOF_PREFIX + _canonical_tla_path(task_id, label="proof marker task_id")


def end_agent_proof(task_id: str) -> str:
    """Canonical closing marker for one existing theorem task ID."""

    return END_AGENT_PROOF_PREFIX + _canonical_tla_path(task_id, label="proof marker task_id")


def _line_marker(line: str) -> str:
    return line.removesuffix("\n").removesuffix("\r")


def _single_line_index(lines: list[str], marker: str, *, label: str) -> int:
    matches = [index for index, line in enumerate(lines) if _line_marker(line) == marker]
    if len(matches) != 1:
        raise ModuleTaskContractError(f"module task must contain exactly one {label} marker")
    return matches[0]


def _body_bounds(begin_line: int, end_line: int) -> tuple[int, int]:
    """Return inclusive one-based body bounds; an empty body has start > end."""

    return (begin_line + 2, end_line)


def parse_module_task_regions(source: str, expected_unit_ids: Iterable[str]) -> ModuleTaskRegions:
    """Parse one helper region followed by identified proof regions.

    Marker lines and every byte outside the bodies belong to ``fixed_segments``.
    Comparing those segments between the canonical task and a submission keeps
    the Model/Defs interface, target statements, target order, and marker IDs
    immutable without making the whole task file editable.
    """

    if type(source) is not str:
        raise ModuleTaskContractError("module task source must be a string")
    expected = tuple(_canonical_tla_path(value, label="expected proof unit ID") for value in expected_unit_ids)
    if not expected:
        raise ModuleTaskContractError("expected proof unit IDs must not be empty")
    if len(expected) != len(set(expected)):
        raise ModuleTaskContractError("expected proof unit IDs repeat a task ID")

    lines = source.splitlines(keepends=True)
    helper_begin = _single_line_index(lines, BEGIN_AGENT_HELPERS, label="BEGIN AGENT HELPERS")
    helper_end = _single_line_index(lines, END_AGENT_HELPERS, label="END AGENT HELPERS")
    if helper_begin >= helper_end:
        raise ModuleTaskContractError("module helper markers are reversed or nested incorrectly")

    editable_ranges: list[tuple[int, int, str, str]] = [
        (helper_begin + 1, helper_end, "helpers", ""),
    ]
    proof_regions: list[ModuleProofRegion] = []
    previous_end = helper_end
    for unit_id in expected:
        begin = _single_line_index(lines, begin_agent_proof(unit_id), label=f"BEGIN AGENT PROOF {unit_id}")
        end = _single_line_index(lines, end_agent_proof(unit_id), label=f"END AGENT PROOF {unit_id}")
        if begin <= previous_end or begin >= end:
            raise ModuleTaskContractError(f"proof region {unit_id!r} is out of order or malformed")
        body = "".join(lines[begin + 1 : end])
        proof_regions.append(
            ModuleProofRegion(
                task_id=unit_id,
                text=body,
                line_bounds=_body_bounds(begin, end),
            )
        )
        editable_ranges.append((begin + 1, end, "proof", unit_id))
        previous_end = end

    known_markers = {
        BEGIN_AGENT_HELPERS,
        END_AGENT_HELPERS,
        *(begin_agent_proof(unit_id) for unit_id in expected),
        *(end_agent_proof(unit_id) for unit_id in expected),
    }
    for line in lines:
        marker = _line_marker(line)
        if marker in {BEGIN_AGENT_PROOF, END_AGENT_PROOF} or marker.startswith(
            (BEGIN_AGENT_PROOF_PREFIX, END_AGENT_PROOF_PREFIX)
        ):
            if marker not in known_markers:
                raise ModuleTaskContractError(f"module task contains unknown proof marker {marker!r}")

    fixed_segments: list[str] = []
    cursor = 0
    for start, end, _kind, _unit_id in editable_ranges:
        fixed_segments.append("".join(lines[cursor:start]))
        cursor = end
    fixed_segments.append("".join(lines[cursor:]))

    return ModuleTaskRegions(
        fixed_segments=tuple(fixed_segments),
        helpers="".join(lines[helper_begin + 1 : helper_end]),
        helper_line_bounds=_body_bounds(helper_begin, helper_end),
        proofs=tuple(proof_regions),
    )


def compute_trusted_units(
    raw_pass: Iterable[str],
    local_dependencies: Mapping[str, Iterable[str]],
) -> frozenset[str]:
    """Return the least dependency-closed set of raw checker passes.

    ``local_dependencies`` must include every original theorem and submitted
    helper involved in local trust.  Canonical givens and official-library facts
    are trusted outside this graph.  Unknown dependencies fail closed instead of
    being silently treated as external facts.  Starting from the empty set also
    prevents a raw-PASS cycle from making its own members trusted.
    """

    if not isinstance(local_dependencies, Mapping):
        raise ModuleTaskContractError("local dependencies must be a mapping")

    dependencies: dict[str, frozenset[str]] = {}
    for unit_id, raw in local_dependencies.items():
        if type(unit_id) is not str or not unit_id:
            raise ModuleTaskContractError("local dependency unit IDs must be non-empty strings")
        if isinstance(raw, str):
            raise ModuleTaskContractError(f"dependencies for {unit_id!r} must be an iterable of unit IDs")
        values = tuple(raw)
        if any(type(value) is not str or not value for value in values):
            raise ModuleTaskContractError(f"dependencies for {unit_id!r} must be non-empty strings")
        if len(values) != len(set(values)):
            raise ModuleTaskContractError(f"dependencies for {unit_id!r} repeat a unit ID")
        dependencies[unit_id] = frozenset(values)

    known = set(dependencies)
    if isinstance(raw_pass, str):
        raise ModuleTaskContractError("raw PASS unit IDs must be an iterable of unit IDs")
    passed = set(raw_pass)
    if any(type(unit_id) is not str or not unit_id for unit_id in passed):
        raise ModuleTaskContractError("raw PASS unit IDs must be non-empty strings")
    unknown_passes = passed - known
    if unknown_passes:
        raise ModuleTaskContractError(f"raw PASS contains unknown unit IDs: {sorted(unknown_passes)}")
    unknown_dependencies = {value for values in dependencies.values() for value in values if value not in known}
    if unknown_dependencies:
        raise ModuleTaskContractError(f"local dependencies contain unknown unit IDs: {sorted(unknown_dependencies)}")

    trusted: set[str] = set()
    while True:
        newly_trusted = {unit_id for unit_id in passed - trusted if dependencies[unit_id] <= trusted}
        if not newly_trusted:
            return frozenset(trusted)
        trusted.update(newly_trusted)


__all__ = [
    "BEGIN_AGENT_PROOF_PREFIX",
    "END_AGENT_PROOF_PREFIX",
    "MODULE_TASK_FORMAT_VERSION",
    "ModuleProofRegion",
    "ModuleProofUnit",
    "ModuleTaskContractError",
    "ModuleTaskRegions",
    "ModuleTaskSpec",
    "begin_agent_proof",
    "compute_trusted_units",
    "end_agent_proof",
    "load_module_task_spec",
    "parse_module_task_regions",
    "statement_sha256",
    "validate_module_task_spec_data",
]

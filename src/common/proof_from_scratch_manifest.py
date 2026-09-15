"""Strict loader for the generated proof-from-scratch module corpus.

The generator owns how module tasks are produced. The evaluator consumes only
the versioned manifest and the exact files named by it; it never reconstructs a
second grouping from the legacy theorem-level corpus.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from common.proof_from_scratch_module import (
    MODULE_TASK_FORMAT_VERSION,
    ModuleTaskContractError,
    ModuleTaskRegions,
    ModuleTaskSpec,
    parse_module_task_regions,
    statement_sha256,
    validate_module_task_spec_data,
)
from common.task_contract import TaskContractError, load_manifest_specification_ids
from tlacore.source import strip_comments

MANIFEST_FILENAME = "manifest.json"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_THEOREM_SCAN = re.compile(r"^[ \t]*(THEOREM|LEMMA|COROLLARY|PROPOSITION)\b", re.MULTILINE)
_PROOF_ARTIFACT_SCAN = re.compile(
    r"^[ \t]*(?:(?:LOCAL[ \t]+)?(?:THEOREM|LEMMA|COROLLARY|PROPOSITION)\b"
    r"|(?:PROOF|OMITTED|OBVIOUS|BY|QED)\b|<\d+>)",
    re.MULTILINE,
)
_TASK_PROOF_ARTIFACT_SCAN = re.compile(
    r"^[ \t]*(?:(?:PROOF|OMITTED|OBVIOUS|BY|QED|USE|HIDE|DEFINE|SUFFICES|WITNESS|PICK|TAKE)\b|<\d+>)",
    re.MULTILINE,
)


class ModuleTaskManifestError(ValueError):
    """The module corpus manifest or one of its declared files is invalid."""


@dataclass(frozen=True)
class ModuleTaskEntry:
    """One generated module task and its exact read-only context."""

    spec: ModuleTaskSpec
    context: tuple[str, ...]
    renamed_bindings: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class ModuleTaskManifest:
    """Validated, complete module-task corpus metadata."""

    format_version: int
    corpus_sha256: str
    entries: tuple[ModuleTaskEntry, ...]

    @property
    def proof_unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.task_id for entry in self.entries for unit in entry.spec.proof_units)


def _reject_json_constant(value: str) -> Any:
    raise ModuleTaskManifestError(f"manifest contains non-standard JSON constant {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModuleTaskManifestError(f"manifest contains duplicate JSON key {key!r}")
        result[key] = value
    return result


def _exact_object(value: object, keys: set[str], *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        expected = ", ".join(sorted(keys))
        raise ModuleTaskManifestError(f"{label} must contain exactly: {expected}")
    return value


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ModuleTaskManifestError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _canonical_tla_path(value: object, *, label: str) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise ModuleTaskManifestError(f"{label} must be a non-empty canonical relative .tla path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise ModuleTaskManifestError(f"{label} must be a canonical relative path: {value!r}")
    if path.suffix != ".tla":
        raise ModuleTaskManifestError(f"{label} must name a .tla file: {value!r}")
    return value


def _validate_renamed_bindings(
    value: object,
    spec: ModuleTaskSpec,
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    if type(value) is not dict:
        raise ModuleTaskManifestError(f"renamed_bindings for {spec.task_id!r} must be an object")
    unknown = set(value) - set(spec.proof_unit_ids)
    if unknown:
        raise ModuleTaskManifestError(
            f"renamed_bindings for {spec.task_id!r} contains unknown proof units: {sorted(unknown)}"
        )

    result: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for unit_id, raw_renames in value.items():
        if type(raw_renames) is not dict or not raw_renames:
            raise ModuleTaskManifestError(f"renamed_bindings for proof unit {unit_id!r} must be a non-empty object")
        renames: dict[str, str] = {}
        for original, replacement in raw_renames.items():
            if type(original) is not str or not original or type(replacement) is not str or not replacement:
                raise ModuleTaskManifestError(
                    f"renamed binding names for proof unit {unit_id!r} must be non-empty strings"
                )
            if original == replacement:
                raise ModuleTaskManifestError(
                    f"renamed binding {original!r} for proof unit {unit_id!r} does not change the name"
                )
            renames[original] = replacement
        result.append((unit_id, tuple(sorted(renames.items()))))
    return tuple(sorted(result))


def module_task_statements(source: str, regions: ModuleTaskRegions) -> tuple[tuple[str, str], ...]:
    """Return the exact target statements carried by a generated module task."""

    lines = source.splitlines(keepends=True)
    statements: list[tuple[str, str]] = []
    cursor = regions.helper_line_bounds[1] + 1
    for proof in regions.proofs:
        marker_index = proof.line_bounds[0] - 2
        statement = "".join(lines[cursor:marker_index]).strip()
        if not statement:
            raise ModuleTaskManifestError(f"proof unit {proof.task_id!r} has an empty target statement")
        statements.append((proof.task_id, statement))
        cursor = proof.line_bounds[1] + 1
    return tuple(statements)


def _resolve_declared_file(root: Path, relative: str, *, label: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ModuleTaskManifestError(
            f"{label} does not resolve to a file inside the declared root: {relative!r}"
        ) from exc
    if not resolved.is_file() or path.is_symlink():
        raise ModuleTaskManifestError(f"{label} must be a regular non-symlink file: {relative!r}")
    return resolved


def _validate_source_file(source_root: Path, entry: ModuleTaskEntry) -> None:
    """Bind a generated task to the exact source specification it represents."""

    source_path = _resolve_declared_file(source_root, entry.spec.task_id, label="source specification")
    try:
        source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ModuleTaskManifestError(f"cannot read source specification {entry.spec.task_id!r}: {exc}") from exc
    if source_sha256 != entry.spec.source_sha256:
        raise ModuleTaskManifestError(
            f"source specification {entry.spec.task_id!r} source_sha256 does not match the shipped source"
        )


def _validate_task_file(root: Path, entry: ModuleTaskEntry) -> None:
    task_path = _resolve_declared_file(root, entry.spec.task_id, label="module task")
    try:
        source = task_path.read_text(encoding="utf-8")
        regions = parse_module_task_regions(source, entry.spec.proof_unit_ids)
    except (OSError, UnicodeError, ModuleTaskContractError) as exc:
        raise ModuleTaskManifestError(f"invalid module task {entry.spec.task_id!r}: {exc}") from exc

    statements = dict(module_task_statements(source, regions))
    if regions.render() != source:
        raise ModuleTaskManifestError(f"module task {entry.spec.task_id!r} does not round-trip through its regions")
    if regions.helpers.strip():
        raise ModuleTaskManifestError(f"canonical module task {entry.spec.task_id!r} has a non-empty helper region")
    for unit in entry.spec.proof_units:
        if statement_sha256(statements[unit.task_id]) != unit.statement_sha256:
            raise ModuleTaskManifestError(
                f"module task {entry.spec.task_id!r} statement digest does not match proof unit {unit.task_id!r}"
            )
    for proof in regions.proofs:
        if proof.text.strip() != "PROOF OMITTED":
            raise ModuleTaskManifestError(
                f"canonical module task {entry.spec.task_id!r} proof region {proof.task_id!r} is not PROOF OMITTED"
            )

    fixed_source = strip_comments("".join(regions.fixed_segments))
    artifact = _TASK_PROOF_ARTIFACT_SCAN.search(fixed_source)
    if artifact is not None:
        raise ModuleTaskManifestError(
            f"canonical module task {entry.spec.task_id!r} contains proof artifact "
            f"{artifact.group(0).strip()!r} outside an editable region"
        )
    theorem_keywords = _THEOREM_SCAN.findall(fixed_source)
    if len(theorem_keywords) != len(entry.spec.proof_units):
        raise ModuleTaskManifestError(
            f"canonical module task {entry.spec.task_id!r} contains {len(theorem_keywords)} target statements; "
            f"expected {len(entry.spec.proof_units)}"
        )

    for context in entry.context:
        context_path = _resolve_declared_file(root, context, label=f"context for {entry.spec.task_id!r}")
        try:
            context_source = context_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ModuleTaskManifestError(f"cannot read context {context!r}: {exc}") from exc
        artifact = _PROOF_ARTIFACT_SCAN.search(strip_comments(context_source))
        if artifact is not None:
            raise ModuleTaskManifestError(f"context {context!r} contains proof artifact {artifact.group(0).strip()!r}")


def load_module_task_manifest(
    root: Path,
    *,
    corpus_manifest_path: Path | None = None,
    source_root: Path | None = None,
) -> ModuleTaskManifest:
    """Load and fully validate the generated module-task corpus manifest.

    corpus_manifest_path binds the generated suite to the exact legacy theorem
    corpus from which the generator produced it. The evaluator passes this path
    explicitly instead of inferring any task grouping from that corpus.

    source_root identifies the shipped source-specification tree used to verify
    each entry's ``source_sha256``. When omitted, it is inferred as the
    repository's ``source`` sibling for the conventional ``benchmark`` layout.
    """

    try:
        resolved_root = root.resolve(strict=True)
        text = (resolved_root / MANIFEST_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError) as exc:
        raise ModuleTaskManifestError(f"cannot read module-task manifest under {root}: {exc}") from exc
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except ModuleTaskManifestError:
        raise
    except json.JSONDecodeError as exc:
        raise ModuleTaskManifestError(
            f"invalid JSON in module-task manifest at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    document = _exact_object(
        raw,
        {"format_version", "corpus_sha256", "complete", "module_tasks"},
        label="module-task manifest",
    )
    if type(document["format_version"]) is not int or document["format_version"] != MODULE_TASK_FORMAT_VERSION:
        raise ModuleTaskManifestError(
            f"unsupported module-task manifest format_version {document['format_version']!r}; "
            f"expected {MODULE_TASK_FORMAT_VERSION}"
        )
    if document["complete"] is not True:
        raise ModuleTaskManifestError("module-task manifest must describe a complete corpus")
    corpus_sha256 = _sha256(document["corpus_sha256"], label="manifest corpus_sha256")
    if corpus_manifest_path is not None:
        try:
            current_corpus_sha256 = hashlib.sha256(corpus_manifest_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ModuleTaskManifestError(f"cannot read source corpus manifest {corpus_manifest_path}: {exc}") from exc
        if current_corpus_sha256 != corpus_sha256:
            raise ModuleTaskManifestError(
                "module-task manifest was generated from a different proof-from-scratch corpus"
            )

    raw_entries = document["module_tasks"]
    if type(raw_entries) is not list or not raw_entries:
        raise ModuleTaskManifestError("module-task manifest module_tasks must be a non-empty list")

    if source_root is None:
        source_root = resolved_root.parent.parent / "source"
    try:
        resolved_source_root = source_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ModuleTaskManifestError(f"cannot read shipped source tree under {source_root}: {exc}") from exc

    entries: list[ModuleTaskEntry] = []
    seen_tasks: set[str] = set()
    seen_units: set[str] = set()
    for index, value in enumerate(raw_entries):
        raw_entry = _exact_object(value, {"spec", "context", "renamed_bindings"}, label=f"module task {index}")
        try:
            spec = validate_module_task_spec_data(raw_entry["spec"])
        except ModuleTaskContractError as exc:
            raise ModuleTaskManifestError(f"invalid module task {index}: {exc}") from exc
        if spec.task_id in seen_tasks:
            raise ModuleTaskManifestError(f"module-task manifest repeats task ID {spec.task_id!r}")
        seen_tasks.add(spec.task_id)
        repeated_units = seen_units.intersection(spec.proof_unit_ids)
        if repeated_units:
            raise ModuleTaskManifestError(f"proof units appear in more than one module task: {sorted(repeated_units)}")
        seen_units.update(spec.proof_unit_ids)

        raw_context = raw_entry["context"]
        if type(raw_context) is not list:
            raise ModuleTaskManifestError(f"context for {spec.task_id!r} must be a list")
        context = tuple(
            _canonical_tla_path(path, label=f"context path {context_index} for {spec.task_id!r}")
            for context_index, path in enumerate(raw_context)
        )
        if len(context) != len(set(context)):
            raise ModuleTaskManifestError(f"context for {spec.task_id!r} repeats a path")
        if spec.task_id in context:
            raise ModuleTaskManifestError(f"module task {spec.task_id!r} also appears in its context")
        workspace_names = [PurePosixPath(spec.task_id).name, *(PurePosixPath(path).name for path in context)]
        if len(workspace_names) != len(set(workspace_names)):
            raise ModuleTaskManifestError(f"module task {spec.task_id!r} has colliding workspace filenames")

        entry = ModuleTaskEntry(
            spec=spec,
            context=context,
            renamed_bindings=_validate_renamed_bindings(raw_entry["renamed_bindings"], spec),
        )
        _validate_source_file(resolved_source_root, entry)
        _validate_task_file(resolved_root, entry)
        entries.append(entry)

    ordered_ids = [entry.spec.task_id for entry in entries]
    if ordered_ids != sorted(ordered_ids):
        raise ModuleTaskManifestError("module-task manifest entries must be sorted by task ID")
    if corpus_manifest_path is not None:
        try:
            corpus_specification_ids = load_manifest_specification_ids(
                corpus_manifest_path.parent,
                suite_name="proof-from-scratch",
            )
        except TaskContractError as exc:
            raise ModuleTaskManifestError(f"invalid source proof-from-scratch manifest: {exc}") from exc
        expected_by_spec: dict[str, set[str]] = {}
        for unit_id, spec_id in corpus_specification_ids.items():
            expected_by_spec.setdefault(spec_id, set()).add(unit_id)
        actual_by_spec = {entry.spec.task_id: set(entry.spec.proof_unit_ids) for entry in entries}
        if set(actual_by_spec) != set(expected_by_spec):
            missing = sorted(set(expected_by_spec) - set(actual_by_spec))
            extra = sorted(set(actual_by_spec) - set(expected_by_spec))
            raise ModuleTaskManifestError(
                f"module-task manifest specification coverage differs from the source corpus; "
                f"missing={missing}, extra={extra}"
            )
        mismatched = [
            spec_id for spec_id in sorted(expected_by_spec) if actual_by_spec[spec_id] != expected_by_spec[spec_id]
        ]
        if mismatched:
            raise ModuleTaskManifestError(
                f"module-task manifest proof-unit coverage differs from the source corpus for {mismatched}"
            )
    return ModuleTaskManifest(
        format_version=MODULE_TASK_FORMAT_VERSION,
        corpus_sha256=corpus_sha256,
        entries=tuple(entries),
    )


__all__ = [
    "MANIFEST_FILENAME",
    "ModuleTaskEntry",
    "ModuleTaskManifest",
    "ModuleTaskManifestError",
    "load_module_task_manifest",
    "module_task_statements",
]

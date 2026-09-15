"""Shared manifest and editable-region contract for layered proof tasks.

Generators produce the manifest and editable-region markers; evaluators consume
them. Keeping their validation here gives both sides one small, fail-closed
interface without coupling evaluator code to generator logic.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from common.tla_modules import RESOLVABLE_MODULES, referenced_modules

MANIFEST_FILENAME = "manifest.json"

_BASE_MANIFEST_ENTRY_KEYS = frozenset({"spec_id", "context"})
_SUITE_MANIFEST_ENTRY_KEYS = {
    "proof-completion": frozenset({"spec_id", "context", "reference_proof_steps"}),
    "proof-from-scratch": _BASE_MANIFEST_ENTRY_KEYS,
}

BEGIN_AGENT_HELPERS = r"\* BEGIN AGENT HELPERS"
END_AGENT_HELPERS = r"\* END AGENT HELPERS"
BEGIN_AGENT_PROOF = r"\* BEGIN AGENT PROOF"
END_AGENT_PROOF = r"\* END AGENT PROOF"

EDITABLE_REGION_MARKERS = (
    BEGIN_AGENT_HELPERS,
    END_AGENT_HELPERS,
    BEGIN_AGENT_PROOF,
    END_AGENT_PROOF,
)
PROOF_REGION_MARKERS = (BEGIN_AGENT_PROOF, END_AGENT_PROOF)

_MODULE_HEADER = re.compile(r"^-+\s*MODULE\s+([A-Za-z_]\w*)\s*-+\s*$")
_SOURCE_NEWLINE = re.compile(r"\r\n|\r|\n")


class TaskContractError(ValueError):
    """Base class for an invalid layered-task contract."""


class ManifestError(TaskContractError):
    """A layered-task manifest or one of its files is invalid."""


class EditableRegionError(TaskContractError):
    """A task does not contain the exact editable-region marker structure."""


class FixedSegmentStatus(StrEnum):
    """How submitted immutable task segments differ from the canonical task."""

    MATCH = "match"
    FORMAT_MODIFIED = "format-modified"
    MODIFIED = "modified"


@dataclass(frozen=True)
class TaskBoundary:
    """One editable task and the complete local context assigned to it."""

    task_key: str
    spec_id: str
    task_path: Path
    context_paths: tuple[Path, ...]
    reference_proof_steps: int | None = None


@dataclass(frozen=True)
class EditableRegions:
    """A task split into two editable regions and three immutable segments.

    Marker lines are intentionally part of the immutable segments.  Comparing
    ``fixed_segments`` between canonical and submitted sources therefore checks
    the marker bytes as well as the scaffold around them.
    """

    fixed_prefix: str
    helpers: str
    fixed_middle: str
    proof: str
    fixed_suffix: str
    helper_line_bounds: tuple[int, int]
    proof_line_bounds: tuple[int, int]

    @property
    def fixed_segments(self) -> tuple[str, str, str]:
        """Return the portions that must match the canonical task byte-for-byte."""

        return (self.fixed_prefix, self.fixed_middle, self.fixed_suffix)

    def render(self, *, helpers: str | None = None, proof: str | None = None) -> str:
        """Rebuild the source, optionally replacing either editable region."""

        return "".join(
            (
                self.fixed_prefix,
                self.helpers if helpers is None else helpers,
                self.fixed_middle,
                self.proof if proof is None else proof,
                self.fixed_suffix,
            )
        )


@dataclass(frozen=True)
class ProofRegion:
    """A task split around one editable proof and two immutable segments."""

    fixed_prefix: str
    proof: str
    fixed_suffix: str
    proof_line_bounds: tuple[int, int]

    @property
    def fixed_segments(self) -> tuple[str, str]:
        """Return the portions that must match the canonical task byte-for-byte."""

        return (self.fixed_prefix, self.fixed_suffix)

    def render(self, *, proof: str | None = None) -> str:
        """Rebuild the source, optionally replacing the editable proof."""

        return "".join((self.fixed_prefix, self.proof if proof is None else proof, self.fixed_suffix))


def compare_fixed_segments(canonical: Sequence[str], submitted: Sequence[str]) -> FixedSegmentStatus:
    """Compare immutable task bytes under the documented newline policy.

    Extra CR/LF newlines at EOF are harmless and count as a match. Differences
    consisting only of line-ending style or a missing final newline are format
    failures, while every other difference changes the canonical scaffold.
    """

    canonical_segments = tuple(canonical)
    submitted_segments = tuple(submitted)
    if submitted_segments == canonical_segments:
        return FixedSegmentStatus.MATCH
    if len(submitted_segments) != len(canonical_segments):
        return FixedSegmentStatus.MODIFIED

    canonical_suffix = canonical_segments[-1]
    submitted_suffix = submitted_segments[-1]
    extra_suffix = submitted_suffix[len(canonical_suffix) :] if submitted_suffix.startswith(canonical_suffix) else None
    if submitted_segments[:-1] == canonical_segments[:-1] and extra_suffix and not extra_suffix.strip("\r\n"):
        return FixedSegmentStatus.MATCH

    def normalize_format(segments: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_SOURCE_NEWLINE.sub("\n", segment) for segment in segments)
        return (*normalized[:-1], normalized[-1].rstrip("\n"))

    if normalize_format(submitted_segments) == normalize_format(canonical_segments):
        return FixedSegmentStatus.FORMAT_MODIFIED
    return FixedSegmentStatus.MODIFIED


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ManifestError(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def _load_manifest_json(manifest_path: Path) -> Any:
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ManifestError(f"cannot read {manifest_path}: {exc}") from exc

    try:
        return json.loads(text, object_pairs_hook=_json_object_without_duplicates)
    except ManifestError as exc:
        raise ManifestError(f"invalid {manifest_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"invalid JSON in {manifest_path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _suite_root(path: Path, *, suite_name: str) -> Path:
    try:
        root = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ManifestError(f"{suite_name} suite root does not exist: {path}") from exc
    if not root.is_dir():
        raise ManifestError(f"{suite_name} suite root is not a directory: {path}")
    return root


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_manifest(root: Path, *, suite_name: str) -> Path:
    manifest_path = root / MANIFEST_FILENAME
    try:
        resolved = manifest_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ManifestError(f"missing {suite_name} manifest: {manifest_path}") from exc
    if not _is_within(resolved, root):
        raise ManifestError(f"{suite_name} manifest escapes the suite root: {manifest_path}")
    if not resolved.is_file():
        raise ManifestError(f"{suite_name} manifest is not a file: {manifest_path}")
    return resolved


def _relative_tla_path(value: str, *, label: str) -> PurePosixPath:
    if not value:
        raise ManifestError(f"{label} must not be empty")
    if "\\" in value:
        raise ManifestError(f"{label} must use POSIX separators: {value!r}")

    path = PurePosixPath(value)
    if path.is_absolute():
        raise ManifestError(f"{label} must be suite-root-relative: {value!r}")
    if path.as_posix() != value or any(part in {".", ".."} for part in path.parts):
        raise ManifestError(f"{label} must be a canonical path without traversal: {value!r}")
    if path.suffix != ".tla":
        raise ManifestError(f"{label} must name a .tla file: {value!r}")
    return path


def _manifest_entry_keys(suite_name: str) -> frozenset[str]:
    return _SUITE_MANIFEST_ENTRY_KEYS.get(suite_name, _BASE_MANIFEST_ENTRY_KEYS)


def _manifest_entry_keys_message(suite_name: str) -> str:
    preferred = ("spec_id", "context", "reference_proof_steps")
    keys = [key for key in preferred if key in _manifest_entry_keys(suite_name)]
    for key in sorted(_manifest_entry_keys(suite_name)):
        if key not in keys:
            keys.append(key)
    if len(keys) == 1:
        return f"exactly '{keys[0]}'"
    if len(keys) == 2:
        return f"exactly '{keys[0]}' and '{keys[1]}'"
    return "exactly " + ", ".join(f"'{key}'" for key in keys[:-1]) + f", and '{keys[-1]}'"


def _manifest_reference_proof_steps(task_key: str, entry: Mapping[str, Any], *, suite_name: str) -> int | None:
    if suite_name != "proof-completion":
        return None
    steps = entry["reference_proof_steps"]
    if steps is None:
        return None
    if type(steps) is not int or isinstance(steps, bool) or steps < 0:
        raise ManifestError(
            f"manifest entry {task_key!r} field 'reference_proof_steps' must be a non-negative integer or null"
        )
    return steps


def _manifest_specification_id(task_key: str, entry: Any, *, suite_name: str) -> str:
    expected = _manifest_entry_keys(suite_name)
    if type(entry) is not dict or set(entry) != expected:
        raise ManifestError(
            f"manifest entry {task_key!r} must be an object containing {_manifest_entry_keys_message(suite_name)}"
        )
    spec_id = entry["spec_id"]
    if type(spec_id) is not str:
        raise ManifestError(f"manifest entry {task_key!r} field 'spec_id' must be a string")
    _relative_tla_path(spec_id, label=f"manifest entry {task_key!r} field 'spec_id'")
    _manifest_reference_proof_steps(task_key, entry, suite_name=suite_name)
    return spec_id


def load_manifest_specification_ids(suite_root: Path, *, suite_name: str) -> Mapping[str, str]:
    """Load only the stable task-to-specification identities needed to score.

    This validates the versioned manifest keys and identity fields without
    parsing every TLA+ file. Full task execution continues to use
    :func:`load_task_manifest` and its stronger file/content validation.
    """

    root = _suite_root(Path(suite_root), suite_name=suite_name)
    raw = _load_manifest_json(_resolve_manifest(root, suite_name=suite_name))
    if type(raw) is not dict:
        raise ManifestError(f"{suite_name} manifest root must be a JSON object")

    specification_ids: dict[str, str] = {}
    for task_key, entry in raw.items():
        if type(task_key) is not str:
            raise ManifestError(f"{suite_name} manifest task keys must be strings")
        _relative_tla_path(task_key, label="manifest task key")
        specification_ids[task_key] = _manifest_specification_id(task_key, entry, suite_name=suite_name)
    return MappingProxyType(dict(sorted(specification_ids.items())))


def _resolve_suite_file(root: Path, relative_path: PurePosixPath, *, label: str) -> Path:
    candidate = root.joinpath(*relative_path.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ManifestError(f"{label} does not exist: {relative_path.as_posix()!r}") from exc
    if not _is_within(resolved, root):
        raise ManifestError(f"{label} escapes the suite root through a symlink: {relative_path.as_posix()!r}")
    if not resolved.is_file():
        raise ManifestError(f"{label} is not a file: {relative_path.as_posix()!r}")
    return resolved


def _read_module_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ManifestError(f"cannot read TLA+ module {path}: {exc}") from exc


def _declared_module_name(path: Path, source: str) -> str:
    for line in source.splitlines():
        match = _MODULE_HEADER.fullmatch(line)
        if match:
            return match.group(1)
    raise ManifestError(f"TLA+ file has no module header: {path}")


def _validate_module_files(
    task_key: str,
    files: tuple[tuple[str, Path], ...],
) -> dict[str, tuple[str, Path, str]]:
    basenames: dict[str, tuple[str, Path]] = {}
    modules: dict[str, tuple[str, Path, str]] = {}

    for declared_path, resolved_path in files:
        relative_path = PurePosixPath(declared_path)
        previous_basename = basenames.get(relative_path.name)
        if previous_basename is not None:
            previous_declared, previous_resolved = previous_basename
            raise ManifestError(
                f"task {task_key!r} has duplicate module basename {relative_path.name!r}: "
                f"{previous_declared} ({previous_resolved}) and {declared_path} ({resolved_path})"
            )
        basenames[relative_path.name] = (declared_path, resolved_path)

        source = _read_module_source(resolved_path)
        module_name = _declared_module_name(resolved_path, source)
        if relative_path.stem != module_name:
            raise ManifestError(
                f"TLA+ filename/module mismatch for manifest path {declared_path!r}: "
                f"filename {relative_path.stem!r}, header {module_name!r} in {resolved_path}"
            )
        previous_module = modules.get(module_name)
        if previous_module is not None:
            previous_declared, previous_resolved, _ = previous_module
            raise ManifestError(
                f"task {task_key!r} has duplicate module name {module_name!r}: "
                f"{previous_declared} ({previous_resolved}) and {declared_path} ({resolved_path})"
            )
        modules[module_name] = (declared_path, resolved_path, source)

    return modules


def _validate_task_contract(
    task_key: str,
    modules: Mapping[str, tuple[str, Path, str]],
    *,
    parse_task_regions: Callable[[str], EditableRegions | ProofRegion],
) -> None:
    task_name = PurePosixPath(task_key).stem
    task_source = modules[task_name][2]
    try:
        parse_task_regions(task_source)
    except EditableRegionError as exc:
        raise ManifestError(f"manifest task {task_key!r} has invalid editable regions: {exc}") from exc

    declared_modules = set(modules)
    for module_name, (declared_path, _resolved_path, source) in modules.items():
        missing = referenced_modules(source) - declared_modules - RESOLVABLE_MODULES
        if missing:
            missing_names = ", ".join(repr(name) for name in sorted(missing))
            raise ManifestError(
                f"manifest task {task_key!r} has incomplete context: module {module_name!r} "
                f"from {declared_path!r} references undeclared module(s) {missing_names}"
            )


def load_task_manifest(
    suite_root: Path,
    *,
    suite_name: str,
    parse_task_regions: Callable[[str], EditableRegions | ProofRegion],
) -> Mapping[str, TaskBoundary]:
    """Load and fully validate ``<suite_root>/manifest.json``.

    The returned mapping is immutable and ordered by task key.  All paths are
    absolute, resolved paths beneath ``suite_root``; no discovery heuristic or
    fallback is used when the manifest is absent or invalid.
    """

    root = _suite_root(Path(suite_root), suite_name=suite_name)
    raw = _load_manifest_json(_resolve_manifest(root, suite_name=suite_name))
    if type(raw) is not dict:
        raise ManifestError(f"{suite_name} manifest root must be a JSON object")

    specifications: dict[str, tuple[str, Path, list[tuple[str, Path]], int | None]] = {}
    task_paths: dict[Path, str] = {}

    for task_key, entry in raw.items():
        if type(task_key) is not str:
            raise ManifestError(f"{suite_name} manifest task keys must be strings")
        task_relative = _relative_tla_path(task_key, label="manifest task key")
        task_path = _resolve_suite_file(root, task_relative, label=f"manifest task {task_key!r}")

        previous_task = task_paths.get(task_path)
        if previous_task is not None:
            raise ManifestError(f"manifest tasks {previous_task!r} and {task_key!r} resolve to the same file")
        task_paths[task_path] = task_key

        spec_id = _manifest_specification_id(task_key, entry, suite_name=suite_name)
        reference_proof_steps = _manifest_reference_proof_steps(task_key, entry, suite_name=suite_name)

        context = entry["context"]
        if type(context) is not list:
            raise ManifestError(f"manifest entry {task_key!r} field 'context' must be a list")

        seen_context_keys: set[str] = set()
        seen_context_paths: set[Path] = set()
        resolved_context: list[tuple[str, Path]] = []
        for index, context_key in enumerate(context):
            if type(context_key) is not str:
                raise ManifestError(f"manifest entry {task_key!r} context item {index} must be a string")
            context_relative = _relative_tla_path(
                context_key,
                label=f"manifest entry {task_key!r} context item {index}",
            )
            if context_key in seen_context_keys:
                raise ManifestError(f"manifest entry {task_key!r} repeats context path {context_key!r}")
            seen_context_keys.add(context_key)

            context_path = _resolve_suite_file(
                root,
                context_relative,
                label=f"manifest entry {task_key!r} context item {index}",
            )
            if context_path in seen_context_paths:
                raise ManifestError(
                    f"manifest entry {task_key!r} has multiple context paths resolving to {context_path}"
                )
            seen_context_paths.add(context_path)
            resolved_context.append((context_key, context_path))

        specifications[task_key] = (spec_id, task_path, resolved_context, reference_proof_steps)

    boundaries: dict[str, TaskBoundary] = {}
    task_keys = set(specifications)
    for task_key in sorted(specifications):
        spec_id, task_path, context_entries, reference_proof_steps = specifications[task_key]
        context_paths: list[Path] = []
        for context_key, context_path in context_entries:
            if context_key == task_key or context_path == task_path:
                raise ManifestError(f"manifest task {task_key!r} includes itself in its context")
            if context_key in task_keys or context_path in task_paths:
                other_task = task_paths.get(context_path, context_key)
                raise ManifestError(f"manifest task {task_key!r} includes task {other_task!r} in its context")
            context_paths.append(context_path)

        resolved_paths = tuple(context_paths)
        modules = _validate_module_files(task_key, ((task_key, task_path), *context_entries))
        _validate_task_contract(task_key, modules, parse_task_regions=parse_task_regions)
        boundaries[task_key] = TaskBoundary(
            task_key=task_key,
            spec_id=spec_id,
            task_path=task_path,
            context_paths=resolved_paths,
            reference_proof_steps=reference_proof_steps,
        )

    return MappingProxyType(boundaries)


def _line_without_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def _physical_lines(source: str) -> Iterator[tuple[int, int, str]]:
    """Yield source offsets and text for CR/LF-delimited source lines.

    Python's ``str.splitlines`` also treats form feed, vertical tab, NEL, and
    Unicode line separators as new lines. SANY does not, so using it for policy
    locations can make marker bounds disagree with SANY's ``Loc`` line numbers.
    """

    start = 0
    for newline in _SOURCE_NEWLINE.finditer(source):
        end = newline.end()
        yield start, end, source[start:end]
        start = end
    if start < len(source):
        yield start, len(source), source[start:]


def has_marker_line(source: str, markers: tuple[str, ...] = PROOF_REGION_MARKERS) -> bool:
    """Return whether ``source`` contains any exact marker as a physical line."""

    return any(_line_without_ending(line) in markers for _start, _end, line in _physical_lines(source))


def contains_marker_text(source: str, markers: tuple[str, ...] = PROOF_REGION_MARKERS) -> bool:
    """Return whether marker text occurs, including on a malformed marker line."""

    return any(marker in source for marker in markers)


def _marker_positions(source: str, markers: tuple[str, ...]) -> tuple[tuple[int, int, int], ...]:
    positions: dict[str, list[tuple[int, int, int]]] = {marker: [] for marker in markers}
    for line_number, (line_start, line_end, line) in enumerate(_physical_lines(source), start=1):
        marker = _line_without_ending(line)
        if marker in positions:
            positions[marker].append((line_start, line_end, line_number))

    for marker in markers:
        count = len(positions[marker])
        if count != 1:
            raise EditableRegionError(f"expected marker line {marker!r} exactly once, found {count}")

    ordered = tuple(positions[marker][0] for marker in markers)
    starts = tuple(position[0] for position in ordered)
    if starts != tuple(sorted(starts)):
        raise EditableRegionError("editable-region marker lines are not in the required order")
    return ordered


def parse_editable_regions(source: str) -> EditableRegions:
    """Split a task around its four exact, unique, ordered marker lines."""

    begin_helpers, end_helpers, begin_proof, end_proof = _marker_positions(source, EDITABLE_REGION_MARKERS)

    return EditableRegions(
        fixed_prefix=source[: begin_helpers[1]],
        helpers=source[begin_helpers[1] : end_helpers[0]],
        fixed_middle=source[end_helpers[0] : begin_proof[1]],
        proof=source[begin_proof[1] : end_proof[0]],
        fixed_suffix=source[end_proof[0] :],
        helper_line_bounds=(begin_helpers[2] + 1, end_helpers[2] - 1),
        proof_line_bounds=(begin_proof[2] + 1, end_proof[2] - 1),
    )


def parse_proof_region(source: str) -> ProofRegion:
    """Split a proof-completion task around its exact proof marker pair."""

    begin_proof, end_proof = _marker_positions(source, PROOF_REGION_MARKERS)
    return ProofRegion(
        fixed_prefix=source[: begin_proof[1]],
        proof=source[begin_proof[1] : end_proof[0]],
        fixed_suffix=source[end_proof[0] :],
        proof_line_bounds=(begin_proof[2] + 1, end_proof[2] - 1),
    )

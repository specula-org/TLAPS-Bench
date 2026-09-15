"""Pinned official proof-library discovery and frozen run catalogs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.task_contract import EditableRegionError, parse_editable_regions
from common.tla_modules import mask_comments_and_strings

CATALOG_FILENAME = "proof-library-catalog.json"
CATALOG_ENV = "TLAPS_PROOF_LIBRARY_CATALOG"
SOURCE_MARKER_FILENAME = ".proof-library-source.json"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_LOCK = _REPO_ROOT / "config" / "proof-library-sources.json"
DEFAULT_TLAPM_LIBRARY = _REPO_ROOT / "lib" / "tlapm"
DEFAULT_COMMUNITY_LIBRARY = _REPO_ROOT / "lib" / "community"
_MODULE_HEADER = re.compile(r"^-+\s*MODULE\s+([A-Za-z_]\w*)\s*-+\s*$")
_INSTANCE_KEYWORD = re.compile(r"\bINSTANCE\b")
_WITH_KEYWORD = re.compile(r"\bWITH\b")
_NAMED_INSTANCE = re.compile(r"^\s*LOCAL\s+([A-Za-z_]\w*)\s*==\s*INSTANCE\s+([A-Za-z_]\w*)\s*$")
_UNNAMED_INSTANCE = re.compile(r"^\s*LOCAL\s+INSTANCE\b")


class ProofLibraryError(ValueError):
    """The official proof-library provenance or frozen catalog is invalid."""


@dataclass(frozen=True)
class ImportViolation:
    code: str
    message: str
    line: int


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _update_digest(digest: Any, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, byteorder="big"))
    digest.update(value)


def tree_digest(directory: Path) -> str:
    """Hash the sorted top-level .tla filenames and bytes in one library."""

    digest = hashlib.sha256()
    files = sorted(directory.glob("*.tla"), key=lambda path: path.name)
    if not files:
        raise ProofLibraryError(f"official proof-library directory contains no .tla modules: {directory}")
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ProofLibraryError(f"official proof-library module must be a regular file: {path}")
        _update_digest(digest, path.name.encode())
        _update_digest(digest, path.read_bytes())
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProofLibraryError(f"cannot read {label} {path}: {exc}") from exc


def load_source_lock(path: Path = DEFAULT_SOURCE_LOCK) -> dict[str, dict[str, str]]:
    """Load the two exact upstream commits that define the official libraries."""

    value = _read_json(path, label="proof-library source lock")
    if type(value) is not dict or value.get("schema_version") != 1 or type(value.get("sources")) is not dict:
        raise ProofLibraryError(f"invalid proof-library source lock: {path}")
    sources = value["sources"]
    if set(sources) != {"tlapm", "community_modules"}:
        raise ProofLibraryError("proof-library source lock must contain tlapm and community_modules")
    return {name: dict(source) for name, source in sources.items()}


def _module_name(path: Path, content: bytes) -> str:
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProofLibraryError(f"official proof-library module is not UTF-8: {path}") from exc
    for line in source.splitlines():
        match = _MODULE_HEADER.fullmatch(line)
        if match:
            name = match.group(1)
            if path.stem != name:
                raise ProofLibraryError(
                    f"official proof-library filename/module mismatch: {path.name!r} declares {name!r}"
                )
            return name
    raise ProofLibraryError(f"official proof-library module has no module header: {path}")


def _source_marker(source_name: str, source: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": source_name,
        "repository": source["repository"],
        "commit": source["commit"],
        "tree_sha256": source["tree_sha256"],
    }


def _scan_source(
    source_name: str,
    source: dict[str, str],
    directory: Path,
) -> dict[str, dict[str, str]]:
    marker = _read_json(directory / SOURCE_MARKER_FILENAME, label=f"{source_name} source marker")
    expected_marker = _source_marker(source_name, source)
    if marker != expected_marker:
        raise ProofLibraryError(f"{source_name} source marker does not match the pinned official source")
    actual_tree = tree_digest(directory)
    if actual_tree != source["tree_sha256"]:
        raise ProofLibraryError(
            f"{source_name} library content drifted: expected {source['tree_sha256']}, got {actual_tree}"
        )

    modules: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.tla"), key=lambda candidate: candidate.name):
        content = path.read_bytes()
        name = _module_name(path, content)
        if name.endswith("_proofs"):
            continue
        modules[name] = {
            "source": source_name,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    return modules


@dataclass(frozen=True)
class OfficialLibraryCatalog:
    """Official module names and bytes frozen before an agent starts."""

    sources: dict[str, dict[str, str]]
    modules: dict[str, dict[str, str]]
    digest: str

    @property
    def allowed_modules(self) -> frozenset[str]:
        return frozenset(self.modules)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "sources": {name: dict(source) for name, source in self.sources.items()},
            "modules": {name: dict(module) for name, module in self.modules.items()},
        }

    def to_bytes(self) -> bytes:
        return _canonical_json({**self.to_payload(), "digest": self.digest})

    @classmethod
    def from_bytes(cls, content: bytes) -> OfficialLibraryCatalog:
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProofLibraryError(f"invalid frozen proof-library catalog JSON: {exc}") from exc
        if type(value) is not dict or set(value) != {"schema_version", "sources", "modules", "digest"}:
            raise ProofLibraryError("invalid frozen proof-library catalog shape")
        if value["schema_version"] != 1 or type(value["sources"]) is not dict or type(value["modules"]) is not dict:
            raise ProofLibraryError("invalid frozen proof-library catalog fields")
        digest = value["digest"]
        payload = {key: value[key] for key in ("schema_version", "sources", "modules")}
        if type(digest) is not str or digest != _digest_payload(payload):
            raise ProofLibraryError("frozen proof-library catalog digest does not match its content")
        for name, module in value["modules"].items():
            if type(name) is not str or type(module) is not dict or set(module) != {"source", "sha256"}:
                raise ProofLibraryError(f"invalid frozen proof-library module entry {name!r}")
            if module["source"] not in value["sources"] or type(module["sha256"]) is not str:
                raise ProofLibraryError(f"invalid frozen proof-library module provenance {name!r}")
        return cls(sources=value["sources"], modules=value["modules"], digest=digest)


def _build_catalog(
    sources: dict[str, dict[str, str]],
    directories: dict[str, Path],
) -> OfficialLibraryCatalog:
    modules: dict[str, dict[str, str]] = {}
    for source_name, source in sources.items():
        for module_name, module in _scan_source(source_name, source, directories[source_name]).items():
            previous = modules.get(module_name)
            if previous is not None:
                raise ProofLibraryError(
                    f"official module {module_name!r} is provided by both {previous['source']} and {source_name}"
                )
            modules[module_name] = module
    payload = {
        "schema_version": 1,
        "sources": sources,
        "modules": dict(sorted(modules.items())),
    }
    return OfficialLibraryCatalog(sources=sources, modules=payload["modules"], digest=_digest_payload(payload))


def scan_official_libraries(
    *,
    source_lock: Path = DEFAULT_SOURCE_LOCK,
    tlapm_library: Path = DEFAULT_TLAPM_LIBRARY,
    community_library: Path = DEFAULT_COMMUNITY_LIBRARY,
) -> OfficialLibraryCatalog:
    """Discover every module in the two pinned official source trees."""

    sources = load_source_lock(source_lock)
    directories = {"tlapm": tlapm_library, "community_modules": community_library}
    return _build_catalog(sources, directories)


def scan_installed_libraries() -> OfficialLibraryCatalog:
    """Discover a catalog from the pinned source markers beside installed files."""

    tlapm, community = installed_library_dirs()
    directories = {"tlapm": tlapm, "community_modules": community}
    sources: dict[str, dict[str, str]] = {}
    for source_name, directory in directories.items():
        marker = _read_json(directory / SOURCE_MARKER_FILENAME, label=f"{source_name} source marker")
        required = {"schema_version", "source", "repository", "commit", "tree_sha256"}
        if type(marker) is not dict or set(marker) != required or marker.get("source") != source_name:
            raise ProofLibraryError(f"invalid {source_name} source marker")
        source = {
            "repository": marker["repository"],
            "commit": marker["commit"],
            "tree_sha256": marker["tree_sha256"],
        }
        sources[source_name] = source
    return _build_catalog(sources, directories)


def load_frozen_catalog(path: Path) -> OfficialLibraryCatalog:
    try:
        return OfficialLibraryCatalog.from_bytes(path.read_bytes())
    except OSError as exc:
        raise ProofLibraryError(f"cannot read frozen proof-library catalog {path}: {exc}") from exc


def resolve_frozen_catalog(benchmark_dir: str | None) -> Path | None:
    configured = os.environ.get(CATALOG_ENV)
    candidates = [Path(configured)] if configured else []
    if benchmark_dir:
        candidates.append(Path(benchmark_dir) / CATALOG_FILENAME)
    return next((path for path in candidates if path.is_file()), None)


def installed_library_dirs() -> tuple[Path, Path]:
    tlapm = Path(os.environ.get("TLAPS_LIB", DEFAULT_TLAPM_LIBRARY))
    community = Path(os.environ.get("COMMUNITY_LIB", DEFAULT_COMMUNITY_LIBRARY))
    return tlapm, community


def verify_installed_libraries(catalog: OfficialLibraryCatalog) -> None:
    """Require the grader's official library bytes to match the frozen run."""

    tlapm, community = installed_library_dirs()
    directories = {"tlapm": tlapm, "community_modules": community}
    modules: dict[str, dict[str, str]] = {}
    for source_name, source in catalog.sources.items():
        modules.update(_scan_source(source_name, source, directories[source_name]))
    actual_payload = {
        "schema_version": 1,
        "sources": {name: dict(source) for name, source in catalog.sources.items()},
        "modules": dict(sorted(modules.items())),
    }
    actual_digest = _digest_payload(actual_payload)
    if actual_digest != catalog.digest:
        raise ProofLibraryError(
            f"official proof-library catalog drifted: expected {catalog.digest}, got {actual_digest}"
        )


def validate_official_imports(source: str, allowed_modules: frozenset[str]) -> list[ImportViolation]:
    """Validate the intentionally small, one-line helper import grammar."""

    try:
        regions = parse_editable_regions(source)
    except EditableRegionError:
        try:
            from common.proof_from_scratch_grading import proof_unit_ids_from_markers
            from common.proof_from_scratch_module import parse_module_task_regions

            regions = parse_module_task_regions(source, proof_unit_ids_from_markers(source))
        except (ValueError, EditableRegionError):
            return []
    code = mask_comments_and_strings(regions.helpers)
    violations: list[ImportViolation] = []
    first_line = regions.helper_line_bounds[0]
    for offset, line in enumerate(code.splitlines()):
        if not _INSTANCE_KEYWORD.search(line):
            continue
        line_number = first_line + offset
        if _WITH_KEYWORD.search(line):
            violations.append(
                ImportViolation(
                    "IMPORT_WITH_FORBIDDEN",
                    "IMPORT_WITH_FORBIDDEN: INSTANCE ... WITH is not allowed",
                    line_number,
                )
            )
            continue
        match = _NAMED_INSTANCE.fullmatch(line)
        if match is None:
            if _UNNAMED_INSTANCE.match(line):
                code_name = "IMPORT_ALIAS_REQUIRED"
                message = "IMPORT_ALIAS_REQUIRED: use LOCAL <alias> == INSTANCE <module>"
            else:
                code_name = "IMPORT_SYNTAX"
                message = "IMPORT_SYNTAX: use LOCAL <alias> == INSTANCE <module> on one line"
            violations.append(ImportViolation(code_name, message, line_number))
            continue
        module_name = match.group(2)
        if module_name not in allowed_modules:
            violations.append(
                ImportViolation(
                    "IMPORT_NOT_ALLOWED",
                    f"IMPORT_NOT_ALLOWED: module {module_name} is not in the official proof-library catalog",
                    line_number,
                )
            )
    full_code = mask_comments_and_strings(source)
    helper_start, helper_end = regions.helper_line_bounds
    for line_number, line in enumerate(full_code.splitlines(), start=1):
        if helper_start <= line_number <= helper_end or not _INSTANCE_KEYWORD.search(line):
            continue
        violations.append(
            ImportViolation(
                "IMPORT_OUTSIDE_HELPERS",
                "IMPORT_OUTSIDE_HELPERS: library imports are allowed only inside AGENT HELPERS",
                line_number,
            )
        )
    return violations

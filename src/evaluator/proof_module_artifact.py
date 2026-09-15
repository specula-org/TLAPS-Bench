"""Content-addressed snapshots of complete submitted proof modules."""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

MODULE_ARTIFACT_DIRECTORY = "module-artifacts"
MODULE_ARTIFACT_SCHEMA_VERSION = 1


class ModuleArtifactError(ValueError):
    """A module artifact receipt cannot be tied to immutable bytes."""


def _relative_path(digest: str) -> str:
    return (PurePosixPath(MODULE_ARTIFACT_DIRECTORY) / digest[:2] / f"{digest}.tla").as_posix()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(root: Path, relative_parent: PurePosixPath) -> Path:
    current = root
    for part in relative_parent.parts:
        current = current / part
        created = False
        try:
            current.mkdir()
            created = True
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise ModuleArtifactError(f"module artifact directory component is unsafe: {current}")
        if created:
            _fsync_directory(current.parent)
    return current


def publish_module_artifact(output_dir: str | Path, content: bytes) -> dict[str, object]:
    """Publish exact submission bytes once and return their strict receipt."""

    if type(content) is not bytes or not content:
        raise ModuleArtifactError("module artifact content must be non-empty bytes")
    root = Path(output_dir).resolve()
    digest = hashlib.sha256(content).hexdigest()
    relative = PurePosixPath(_relative_path(digest))
    parent = _ensure_directory(root, relative.parent)
    path = parent / relative.name
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ModuleArtifactError(f"module artifact path is unsafe: {path}")
        if path.read_bytes() != content:
            raise ModuleArtifactError(f"module artifact path already contains different bytes: {path}")
    else:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{digest}.", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary_name, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != content:
                    raise ModuleArtifactError(f"module artifact path raced with different bytes: {path}") from None
            _fsync_directory(parent)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name)
    return {
        "schema_version": MODULE_ARTIFACT_SCHEMA_VERSION,
        "sha256": digest,
        "path": relative.as_posix(),
        "byte_count": len(content),
    }


def read_module_artifact(output_dir: str | Path, receipt: object) -> bytes:
    """Validate a receipt, path, and digest before returning reusable bytes."""

    if type(receipt) is not dict or set(receipt) != {"schema_version", "sha256", "path", "byte_count"}:
        raise ModuleArtifactError("module artifact receipt has an invalid shape")
    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != MODULE_ARTIFACT_SCHEMA_VERSION:
        raise ModuleArtifactError(f"unsupported module artifact schema_version {receipt['schema_version']!r}")
    digest = receipt["sha256"]
    if type(digest) is not str or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ModuleArtifactError("module artifact receipt has an invalid SHA-256 digest")
    expected_relative = _relative_path(digest)
    if receipt["path"] != expected_relative:
        raise ModuleArtifactError("module artifact receipt does not use its digest-owned path")
    if type(receipt["byte_count"]) is not int or receipt["byte_count"] <= 0:
        raise ModuleArtifactError("module artifact receipt has an invalid byte count")

    root = Path(output_dir).resolve()
    relative = PurePosixPath(expected_relative)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ModuleArtifactError(f"module artifact path cannot contain a symlink: {current}")
    if not current.is_file():
        raise ModuleArtifactError(f"module artifact is missing: {current}")
    try:
        content = current.read_bytes()
    except OSError as exc:
        raise ModuleArtifactError(f"cannot read module artifact {current}: {exc}") from exc
    if len(content) != receipt["byte_count"] or hashlib.sha256(content).hexdigest() != digest:
        raise ModuleArtifactError(f"module artifact no longer matches its receipt: {current}")
    return content


def result_module_artifact(result: Mapping[str, object]) -> object | None:
    """Return the latest submission receipt, including continuation progress."""

    continuations = result.get("continuations")
    if isinstance(continuations, list):
        for round_result in reversed(continuations):
            if isinstance(round_result, Mapping) and round_result.get("module_artifact") is not None:
                return round_result["module_artifact"]
    return result.get("module_artifact")


__all__ = [
    "MODULE_ARTIFACT_DIRECTORY",
    "MODULE_ARTIFACT_SCHEMA_VERSION",
    "ModuleArtifactError",
    "publish_module_artifact",
    "read_module_artifact",
    "result_module_artifact",
]

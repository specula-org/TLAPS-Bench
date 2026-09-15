"""Atomic per-module checkpoints for proof-from-scratch evaluation."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluator.proof_module_artifact import ModuleArtifactError, read_module_artifact
from evaluator.proof_module_result import ModuleResultError, validate_module_result

MODULE_CHECKPOINT_DIRECTORY = "module-checkpoints"
MODULE_CHECKPOINT_FORMAT_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ModuleCheckpointError(ValueError):
    """Persisted module progress does not match the frozen run."""


@dataclass(frozen=True)
class ModuleCheckpointIdentity:
    task_id: str
    proof_unit_ids: tuple[str, ...]
    canonical_input_sha256: str
    run_identity_sha256: str

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.endswith(".tla"):
            raise ModuleCheckpointError("module checkpoint task_id must be a non-empty .tla path")
        if any(type(unit_id) is not str or not unit_id for unit_id in self.proof_unit_ids):
            raise ModuleCheckpointError("module checkpoint proof_unit_ids must be non-empty strings")
        if not self.proof_unit_ids or len(self.proof_unit_ids) != len(set(self.proof_unit_ids)):
            raise ModuleCheckpointError("module checkpoint proof_unit_ids must be non-empty and unique")
        for label, value in (
            ("canonical_input_sha256", self.canonical_input_sha256),
            ("run_identity_sha256", self.run_identity_sha256),
        ):
            if type(value) is not str or not _SHA256_RE.fullmatch(value):
                raise ModuleCheckpointError(f"module checkpoint {label} must be a lowercase SHA-256 digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "proof_unit_ids": list(self.proof_unit_ids),
            "canonical_input_sha256": self.canonical_input_sha256,
            "run_identity_sha256": self.run_identity_sha256,
        }


@dataclass(frozen=True)
class ModuleCheckpoint:
    identity: ModuleCheckpointIdentity
    sequence: int
    result: dict[str, object]


def run_identity_sha256(run_identity: Mapping[str, object]) -> str:
    """Hash semantic run inputs while leaving the informational Git revision out."""

    comparable = {key: value for key, value in run_identity.items() if key != "benchmark_revision"}
    try:
        encoded = json.dumps(
            comparable,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ModuleCheckpointError(f"run identity is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_filename(task_id: str) -> str:
    return f"module-{hashlib.sha256(task_id.encode()).hexdigest()}.json"


def checkpoint_path(output_dir: str | Path, task_id: str) -> Path:
    return Path(output_dir) / MODULE_CHECKPOINT_DIRECTORY / checkpoint_filename(task_id)


def _reject_constant(value: str) -> Any:
    raise ModuleCheckpointError(f"module checkpoint contains non-standard JSON constant {value}")


def _without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModuleCheckpointError(f"module checkpoint contains duplicate JSON key {key!r}")
        result[key] = value
    return result


def _parse_identity(raw: object) -> ModuleCheckpointIdentity:
    keys = {"task_id", "proof_unit_ids", "canonical_input_sha256", "run_identity_sha256"}
    if type(raw) is not dict or set(raw) != keys or type(raw["proof_unit_ids"]) is not list:
        raise ModuleCheckpointError("module checkpoint identity has an invalid shape")
    return ModuleCheckpointIdentity(
        task_id=raw["task_id"],
        proof_unit_ids=tuple(raw["proof_unit_ids"]),
        canonical_input_sha256=raw["canonical_input_sha256"],
        run_identity_sha256=raw["run_identity_sha256"],
    )


def _validate_result(
    output_dir: str | Path,
    identity: ModuleCheckpointIdentity,
    result: object,
) -> dict[str, object]:
    if type(result) is not dict:
        raise ModuleCheckpointError("module checkpoint result must be an object")
    if result.get("benchmark") != identity.task_id:
        raise ModuleCheckpointError("module checkpoint result names the wrong task")
    if result.get("proof_unit_ids") != list(identity.proof_unit_ids):
        raise ModuleCheckpointError("module checkpoint result proof-unit IDs differ from the task identity")
    if type(result.get("proof_unit_count")) is not int or result["proof_unit_count"] != len(identity.proof_unit_ids):
        raise ModuleCheckpointError("module checkpoint result has the wrong proof-unit count")

    def validate_attempt(attempt: dict[str, object], *, label: str) -> None:
        verdict = attempt.get("check_verdict")
        if type(verdict) is not str or verdict not in {"PASS", "FAIL", "TIMEOUT", "ERROR", "CHEATING"}:
            raise ModuleCheckpointError(f"module checkpoint {label} has an invalid checker verdict")
        for field in ("logical_timeout_secs", "logical_timeout_used_secs"):
            value = attempt.get(field)
            if value is not None and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
                or not math.isfinite(float(value))
            ):
                raise ModuleCheckpointError(f"module checkpoint {label} has an invalid {field}")
        remaining = attempt.get("logical_timeout_remaining_secs")
        if remaining is not None and (
            not isinstance(remaining, (int, float))
            or isinstance(remaining, bool)
            or remaining < 0
            or not math.isfinite(float(remaining))
        ):
            raise ModuleCheckpointError(f"module checkpoint {label} has an invalid logical timeout remainder")
        resume_count = attempt.get("logical_resume_count")
        if resume_count is not None and (type(resume_count) is not int or resume_count < 0):
            raise ModuleCheckpointError(f"module checkpoint {label} has an invalid logical resume count")
        module_result = attempt.get("module_result")
        invalid_after_interruption = attempt.get("invalid_submission_after_interruption")
        if invalid_after_interruption is not None:
            # A resumed segment may fail to materialize new bytes while the
            # attempt still retains its previous durable artifact as the next
            # resume point. The marker describes this segment's submission;
            # module_artifact remains the latest successfully published bytes.
            if invalid_after_interruption is not True:
                raise ModuleCheckpointError(f"module checkpoint {label} has an invalid interrupted-submission marker")
            if (
                attempt.get("termination_reason") not in {"INFRA_ERROR", "QUOTA_EXHAUSTED"}
                or verdict != "FAIL"
                or module_result is not None
                or attempt.get("graded_after_interruption") is not None
            ):
                raise ModuleCheckpointError(
                    f"module checkpoint {label} has an inconsistent interrupted-submission failure"
                )
        if module_result is None:
            if verdict == "PASS":
                raise ModuleCheckpointError(
                    f"module checkpoint {label} records PASS without a complete module checker result"
                )
            return
        if attempt.get("module_artifact") is None:
            raise ModuleCheckpointError(f"module checkpoint {label} has a checker result without an artifact")
        try:
            validated = validate_module_result(module_result, identity.proof_unit_ids)
        except ModuleResultError as exc:
            raise ModuleCheckpointError(f"module checkpoint contains an invalid {label} checker result: {exc}") from exc
        trusted_targets = validated["trusted_proof_unit_ids"]
        if type(attempt.get("proof_unit_count")) is not int or attempt["proof_unit_count"] != len(
            identity.proof_unit_ids
        ):
            raise ModuleCheckpointError(f"module checkpoint {label} has the wrong proof-unit count")
        if type(attempt.get("trusted_proof_unit_count")) is not int or attempt["trusted_proof_unit_count"] != len(
            trusted_targets
        ):
            raise ModuleCheckpointError(f"module checkpoint {label} has the wrong trusted proof-unit count")
        if attempt.get("trusted_proof_unit_ids") != trusted_targets:
            raise ModuleCheckpointError(f"module checkpoint {label} has inconsistent trusted proof-unit IDs")
        if verdict == "PASS" and not validated["complete"]:
            raise ModuleCheckpointError(f"module checkpoint {label} records PASS for an incomplete module")
        if validated["complete"] and verdict not in {"PASS", "ERROR"}:
            raise ModuleCheckpointError(f"module checkpoint {label} does not record PASS for a complete module")

    validate_attempt(result, label="first attempt")
    continuations = result.get("continuations")
    max_continuations = result.get("max_continuations", 0)
    if type(max_continuations) is not int or max_continuations < 0:
        raise ModuleCheckpointError("module checkpoint max_continuations must be a non-negative integer")
    if continuations is not None:
        if type(continuations) is not list or any(type(round_result) is not dict for round_result in continuations):
            raise ModuleCheckpointError("module checkpoint continuations must be a list of objects")
        if len(continuations) > max_continuations:
            raise ModuleCheckpointError("module checkpoint exceeds its configured continuation budget")
        if result.get("check_verdict") == "PASS" and continuations:
            raise ModuleCheckpointError("module checkpoint cannot continue after a first-attempt PASS")
        passed_round = False
        for index, round_result in enumerate(continuations, start=1):
            if passed_round:
                raise ModuleCheckpointError("module checkpoint cannot continue after a passing continuation")
            if round_result.get("round") != index:
                raise ModuleCheckpointError("module checkpoint continuation rounds must be consecutive and one-based")
            validate_attempt(round_result, label=f"continuation {index}")
            passed_round = round_result.get("check_verdict") == "PASS"

    interrupted_continuations = result.get("interrupted_continuations")
    if interrupted_continuations is not None:
        if type(interrupted_continuations) is not list or any(
            type(round_result) is not dict for round_result in interrupted_continuations
        ):
            raise ModuleCheckpointError("module checkpoint interrupted continuations must be a list of objects")
        for index, round_result in enumerate(interrupted_continuations, start=1):
            round_number = round_result.get("round")
            if type(round_number) is not int or not 1 <= round_number <= max_continuations:
                raise ModuleCheckpointError("module checkpoint interrupted continuation has an invalid round")
            if round_result.get("termination_reason") not in {"INFRA_ERROR", "QUOTA_EXHAUSTED"}:
                raise ModuleCheckpointError(
                    "module checkpoint interrupted continuation must record an infra or quota interruption"
                )
            validate_attempt(round_result, label=f"interrupted continuation {index}")

    pending_grading = result.get("module_grading_pending")
    if pending_grading is not None:
        if type(pending_grading) is not int or pending_grading < 0:
            raise ModuleCheckpointError("module checkpoint pending grading round must be a non-negative integer")
        if pending_grading == 0:
            pending_attempt = result
        elif not isinstance(continuations, list) or pending_grading != len(continuations):
            raise ModuleCheckpointError("module checkpoint pending grading must identify the latest continuation")
        else:
            pending_attempt = continuations[-1]
        if pending_attempt.get("module_result") is not None and pending_attempt.get("check_verdict") != "ERROR":
            raise ModuleCheckpointError("module checkpoint cannot mark a successfully graded attempt as pending")
        if pending_attempt.get("module_artifact") is None:
            raise ModuleCheckpointError("module checkpoint pending grading requires a preserved module artifact")

    artifact_attempts = [result]
    if isinstance(continuations, list):
        artifact_attempts.extend(continuations)
    if isinstance(interrupted_continuations, list):
        artifact_attempts.extend(interrupted_continuations)
    for attempt in artifact_attempts:
        receipt = attempt.get("module_artifact")
        if receipt is not None:
            try:
                read_module_artifact(output_dir, receipt)
            except ModuleArtifactError as exc:
                raise ModuleCheckpointError(f"module checkpoint contains an invalid artifact: {exc}") from exc
    return dict(result)


def load_module_checkpoint(
    output_dir: str | Path,
    expected_identity: ModuleCheckpointIdentity,
) -> ModuleCheckpoint:
    path = checkpoint_path(output_dir, expected_identity.task_id)
    if path.is_symlink() or not path.is_file():
        raise ModuleCheckpointError(f"module checkpoint is not a regular file: {path}")
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_without_duplicates,
            parse_constant=_reject_constant,
        )
    except ModuleCheckpointError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModuleCheckpointError(f"cannot read module checkpoint {path}: {exc}") from exc
    if type(raw) is not dict or set(raw) != {"format_version", "identity", "sequence", "result"}:
        raise ModuleCheckpointError(f"module checkpoint {path} has an invalid shape")
    if type(raw["format_version"]) is not int or raw["format_version"] != MODULE_CHECKPOINT_FORMAT_VERSION:
        raise ModuleCheckpointError(f"unsupported module checkpoint format_version {raw['format_version']!r}")
    identity = _parse_identity(raw["identity"])
    if identity != expected_identity:
        raise ModuleCheckpointError(f"module checkpoint identity differs from the current run for {identity.task_id!r}")
    if type(raw["sequence"]) is not int or raw["sequence"] <= 0:
        raise ModuleCheckpointError("module checkpoint sequence must be a positive integer")
    result = _validate_result(output_dir, identity, raw["result"])
    return ModuleCheckpoint(identity=identity, sequence=raw["sequence"], result=result)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_module_checkpoint(
    output_dir: str | Path,
    identity: ModuleCheckpointIdentity,
    result: Mapping[str, object],
) -> ModuleCheckpoint:
    root = Path(output_dir)
    directory = root / MODULE_CHECKPOINT_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(root, identity.task_id)
    if path.is_symlink():
        raise ModuleCheckpointError(f"module checkpoint path is unsafe: {path}")
    frozen_result = _validate_result(root, identity, dict(result))
    previous = load_module_checkpoint(root, identity) if path.exists() else None
    if previous is not None and previous.result == frozen_result:
        return previous
    sequence = 1 if previous is None else previous.sequence + 1
    checkpoint = ModuleCheckpoint(identity=identity, sequence=sequence, result=frozen_result)
    payload = {
        "format_version": MODULE_CHECKPOINT_FORMAT_VERSION,
        "identity": identity.as_dict(),
        "sequence": sequence,
        "result": frozen_result,
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        _fsync_directory(directory)
    except (OSError, TypeError, ValueError) as exc:
        raise ModuleCheckpointError(f"cannot write module checkpoint {path}: {exc}") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary_name)
    return checkpoint


def prepare_module_checkpoints(
    output_dir: str | Path,
    identities: Mapping[str, ModuleCheckpointIdentity],
    *,
    resume: bool,
) -> dict[str, ModuleCheckpoint]:
    """Validate the checkpoint cohort and load all durable module progress."""

    if not identities:
        raise ModuleCheckpointError("module checkpoint cohort must not be empty")
    root = Path(output_dir)
    directory = root / MODULE_CHECKPOINT_DIRECTORY
    if not resume:
        existing_run_state = [
            name
            for name in ("results.json", "run-manifest.json", "task-list.json", "module-artifacts")
            if (root / name).exists() or (root / name).is_symlink()
        ]
        if existing_run_state:
            raise ModuleCheckpointError(
                f"module output already contains run state {sorted(existing_run_state)}; use --resume or a new directory"
            )
    if not directory.exists():
        if resume:
            return {}
        directory.mkdir(parents=True)
        return {}
    if directory.is_symlink() or not directory.is_dir():
        raise ModuleCheckpointError(f"module checkpoint directory is unsafe: {directory}")
    expected_names = {checkpoint_filename(task_id) for task_id in identities}
    entries = tuple(directory.iterdir())

    def owned_temporary(path: Path) -> bool:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.name.endswith(".tmp")
            and any(path.name.startswith(f".{checkpoint_name}.") for checkpoint_name in expected_names)
        )

    actual_names = {path.name for path in entries if not owned_temporary(path)}
    unexpected = actual_names - expected_names
    if unexpected:
        raise ModuleCheckpointError(f"module checkpoint directory contains unexpected entries: {sorted(unexpected)}")
    if actual_names and not resume:
        raise ModuleCheckpointError("module checkpoints already exist; use --resume with the same run inputs")
    if actual_names and resume:
        missing_records = [
            name
            for name in ("task-list.json", "run-manifest.json")
            if not (root / name).is_file() or (root / name).is_symlink()
        ]
        if missing_records:
            raise ModuleCheckpointError(
                f"module checkpoints cannot resume without recorded run inputs: {sorted(missing_records)}"
            )
    checkpoints: dict[str, ModuleCheckpoint] = {}
    for task_id, identity in identities.items():
        if checkpoint_filename(task_id) in actual_names:
            checkpoints[task_id] = load_module_checkpoint(output_dir, identity)
    return checkpoints


__all__ = [
    "MODULE_CHECKPOINT_DIRECTORY",
    "MODULE_CHECKPOINT_FORMAT_VERSION",
    "ModuleCheckpoint",
    "ModuleCheckpointError",
    "ModuleCheckpointIdentity",
    "checkpoint_filename",
    "checkpoint_path",
    "load_module_checkpoint",
    "prepare_module_checkpoints",
    "run_identity_sha256",
    "write_module_checkpoint",
]

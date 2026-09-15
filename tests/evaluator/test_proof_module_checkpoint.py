"""Durable module artifacts and checkpoint recovery."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluator import runner
from evaluator.backends.agentic import AgenticBackend
from evaluator.proof_module_artifact import (
    ModuleArtifactError,
    publish_module_artifact,
    read_module_artifact,
    result_module_artifact,
)
from evaluator.proof_module_checkpoint import (
    MODULE_CHECKPOINT_FORMAT_VERSION,
    ModuleCheckpointError,
    ModuleCheckpointIdentity,
    checkpoint_path,
    load_module_checkpoint,
    prepare_module_checkpoints,
    run_identity_sha256,
    write_module_checkpoint,
)

TASK_ID = "Suite/Task.tla"
UNIT_ID = "Suite/Task-Target.tla"
CANONICAL_INPUT_SHA256 = "1" * 64
RUN_IDENTITY_SHA256 = "2" * 64


def _identity(**changes: object) -> ModuleCheckpointIdentity:
    values: dict[str, object] = {
        "task_id": TASK_ID,
        "proof_unit_ids": (UNIT_ID,),
        "canonical_input_sha256": CANONICAL_INPUT_SHA256,
        "run_identity_sha256": RUN_IDENTITY_SHA256,
    }
    values.update(changes)
    return ModuleCheckpointIdentity(**values)  # type: ignore[arg-type]


def _module_result(*, complete: bool = True, schema_version: int = 1) -> dict[str, object]:
    unit = {
        "unit_id": UNIT_ID,
        "kind": "target",
        "theorem_name": "Target",
        "line_start": 4,
        "line_end": 6,
        "dependencies": [],
        "raw_verdict": "PASS" if complete else "FAIL",
        "tlapm_exit": 0 if complete else 1,
        "missing_proofs": 0 if complete else 1,
        "obligation_failed": False,
        "trusted": complete,
    }
    return {
        "schema_version": schema_version,
        "sany_status": "valid",
        "proof_unit_ids": [UNIT_ID],
        "units": [unit],
        "trusted_unit_ids": [UNIT_ID] if complete else [],
        "trusted_proof_unit_ids": [UNIT_ID] if complete else [],
        "complete": complete,
    }


def _result(
    *, artifact: dict[str, object] | None = None, module_result: dict[str, object] | None = None
) -> dict[str, object]:
    result: dict[str, object] = {
        "benchmark": TASK_ID,
        "proof_unit_ids": [UNIT_ID],
        "proof_unit_count": 1,
        "trusted_proof_unit_count": len(module_result.get("trusted_proof_unit_ids", [])) if module_result else 0,
        "trusted_proof_unit_ids": list(module_result.get("trusted_proof_unit_ids", [])) if module_result else [],
        "check_verdict": "PASS" if module_result is None or module_result.get("complete", False) else "FAIL",
    }
    if artifact is not None:
        result["module_artifact"] = artifact
    if module_result is not None:
        result["module_result"] = module_result
    return result


def test_module_artifact_publish_read_is_content_addressed_and_idempotent(tmp_path):
    content = b"---- MODULE Task ----\nPROOF OBVIOUS\n====\n"

    receipt = publish_module_artifact(tmp_path, content)
    duplicate_receipt = publish_module_artifact(tmp_path, content)

    assert receipt == duplicate_receipt
    assert receipt == {
        "schema_version": 1,
        "sha256": hashlib.sha256(content).hexdigest(),
        "path": f"module-artifacts/{hashlib.sha256(content).hexdigest()[:2]}/{hashlib.sha256(content).hexdigest()}.tla",
        "byte_count": len(content),
    }
    assert read_module_artifact(tmp_path, receipt) == content
    assert list((tmp_path / "module-artifacts").rglob("*.tmp")) == []


def test_parallel_module_artifact_publish_handles_directory_creation_race(tmp_path, monkeypatch):
    original_mkdir = Path.mkdir
    barrier = threading.Barrier(2)

    def synchronized_mkdir(path, *args, **kwargs):
        if path.name == "module-artifacts" and not path.exists():
            barrier.wait(timeout=5)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", synchronized_mkdir)
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda content: publish_module_artifact(tmp_path, content), (b"a", b"b")))

    assert [read_module_artifact(tmp_path, receipt) for receipt in receipts] == [b"a", b"b"]


def test_module_artifact_read_rejects_tampered_bytes(tmp_path):
    content = b"canonical module bytes"
    receipt = publish_module_artifact(tmp_path, content)
    artifact_path = tmp_path / receipt["path"]
    artifact_path.write_bytes(b"changed module bytes")

    with pytest.raises(ModuleArtifactError, match="no longer matches its receipt"):
        read_module_artifact(tmp_path, receipt)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", True, "unsupported"),
        ("sha256", "f" * 64, "digest-owned path"),
        ("path", "module-artifacts/../outside.tla", "digest-owned path"),
        ("byte_count", 1, "no longer matches"),
    ],
)
def test_module_artifact_read_rejects_tampered_receipt(tmp_path, field, value, message):
    content = b"canonical module bytes"
    receipt = publish_module_artifact(tmp_path, content)
    tampered = {**receipt, field: value}

    with pytest.raises(ModuleArtifactError, match=message):
        read_module_artifact(tmp_path, tampered)


def test_result_module_artifact_uses_latest_continuation_receipt(tmp_path):
    first = publish_module_artifact(tmp_path, b"first")
    latest = publish_module_artifact(tmp_path, b"latest")
    result = {
        "module_artifact": first,
        "continuations": [{"module_artifact": first}, {"module_artifact": latest}],
    }

    assert result_module_artifact(result) == latest
    assert read_module_artifact(tmp_path, result_module_artifact(result)) == b"latest"


def test_checkpoint_save_load_and_sequence_are_durable(tmp_path):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")
    result = _result(artifact=artifact, module_result=_module_result(complete=False))

    first = write_module_checkpoint(tmp_path, identity, result)
    assert first.sequence == 1
    assert load_module_checkpoint(tmp_path, identity) == first

    second = write_module_checkpoint(tmp_path, identity, {**result, "check_verdict": "ERROR"})
    assert second.sequence == 2
    assert load_module_checkpoint(tmp_path, identity) == second

    path = checkpoint_path(tmp_path, TASK_ID)
    assert json.loads(path.read_text()) == {
        "format_version": MODULE_CHECKPOINT_FORMAT_VERSION,
        "identity": identity.as_dict(),
        "sequence": 2,
        "result": second.result,
    }
    assert [entry for entry in path.parent.iterdir() if entry.name.endswith(".tmp")] == []


def test_checkpoint_identical_write_is_idempotent(tmp_path):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")
    result = _result(artifact=artifact, module_result=_module_result(complete=False))

    first = write_module_checkpoint(tmp_path, identity, result)
    second = write_module_checkpoint(tmp_path, identity, result)

    assert second == first
    assert load_module_checkpoint(tmp_path, identity).sequence == 1


def test_checkpoint_atomic_save_preserves_previous_file_on_replace_failure(tmp_path, monkeypatch):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")
    result = _result(artifact=artifact, module_result=_module_result(complete=False))
    write_module_checkpoint(tmp_path, identity, result)
    path = checkpoint_path(tmp_path, TASK_ID)
    before = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("simulated interrupted checkpoint replacement")

    monkeypatch.setattr("evaluator.proof_module_checkpoint.os.replace", fail_replace)
    with pytest.raises(ModuleCheckpointError, match="cannot write module checkpoint"):
        write_module_checkpoint(tmp_path, identity, {**result, "check_verdict": "ERROR"})

    assert path.read_bytes() == before
    assert load_module_checkpoint(tmp_path, identity).sequence == 1
    assert [entry for entry in path.parent.iterdir() if entry.name.endswith(".tmp")] == []


def test_checkpoint_load_rejects_identity_mismatch(tmp_path):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")
    write_module_checkpoint(
        tmp_path, identity, _result(artifact=artifact, module_result=_module_result(complete=False))
    )

    with pytest.raises(ModuleCheckpointError, match="identity differs from the current run"):
        load_module_checkpoint(tmp_path, _identity(run_identity_sha256="3" * 64))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(format_version=True), "format_version"),
        (lambda payload: payload["identity"].update(task_id=1), "task_id"),
        (lambda payload: payload["identity"].update(proof_unit_ids=[[UNIT_ID]]), "proof_unit_ids"),
        (lambda payload: payload["identity"].update(run_identity_sha256=1), "run_identity_sha256"),
    ],
)
def test_checkpoint_load_rejects_malformed_scalar_types(tmp_path, mutate, message):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")
    write_module_checkpoint(
        tmp_path, identity, _result(artifact=artifact, module_result=_module_result(complete=False))
    )
    path = checkpoint_path(tmp_path, TASK_ID)
    payload = json.loads(path.read_text())
    mutate(payload)
    path.write_text(json.dumps(payload))

    with pytest.raises(ModuleCheckpointError, match=message):
        load_module_checkpoint(tmp_path, identity)


@pytest.mark.parametrize(
    "module_result",
    [
        _module_result(schema_version=0),
        {"schema_version": 1, "sany_status": "valid"},
    ],
)
def test_checkpoint_rejects_invalid_or_old_module_result(tmp_path, module_result):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")

    with pytest.raises(ModuleCheckpointError, match="invalid .* checker result"):
        write_module_checkpoint(tmp_path, identity, _result(artifact=artifact, module_result=module_result))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda result: result.update(proof_unit_count=True), "proof-unit count"),
        (lambda result: result.update(trusted_proof_unit_count=True), "trusted proof-unit count"),
        (lambda result: result.update(check_verdict=[]), "checker verdict"),
    ],
)
def test_checkpoint_rejects_malformed_derived_module_fields(tmp_path, mutate, message):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"partial module")
    result = _result(artifact=artifact, module_result=_module_result(complete=False))
    mutate(result)

    with pytest.raises(ModuleCheckpointError, match=message):
        write_module_checkpoint(tmp_path, identity, result)


def test_checkpoint_rejects_pass_without_module_result(tmp_path):
    identity = _identity()

    with pytest.raises(ModuleCheckpointError, match="PASS without a complete module checker result"):
        write_module_checkpoint(tmp_path, identity, _result())


def test_checkpoint_rejects_continuation_pass_without_module_result(tmp_path):
    identity = _identity()
    first_artifact = publish_module_artifact(tmp_path, b"first module")
    continuation_artifact = publish_module_artifact(tmp_path, b"continued module")
    result = _result(artifact=first_artifact, module_result=_module_result(complete=False))
    result["max_continuations"] = 1
    continuation = _result(artifact=continuation_artifact)
    continuation["round"] = 1
    result["continuations"] = [continuation]

    with pytest.raises(ModuleCheckpointError, match="continuation 1.*PASS without a complete module checker result"):
        write_module_checkpoint(tmp_path, identity, result)


def test_checkpoint_preserves_cheating_verdict(tmp_path):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"cheating module")
    module_result = {
        "schema_version": 1,
        "sany_status": "valid",
        "proof_unit_ids": [UNIT_ID],
        "units": [],
        "trusted_unit_ids": [],
        "trusted_proof_unit_ids": [],
        "complete": False,
        "integrity_issues": [{"code": "SCAFFOLD_MODIFIED", "message": "scaffold changed"}],
    }
    result = _result(artifact=artifact, module_result=module_result)
    result["check_verdict"] = "CHEATING"

    checkpoint = write_module_checkpoint(tmp_path, identity, result)

    assert checkpoint.result["check_verdict"] == "CHEATING"
    assert load_module_checkpoint(tmp_path, identity).result["check_verdict"] == "CHEATING"


def test_checkpoint_recovery_returns_last_partial_module_bytes(tmp_path):
    identity = _identity()
    partial = b"partial module to continue"
    artifact = publish_module_artifact(tmp_path, partial)
    result = _result(artifact=artifact, module_result=_module_result(complete=False))
    write_module_checkpoint(tmp_path, identity, result)
    (tmp_path / "run-manifest.json").write_text("{}\n")
    (tmp_path / "task-list.json").write_text("{}\n")

    recovered = prepare_module_checkpoints(tmp_path, {TASK_ID: identity}, resume=True)

    assert recovered[TASK_ID].sequence == 1
    recovered_receipt = result_module_artifact(recovered[TASK_ID].result)
    assert read_module_artifact(tmp_path, recovered_receipt) == partial


def test_runner_recovery_rejects_old_result_without_checkpoint(tmp_path):
    identity = _identity()

    with pytest.raises(ValueError, match="cannot resume theorem-level or pre-checkpoint"):
        runner._recover_module_resume(
            str(tmp_path),
            [{"benchmark": TASK_ID, "check_verdict": "FAIL"}],
            {TASK_ID: identity},
            {},
            max_continuations=0,
        )


def test_run_identity_hash_ignores_provenance_revision():
    identity = {"mode": "proof-from-scratch", "benchmark_revision": "old", "corpus_digest": "corpus"}
    changed_revision = {**identity, "benchmark_revision": "new"}

    assert run_identity_sha256(identity) == run_identity_sha256(changed_revision)


class _ModuleBackend(AgenticBackend):
    name = "copilot"

    def build_command(self, workspace, result_dir):
        return ["fake-agent"]

    def parse_output(self, jsonl_path):
        return "", 0, 0


class _ModuleMode:
    name = "proof-from-scratch"
    description = "module fixture"
    canonical_replay_required = True
    requires_workspace_tools = True

    def __init__(self, root: Path, task: Path):
        self._root = root
        self._task = task

    def benchmark_dir(self):
        return str(self._root)

    def get_benchmark_files(self, _filter=None):
        return [str(self._task)]

    def get_dependencies(self, _benchmark_path):
        return []

    def module_task_spec(self, _benchmark_path):
        return SimpleNamespace(proof_unit_ids=(UNIT_ID,))


def test_runner_resume_work_item_carries_checkpoint_identity_and_submission(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "proof-from-scratch-module"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    task.write_bytes(b"canonical module task")
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    (tmp_path / "lib" / "tlapm").mkdir(parents=True)

    run_identity = {
        "schema_version": 2,
        "mode": "proof-from-scratch",
        "corpus_digest": "corpus",
        "proof_library_digest": "libraries",
        "verification_toolchain_digest": "toolchain",
    }
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    identity = ModuleCheckpointIdentity(
        task_id=TASK_ID,
        proof_unit_ids=(UNIT_ID,),
        canonical_input_sha256=canonical_inputs.digest(),
        run_identity_sha256=run_identity_sha256(run_identity),
    )
    partial = b"partial module to continue"
    artifact = publish_module_artifact(output_dir, partial)
    pending = _result(artifact=artifact)
    pending["check_verdict"] = "ERROR"
    pending["module_grading_pending"] = 0
    write_module_checkpoint(output_dir, identity, pending)
    (output_dir / "run-manifest.json").write_text(json.dumps(run_identity))
    (output_dir / "task-list.json").write_text(json.dumps({"mode": "proof-from-scratch", "tasks": [TASK_ID]}))
    (output_dir / "results.json").write_text(json.dumps([{"benchmark": TASK_ID, "check_verdict": "FAIL"}]))

    backend = _ModuleBackend()
    mode = _ModuleMode(benchmark_root, task)
    captured: list[runner.WorkItem] = []
    monkeypatch.setattr(runner, "get_backend", lambda *_args, **_kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *_args, **_kwargs: mode)
    monkeypatch.setattr(runner, "resolve_paths", lambda: (str(tmp_path), "/checker"))
    monkeypatch.setattr(runner, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(runner, "_native_verification_environment", lambda: (None, {"digest": "toolchain"}))
    monkeypatch.setattr(runner, "_proof_from_scratch_run_identity", lambda *_args: run_identity)
    monkeypatch.setattr(runner, "_run_sany_preflight", lambda **_kwargs: None)
    monkeypatch.setattr(
        runner,
        "run_single_benchmark",
        lambda item: (
            captured.append(item)
            or {
                "benchmark": TASK_ID,
                "check_verdict": "FAIL",
                "time_secs": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ),
    )
    monkeypatch.setattr(runner, "update_summary", lambda *_args: None)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "tlaps-bench",
            "--backend",
            "copilot",
            "--mode",
            "proof-from-scratch",
            "--no-container",
            "--resume",
            "--output-dir",
            str(output_dir),
        ],
    )

    runner.main()

    assert len(captured) == 1
    assert captured[0].module_checkpoint_identity == identity
    module_resume = captured[0].module_resume
    assert module_resume is not None
    assert module_resume.action == runner.MODULE_RESUME_GRADE_SAVED
    assert module_resume.submission == partial
    assert module_resume.artifact_receipt == artifact
    assert module_resume.checkpoint_sequence == 1

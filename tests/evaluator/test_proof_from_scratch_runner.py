"""Synthetic end-to-end runner boundary for proof-from-scratch."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.proof_from_scratch_module import (
    MODULE_TASK_FORMAT_VERSION,
    begin_agent_proof,
    end_agent_proof,
    statement_sha256,
)
from common.proof_libraries import OfficialLibraryCatalog
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS
from common.verification_budget import POLICY_ENV, VerificationPolicy
from evaluator import runner
from evaluator.backends.agentic import AgenticBackend
from evaluator.backends.base import BackendCapabilities, SubmissionDisposition, SubmissionPlan
from evaluator.modes.proof_from_scratch import ProofFromScratch


class _Backend(AgenticBackend):
    name = "copilot"

    def build_command(self, workspace, result_dir):
        return ["fake-agent"]

    def parse_output(self, jsonl_path):
        return "", 0, 100

    def detect_quota_block(self, jsonl_path):
        return None


def _module(name, body=""):
    return f"---- MODULE {name} ----\n{body}====\n"


MODULE_TASK_ID = "Suite/Task.tla"
PROOF_UNIT_ID = "Suite/Task_Target.tla"
TARGET_STATEMENT = "THEOREM Target == TRUE"


def _task():
    return "\n".join(
        (
            "---- MODULE Task ----",
            "EXTENDS Model",
            BEGIN_AGENT_HELPERS,
            "",
            END_AGENT_HELPERS,
            TARGET_STATEMENT,
            begin_agent_proof(PROOF_UNIT_ID),
            "PROOF OMITTED",
            end_agent_proof(PROOF_UNIT_ID),
            "====",
            "",
        )
    )


def _write_module_manifests(benchmark_root, task_source):
    """Write a strict module manifest bound to its source-corpus manifest."""
    corpus_manifest = (
        json.dumps(
            {
                PROOF_UNIT_ID: {
                    "spec_id": MODULE_TASK_ID,
                    "context": ["Context/Model.tla"],
                }
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    corpus_manifest_path = benchmark_root / "proof-from-scratch" / "manifest.json"
    corpus_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_manifest_path.write_bytes(corpus_manifest)

    module_manifest = {
        "format_version": MODULE_TASK_FORMAT_VERSION,
        "corpus_sha256": hashlib.sha256(corpus_manifest).hexdigest(),
        "complete": True,
        "module_tasks": [
            {
                "spec": {
                    "format_version": MODULE_TASK_FORMAT_VERSION,
                    "task_id": MODULE_TASK_ID,
                    "source_sha256": hashlib.sha256(task_source.encode("utf-8")).hexdigest(),
                    "proof_units": [
                        {
                            "task_id": PROOF_UNIT_ID,
                            "statement_sha256": statement_sha256(TARGET_STATEMENT),
                        }
                    ],
                },
                "context": ["Context/Model.tla"],
                "renamed_bindings": {},
            }
        ],
    }
    module_manifest_path = benchmark_root / "proof-from-scratch-module" / "manifest.json"
    module_manifest_path.write_text(json.dumps(module_manifest), encoding="utf-8")


def _write_fixture(tmp_path):
    benchmark_root = tmp_path / "benchmark"
    suite = benchmark_root / "proof-from-scratch-module"
    task = suite / MODULE_TASK_ID
    model = suite / "Context" / "Model.tla"
    task.parent.mkdir(parents=True)
    model.parent.mkdir(parents=True)
    task_source = _task()
    model_source = _module("Model", "Value == TRUE\n")
    task.write_text(task_source, encoding="utf-8")
    model.write_text(model_source, encoding="utf-8")
    source = tmp_path / "source" / MODULE_TASK_ID
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(task_source.encode("utf-8"))
    _write_module_manifests(benchmark_root, task_source)
    return benchmark_root, suite, task, model, task_source, model_source


def _catalog():
    payload = {"schema_version": 1, "sources": {}, "modules": {}}
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return OfficialLibraryCatalog(sources={}, modules={}, digest=hashlib.sha256(encoded).hexdigest())


def _toolchain():
    return {"schema_version": 1, "digest": "locked-toolchain"}


def test_runner_grades_from_pre_agent_canonical_bytes(tmp_path, monkeypatch):
    benchmark_root, suite, task, model, task_source, model_source = _write_fixture(tmp_path)
    sibling = suite / "Suite" / "Sibling_Task.tla"
    unrelated = suite / "Suite" / "UnrelatedDefs.tla"
    sibling.write_text(_module("Sibling_Task", "THEOREM Leak == TRUE\nPROOF OBVIOUS\n"))
    unrelated.write_text(_module("UnrelatedDefs", "Leak == TRUE\n"))

    mode = ProofFromScratch(str(benchmark_root), "/checker")
    # Strict module metadata is validated before workers start. Warm its
    # manifest cache before simulating host-file mutation below so this direct
    # WorkItem call exercises canonical replay rather than manifest discovery.
    assert mode.get_benchmark_files() == [str(task.resolve())]
    backend = _Backend()
    agent_canonical_dirs = []
    grader_canonical_dirs = []
    agent_workspaces = []
    submitted_task = task_source.replace("PROOF OMITTED", "PROOF BY TRUE")

    def fake_prompt(mode_, benchmark_path, dependencies, basename, tlapm_path, tlapm_lib):
        assert Path(benchmark_path).read_text() == task_source
        assert [Path(path).read_text() for path in dependencies] == [model_source]
        return mode_.build_prompt(basename, tlapm_path, tlapm_lib)

    def fake_agent(
        item,
        backend_,
        mode_,
        workspace,
        agent_dir,
        agent_jsonl,
        prompt,
        result,
        checker_bin,
        canonical_dir=None,
    ):
        assert sorted(name for name in os.listdir(workspace) if name.endswith(".tla")) == ["Model.tla", "Task.tla"]
        assert os.stat(os.path.join(workspace, "Model.tla")).st_mode & 0o777 == 0o444
        assert os.stat(os.path.join(workspace, "Task.tla")).st_mode & 0o200
        assert sorted(name for name in os.listdir(canonical_dir) if name.endswith(".tla")) == [
            "Model.tla",
            "Task.tla",
        ]
        agent_workspaces.append(workspace)
        agent_canonical_dirs.append(canonical_dir)
        Path(workspace, "Task.tla").write_text(submitted_task)
        Path(workspace, "MCTask.tla").write_text(_module("MCTask", "EXTENDS Task\n"))
        Path(workspace, "Task_TTrace_1.tla").write_text(_module("Task_TTrace_1"))
        task.write_text(task_source.replace("THEOREM Target == TRUE", "THEOREM Target == FALSE"))
        model.write_text(_module("Model", "Value == FALSE\n"))
        (Path(canonical_dir) / "Model.tla").write_text("TAINTED SELF-CHECK SNAPSHOT")
        with open(agent_jsonl, "w") as f:
            f.write('{"type": "result", "exitCode": 0}\n')
        result["agent_exit"] = 0

    def fake_grader(item, workspace, basename, grading_dir, check_result_path, result, canonical_dir=None):
        assert workspace != agent_workspaces[0]
        assert sorted(name for name in os.listdir(workspace) if name.endswith(".tla")) == ["Model.tla", "Task.tla"]
        assert Path(workspace, "Task.tla").read_text() == submitted_task
        assert Path(workspace, "Model.tla").read_text() == model_source
        assert (Path(canonical_dir) / "Task.tla").read_text() == task_source
        assert (Path(canonical_dir) / "Model.tla").read_text() == model_source
        grader_canonical_dirs.append(canonical_dir)
        result.update(
            {
                "check_verdict": "PASS",
                "sany_status": "valid",
                "sany_valid": True,
                "trusted_proof_unit_count": 1,
                "trusted_proof_unit_ids": [PROOF_UNIT_ID],
                "module_result": {
                    "schema_version": 1,
                    "sany_status": "valid",
                    "proof_unit_ids": [PROOF_UNIT_ID],
                    "units": [
                        {
                            "unit_id": PROOF_UNIT_ID,
                            "kind": "target",
                            "theorem_name": "Target",
                            "line_start": 1,
                            "line_end": 1,
                            "dependencies": [],
                            "raw_verdict": "PASS",
                            "tlapm_exit": 0,
                            "missing_proofs": 0,
                            "obligation_failed": False,
                            "trusted": True,
                        }
                    ],
                    "trusted_unit_ids": [PROOF_UNIT_ID],
                    "trusted_proof_unit_ids": [PROOF_UNIT_ID],
                    "unused_helper_names": [],
                    "complete": True,
                },
            }
        )

    monkeypatch.setattr(backend, "build_prompt", fake_prompt)
    monkeypatch.setattr(runner, "_run_backend_local", fake_agent)
    monkeypatch.setattr(runner, "_run_grader_local", fake_grader)

    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [str(model)])
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(tmp_path / "results"),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=mode,
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=runner.ModuleCheckpointIdentity(
            task_id=MODULE_TASK_ID,
            proof_unit_ids=(PROOF_UNIT_ID,),
            canonical_input_sha256=canonical_inputs.digest(),
            run_identity_sha256="0" * 64,
        ),
    )
    task.write_text("TAINTED BEFORE THIS WORKER STARTED")
    model.write_text("TAINTED BEFORE THIS WORKER STARTED")

    runner.run_single_benchmark(item)

    input_dir = tmp_path / "results" / "Suite" / "Task" / "input"
    assert sorted(path.name for path in input_dir.iterdir()) == ["Model.tla", "benchmark.tla", "prompt.txt", "skills"]
    assert (input_dir / "benchmark.tla").read_text() == task_source
    assert (input_dir / "Model.tla").read_text() == model_source
    assert "identified AGENT PROOF region" in (input_dir / "prompt.txt").read_text()
    assert list((input_dir / "skills").iterdir()) == []
    assert grader_canonical_dirs[0] != agent_canonical_dirs[0]


@pytest.mark.parametrize("mutation", ["deleted", "empty", "symlink", "directory", "fifo", "not_materialized"])
def test_invalid_module_submission_fails_without_grading_canonical_input(tmp_path, monkeypatch, mutation):
    benchmark_root, _suite, task, model, task_source, _model_source = _write_fixture(tmp_path)
    mode = ProofFromScratch(str(benchmark_root), "/checker")
    backend = _Backend()
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [str(model)])
    identity = runner.ModuleCheckpointIdentity(
        task_id=MODULE_TASK_ID,
        proof_unit_ids=(PROOF_UNIT_ID,),
        canonical_input_sha256=canonical_inputs.digest(),
        run_identity_sha256="0" * 64,
    )
    grader_calls = []

    def fake_agent(
        item,
        backend_,
        mode_,
        workspace,
        agent_dir,
        agent_jsonl,
        prompt,
        result,
        checker_bin,
        canonical_dir=None,
    ):
        if mutation == "deleted":
            os.unlink(os.path.join(workspace, task.name))
        elif mutation == "empty":
            Path(workspace, task.name).write_bytes(b"")
        elif mutation == "symlink":
            Path(workspace, task.name).unlink()
            Path(workspace, task.name).symlink_to(model.name)
        elif mutation == "directory":
            Path(workspace, task.name).unlink()
            Path(workspace, task.name).mkdir()
        elif mutation == "fifo":
            Path(workspace, task.name).unlink()
            os.mkfifo(Path(workspace, task.name))
        with open(agent_jsonl, "w") as f:
            f.write('{"type": "result", "exitCode": 0}\n')
        result["agent_exit"] = 0

    def fake_grader(item, workspace, basename, grading_dir, check_result_path, result, canonical_dir=None):
        submitted = Path(workspace, basename)
        grader_calls.append((submitted.exists(), submitted.read_bytes() if submitted.exists() else None))
        assert Path(canonical_dir, basename).read_text() == task_source
        result["check_verdict"] = "PASS"

    if mutation == "not_materialized":
        monkeypatch.setattr(
            backend,
            "prepare_submission",
            lambda *args, **kwargs: SubmissionPlan(
                disposition=SubmissionDisposition.FAIL,
                copy_solution=False,
                error="module submission was not materialized",
            ),
        )
    monkeypatch.setattr(runner, "_run_backend_local", fake_agent)
    monkeypatch.setattr(runner, "_run_grader_local", fake_grader)

    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(tmp_path / "results"),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=mode,
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=identity,
    )

    result = runner.run_single_benchmark(item)

    assert result["check_verdict"] == "FAIL"
    assert result["termination_reason"] == runner.TerminationReason.OK
    assert "module_artifact" not in result
    assert grader_calls == []
    assert runner._module_resume_action(result, max_continuations=0) == runner.MODULE_RESUME_COMPLETE


@pytest.mark.parametrize("target_count,expected_timeout", [(1, 13), (2, 17), (5, 26), (12, 39)])
def test_cli_captures_all_replay_inputs_before_backend_setup(tmp_path, monkeypatch, target_count, expected_timeout):
    benchmark_root, _suite, task, model, task_source, model_source = _write_fixture(tmp_path)

    mode = ProofFromScratch(str(benchmark_root), "/checker")
    selected_ids = tuple(f"Suite/Task_Target{i}.tla" for i in range(target_count))
    monkeypatch.setattr(mode, "module_task_spec", lambda _path: SimpleNamespace(proof_unit_ids=selected_ids))
    backend = _Backend()
    captured_items = []

    def mutate_during_backend_setup():
        task.write_text("TAINTED DURING BACKEND SETUP")
        model.write_text("TAINTED DURING BACKEND SETUP")
        return None

    def fake_run(item):
        captured_items.append(item)
        return {
            "benchmark": "Suite/Task.tla",
            "check_verdict": "FAIL",
            "time_secs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args, **kwargs: mode)
    monkeypatch.setattr(runner, "resolve_paths", lambda: (str(benchmark_root), "/checker"))
    monkeypatch.setattr(runner, "_native_verification_environment", lambda: (_catalog(), _toolchain()))
    monkeypatch.setattr(backend, "check_auth", mutate_during_backend_setup)
    monkeypatch.setattr(runner, "ensure_tlapm", lambda: None)
    monkeypatch.setattr(runner, "find_tlapm_lib", lambda _tlapm: "/tlapm/lib")
    monkeypatch.setattr(runner, "run_single_benchmark", fake_run)
    monkeypatch.setattr(runner, "update_summary", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tlaps-bench",
            "--mode",
            "proof-from-scratch",
            "--no-container",
            "--output-dir",
            str(tmp_path / "results"),
            "--check-timeout",
            "13",
            "--timeout",
            "0",
        ],
    )

    runner.main()

    assert len(captured_items) == 1
    canonical_inputs = captured_items[0].canonical_inputs
    assert canonical_inputs is not None
    assert canonical_inputs.target_bytes == task_source.encode()
    assert canonical_inputs.dependencies == (("Model.tla", model_source.encode()),)
    checkpoint_identity = captured_items[0].module_checkpoint_identity
    assert checkpoint_identity is not None
    assert checkpoint_identity.task_id == MODULE_TASK_ID
    assert checkpoint_identity.proof_unit_ids == selected_ids
    assert checkpoint_identity.canonical_input_sha256 == canonical_inputs.digest()
    item = captured_items[0]
    assert item.check_timeout == expected_timeout
    assert item.timeout == 0
    policy = item.verification_policy
    assert policy.proof_unit_ids == selected_ids
    assert policy.base_timeout_secs == 13
    record = json.loads((tmp_path / "results" / runner.RUN_MANIFEST_RECORD).read_text())
    assert record["execution_policy"]["verification"]["modules"][MODULE_TASK_ID] == policy.as_dict()


@pytest.mark.parametrize(
    "option,value", [("--check-timeout", "0"), ("--check-timeout", "-1"), ("--check-cpus", "0"), ("--check-cpus", "9")]
)
def test_invalid_pfs_budget_fails_before_tool_or_model_setup(tmp_path, monkeypatch, option, value):
    benchmark_root, *_ = _write_fixture(tmp_path)
    mode = ProofFromScratch(str(benchmark_root), "/checker")
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: _Backend())
    monkeypatch.setattr(runner, "get_mode", lambda *args, **kwargs: mode)
    monkeypatch.setattr(runner, "ensure_image", lambda **_kwargs: pytest.fail("invalid budget reached tool setup"))
    monkeypatch.setattr(sys, "argv", ["tlaps-bench", "--mode", "proof-from-scratch", option, value])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("container", [False, True])
def test_self_check_and_grader_receive_identical_effective_policy(tmp_path, monkeypatch, container):
    root, _, task, _, _, _ = _write_fixture(tmp_path)
    mode = ProofFromScratch(str(root), "/checker")
    backend = _Backend()
    policy = VerificationPolicy.create(60, ("A", "B", "C", "D", "E"))
    item = runner.WorkItem(
        str(task),
        str(tmp_path),
        0,
        policy.effective_timeout_secs,
        backend,
        mode,
        "/tlapm",
        "/tlapm/lib",
        verification_policy=policy,
    )
    captured = {}

    class FakeRunner:
        def run(self, config, cmd, **_kwargs):
            captured["agent"] = (config.env, cmd, config.cpus)
            raise RuntimeError("captured without a model call")

        def run_with_output(self, config, cmd, **_kwargs):
            captured["grader"] = (config.env, cmd, config.cpus)
            raise RuntimeError("captured without a checker call")

        def cleanup_credential_tmps(self):
            pass

    if container:
        monkeypatch.setattr(runner, "ContainerRunner", FakeRunner)
        runner._run_backend_container(
            item, backend, str(task.parent), str(tmp_path), str(tmp_path / "agent.jsonl"), "prompt", {}
        )
        runner._run_grader_container(
            item, str(task.parent), task.name, str(tmp_path), str(tmp_path / "check.result"), {}
        )
    else:

        def popen(cmd, **kwargs):
            captured["agent"] = (kwargs["env"], cmd, 8)
            raise RuntimeError("captured without a model call")

        def run(cmd, **kwargs):
            captured["grader"] = (kwargs["env"], cmd, 8)
            raise RuntimeError("captured without a checker call")

        monkeypatch.setattr(runner.subprocess, "Popen", popen)
        monkeypatch.setattr(runner.subprocess, "run", run)
        runner._run_backend_local(
            item,
            backend,
            mode,
            str(task.parent),
            str(tmp_path),
            str(tmp_path / "agent.jsonl"),
            "prompt",
            {},
            "/checker",
        )
        runner._run_grader_local(item, str(task.parent), task.name, str(tmp_path), str(tmp_path / "check.result"), {})
    agent_env, agent_cmd, agent_cpus = captured["agent"]
    grader_env, grader_cmd, grader_cpus = captured["grader"]
    assert agent_env["TLAPS_CHECK_TIMEOUT"] == "120"
    assert grader_cmd[grader_cmd.index("--timeout") + 1] == "120"
    assert json.loads(agent_env[POLICY_ENV]) == json.loads(grader_env[POLICY_ENV]) == policy.as_dict()
    assert agent_cpus == grader_cpus == 8
    assert "--check-session" in grader_cmd
    if not container:
        assert "--cpu-list" in agent_cmd and "--cpu-list" in grader_cmd


def test_proof_from_scratch_tool_free_backend_fails_before_setup(tmp_path, monkeypatch, capsys):
    benchmark_root, _suite, _task_path, _model, _task_source, _model_source = _write_fixture(tmp_path)
    mode = ProofFromScratch(str(benchmark_root), "/checker")
    backend = _Backend()
    backend.name = "tool-free"
    backend.capabilities = BackendCapabilities(workspace_tools=False)
    ensure_image_calls = []

    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args, **kwargs: mode)
    monkeypatch.setattr(runner, "ensure_image", lambda **kwargs: ensure_image_calls.append(kwargs))
    monkeypatch.setattr(
        sys,
        "argv",
        ["tlaps-bench", "--mode", "proof-from-scratch", "--output-dir", str(tmp_path / "results")],
    )

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 2
    assert "is tool-free and does not support mode 'proof-from-scratch'" in capsys.readouterr().err
    assert ensure_image_calls == []


def test_container_proof_from_scratch_uses_image_environment(tmp_path, monkeypatch):
    benchmark_root, _suite, _task, _model, _task_source, _model_source = _write_fixture(tmp_path)
    mode = ProofFromScratch(str(benchmark_root), "/checker")
    backend = _Backend()
    captured_items = []
    inspected_images = []

    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args, **kwargs: mode)
    monkeypatch.setattr(runner, "ensure_image", lambda force=False: "tlaps-bench-base:locked")
    monkeypatch.setattr(
        runner,
        "_container_verification_environment",
        lambda image: (inspected_images.append(image) or _catalog(), _toolchain()),
    )
    monkeypatch.setattr(runner, "scan_official_libraries", lambda: pytest.fail("host libraries were scanned"))
    monkeypatch.setattr(backend, "check_auth", lambda: None)
    monkeypatch.setattr(runner, "_run_sany_preflight", lambda **_kwargs: None)
    monkeypatch.setattr(runner, "_run_preflight", lambda *args: None)
    monkeypatch.setattr(
        runner,
        "run_single_benchmark",
        lambda item: (
            captured_items.append(item)
            or {
                "benchmark": "Suite/Task.tla",
                "check_verdict": "FAIL",
                "time_secs": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ),
    )
    monkeypatch.setattr(runner, "update_summary", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tlaps-bench",
            "--mode",
            "proof-from-scratch",
            "--skip-preflight",
            "--output-dir",
            str(tmp_path / "results"),
        ],
    )

    runner.main()

    assert inspected_images == ["tlaps-bench-base:locked"]
    assert captured_items[0].container_image == "tlaps-bench-base:locked"
    assert captured_items[0].canonical_inputs.proof_library_catalog == _catalog().to_bytes()

"""Regression coverage for durable proof-from-scratch module resume state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluator import runner
from evaluator.backends.agentic import AgenticBackend
from evaluator.proof_module_artifact import publish_module_artifact
from evaluator.proof_module_checkpoint import (
    MODULE_CHECKPOINT_DIRECTORY,
    ModuleCheckpointError,
    ModuleCheckpointIdentity,
    checkpoint_filename,
    checkpoint_path,
    load_module_checkpoint,
    prepare_module_checkpoints,
    write_module_checkpoint,
)
from evaluator.usage import UsageSummary

TASK_ID = "Suite/Task.tla"
UNIT_ID = "Suite/Task-Target.tla"


def _identity(**changes: object) -> ModuleCheckpointIdentity:
    values: dict[str, object] = {
        "task_id": TASK_ID,
        "proof_unit_ids": (UNIT_ID,),
        "canonical_input_sha256": "1" * 64,
        "run_identity_sha256": "2" * 64,
    }
    values.update(changes)
    return ModuleCheckpointIdentity(**values)  # type: ignore[arg-type]


def _module_result(*, complete: bool) -> dict[str, object]:
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
        "schema_version": 1,
        "sany_status": "valid",
        "proof_unit_ids": [UNIT_ID],
        "units": [unit],
        "trusted_unit_ids": [UNIT_ID] if complete else [],
        "trusted_proof_unit_ids": [UNIT_ID] if complete else [],
        "complete": complete,
    }


def _attempt(
    *,
    artifact: dict[str, object] | None = None,
    module_result: dict[str, object] | None = None,
    verdict: str | None = None,
    round: int | None = None,
    termination_reason: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "benchmark": TASK_ID,
        "proof_unit_ids": [UNIT_ID],
        "proof_unit_count": 1,
        "trusted_proof_unit_count": len(module_result.get("trusted_proof_unit_ids", [])) if module_result else 0,
        "trusted_proof_unit_ids": list(module_result.get("trusted_proof_unit_ids", [])) if module_result else [],
        "check_verdict": verdict
        or ("PASS" if module_result is None or module_result.get("complete", False) else "FAIL"),
    }
    if artifact is not None:
        result["module_artifact"] = artifact
    if module_result is not None:
        result["module_result"] = module_result
    if round is not None:
        result["round"] = round
    if termination_reason is not None:
        result["termination_reason"] = termination_reason
    return result


def _checkpoint_result(
    output_dir: Path,
    *,
    first_content: bytes = b"first partial module",
    first_complete: bool = False,
    continuation_contents: tuple[bytes, ...] = (),
    continuation_verdicts: tuple[str, ...] = (),
    continuation_termination_reasons: tuple[str | None, ...] = (),
    max_continuations: int | None = None,
) -> tuple[ModuleCheckpointIdentity, dict[str, object]]:
    first_receipt = publish_module_artifact(output_dir, first_content)
    first_result = _attempt(
        artifact=first_receipt,
        module_result=_module_result(complete=first_complete),
    )
    if not first_complete:
        first_result["check_verdict"] = "FAIL"
    result = first_result
    if continuation_contents:
        rounds: list[dict[str, object]] = []
        for index, content in enumerate(continuation_contents, start=1):
            receipt = publish_module_artifact(output_dir, content)
            verdict = continuation_verdicts[index - 1] if continuation_verdicts else "FAIL"
            reason = (
                continuation_termination_reasons[index - 1]
                if index - 1 < len(continuation_termination_reasons)
                else None
            )
            round_result = _attempt(
                artifact=receipt,
                module_result=_module_result(complete=verdict == "PASS") if verdict in {"PASS", "FAIL"} else None,
                verdict=verdict,
                round=index,
                termination_reason=reason,
            )
            rounds.append(round_result)
        result["continuations"] = rounds
        result["max_continuations"] = max_continuations if max_continuations is not None else len(continuation_contents)
    identity = _identity()
    write_module_checkpoint(output_dir, identity, result)
    return identity, result


class _ResumeBackend(AgenticBackend):
    name = "copilot"

    def build_command(self, workspace, result_dir):
        return ["fake-agent"]

    def parse_output(self, jsonl_path):
        return "", 0, 0


class _ResumeMode:
    name = "proof-from-scratch"
    canonical_replay_required = True
    requires_workspace_tools = True

    def __init__(self, root: Path, task: Path):
        self._root = root
        self._task = task

    def benchmark_dir(self):
        return str(self._root)

    def get_dependencies(self, _benchmark_path):
        return []

    def checker_binary_path(self):
        return "/checker"

    def module_task_spec(self, _benchmark_path):
        return SimpleNamespace(proof_unit_ids=(UNIT_ID,))

    def build_prompt(self, *_args):
        return "prove the module"

    def build_continuation_prompt(self, *_args):
        return "continue the module"


def _resume_item(
    tmp_path: Path,
    result: dict[str, object],
    submission: bytes,
    *,
    action: str = runner.MODULE_RESUME_GRADE_SAVED,
    checkpoint_sequence: int = 1,
    max_continuations: int = 0,
) -> runner.WorkItem:
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_bytes(b"canonical task module")
    output_dir = tmp_path / "results"
    artifact = result.get("module_artifact")
    if isinstance(result.get("continuations"), list) and result["continuations"]:
        artifact = result["continuations"][-1].get("module_artifact")
    if not isinstance(artifact, dict):
        raise AssertionError("resume test result must contain an artifact")
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    # The caller constructs the durable identity before this helper is used;
    # the fixed digest keeps the small direct WorkItem fixture aligned with the
    # checkpoint written by the test.
    identity = _identity()
    mode = _ResumeMode(benchmark_root, task)
    backend = _ResumeBackend()
    return runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=mode,
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        max_continuations=max_continuations,
        canonical_inputs=canonical_inputs,
        module_resume=runner.ModuleResume(
            action=action,
            result=result,
            submission=submission,
            artifact_receipt=artifact,
            checkpoint_sequence=checkpoint_sequence,
        ),
        module_checkpoint_identity=identity,
    )


def _complete_grading(result: dict[str, object]) -> None:
    module_result = _module_result(complete=True)
    result.update(
        {
            "check_verdict": "PASS",
            "module_result": module_result,
            "proof_unit_count": 1,
            "trusted_proof_unit_count": 1,
            "trusted_proof_unit_ids": [UNIT_ID],
        }
    )


def test_pending_first_attempt_grades_saved_bytes_without_agent_and_preserves_accounting(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    saved = b"saved first-attempt module"
    artifact = publish_module_artifact(output_dir, saved)
    pending = _attempt(artifact=artifact, verdict="ERROR")
    pending.update(
        {
            "module_grading_pending": 0,
            "agent_exit": 0,
            "input_tokens": 123,
            "output_tokens": 456,
            "time_secs": 3.25,
            "equivalent_cost_usd": 0.012,
            "usage": {"input_tokens": 123, "output_tokens": 456, "model_requests": 1},
        }
    )
    identity = _identity()
    write_module_checkpoint(output_dir, identity, pending)

    item = _resume_item(tmp_path, pending, saved, checkpoint_sequence=1)
    agent_calls: list[object] = []
    graded_bytes: list[bytes] = []

    def unexpected_agent(*args, **kwargs):
        agent_calls.append((args, kwargs))
        raise AssertionError("a pending artifact must be graded before any new agent call")

    def grade(item, workspace, basename, grading_dir, check_result_path, result, canonical_dir=None):
        graded_bytes.append(Path(workspace, basename).read_bytes())
        _complete_grading(result)

    monkeypatch.setattr(runner, "_run_backend_local", unexpected_agent)
    monkeypatch.setattr(runner, "_run_grader_local", grade)

    recovered = runner.run_single_benchmark(item)

    assert agent_calls == []
    assert graded_bytes == [saved]
    assert recovered["check_verdict"] == "PASS"
    assert recovered["input_tokens"] == 123
    assert recovered["output_tokens"] == 456
    assert recovered["agent_time_secs"] == 3.25
    assert recovered["grading_time_secs"] > 0
    assert recovered["time_secs"] == pytest.approx(recovered["agent_time_secs"] + recovered["grading_time_secs"])
    assert recovered["equivalent_cost_usd"] == 0.012
    assert recovered["usage"] == {"input_tokens": 123, "output_tokens": 456, "model_requests": 1}


def test_failed_regrade_keeps_pending_artifact_until_the_same_bytes_are_graded(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    saved = b"saved module awaiting a working checker"
    artifact = publish_module_artifact(output_dir, saved)
    pending = _attempt(artifact=artifact, verdict="ERROR")
    pending["module_grading_pending"] = 0
    identity = _identity()
    write_module_checkpoint(output_dir, identity, pending)
    grader_calls = 0
    agent_calls: list[object] = []

    def no_agent(*args, **kwargs):
        agent_calls.append((args, kwargs))
        raise AssertionError("pending grading must not launch the agent")

    def grade(_item, workspace, basename, _grading_dir, _check_path, result, _canonical_dir=None):
        nonlocal grader_calls
        grader_calls += 1
        assert Path(workspace, basename).read_bytes() == saved
        if grader_calls == 1:
            result.update(
                {
                    "check_verdict": "ERROR",
                    "error": "checker unavailable",
                    "module_result": _module_result(complete=False),
                    "proof_unit_count": 1,
                    "trusted_proof_unit_count": 0,
                    "trusted_proof_unit_ids": [],
                }
            )
        else:
            _complete_grading(result)

    monkeypatch.setattr(runner, "_run_backend_with_retries", no_agent)
    monkeypatch.setattr(runner, "_run_grader_local", grade)

    first_item = _resume_item(
        tmp_path,
        pending,
        saved,
        checkpoint_sequence=1,
        max_continuations=1,
    )
    first = runner.run_single_benchmark(first_item)

    assert first["module_grading_pending"] == 0
    assert first["module_artifact"] == artifact
    assert first["grading_time_secs"] == 0
    assert first["grader_error_time_secs"] > 0
    assert runner._module_resume_action(first, max_continuations=1) == runner.MODULE_RESUME_GRADE_SAVED
    checkpoint = load_module_checkpoint(output_dir, identity)
    assert checkpoint.result["module_grading_pending"] == 0

    second_item = _resume_item(
        tmp_path,
        checkpoint.result,
        saved,
        checkpoint_sequence=checkpoint.sequence,
        max_continuations=1,
    )
    second = runner.run_single_benchmark(second_item)

    assert agent_calls == []
    assert grader_calls == 2
    assert second["check_verdict"] == "PASS"
    assert "module_grading_pending" not in second
    assert second["module_artifact"] == artifact
    assert second["grading_time_secs"] > 0
    assert second["agent_time_secs"] is None
    assert second["time_secs"] is None
    assert second["error"] == ""
    assert "grader_error" not in second


def test_zero_work_quota_does_not_grade_canonical_input_or_consume_pass_at_one(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    task.write_bytes(b"canonical omitted module")
    output_dir = tmp_path / "results"
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    backend = _ResumeBackend()
    mode = _ResumeMode(benchmark_root, task)
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=mode,
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=_identity(),
    )
    grader_calls: list[object] = []
    prompts: list[str] = []

    def zero_work_quota(item, prompt, *_args, **_kwargs):
        prompts.append(prompt)
        attempt = len(prompts)
        workspace = tmp_path / f"zero-workspace-{attempt}"
        canonical = tmp_path / f"zero-canonical-{attempt}"
        workspace.mkdir()
        canonical.mkdir()
        canonical_inputs.materialize(str(workspace))
        canonical_inputs.materialize(str(canonical))
        result = _args[3]
        usage = UsageSummary(available=False, warnings=("no model request",))
        result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK",
                "time_secs": None,
                "equivalent_cost_usd": None,
                "usage": usage.to_dict(),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "",
            True,
            False,
            False,
            False,
            [],
            usage,
        )

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", zero_work_quota)
    monkeypatch.setattr(runner, "_run_grader_local", lambda *args, **kwargs: grader_calls.append((args, kwargs)))

    result = runner.run_single_benchmark(item)

    assert grader_calls == []
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == "QUOTA_EXHAUSTED"
    assert "module_artifact" not in result
    assert "module_result" not in result
    assert "graded_after_interruption" not in result
    assert runner._module_resume_action(result, max_continuations=0) == runner.MODULE_RESUME_RETRY_FIRST

    checkpoint = load_module_checkpoint(output_dir, _identity())
    _recovered, resumes, completed = runner._recover_module_resume(
        str(output_dir),
        [result],
        {TASK_ID: _identity()},
        {TASK_ID: checkpoint},
        max_continuations=0,
    )
    assert completed == set()
    resume = resumes[TASK_ID]
    assert resume.action == runner.MODULE_RESUME_RETRY_FIRST
    assert resume.submission is None

    resumed_item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=mode,
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_resume=resume,
        module_checkpoint_identity=_identity(),
    )
    runner.run_single_benchmark(resumed_item)

    assert prompts == ["prove the module", "prove the module"]


def test_zero_work_nonretryable_infra_first_attempt_does_not_materialize_or_grade(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    task.write_bytes(b"canonical omitted module")
    output_dir = tmp_path / "results"
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    backend = _ResumeBackend()
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=_ResumeMode(benchmark_root, task),
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=_identity(),
    )
    materialization_permissions: list[bool] = []
    original_prepare = backend.prepare_submission

    def zero_work_infra(*args, **_kwargs):
        workspace = tmp_path / "infra-workspace"
        canonical = tmp_path / "infra-canonical"
        workspace.mkdir()
        canonical.mkdir()
        canonical_inputs.materialize(str(workspace))
        canonical_inputs.materialize(str(canonical))
        result = args[5]
        usage = UsageSummary(available=False, warnings=("malformed stream without a model request",))
        result.update(
            {
                "agent_exit": 1,
                "termination_reason": "INFRA_ERROR",
                "error": "invalid terminal event stream",
                "time_secs": None,
                "equivalent_cost_usd": None,
                "usage": usage.to_dict(),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "invalid event stream",
            False,
            False,
            False,
            False,
            [],
            usage,
        )

    def record_prepare(*args, **kwargs):
        materialization_permissions.append(kwargs["allow_materialization"])
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", zero_work_infra)
    monkeypatch.setattr(backend, "prepare_submission", record_prepare)
    monkeypatch.setattr(
        runner,
        "_preserve_module_submission",
        lambda *_args, **_kwargs: pytest.fail("zero-work interruption must not publish canonical bytes"),
    )
    monkeypatch.setattr(
        runner,
        "_run_grader_local",
        lambda *_args, **_kwargs: pytest.fail("zero-work interruption must not run the grader"),
    )

    result = runner.run_single_benchmark(item)

    assert materialization_permissions == [False]
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == "INFRA_ERROR"
    assert "module_artifact" not in result
    assert "module_result" not in result
    assert runner._module_resume_action(result, max_continuations=0) == runner.MODULE_RESUME_RETRY_FIRST


def test_quota_after_model_work_grades_for_diagnostics_but_retries_first_attempt(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    task.write_bytes(b"canonical omitted module")
    output_dir = tmp_path / "results"
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=_ResumeBackend(),
        mode=_ResumeMode(benchmark_root, task),
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=_identity(),
    )
    submitted = b"partially proved module after model work"
    usage = UsageSummary(input_tokens=25, output_tokens=50, model_requests=1, available=True, complete=True)
    graded_bytes: list[bytes] = []

    def interrupted_after_work(item, _prompt, *_args, **_kwargs):
        workspace = tmp_path / "worked-workspace"
        canonical = tmp_path / "worked-canonical"
        workspace.mkdir()
        canonical.mkdir()
        canonical_inputs.materialize(str(workspace))
        canonical_inputs.materialize(str(canonical))
        (workspace / "Task.tla").write_bytes(submitted)
        result = _args[3]
        result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK",
                "time_secs": 4.5,
                "equivalent_cost_usd": 0.02,
                "usage": usage.to_dict(),
                "input_tokens": 25,
                "output_tokens": 50,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "partial work",
            True,
            True,
            False,
            True,
            [],
            usage,
        )

    def grade(_item, workspace, basename, _grading_dir, _check_path, result, _canonical_dir=None):
        graded_bytes.append(Path(workspace, basename).read_bytes())
        module_result = _module_result(complete=False)
        result.update(
            {
                "check_verdict": "FAIL",
                "module_result": module_result,
                "proof_unit_count": 1,
                "trusted_proof_unit_count": 0,
                "trusted_proof_unit_ids": [],
            }
        )

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", interrupted_after_work)
    monkeypatch.setattr(runner, "_run_grader_local", grade)

    result = runner.run_single_benchmark(item)

    assert graded_bytes == [submitted]
    assert result["check_verdict"] == "FAIL"
    assert result["termination_reason"] == "QUOTA_EXHAUSTED"
    assert result["graded_after_interruption"] is True
    assert result["input_tokens"] == 25
    assert result["output_tokens"] == 50
    assert result["agent_time_secs"] == 4.5
    assert result["grading_time_secs"] > 0
    assert result["time_secs"] == pytest.approx(result["agent_time_secs"] + result["grading_time_secs"])
    assert result["equivalent_cost_usd"] == 0.02
    assert result["module_artifact"]["sha256"] == hashlib.sha256(submitted).hexdigest()
    assert runner._module_resume_action(result, max_continuations=0) == runner.MODULE_RESUME_RETRY_FIRST


def test_interrupted_first_attempt_resume_keeps_accounting_and_uses_only_remaining_timeout(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    partial = b"partial first-attempt module"
    identity, result = _checkpoint_result(output_dir, first_content=partial)
    result.update(
        {
            "termination_reason": "INFRA_ERROR",
            "graded_after_interruption": True,
            "agent_time_secs": 3.0,
            "grading_time_secs": 1.0,
            "logical_timeout_used_secs": 4.0,
            "time_secs": 4.0,
            "logical_timeout_secs": 10,
            "input_tokens": 10,
            "output_tokens": 20,
            "usage": UsageSummary(
                input_tokens=10,
                output_tokens=20,
                model_requests=1,
                available=True,
                complete=True,
            ).to_dict(),
            "equivalent_cost_usd": 0.1,
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(tmp_path, result, partial, action=runner.MODULE_RESUME_RETRY_FIRST)
    resumed_usage = UsageSummary(
        input_tokens=3,
        output_tokens=4,
        model_requests=1,
        available=True,
        complete=True,
    )
    observed_timeouts: list[float] = []
    observed_inputs: list[bytes] = []

    def resumed_segment(execution_item, _prompt, *_args, **_kwargs):
        observed_timeouts.append(execution_item.timeout)
        workspace = tmp_path / "resumed-first-workspace"
        canonical = tmp_path / "resumed-first-canonical"
        workspace.mkdir()
        canonical.mkdir()
        item.canonical_inputs.materialize(str(workspace))
        item.canonical_inputs.materialize(str(canonical))
        (workspace / "Task.tla").write_bytes(execution_item.module_resume.submission)
        observed_inputs.append((workspace / "Task.tla").read_bytes())
        (workspace / "Task.tla").write_bytes(b"completed first-attempt module")
        segment_result = _args[3]
        segment_result.update(
            {
                "agent_exit": 0,
                "termination_reason": "OK",
                "agent_time_secs": 2.0,
                "grading_time_secs": 0.0,
                "logical_timeout_used_secs": 2.0,
                "time_secs": 2.0,
                "usage": resumed_usage.to_dict(),
                "input_tokens": 3,
                "output_tokens": 4,
                "equivalent_cost_usd": 0.05,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "resumed model work",
            False,
            False,
            False,
            True,
            [],
            resumed_usage,
        )

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", resumed_segment)
    monkeypatch.setattr(runner, "_run_grader_local", lambda *args, **_kwargs: _complete_grading(args[5]))

    recovered = runner.run_single_benchmark(item)

    assert observed_timeouts == [6.0]
    assert observed_inputs == [partial]
    assert recovered["check_verdict"] == "PASS"
    assert recovered["logical_resume_count"] == 1
    assert recovered["agent_time_secs"] == 5.0
    assert recovered["logical_timeout_used_secs"] == 6.0
    assert recovered["logical_timeout_remaining_secs"] == 4.0
    assert recovered["grading_time_secs"] > 1.0
    assert recovered["time_secs"] == pytest.approx(recovered["agent_time_secs"] + recovered["grading_time_secs"])
    assert (recovered["input_tokens"], recovered["output_tokens"]) == (13, 24)
    assert recovered["equivalent_cost_usd"] == pytest.approx(0.15)


def test_exhausted_first_attempt_timeout_is_not_reset_on_resume(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    partial = b"partial module at timeout boundary"
    identity, result = _checkpoint_result(output_dir, first_content=partial)
    result.update(
        {
            "termination_reason": "INFRA_ERROR",
            "graded_after_interruption": True,
            "agent_time_secs": 10.0,
            "grading_time_secs": 1.0,
            "logical_timeout_used_secs": 10.0,
            "time_secs": 11.0,
            "logical_timeout_secs": 10,
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(tmp_path, result, partial, action=runner.MODULE_RESUME_RETRY_FIRST)

    monkeypatch.setattr(
        runner,
        "_run_backend_with_retries",
        lambda *_args, **_kwargs: pytest.fail("an exhausted logical attempt must not launch the agent"),
    )

    recovered = runner.run_single_benchmark(item)

    assert recovered["check_verdict"] == "TIMEOUT"
    assert recovered["termination_reason"] == "TIMEOUT"
    assert recovered["logical_timeout_remaining_secs"] == 0.0
    assert recovered["agent_time_secs"] == 10.0
    assert recovered["time_secs"] == 11.0


def test_exhausted_first_attempt_starts_first_continuation_with_fresh_round_timeout(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    partial = b"partial module after exhausted first attempt"
    identity, result = _checkpoint_result(output_dir, first_content=partial, max_continuations=1)
    result.update(
        {
            "termination_reason": "INFRA_ERROR",
            "graded_after_interruption": True,
            "agent_time_secs": 10.0,
            "grading_time_secs": 1.0,
            "logical_timeout_used_secs": 10.0,
            "time_secs": 11.0,
            "logical_timeout_secs": 10,
            "max_continuations": 1,
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        partial,
        action=runner.MODULE_RESUME_RETRY_FIRST,
        max_continuations=1,
    )
    continuation_usage = UsageSummary(
        input_tokens=2,
        output_tokens=3,
        model_requests=1,
        available=True,
        complete=True,
    )
    observed: list[tuple[float, int, bytes]] = []

    def continuation_segment(execution_item, _prompt, *_args, **kwargs):
        workspace = Path(kwargs["fixed_workspace"])
        round_result = _args[3]
        observed.append((execution_item.timeout, round_result["round"], (workspace / "Task.tla").read_bytes()))
        (workspace / "Task.tla").write_bytes(b"completed by continuation")
        canonical = tmp_path / "first-timeout-continuation-canonical"
        canonical.mkdir()
        round_result.update(
            {
                "agent_exit": 0,
                "termination_reason": "OK",
                "agent_time_secs": 1.0,
                "grading_time_secs": 0.0,
                "logical_timeout_used_secs": 1.0,
                "time_secs": 1.0,
                "usage": continuation_usage.to_dict(),
                "input_tokens": 2,
                "output_tokens": 3,
                "equivalent_cost_usd": 0.01,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "continuation model work",
            False,
            False,
            False,
            True,
            [],
            continuation_usage,
        )

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", continuation_segment)
    monkeypatch.setattr(runner, "_run_grader_local", lambda *args, **_kwargs: _complete_grading(args[5]))

    recovered = runner.run_single_benchmark(item)

    assert observed == [(10, 1, partial)]
    assert recovered["check_verdict"] == "TIMEOUT"
    assert [round_result["check_verdict"] for round_result in recovered["continuations"]] == ["PASS"]
    assert recovered["continuations"][0]["round"] == 1


def test_repeated_interruption_with_invalid_submission_keeps_fallback_artifact_and_accounting(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    partial = b"durable partial module"
    identity, result = _checkpoint_result(output_dir, first_content=partial)
    artifact = result["module_artifact"]
    result.update(
        {
            "termination_reason": "INFRA_ERROR",
            "graded_after_interruption": True,
            "agent_time_secs": 3.0,
            "grading_time_secs": 0.5,
            "logical_timeout_used_secs": 3.0,
            "time_secs": 3.5,
            "logical_timeout_secs": 10,
            "input_tokens": 10,
            "output_tokens": 20,
            "usage": UsageSummary(
                input_tokens=10,
                output_tokens=20,
                model_requests=1,
                available=True,
                complete=True,
            ).to_dict(),
            "equivalent_cost_usd": 0.1,
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(tmp_path, result, partial, action=runner.MODULE_RESUME_RETRY_FIRST)
    interrupted_usage = UsageSummary(
        input_tokens=3,
        output_tokens=4,
        model_requests=1,
        available=True,
        complete=True,
    )

    def interrupted_invalid_segment(execution_item, _prompt, *_args, **_kwargs):
        workspace = tmp_path / "repeated-interruption-workspace"
        canonical = tmp_path / "repeated-interruption-canonical"
        workspace.mkdir()
        canonical.mkdir()
        item.canonical_inputs.materialize(str(workspace))
        item.canonical_inputs.materialize(str(canonical))
        (workspace / "Task.tla").write_bytes(execution_item.module_resume.submission)
        (workspace / "Task.tla").unlink()
        segment_result = _args[3]
        segment_result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK",
                "agent_time_secs": 2.0,
                "grading_time_secs": 0.0,
                "logical_timeout_used_secs": 2.0,
                "time_secs": 2.0,
                "usage": interrupted_usage.to_dict(),
                "input_tokens": 3,
                "output_tokens": 4,
                "equivalent_cost_usd": 0.02,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "model deleted its submission before interruption",
            True,
            True,
            False,
            True,
            [],
            interrupted_usage,
        )

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", interrupted_invalid_segment)
    monkeypatch.setattr(
        runner,
        "_run_grader_local",
        lambda *_args, **_kwargs: pytest.fail("an invalid segment must not reach the grader"),
    )

    recovered = runner.run_single_benchmark(item)

    assert recovered["check_verdict"] == "FAIL"
    assert recovered["termination_reason"] == "QUOTA_EXHAUSTED"
    assert recovered["invalid_submission_after_interruption"] is True
    assert recovered["module_artifact"] == artifact
    assert "module_result" not in recovered
    assert recovered["agent_time_secs"] == 5.0
    assert recovered["logical_timeout_used_secs"] == 5.0
    assert (recovered["input_tokens"], recovered["output_tokens"]) == (13, 24)
    assert recovered["equivalent_cost_usd"] == pytest.approx(0.12)
    assert "cannot checkpoint module progress" not in recovered["error"]
    checkpoint = load_module_checkpoint(output_dir, identity)
    assert checkpoint.result["invalid_submission_after_interruption"] is True
    assert checkpoint.result["module_artifact"] == artifact
    assert checkpoint.result["agent_time_secs"] == 5.0


@pytest.mark.parametrize(
    ("submission_state", "quota_exhausted", "expected_termination", "expected_error"),
    [
        ("missing", True, "QUOTA_EXHAUSTED", "module submission is missing"),
        ("empty", False, "INFRA_ERROR", "module submission is empty"),
    ],
)
def test_interrupted_model_work_with_invalid_submission_requires_first_attempt_retry(
    tmp_path,
    monkeypatch,
    submission_state,
    quota_exhausted,
    expected_termination,
    expected_error,
):
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    task.write_bytes(b"canonical omitted module")
    output_dir = tmp_path / "results"
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=_ResumeBackend(),
        mode=_ResumeMode(benchmark_root, task),
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=_identity(),
    )
    usage = UsageSummary(input_tokens=100, output_tokens=50, model_requests=1, available=True, complete=True)

    def interrupted_invalid_submission(_item, _prompt, *_args, **_kwargs):
        workspace = tmp_path / "worked-workspace"
        canonical = tmp_path / "worked-canonical"
        workspace.mkdir()
        canonical.mkdir()
        canonical_inputs.materialize(str(workspace))
        canonical_inputs.materialize(str(canonical))
        destination = workspace / "Task.tla"
        if submission_state == "missing":
            destination.unlink()
        else:
            destination.write_bytes(b"")
        result = _args[3]
        result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK" if quota_exhausted else "INFRA_ERROR",
                "time_secs": 4.5,
                "equivalent_cost_usd": 0.25,
                "usage": usage.to_dict(),
                "input_tokens": 100,
                "output_tokens": 50,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "paid model work",
            quota_exhausted,
            quota_exhausted,
            False,
            True,
            [],
            usage,
        )

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", interrupted_invalid_submission)
    monkeypatch.setattr(
        runner,
        "_run_grader_local",
        lambda *_args, **_kwargs: pytest.fail("a missing or empty module is a direct submission failure"),
    )

    result = runner.run_single_benchmark(item)

    assert result["check_verdict"] == "FAIL"
    assert result["termination_reason"] == expected_termination
    assert result["error"] == expected_error
    assert result["invalid_submission_after_interruption"] is True
    assert "graded_after_interruption" not in result
    assert "module_artifact" not in result
    assert "module_result" not in result
    assert (result["input_tokens"], result["output_tokens"]) == (100, 50)
    assert result["equivalent_cost_usd"] == 0.25
    assert runner.is_non_genuine(result)
    assert runner._module_resume_action(result, max_continuations=0) == runner.MODULE_RESUME_RETRY_FIRST
    checkpoint = load_module_checkpoint(output_dir, _identity())
    assert checkpoint.result["invalid_submission_after_interruption"] is True


@pytest.mark.parametrize("submission_state", ["missing", "empty"])
def test_invalid_interrupted_first_submission_retries_pass_at_one_from_canonical_bytes(
    tmp_path,
    monkeypatch,
    submission_state,
):
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    canonical_bytes = b"canonical task module"
    task.write_bytes(canonical_bytes)
    output_dir = tmp_path / "results"
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    identity = _identity()
    backend = _ResumeBackend()
    mode = _ResumeMode(benchmark_root, task)
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=mode,
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        max_continuations=1,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=identity,
    )
    usage = UsageSummary(input_tokens=5, output_tokens=6, model_requests=1, available=True, complete=True)

    def interrupted_invalid_submission(_item, _prompt, *_args, **_kwargs):
        workspace = tmp_path / "worked-workspace"
        canonical = tmp_path / "worked-canonical"
        workspace.mkdir()
        canonical.mkdir()
        canonical_inputs.materialize(str(workspace))
        canonical_inputs.materialize(str(canonical))
        destination = workspace / "Task.tla"
        if submission_state == "missing":
            destination.unlink()
        else:
            destination.write_bytes(b"")
        result = _args[3]
        result.update(
            {
                "agent_exit": -1,
                "termination_reason": "INFRA_ERROR",
                "time_secs": 1.0,
                "equivalent_cost_usd": 0.01,
                "usage": usage.to_dict(),
                "input_tokens": 5,
                "output_tokens": 6,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "paid model work",
            False,
            False,
            False,
            True,
            [],
            usage,
        )

    continuation_inputs: list[bytes] = []

    def capture_continuation(_item, workspace, *_args, **_kwargs):
        continuation_inputs.append(Path(workspace, "Task.tla").read_bytes())

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", interrupted_invalid_submission)
    monkeypatch.setattr(runner, "_run_continuations", capture_continuation)
    monkeypatch.setattr(
        runner,
        "_run_grader_local",
        lambda *_args, **_kwargs: pytest.fail("an invalid module must not reach the grader"),
    )

    result = runner.run_single_benchmark(item)
    checkpoint = load_module_checkpoint(output_dir, identity)
    recovered, resumes, completed = runner._recover_module_resume(
        str(output_dir),
        [result],
        {TASK_ID: identity},
        {TASK_ID: checkpoint},
        max_continuations=1,
    )

    assert completed == set()
    assert recovered[0]["check_verdict"] == "FAIL"
    resume = resumes[TASK_ID]
    assert resume.action == runner.MODULE_RESUME_RETRY_FIRST
    assert resume.submission is None
    assert continuation_inputs == []


def test_first_attempt_checker_failure_keeps_artifact_pending_and_stops_continuations(tmp_path, monkeypatch):
    benchmark_root = tmp_path / "benchmark"
    task = benchmark_root / TASK_ID
    task.parent.mkdir(parents=True)
    task.write_bytes(b"canonical omitted module")
    output_dir = tmp_path / "results"
    canonical_inputs = runner.CanonicalInputs.capture(str(task), task.name, [])
    item = runner.WorkItem(
        benchmark_path=str(task),
        output_dir=str(output_dir),
        timeout=10,
        check_timeout=10,
        backend=_ResumeBackend(),
        mode=_ResumeMode(benchmark_root, task),
        tlapm_path="/opt/tlapm",
        tlapm_lib="/opt/tlapm/lib",
        infra_retries=0,
        max_continuations=1,
        canonical_inputs=canonical_inputs,
        module_checkpoint_identity=_identity(),
    )
    submitted = b"model-produced partial module"
    usage = UsageSummary(input_tokens=5, output_tokens=7, model_requests=1, available=True, complete=True)

    def model_work(item, _prompt, *_args, **_kwargs):
        workspace = tmp_path / "worked-workspace"
        canonical = tmp_path / "worked-canonical"
        workspace.mkdir()
        canonical.mkdir()
        canonical_inputs.materialize(str(workspace))
        canonical_inputs.materialize(str(canonical))
        (workspace / "Task.tla").write_bytes(submitted)
        result = _args[3]
        result.update(
            {
                "agent_exit": 0,
                "termination_reason": "OK",
                "time_secs": 1.0,
                "equivalent_cost_usd": 0.01,
                "usage": usage.to_dict(),
                "input_tokens": 5,
                "output_tokens": 7,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "model work",
            False,
            False,
            False,
            True,
            [],
            usage,
        )

    def checker_unavailable(_item, _workspace, _basename, _grading_dir, _check_path, result, _canonical=None):
        result["check_verdict"] = "ERROR"
        result["error"] = "checker unavailable"

    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_run_backend_with_retries", model_work)
    monkeypatch.setattr(runner, "_run_grader_local", checker_unavailable)
    monkeypatch.setattr(
        runner,
        "_run_continuations",
        lambda *_args, **_kwargs: pytest.fail("ungraded saved bytes must stop before a continuation"),
    )

    result = runner.run_single_benchmark(item)

    assert result["check_verdict"] == "ERROR"
    assert result["module_grading_pending"] == 0
    assert result["module_artifact"]["sha256"] == hashlib.sha256(submitted).hexdigest()
    assert runner._module_resume_action(result, max_continuations=1) == runner.MODULE_RESUME_GRADE_SAVED
    assert load_module_checkpoint(output_dir, _identity()).result["module_grading_pending"] == 0


def test_pending_continuation_grades_as_continuation_and_keeps_pass_at_one(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    first = publish_module_artifact(output_dir, b"first failed module")
    continuation = publish_module_artifact(output_dir, b"saved continuation module")
    first_result = _attempt(artifact=first, module_result=_module_result(complete=False), verdict="FAIL")
    pending_round = _attempt(artifact=continuation, verdict="ERROR", round=1)
    pending_round.update({"agent_exit": 0, "input_tokens": 7, "output_tokens": 8})
    result = {
        **first_result,
        "input_tokens": 100,
        "output_tokens": 200,
        "time_secs": 4.0,
        "equivalent_cost_usd": 0.02,
        "continuations": [pending_round],
        "module_grading_pending": 1,
        "max_continuations": 2,
    }
    identity = _identity()
    write_module_checkpoint(output_dir, identity, result)

    item = _resume_item(
        tmp_path,
        result,
        b"saved continuation module",
        checkpoint_sequence=3,
        max_continuations=2,
    )
    agent_calls: list[object] = []
    graded_bytes: list[bytes] = []

    def unexpected_agent(*args, **kwargs):
        agent_calls.append((args, kwargs))
        raise AssertionError("a pending continuation must be graded before a new continuation agent call")

    def grade(item, workspace, basename, grading_dir, check_result_path, attempt, canonical_dir=None):
        graded_bytes.append(Path(workspace, basename).read_bytes())
        _complete_grading(attempt)

    monkeypatch.setattr(runner, "_run_backend_local", unexpected_agent)
    monkeypatch.setattr(runner, "_run_grader_local", grade)

    recovered = runner.run_single_benchmark(item)

    assert agent_calls == []
    assert graded_bytes == [b"saved continuation module"]
    assert recovered["check_verdict"] == "FAIL"
    assert recovered["continuations"][0]["check_verdict"] == "PASS"
    assert recovered["input_tokens"] == 100
    assert recovered["output_tokens"] == 200
    assert recovered["agent_time_secs"] == 4.0
    assert recovered["grading_time_secs"] > 0
    assert recovered["time_secs"] == pytest.approx(recovered["agent_time_secs"] + recovered["grading_time_secs"])
    assert recovered["equivalent_cost_usd"] == 0.02


def test_recover_marks_spent_continuation_budget_complete(tmp_path):
    identity, result = _checkpoint_result(
        tmp_path,
        continuation_contents=(b"continuation module",),
        continuation_verdicts=("FAIL",),
    )

    recovered, resumes, completed = runner._recover_module_resume(
        str(tmp_path),
        [result],
        {TASK_ID: identity},
        {TASK_ID: load_module_checkpoint(tmp_path, identity)},
        max_continuations=1,
    )

    assert completed == {TASK_ID}
    assert resumes == {}
    assert recovered[0]["check_verdict"] == "FAIL"


def test_recover_retries_interrupted_continuation_at_same_round_without_losing_history(tmp_path):
    identity, result = _checkpoint_result(
        tmp_path,
        continuation_contents=(b"interrupted continuation module",),
        continuation_verdicts=("ERROR",),
        continuation_termination_reasons=("INFRA_ERROR",),
    )
    result["input_tokens"] = 100
    result["output_tokens"] = 200
    result["time_secs"] = 5.0
    result["equivalent_cost_usd"] = 0.03
    # Rewrite the checkpoint with the accounting fields included.
    write_module_checkpoint(tmp_path, identity, result)
    checkpoint = load_module_checkpoint(tmp_path, identity)

    recovered, resumes, completed = runner._recover_module_resume(
        str(tmp_path),
        [result],
        {TASK_ID: identity},
        {TASK_ID: checkpoint},
        max_continuations=2,
    )
    assert completed == set()
    assert resumes[TASK_ID].action == runner.MODULE_RESUME_CONTINUE
    assert recovered[0]["check_verdict"] == "FAIL"
    assert recovered[0]["continuations"][0]["round"] == 1
    assert recovered[0]["continuations"][0]["termination_reason"] == "INFRA_ERROR"
    assert recovered[0]["input_tokens"] == 100
    assert recovered[0]["output_tokens"] == 200
    assert recovered[0]["time_secs"] == 5.0
    assert recovered[0]["equivalent_cost_usd"] == 0.03


def test_recover_retries_graded_but_interrupted_first_attempt(tmp_path):
    identity, result = _checkpoint_result(tmp_path, max_continuations=1)
    result.update(
        {
            "termination_reason": "QUOTA_EXHAUSTED",
            "graded_after_interruption": True,
            "input_tokens": 100,
            "output_tokens": 200,
            "time_secs": 5.0,
            "equivalent_cost_usd": 0.03,
        }
    )
    write_module_checkpoint(tmp_path, identity, result)

    recovered, resumes, completed = runner._recover_module_resume(
        str(tmp_path),
        [result],
        {TASK_ID: identity},
        {TASK_ID: load_module_checkpoint(tmp_path, identity)},
        max_continuations=1,
    )

    assert completed == set()
    assert resumes[TASK_ID].action == runner.MODULE_RESUME_RETRY_FIRST
    assert recovered[0]["check_verdict"] == "FAIL"
    assert recovered[0]["graded_after_interruption"] is True
    assert recovered[0]["input_tokens"] == 100
    assert recovered[0]["output_tokens"] == 200
    assert recovered[0]["time_secs"] == 5.0
    assert recovered[0]["equivalent_cost_usd"] == 0.03


def test_interrupted_continuation_is_archived_when_same_formal_round_restarts(tmp_path, monkeypatch):
    identity, result = _checkpoint_result(
        tmp_path,
        continuation_contents=(b"interrupted continuation module",),
        continuation_verdicts=("ERROR",),
        continuation_termination_reasons=("INFRA_ERROR",),
        max_continuations=2,
    )
    result["continuations"][0].update(
        agent_time_secs=1.0,
        grading_time_secs=0.0,
        logical_timeout_used_secs=1.0,
        time_secs=1.0,
        logical_timeout_secs=10,
    )
    item = _resume_item(
        tmp_path,
        result,
        b"interrupted continuation module",
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    item.mode.build_continuation_prompt = lambda *_args: "continue"  # type: ignore[attr-defined,method-assign]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Task.tla").write_bytes(b"interrupted continuation module")
    observed_rounds: list[int] = []

    def stop_after_round_is_selected(*args, **_kwargs):
        observed_rounds.append(args[5]["round"])
        raise RuntimeError("stop after selecting retry round")

    monkeypatch.setattr(runner, "_run_backend_with_retries", stop_after_round_is_selected)

    with pytest.raises(RuntimeError, match="selecting retry round"):
        runner._run_continuations(
            item,
            str(workspace),
            result,
            str(tmp_path / "task-result"),
            "Task.tla",
            "Task",
            item.canonical_inputs,
            "/checker",
        )

    assert observed_rounds == [1]
    assert result["continuations"] == []
    assert result["interrupted_continuations"][0]["round"] == 1
    assert result["interrupted_continuations"][0]["termination_reason"] == "INFRA_ERROR"
    write_module_checkpoint(tmp_path, identity, result)


def test_zero_work_quota_continuation_does_not_publish_or_consume_the_round(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    prior_submission = b"existing partial module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=prior_submission,
        max_continuations=2,
    )
    result["max_continuations"] = 2
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        prior_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Task.tla").write_bytes(prior_submission)
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    usage = UsageSummary(available=False, warnings=("no model request",))
    grader_calls: list[object] = []

    def zero_work_quota(*args, **_kwargs):
        round_result = args[5]
        round_result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK",
                "time_secs": None,
                "equivalent_cost_usd": None,
                "usage": usage.to_dict(),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical_dir),
            "",
            True,
            False,
            False,
            False,
            [],
            usage,
        )

    monkeypatch.setattr(runner, "_run_backend_with_retries", zero_work_quota)
    monkeypatch.setattr(
        runner,
        "_preserve_module_submission",
        lambda *_args, **_kwargs: pytest.fail("zero-work quota must not publish the prior workspace again"),
    )
    monkeypatch.setattr(runner, "_run_grader_local", lambda *args, **kwargs: grader_calls.append((args, kwargs)))

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    assert grader_calls == []
    assert (workspace / "Task.tla").read_bytes() == prior_submission
    assert result["continuations"][0]["round"] == 1
    assert result["continuations"][0]["termination_reason"] == "QUOTA_EXHAUSTED"
    assert "module_artifact" not in result["continuations"][0]
    assert "module_grading_pending" not in result
    assert result.get("input_tokens", 0) == 0
    assert result.get("output_tokens", 0) == 0
    assert runner._module_resume_action(result, max_continuations=2) == runner.MODULE_RESUME_CONTINUE
    checkpoint = load_module_checkpoint(output_dir, identity)
    assert checkpoint.result["continuations"][0]["round"] == 1


def test_zero_work_nonretryable_infra_continuation_does_not_publish_grade_or_consume_round(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    prior_submission = b"existing partial module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=prior_submission,
        max_continuations=2,
    )
    result["max_continuations"] = 2
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        prior_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Task.tla").write_bytes(prior_submission)
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    usage = UsageSummary(available=False, warnings=("malformed stream without a model request",))

    def zero_work_infra(*args, **_kwargs):
        round_result = args[5]
        round_result.update(
            {
                "agent_exit": 1,
                "termination_reason": "INFRA_ERROR",
                "error": "invalid terminal event stream",
                "time_secs": None,
                "equivalent_cost_usd": None,
                "usage": usage.to_dict(),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical_dir),
            "invalid event stream",
            False,
            False,
            False,
            False,
            [],
            usage,
        )

    monkeypatch.setattr(runner, "_run_backend_with_retries", zero_work_infra)
    monkeypatch.setattr(
        runner,
        "_preserve_module_submission",
        lambda *_args, **_kwargs: pytest.fail("zero-work interruption must not republish the prior workspace"),
    )
    monkeypatch.setattr(
        runner,
        "_run_grader_local",
        lambda *_args, **_kwargs: pytest.fail("zero-work interruption must not run the grader"),
    )

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    interrupted_round = result["continuations"][0]
    assert interrupted_round["round"] == 1
    assert interrupted_round["termination_reason"] == "INFRA_ERROR"
    assert "module_artifact" not in interrupted_round
    assert "module_grading_pending" not in result
    assert runner.is_non_genuine(interrupted_round)
    assert runner._module_resume_action(result, max_continuations=2) == runner.MODULE_RESUME_CONTINUE

    selected_rounds: list[int] = []

    def stop_after_round_selection(*args, **_kwargs):
        selected_rounds.append(args[5]["round"])
        raise RuntimeError("stop after selecting retry round")

    monkeypatch.setattr(runner, "_run_backend_with_retries", stop_after_round_selection)
    with pytest.raises(RuntimeError, match="selecting retry round"):
        runner._run_continuations(
            item,
            str(workspace),
            result,
            str(tmp_path / "task-result"),
            "Task.tla",
            "Task",
            item.canonical_inputs,
            "/checker",
        )

    assert selected_rounds == [1]
    assert result["continuations"] == []
    assert result["interrupted_continuations"][0]["round"] == 1


def test_continuation_checker_failure_keeps_round_pending_and_stops_the_chain(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    prior_submission = b"first partial module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=prior_submission,
        max_continuations=2,
    )
    result["max_continuations"] = 2
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        prior_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    submitted = b"continuation partial module"
    (workspace / "Task.tla").write_bytes(submitted)
    usage = UsageSummary(input_tokens=3, output_tokens=4, model_requests=1, available=True, complete=True)
    backend_calls = 0

    def model_work(*args, **_kwargs):
        nonlocal backend_calls
        backend_calls += 1
        canonical_dir = tmp_path / f"canonical-{backend_calls}"
        canonical_dir.mkdir()
        round_result = args[5]
        round_result.update(
            {
                "agent_exit": 0,
                "termination_reason": "OK",
                "time_secs": 1.0,
                "equivalent_cost_usd": 0.01,
                "usage": usage.to_dict(),
                "input_tokens": 3,
                "output_tokens": 4,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical_dir),
            "model work",
            False,
            False,
            False,
            True,
            [],
            usage,
        )

    def checker_unavailable(_item, _workspace, _basename, _round_dir, _check_path, round_result, _canonical=None):
        round_result["check_verdict"] = "ERROR"
        round_result["error"] = "checker unavailable"

    monkeypatch.setattr(runner, "_run_backend_with_retries", model_work)
    monkeypatch.setattr(runner, "_run_grader_local", checker_unavailable)

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    assert backend_calls == 1
    assert result["module_grading_pending"] == 1
    assert result["continuations"][0]["module_artifact"]["sha256"] == hashlib.sha256(submitted).hexdigest()
    assert runner._module_resume_action(result, max_continuations=2) == runner.MODULE_RESUME_GRADE_SAVED
    checkpoint = load_module_checkpoint(output_dir, identity)
    assert checkpoint.result["module_grading_pending"] == 1


def test_interrupted_worked_continuation_regrade_consumes_the_same_round(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    first_submission = b"first partial module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=first_submission,
        max_continuations=2,
    )
    result["max_continuations"] = 2
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        first_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    interrupted_submission = b"partial module produced before interruption"
    (workspace / "Task.tla").write_bytes(interrupted_submission)
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    usage = UsageSummary(input_tokens=3, output_tokens=4, model_requests=1, available=True, complete=True)

    def interrupted_model_work(*args, **_kwargs):
        round_result = args[5]
        round_result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK",
                "time_secs": 1.0,
                "equivalent_cost_usd": 0.01,
                "usage": usage.to_dict(),
                "input_tokens": 3,
                "output_tokens": 4,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical_dir),
            "model work before interruption",
            True,
            True,
            False,
            True,
            [],
            usage,
        )

    def checker_unavailable(_item, _workspace, _basename, _round_dir, _check_path, round_result, _canonical=None):
        round_result["check_verdict"] = "ERROR"
        round_result["error"] = "checker unavailable"

    monkeypatch.setattr(runner, "_run_backend_with_retries", interrupted_model_work)
    monkeypatch.setattr(runner, "_run_grader_local", checker_unavailable)

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    pending_round = result["continuations"][0]
    assert result["module_grading_pending"] == 1
    assert pending_round["termination_reason"] == "QUOTA_EXHAUSTED"
    assert pending_round["graded_after_interruption"] is True
    assert "module_result" not in pending_round
    assert runner.is_non_genuine(pending_round)

    resumed_workspace = tmp_path / "resumed-workspace"
    resumed_workspace.mkdir()
    (resumed_workspace / "Task.tla").write_bytes(interrupted_submission)

    def partial_grade(_item, _workspace, _basename, _round_dir, _check_path, round_result, _canonical=None):
        module_result = _module_result(complete=False)
        round_result.update(
            {
                "check_verdict": "FAIL",
                "module_result": module_result,
                "proof_unit_count": 1,
                "trusted_proof_unit_count": 0,
                "trusted_proof_unit_ids": [],
            }
        )

    monkeypatch.setattr(runner, "_run_grader_local", partial_grade)
    runner._grade_resumed_module_submission(
        item,
        str(resumed_workspace),
        result,
        str(tmp_path / "task-result"),
        str(tmp_path / "task-result" / "grading"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
    )

    assert "module_grading_pending" not in result
    assert runner.is_non_genuine(result["continuations"][0])
    assert runner._module_resume_action(result, max_continuations=2) == runner.MODULE_RESUME_CONTINUE

    selected_rounds: list[int] = []

    def stop_after_round_selection(*args, **_kwargs):
        selected_rounds.append(args[5]["round"])
        raise RuntimeError("stop after selecting continuation round")

    monkeypatch.setattr(runner, "_run_backend_with_retries", stop_after_round_selection)
    with pytest.raises(RuntimeError, match="selecting continuation round"):
        runner._run_continuations(
            item,
            str(resumed_workspace),
            result,
            str(tmp_path / "task-result"),
            "Task.tla",
            "Task",
            item.canonical_inputs,
            "/checker",
        )

    assert selected_rounds == [1]
    assert len(result["interrupted_continuations"]) == 1


def test_interrupted_continuation_resume_keeps_round_accounting_and_remaining_timeout(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    first_submission = b"first partial module"
    interrupted_submission = b"interrupted continuation module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=first_submission,
        continuation_contents=(interrupted_submission,),
        continuation_verdicts=("FAIL",),
        continuation_termination_reasons=("INFRA_ERROR",),
        max_continuations=2,
    )
    first_usage = UsageSummary(
        input_tokens=10,
        output_tokens=20,
        model_requests=1,
        available=True,
        complete=True,
    )
    interrupted_usage = UsageSummary(
        input_tokens=3,
        output_tokens=4,
        model_requests=1,
        available=True,
        complete=True,
    )
    interrupted_round = result["continuations"][0]
    interrupted_round.update(
        {
            "graded_after_interruption": True,
            "agent_time_secs": 4.0,
            "grading_time_secs": 0.5,
            "logical_timeout_used_secs": 4.0,
            "time_secs": 4.5,
            "logical_timeout_secs": 10,
            "input_tokens": 3,
            "output_tokens": 4,
            "usage": interrupted_usage.to_dict(),
            "equivalent_cost_usd": 0.05,
        }
    )
    result.update(
        {
            "agent_time_secs": 6.0,
            "grading_time_secs": 1.5,
            "time_secs": 7.5,
            "input_tokens": 13,
            "output_tokens": 24,
            "usage": first_usage.merge(interrupted_usage).to_dict(),
            "equivalent_cost_usd": 0.15,
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        interrupted_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "continuation-resume-workspace"
    workspace.mkdir()
    (workspace / "Task.tla").write_bytes(interrupted_submission)
    resumed_usage = UsageSummary(
        input_tokens=5,
        output_tokens=6,
        model_requests=1,
        available=True,
        complete=True,
    )
    observed_timeouts: list[float] = []
    observed_rounds: list[int] = []

    def resumed_segment(execution_item, _prompt, *_args, **_kwargs):
        observed_timeouts.append(execution_item.timeout)
        round_result = _args[3]
        observed_rounds.append(round_result["round"])
        (workspace / "Task.tla").write_bytes(b"completed continuation module")
        canonical = tmp_path / "continuation-resume-canonical"
        canonical.mkdir()
        round_result.update(
            {
                "agent_exit": 0,
                "termination_reason": "OK",
                "agent_time_secs": 2.0,
                "grading_time_secs": 0.0,
                "logical_timeout_used_secs": 2.0,
                "time_secs": 2.0,
                "input_tokens": 5,
                "output_tokens": 6,
                "usage": resumed_usage.to_dict(),
                "equivalent_cost_usd": 0.02,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "resumed continuation work",
            False,
            False,
            False,
            True,
            [],
            resumed_usage,
        )

    monkeypatch.setattr(runner, "_run_backend_with_retries", resumed_segment)
    monkeypatch.setattr(runner, "_run_grader_local", lambda *args, **_kwargs: _complete_grading(args[5]))

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    assert observed_timeouts == [6.0]
    assert observed_rounds == [1]
    assert len(result["continuations"]) == 1
    recovered_round = result["continuations"][0]
    assert recovered_round["round"] == 1
    assert recovered_round["check_verdict"] == "PASS"
    assert recovered_round["logical_resume_count"] == 1
    assert recovered_round["agent_time_secs"] == 6.0
    assert recovered_round["logical_timeout_used_secs"] == 6.0
    assert recovered_round["logical_timeout_remaining_secs"] == 4.0
    assert recovered_round["grading_time_secs"] > 0.5
    assert (recovered_round["input_tokens"], recovered_round["output_tokens"]) == (8, 10)
    assert recovered_round["equivalent_cost_usd"] == pytest.approx(0.07)
    assert result["agent_time_secs"] == 8.0
    assert result["grading_time_secs"] > 1.5
    assert (result["input_tokens"], result["output_tokens"]) == (18, 30)
    assert result["equivalent_cost_usd"] == pytest.approx(0.17)


def test_exhausted_interrupted_continuation_consumes_round_and_starts_next_round(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    first_submission = b"first partial module"
    interrupted_submission = b"round one partial module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=first_submission,
        continuation_contents=(interrupted_submission,),
        continuation_verdicts=("FAIL",),
        continuation_termination_reasons=("INFRA_ERROR",),
        max_continuations=2,
    )
    interrupted_round = result["continuations"][0]
    interrupted_round.update(
        {
            "graded_after_interruption": True,
            "agent_time_secs": 10.0,
            "grading_time_secs": 0.5,
            "logical_timeout_used_secs": 10.0,
            "time_secs": 10.5,
            "logical_timeout_secs": 10,
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        interrupted_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "exhausted-continuation-workspace"
    workspace.mkdir()
    (workspace / "Task.tla").write_bytes(interrupted_submission)
    next_usage = UsageSummary(
        input_tokens=2,
        output_tokens=3,
        model_requests=1,
        available=True,
        complete=True,
    )
    observed: list[tuple[float, int]] = []

    def next_round_segment(execution_item, _prompt, *_args, **_kwargs):
        round_result = _args[3]
        observed.append((execution_item.timeout, round_result["round"]))
        (workspace / "Task.tla").write_bytes(b"completed in round two")
        canonical = tmp_path / "next-round-canonical"
        canonical.mkdir()
        round_result.update(
            {
                "agent_exit": 0,
                "termination_reason": "OK",
                "agent_time_secs": 1.0,
                "grading_time_secs": 0.0,
                "logical_timeout_used_secs": 1.0,
                "time_secs": 1.0,
                "usage": next_usage.to_dict(),
                "input_tokens": 2,
                "output_tokens": 3,
                "equivalent_cost_usd": 0.01,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical),
            "round two model work",
            False,
            False,
            False,
            True,
            [],
            next_usage,
        )

    monkeypatch.setattr(runner, "_run_backend_with_retries", next_round_segment)
    monkeypatch.setattr(runner, "_run_grader_local", lambda *args, **_kwargs: _complete_grading(args[5]))

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    assert observed == [(10, 2)]
    assert [(round_result["round"], round_result["check_verdict"]) for round_result in result["continuations"]] == [
        (1, "TIMEOUT"),
        (2, "PASS"),
    ]
    assert result["continuations"][0]["logical_timeout_remaining_secs"] == 0.0
    assert result["continuations"][1]["logical_timeout_secs"] == 10


def test_interrupted_worked_continuation_with_missing_submission_consumes_the_round(tmp_path, monkeypatch):
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    prior_submission = b"first partial module"
    identity, result = _checkpoint_result(
        output_dir,
        first_content=prior_submission,
        max_continuations=2,
    )
    result.update(
        {
            "max_continuations": 2,
            "input_tokens": 10,
            "output_tokens": 20,
            "time_secs": 2.0,
            "equivalent_cost_usd": 0.1,
            "usage": UsageSummary(
                input_tokens=10,
                output_tokens=20,
                model_requests=1,
                available=True,
                complete=True,
            ).to_dict(),
        }
    )
    write_module_checkpoint(output_dir, identity, result)
    item = _resume_item(
        tmp_path,
        result,
        prior_submission,
        action=runner.MODULE_RESUME_CONTINUE,
        max_continuations=2,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Task.tla").write_bytes(prior_submission)
    canonical_dir = tmp_path / "canonical"
    canonical_dir.mkdir()
    usage = UsageSummary(input_tokens=3, output_tokens=4, model_requests=1, available=True, complete=True)

    def interrupted_after_deletion(*args, **_kwargs):
        (workspace / "Task.tla").unlink()
        round_result = args[5]
        round_result.update(
            {
                "agent_exit": -1,
                "termination_reason": "OK",
                "time_secs": 1.0,
                "equivalent_cost_usd": 0.01,
                "usage": usage.to_dict(),
                "input_tokens": 3,
                "output_tokens": 4,
            }
        )
        return runner.ExecutionOutcome(
            str(workspace),
            str(canonical_dir),
            "paid model work before deletion",
            True,
            True,
            False,
            True,
            [],
            usage,
        )

    monkeypatch.setattr(runner, "_run_backend_with_retries", interrupted_after_deletion)
    monkeypatch.setattr(
        runner,
        "_run_grader_local",
        lambda *_args, **_kwargs: pytest.fail("a missing module is a direct submission failure"),
    )

    runner._run_continuations(
        item,
        str(workspace),
        result,
        str(tmp_path / "task-result"),
        "Task.tla",
        "Task",
        item.canonical_inputs,
        "/checker",
    )

    failed_round = result["continuations"][0]
    assert failed_round["round"] == 1
    assert failed_round["check_verdict"] == "FAIL"
    assert failed_round["termination_reason"] == "QUOTA_EXHAUSTED"
    assert failed_round["error"] == "module submission is missing"
    assert failed_round["invalid_submission_after_interruption"] is True
    assert "module_artifact" not in failed_round
    assert "module_result" not in failed_round
    assert runner.is_non_genuine(failed_round)
    assert (workspace / "Task.tla").read_bytes() == prior_submission
    assert (result["input_tokens"], result["output_tokens"]) == (13, 24)
    assert result["equivalent_cost_usd"] == pytest.approx(0.11)
    assert runner._module_resume_action(result, max_continuations=2) == runner.MODULE_RESUME_CONTINUE

    resumed_workspace = tmp_path / "resumed-workspace"
    resumed_workspace.mkdir()
    (resumed_workspace / "Task.tla").write_bytes(prior_submission)
    selected_rounds: list[int] = []

    def stop_after_round_selection(*args, **_kwargs):
        selected_rounds.append(args[5]["round"])
        raise RuntimeError("stop after selecting next round")

    monkeypatch.setattr(runner, "_run_backend_with_retries", stop_after_round_selection)
    with pytest.raises(RuntimeError, match="selecting next round"):
        runner._run_continuations(
            item,
            str(resumed_workspace),
            result,
            str(tmp_path / "task-result"),
            "Task.tla",
            "Task",
            item.canonical_inputs,
            "/checker",
        )

    assert selected_rounds == [1]
    assert len(result["interrupted_continuations"]) == 1


def test_checkpoint_rejects_graded_result_without_artifact(tmp_path):
    identity = _identity()
    result = _attempt(module_result=_module_result(complete=False), verdict="FAIL")

    with pytest.raises(ModuleCheckpointError, match="checker result without an artifact"):
        write_module_checkpoint(tmp_path, identity, result)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(invalid_submission_after_interruption=False),
        lambda result: result.update(
            invalid_submission_after_interruption=True,
            termination_reason="OK",
        ),
        lambda result: result.update(
            invalid_submission_after_interruption=True,
            check_verdict="ERROR",
        ),
        lambda result: result.update(
            invalid_submission_after_interruption=True,
            graded_after_interruption=True,
        ),
    ],
)
def test_checkpoint_rejects_inconsistent_interrupted_submission_failure(tmp_path, mutate):
    result = _attempt(verdict="FAIL", termination_reason="INFRA_ERROR")
    mutate(result)

    with pytest.raises(ModuleCheckpointError, match="interrupted-submission"):
        write_module_checkpoint(tmp_path, _identity(), result)


def test_checkpoint_rejects_noncontiguous_continuation_round(tmp_path):
    identity, _result = _checkpoint_result(
        tmp_path,
        continuation_contents=(b"continuation module",),
        continuation_verdicts=("FAIL",),
    )
    path = checkpoint_path(tmp_path, TASK_ID)
    payload = json.loads(path.read_text())
    payload["result"]["continuations"][0]["round"] = 2
    path.write_text(json.dumps(payload))

    with pytest.raises(ModuleCheckpointError, match="consecutive"):
        load_module_checkpoint(tmp_path, identity)


def test_checkpoint_rejects_round_after_passing_continuation(tmp_path):
    identity, _result = _checkpoint_result(
        tmp_path,
        continuation_contents=(b"passing continuation module",),
        continuation_verdicts=("PASS",),
    )
    second_receipt = publish_module_artifact(tmp_path, b"post-pass continuation module")
    path = checkpoint_path(tmp_path, TASK_ID)
    payload = json.loads(path.read_text())
    payload["result"]["max_continuations"] = 2
    payload["result"]["continuations"].append(
        _attempt(
            artifact=second_receipt,
            module_result=_module_result(complete=False),
            verdict="FAIL",
            round=2,
        )
    )
    path.write_text(json.dumps(payload))

    with pytest.raises(ModuleCheckpointError, match="after a passing continuation"):
        load_module_checkpoint(tmp_path, identity)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda result: result.update(module_grading_pending=-1), "non-negative integer"),
        (lambda result: result.update(module_grading_pending=True), "non-negative integer"),
        (lambda result: result.update(module_grading_pending=1), "latest continuation"),
        (
            lambda result: (result.pop("module_artifact"), result.update(module_grading_pending=0)),
            "requires a preserved module artifact",
        ),
        (
            lambda result: result.update(
                module_result=_module_result(complete=False),
                proof_unit_count=1,
                trusted_proof_unit_count=0,
                trusted_proof_unit_ids=[],
                check_verdict="FAIL",
                module_grading_pending=0,
            ),
            "successfully graded",
        ),
    ],
)
def test_checkpoint_rejects_invalid_pending_marker(tmp_path, mutate, message):
    identity = _identity()
    artifact = publish_module_artifact(tmp_path, b"pending module")
    result = _attempt(artifact=artifact, verdict="ERROR")
    mutate(result)

    with pytest.raises(ModuleCheckpointError, match=message):
        write_module_checkpoint(tmp_path, identity, result)


def test_prepare_ignores_writer_owned_stale_temp_but_rejects_arbitrary_entry(tmp_path):
    directory = tmp_path / MODULE_CHECKPOINT_DIRECTORY
    directory.mkdir()
    stale = directory / f".{checkpoint_filename(TASK_ID)}.orphan.tmp"
    stale.write_text("incomplete writer output")
    identity = _identity()

    assert prepare_module_checkpoints(tmp_path, {TASK_ID: identity}, resume=False) == {}

    (directory / "unexpected.json").write_text("{}")
    with pytest.raises(ModuleCheckpointError, match="unexpected entries"):
        prepare_module_checkpoints(tmp_path, {TASK_ID: identity}, resume=False)


def test_resume_archives_all_prior_owned_evidence(tmp_path):
    output_dir = tmp_path / "results"
    result_dir = output_dir / "Suite" / "Task"
    result_dir.mkdir(parents=True)
    owned = ("input", "agent", "grading", "continuations", "result.json")
    for name in owned:
        path = result_dir / name
        if name == "result.json":
            path.write_text("old result")
        else:
            path.mkdir()
            (path / "evidence.txt").write_text(name)
    (result_dir / "operator-note.txt").write_text("keep this unrelated evidence")

    runner._reset_benchmark_artifacts(
        str(output_dir),
        str(result_dir),
        resume_checkpoint_sequence=7,
    )

    history = result_dir / "resume-history" / "checkpoint-7"
    assert sorted(path.name for path in history.iterdir()) == sorted(owned)
    assert all(not (result_dir / name).exists() for name in owned)
    assert (result_dir / "operator-note.txt").read_text() == "keep this unrelated evidence"

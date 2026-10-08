"""Resume configuration recovery without model calls or output mutations."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from common.verification_budget import VerificationPolicy
from evaluator import runner


@pytest.fixture
def saved_run(tmp_path):
    task_id = "Suite/Task.tla"
    policy = runner._execution_policy_identity(
        SimpleNamespace(
            name="claude_code",
            approach="agentic",
            model="claude-opus-4-8",
            reasoning_effort="low",
            max_output_tokens=None,
        ),
        use_container=True,
        timeout=0,
        check_timeout=1200,
        infra_retries=5,
        max_continuations=2,
        session_dir=str(tmp_path / "sessions"),
        verification_policies={task_id: VerificationPolicy.create(1200, ("A", "B"), 4).as_dict()},
    )
    manifest = {"schema_version": 5, "mode": "proof-from-scratch", "execution_policy": policy}
    runner._write_run_manifest(str(tmp_path), manifest)
    runner._write_task_list_record(str(tmp_path), "proof-from-scratch", [task_id])
    return tmp_path, manifest


def _snapshot(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def _dry_run(monkeypatch, path, *options):
    task = str(path / "suite" / "Suite" / "Task.tla")
    mode = SimpleNamespace(
        name="proof-from-scratch",
        benchmark_dir=lambda: str(path / "suite"),
        get_benchmark_files=lambda: [task],
    )
    monkeypatch.setattr(runner, "get_mode", lambda *args: mode)
    setup = MagicMock(side_effect=AssertionError("unexpected backend or toolchain setup"))
    for name in ("get_backend", "ensure_image", "resolve_paths", "_run_preflight", "_native_verification_environment"):
        monkeypatch.setattr(runner, name, setup)
    parsed = []
    original = runner._parse_run_args

    def capture(parser):
        result = original(parser)
        parsed.append(result)
        return result

    monkeypatch.setattr(runner, "_parse_run_args", capture)
    monkeypatch.setattr(sys, "argv", ["tlaps-bench run", "--resume", "--output-dir", str(path), "--dry-run", *options])
    runner.main()
    setup.assert_not_called()
    return parsed[0]


def test_omitted_resume_options_and_exact_cohort_are_inherited(saved_run, monkeypatch, capsys):
    path, _manifest = saved_run
    before = _snapshot(path)
    monkeypatch.setattr(runner, "_collection_task_ids", lambda *args: pytest.fail("re-resolved a collection alias"))

    args, tasks = _dry_run(monkeypatch, path)

    assert tasks == ["Suite/Task.tla"]
    assert args.backend == "claude_code"
    assert args.model == "claude-opus-4-8"
    assert args.reasoning_effort == "low"
    assert args.timeout == 0
    assert args.check_timeout == 1200
    assert args.check_cpus == 4
    assert args.infra_retries == 5
    assert args.max_continuations == 2
    assert args.session_dir == str(path / "sessions")
    assert args.no_container is False
    assert args.keep_container is False
    assert args.jobs == 1
    assert "recorded cohort" in capsys.readouterr().out
    assert _snapshot(path) == before


@pytest.mark.parametrize(
    "options",
    [
        ["--backend", "codex"],
        ["--timeout", "28800"],
        ["--check-timeout", "600"],
        ["--check-cpus", "8"],
        ["--max-continuations", "0"],
        ["--infra-retries", "3"],
        ["--reasoning-effort=high"],
        ["--model", "different"],
        ["--no-container"],
        ["--mode", "proof-completion"],
        ["--session-dir", "different"],
        ["--max-output-tokens", "100"],
    ],
)
def test_explicit_conflicts_including_cli_defaults_reject_without_mutation(saved_run, monkeypatch, capsys, options):
    path, _manifest = saved_run
    before = _snapshot(path)
    with pytest.raises(SystemExit) as exc:
        _dry_run(monkeypatch, path, *options)
    assert exc.value.code == 2
    assert "cannot resume with" in capsys.readouterr().err
    assert _snapshot(path) == before


def test_explicit_matching_options_and_equivalent_session_path_are_accepted(saved_run, monkeypatch):
    path, _manifest = saved_run
    args, _tasks = _dry_run(
        monkeypatch,
        path,
        "--backend",
        "claude_code",
        "--timeout",
        "0",
        "--keep-container",
        "--session-dir",
        str(path / "sessions" / ".." / "sessions"),
    )
    assert args.timeout == 0
    assert args.keep_container is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("backend", "unknown"),
        ("timeout", True),
        ("check_timeout", 0),
        ("max_output_tokens", -1),
        ("environment", []),
        ("session", []),
        ("verification", {}),
    ],
)
def test_invalid_saved_options_fail_before_setup(saved_run, monkeypatch, capsys, field, value):
    path, manifest = saved_run
    manifest["execution_policy"][field] = value
    runner._write_run_manifest(str(path), manifest)
    before = _snapshot(path)
    with pytest.raises(SystemExit) as exc:
        _dry_run(monkeypatch, path)
    assert exc.value.code == 2
    assert "invalid recorded" in capsys.readouterr().err
    assert _snapshot(path) == before


def test_old_manifest_is_not_upgraded_silently(saved_run, monkeypatch, capsys):
    path, manifest = saved_run
    manifest["schema_version"] = 4
    runner._write_run_manifest(str(path), manifest)
    with pytest.raises(SystemExit) as exc:
        _dry_run(monkeypatch, path)
    assert exc.value.code == 2
    assert "unsupported recorded run-manifest.json schema" in capsys.readouterr().err


def test_task_list_only_recovers_only_what_was_recorded(tmp_path):
    runner._write_task_list_record(str(tmp_path), "proof-completion", ["Suite/A.tla"])
    assert runner._read_resume_options(str(tmp_path)) == ({"mode": "proof-completion"}, ["Suite/A.tla"])


def test_no_records_leave_existing_defaults_available(tmp_path):
    assert runner._read_resume_options(str(tmp_path)) == ({}, None)


def test_resume_requires_explicit_output_directory(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tlaps-bench run", "--resume"])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
    assert "--resume requires --output-dir" in capsys.readouterr().err


def test_nonobject_records_fail_cleanly(saved_run, monkeypatch, capsys):
    path, _manifest = saved_run
    (path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps([]))
    with pytest.raises(SystemExit) as exc:
        _dry_run(monkeypatch, path)
    assert exc.value.code == 2
    assert "expected an object" in capsys.readouterr().err

"""Exact task-list selection and resume cohort validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from evaluator import runner
from evaluator.modes import get_mode

REPO_ROOT = Path(__file__).resolve().parents[2]


class TaskMode:
    name = "proof-completion"
    description = "fixture"
    canonical_replay_required = False

    def __init__(self, suite, tasks):
        self._suite = suite
        self._tasks = tasks

    def benchmark_dir(self):
        return str(self._suite)

    def get_benchmark_files(self, filter_pattern=None):
        assert filter_pattern is None
        return [str(task) for task in self._tasks]

    def specification_ids(self):
        return None


def test_load_task_list_ignores_blank_lines_and_preserves_order(tmp_path):
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("Suite/B.tla\n\nSuite/A.tla\n", encoding="utf-8")

    assert runner._load_task_list(str(task_list)) == ["Suite/B.tla", "Suite/A.tla"]


def test_load_task_list_rejects_duplicate_ids(tmp_path):
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("Suite/A.tla\nSuite/A.tla\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate task ID.*Suite/A.tla"):
        runner._load_task_list(str(task_list))


def test_load_task_list_rejects_empty_file(tmp_path):
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="is empty"):
        runner._load_task_list(str(task_list))


def test_resolve_task_list_preserves_explicit_paths(tmp_path):
    mode = TaskMode(tmp_path / "proof-completion", [])
    explicit = str(tmp_path / "tasks.txt")

    assert runner._resolve_task_list(explicit, mode) == explicit


def test_core_name_resolves_for_proof_completion_only():
    proof_completion = get_mode("proof-completion", str(REPO_ROOT / "benchmark"), "/checker")
    proof_from_scratch = get_mode("proof-from-scratch", str(REPO_ROOT / "benchmark"), "/checker")

    resolved = runner._resolve_task_list("core", proof_completion)
    assert resolved == str(REPO_ROOT / "benchmark" / "proof-completion" / "core.txt")
    assert len(runner._load_task_list(resolved)) == 190
    with pytest.raises(ValueError, match="named task list 'core'.*proof-from-scratch"):
        runner._resolve_task_list("core", proof_from_scratch)


def test_select_exact_tasks_uses_mode_relative_ids_and_list_order(tmp_path):
    suite = tmp_path / "proof-completion"
    task_a = suite / "Suite" / "A.tla"
    task_b = suite / "Suite" / "A-longer.tla"
    task_a.parent.mkdir(parents=True)
    task_a.touch()
    task_b.touch()
    mode = TaskMode(suite, [task_a, task_b])

    assert runner._select_exact_tasks(mode, ["Suite/A-longer.tla", "Suite/A.tla"]) == [
        str(task_b),
        str(task_a),
    ]
    with pytest.raises(ValueError, match="unknown task ID.*Suite/A"):
        runner._select_exact_tasks(mode, ["Suite/A"])


@pytest.mark.parametrize("mode_name", ["proof-completion", "proof-from-scratch"])
def test_current_manifest_modes_support_exact_task_ids(mode_name):
    suite_name = "proof-from-scratch-module" if mode_name == "proof-from-scratch" else mode_name
    manifest = json.loads((REPO_ROOT / "benchmark" / suite_name / "manifest.json").read_text(encoding="utf-8"))
    task_id = (
        manifest["module_tasks"][0]["spec"]["task_id"] if mode_name == "proof-from-scratch" else sorted(manifest)[0]
    )
    mode = get_mode(mode_name, str(REPO_ROOT / "benchmark"), "/checker")

    assert runner._select_exact_tasks(mode, [task_id]) == [
        str((REPO_ROOT / "benchmark" / suite_name / task_id).resolve())
    ]


def test_resume_requires_the_same_recorded_task_cohort(tmp_path):
    tasks = ["Suite/B.tla", "Suite/A.tla"]
    runner._write_task_list_record(str(tmp_path), "proof-completion", tasks)

    runner._validate_resume_task_list(
        str(tmp_path),
        "proof-completion",
        ["Suite/A.tla", "Suite/B.tla"],
    )
    with pytest.raises(ValueError, match="different task list or mode"):
        runner._validate_resume_task_list(str(tmp_path), "proof-completion", ["Suite/A.tla"])
    with pytest.raises(ValueError, match="without --task-list"):
        runner._validate_resume_task_list(str(tmp_path), "proof-completion", None)


def test_task_list_resume_rejects_unscoped_results(tmp_path):
    (tmp_path / "results.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="results.json but no task-list.json"):
        runner._validate_resume_task_list(str(tmp_path), "proof-completion", ["Suite/A.tla"])


def test_task_list_mismatch_fails_before_auth_or_preflight(tmp_path, monkeypatch, capsys):
    suite = tmp_path / "proof-completion"
    task = suite / "Suite" / "A.tla"
    task.parent.mkdir(parents=True)
    task.touch()
    task_list = tmp_path / "tasks.txt"
    task_list.write_text("Suite/A.tla\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / runner.TASK_LIST_RECORD).write_text(
        json.dumps({"mode": "proof-completion", "tasks": ["Suite/B.tla"]}),
        encoding="utf-8",
    )

    backend = MagicMock()
    mode = TaskMode(suite, [task])
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args: mode)
    ensure_image = MagicMock()
    preflight = MagicMock()
    monkeypatch.setattr(runner, "ensure_image", ensure_image)
    monkeypatch.setattr(runner, "_run_preflight", preflight)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tlaps-bench run",
            "--task-list",
            str(task_list),
            "--output-dir",
            str(output_dir),
            "--resume",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 2
    assert "different task list or mode" in capsys.readouterr().err
    backend.check_auth.assert_not_called()
    ensure_image.assert_not_called()
    preflight.assert_not_called()


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("Suite/Unknown.tla\n", "unknown task ID"),
        ("Suite/A.tla\nSuite/A.tla\n", "duplicate task ID"),
    ],
)
def test_invalid_task_list_fails_before_auth_or_preflight(tmp_path, monkeypatch, capsys, contents, message):
    suite = tmp_path / "proof-completion"
    task = suite / "Suite" / "A.tla"
    task.parent.mkdir(parents=True)
    task.touch()
    task_list = tmp_path / "tasks.txt"
    task_list.write_text(contents, encoding="utf-8")

    backend = MagicMock()
    mode = TaskMode(suite, [task])
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args: mode)
    ensure_image = MagicMock()
    preflight = MagicMock()
    monkeypatch.setattr(runner, "ensure_image", ensure_image)
    monkeypatch.setattr(runner, "_run_preflight", preflight)
    monkeypatch.setattr(sys, "argv", ["tlaps-bench run", "--task-list", str(task_list)])

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 2
    assert message in capsys.readouterr().err
    backend.check_auth.assert_not_called()
    ensure_image.assert_not_called()
    preflight.assert_not_called()


def test_empty_task_list_argument_fails_before_full_discovery_or_backend_setup(monkeypatch, capsys):
    backend = MagicMock()
    mode = MagicMock()
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args: mode)
    ensure_image = MagicMock()
    preflight = MagicMock()
    monkeypatch.setattr(runner, "ensure_image", ensure_image)
    monkeypatch.setattr(runner, "_run_preflight", preflight)
    monkeypatch.setattr(sys, "argv", ["tlaps-bench run", "--task-list", ""])

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 2
    assert "--task-list requires a non-empty name or path" in capsys.readouterr().err
    mode.get_benchmark_files.assert_not_called()
    backend.check_auth.assert_not_called()
    ensure_image.assert_not_called()
    preflight.assert_not_called()


def test_filter_and_task_list_are_mutually_exclusive(tmp_path, monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(
        sys,
        "argv",
        ["tlaps-bench run", "--filter", "Suite", "--task-list", str(tmp_path / "tasks.txt")],
    )

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 2
    backend.check_auth.assert_not_called()

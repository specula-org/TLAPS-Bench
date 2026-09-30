"""PFS collections, default CLI scope, and previews without model/tool setup."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from evaluator import runner
from evaluator.modes import get_mode
from evaluator.problem_sets import load_problem_sets
from tlaps_bench import cli

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "benchmark" / "problem-sets.json"
CURRENT = {
    "tlaplus_examples_FlashProtocol/FlashWithMutex.tla": 15,
    "ZooKeeper/Zab.tla": 9,
    "CahillSSI/CahillSerializability.tla": 1,
    "ivy_examples_tlb/ivy_examples_tlb.tla": 2,
    "OpenAddressing/OpenAddressing.tla": 5,
    "etcd_raft/etcd_raft.tla": 8,
    "HashicorpRaft/HashicorpRaft.tla": 6,
    "ZooKeeper_LowLevel/ZkV3_7_0.tla": 9,
    "MongoDB/MultiShardTxnSnapshot.tla": 1,
}


@pytest.fixture(scope="module")
def pfs_mode():
    return get_mode("proof-from-scratch", str(ROOT / "benchmark"), "/checker")


@pytest.fixture
def preview_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("selection or dry-run reached backend/tool setup")

    for name in ("get_backend", "ensure_image", "ensure_tlapm", "_native_verification_environment", "cpu_command"):
        monkeypatch.setattr(runner, name, forbidden)


def _selected(output):
    return [line.strip().split(" (")[0] for line in output.splitlines() if line.startswith("  ")]


@pytest.mark.parametrize("extra", [[], ["--mode", "proof-from-scratch"], ["--task-list", "current"]])
def test_default_and_explicit_current_are_the_nine_official_modules(extra, preview_only, tmp_path, capsys):
    output = tmp_path / "no-artifacts"
    assert cli.main(["run", *extra, "--dry-run", "--output-dir", str(output)]) == 0
    printed = capsys.readouterr().out
    assert set(_selected(printed)) == set(CURRENT)
    assert "9 specifications, 56 proof units" in printed
    assert not output.exists()


def test_current_has_exact_proof_unit_counts(pfs_mode):
    actual = {
        task: len(pfs_mode.module_task_spec(str(Path(pfs_mode.benchmark_dir()) / task)).proof_unit_ids)
        for task in runner._collection_task_ids(pfs_mode, "current")
    }
    assert actual == CURRENT


def test_collections_cover_every_task_exactly_once(pfs_mode):
    known_tasks = set(pfs_mode.specification_ids())
    collections = load_problem_sets(CATALOG, known_tasks)
    membership = Counter(task for collection in collections.values() for task in collection.tasks)

    assert set(membership) == known_tasks
    assert all(count == 1 for count in membership.values())


def test_readme_current_matches_collection_and_retired_showcases_a_subset(pfs_mode):
    tasks = {e.spec.task_id: len(e.spec.proof_units) for e in pfs_mode._manifest.entries}
    collections = load_problem_sets(CATALOG, tasks)
    readme = (ROOT / "README.md").read_text()
    for name, heading in (
        ("current", "Current Problem Set"),
        ("retired", "Retired Problems (Proofs Available)"),
    ):
        section = readme.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
        members = set()
        for row in section.splitlines():
            links = re.findall(r"/(blob|tree)/main/benchmark/proof-from-scratch-module/([^\s)]+)", row)
            if not links:
                continue
            row_members = set()
            for kind, path in links:
                matched = {task for task in tasks if task == path or (kind == "tree" and task.startswith(path + "/"))}
                assert matched, path
                row_members.update(matched)
            counts = [int(value.strip()) for value in row.split("|")[-3:-1]]
            assert counts == [len(row_members), sum(tasks[task] for task in row_members)]
            members.update(row_members)
        if name == "current":
            assert members == set(collections[name].tasks)
        else:
            assert members
            assert members <= set(collections[name].tasks)
    assert collections["next"].tasks == ("PirateShip/PirateShipProof.tla",)
    assert collections["next"].pending == (("Wildfire", "https://github.com/specula-org/TLAPS-Bench/pull/164"),)


@pytest.mark.parametrize(
    "task", ["tlaplus_examples_tcp/tcp_proof.tla", "Walgit/WalgitProof.tla", "Euclid/Euclid-Hyperbook/GCD.tla"]
)
def test_filter_searches_tasks_outside_current(task, preview_only, capsys):
    assert cli.main(["run", "--filter", task, "--dry-run"]) == 0
    assert _selected(capsys.readouterr().out) == [task]


def test_custom_task_list_can_select_retired_tasks(preview_only, tmp_path, capsys):
    task = "Walgit/WalgitProof.tla"
    path = tmp_path / "tasks.txt"
    path.write_text(task + "\n")
    assert cli.main(["run", "--task-list", str(path), "--dry-run"]) == 0
    assert _selected(capsys.readouterr().out) == [task]


def test_retired_contains_every_task_outside_current_and_next(pfs_mode, preview_only, capsys):
    assert cli.main(["run", "--task-list", "retired", "--dry-run"]) == 0
    output = capsys.readouterr().out
    tasks = set(_selected(output))
    collections = load_problem_sets(CATALOG, pfs_mode.specification_ids())
    expected = set(pfs_mode.specification_ids()) - set(CURRENT) - set(collections["next"].tasks)
    assert tasks == expected
    assert "tlaplus_examples_btree/btree.tla" in tasks
    assert not tasks.intersection(CURRENT)
    assert "libomp/libomp.tla" in tasks
    assert "Walgit/WalgitProof.tla" in tasks


@pytest.mark.parametrize("collection", ["current", "retired", "next"])
def test_pfs_collection_names_are_unavailable_in_proof_completion(collection, preview_only, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--mode", "proof-completion", "--task-list", collection])
    assert exc.value.code == 2
    assert "only available for mode 'proof-from-scratch'" in capsys.readouterr().err


@pytest.mark.parametrize("dry_run", [[], ["--dry-run"]])
def test_next_reports_pending_wildfire_before_backend_setup(dry_run, preview_only, capsys, monkeypatch):
    original = runner.load_problem_sets

    def pending_only(*args):
        collections = original(*args)
        next_set = collections["next"]
        collections["next"] = type(next_set)((), next_set.pending)
        return collections

    monkeypatch.setattr(runner, "load_problem_sets", pending_only)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--task-list", "next", *dry_run])
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "has no runnable tasks" in error
    assert "pending merge: Wildfire (https://github.com/specula-org/TLAPS-Bench/pull/164)" in error


def test_next_selects_pirateship_without_backend_setup(preview_only, capsys):
    assert cli.main(["run", "--task-list", "next", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert _selected(printed) == ["PirateShip/PirateShipProof.tla"]
    assert "1 specifications, 11 proof units" in printed


@pytest.mark.parametrize("extra,count", [([], 706), (["--task-list", "core"], 190)])
def test_proof_completion_preserves_full_and_core(preview_only, capsys, extra, count):
    assert cli.main(["run", "--mode", "proof-completion", *extra, "--dry-run"]) == 0
    assert len(_selected(capsys.readouterr().out)) == count


@pytest.mark.parametrize("pattern", ["", " ", ", ,", "not-a-real-task"])
def test_invalid_filter_never_falls_back_to_a_collection(pattern, preview_only, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--filter", pattern])
    assert exc.value.code == 2
    assert "--filter" in capsys.readouterr().err


def test_default_selection_is_recorded_and_compared_on_resume(pfs_mode, preview_only, tmp_path, capsys):
    runner._write_task_list_record(str(tmp_path), "proof-from-scratch", list(CURRENT))
    arguments = ["run", "--resume", "--output-dir", str(tmp_path), "--dry-run"]
    assert cli.main(arguments) == 0
    # An old full-suite run must not silently resume as Current.
    old = list(CURRENT) + ["Walgit/WalgitProof.tla"]
    runner._write_task_list_record(str(tmp_path), "proof-from-scratch", old)
    with pytest.raises(SystemExit) as exc:
        cli.main(arguments)
    assert exc.value.code == 2
    assert "different task list or mode" in capsys.readouterr().err
    assert json.loads((tmp_path / runner.TASK_LIST_RECORD).read_text())["tasks"] == sorted(old)


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda data: data["current"]["tasks"].append("Missing/Task.tla"), "unknown task ID"),
        (lambda data: data["current"]["tasks"].append(data["current"]["tasks"][0]), "duplicate task ID"),
        (lambda data: data["retired"]["tasks"].append(data["current"]["tasks"][0]), "duplicate task ID"),
        (lambda data: data["retired"]["tasks"].pop(), "unclassified task ID"),
        (lambda data: data.update(format_version=2), "format_version"),
        (lambda data: data.update(current={"tasks": "not-a-list"}), "list of task IDs"),
        (lambda data: data.update(next={"tasks": [], "pending": [{"name": "Wildfire"}]}), "invalid pending"),
        (lambda data: data.pop("retired"), "format_version"),
    ],
)
def test_invalid_catalog_is_rejected(pfs_mode, tmp_path, change, error):
    data = json.loads(CATALOG.read_text())
    change(data)
    path = tmp_path / "problem-sets.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=error):
        load_problem_sets(path, pfs_mode.specification_ids())


@pytest.mark.parametrize("contents", [None, "not json", '{"current": {}, "current": {}}'])
def test_missing_or_malformed_catalog_fails_before_backend_setup(
    contents, pfs_mode, preview_only, tmp_path, monkeypatch
):
    # Keep real manifest discovery but direct only the classification path to a fixture.
    mode = get_mode("proof-from-scratch", str(ROOT / "benchmark"), "/checker")
    mode.__dict__["_manifest"] = pfs_mode._manifest
    monkeypatch.setattr(mode, "benchmark_dir", lambda: str(tmp_path / "proof-from-scratch-module"))
    monkeypatch.setattr(runner, "get_mode", lambda *args: mode)
    if contents is not None:
        (tmp_path / "problem-sets.json").write_text(contents)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run"])
    assert exc.value.code == 2


def test_empty_current_fails_without_full_suite_fallback(pfs_mode, preview_only, monkeypatch, capsys):
    original = runner.load_problem_sets

    def empty_current(*args):
        collections = original(*args)
        collections["current"] = type(collections["current"])(())
        return collections

    monkeypatch.setattr(runner, "load_problem_sets", empty_current)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run"])
    assert exc.value.code == 2
    assert "'current' has no runnable tasks" in capsys.readouterr().err

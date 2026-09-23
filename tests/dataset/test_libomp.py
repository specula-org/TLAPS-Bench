"""The libomp tasks retain real work and reject broken completion protocols."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmark/proof-from-scratch-module"
SOURCE = ROOT / "source/libomp/libomp.tla"
TARGETS = (
    "ActiveTasksImplyActiveTeam",
    "NoQueuedTasksAfterDeactivation",
    "ParityConsistency",
    "ParityRestoredAfterCancel",
)


def stage(directory):
    jar = ROOT / "lib/tla2tools.jar"
    if not jar.is_file() or not shutil.which("java"):
        pytest.skip("Java and the pinned tla2tools.jar are required")
    manifest = json.loads((SUITE / "manifest.json").read_text())
    entry = next(e for e in manifest["module_tasks"] if e["spec"]["task_id"] == "libomp/libomp.tla")
    for rel in [entry["spec"]["task_id"], *entry["context"]]:
        shutil.copyfile(SUITE / rel, directory / Path(rel).name)


def config(threads=2, tasks=1, rounds=2, targets=TARGETS):
    return (
        "SPECIFICATION Spec\nCONSTANTS\n Thread = {"
        + ", ".join(str(i) for i in range(threads))
        + "}\n Task = {"
        + ", ".join(f"T{i}" for i in range(tasks))
        + f"}}\n MaxBarriers = {rounds}\n Nil = Nil\n"
        + "INVARIANTS "
        + " ".join(targets)
        + "\nCHECK_DEADLOCK FALSE\n"
    )


def run_tlc(directory, cfg, module="libomp"):
    (directory / f"{module}.cfg").write_text(cfg)
    output = directory / "output"
    output.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-Xmx2g",
            "-cp",
            str(ROOT / "lib/tla2tools.jar"),
            "tlc2.TLC",
            "-workers",
            "1",
            "-metadir",
            str(output / "states"),
            "-config",
            f"{module}.cfg",
            f"{module}.tla",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=180,
    )
    text = result.stdout + result.stderr
    (output / "tlc.log").write_text(text)
    return result.returncode, text


def modify_action(path, name, update):
    text = path.read_text()
    starts = list(re.finditer(r"(?m)^([A-Za-z_][A-Za-z_0-9]*)(?:\([^\n]*\))?\s*==", text))
    index = next(i for i, m in enumerate(starts) if m[1] == name)
    start = starts[index].start()
    end = starts[index + 1].start()
    old = text[start:end]
    new = update(old)
    assert old != new
    path.write_text(text[:start] + new + text[end:])


@pytest.mark.parametrize("threads,tasks,rounds", [(2, 1, 2), (2, 2, 1), (3, 1, 1)])
def test_all_four_goals_on_complete_small_instances(tmp_path, threads, tasks, rounds):
    stage(tmp_path)
    code, text = run_tlc(tmp_path, config(threads, tasks, rounds))
    assert code == 0, text
    assert "Model checking completed. No error has been found." in text, text
    assert "0 states left on queue" in text, text


def test_enqueue_before_activation_is_valid(tmp_path):
    stage(tmp_path)
    (tmp_path / "EnqueueBeforeActivation.tla").write_text(
        "---- MODULE EnqueueBeforeActivation ----\nEXTENDS libompDefs\n"
        "VARIABLE step\nAuditVars == <<allVars, step>>\n"
        "AuditInit == Init /\\ step = 0\n"
        "AuditNext == /\\ step = 0 /\\ ScheduleTask(Primary) /\\ step' = 1\n"
        "AuditSpec == AuditInit /\\ [][AuditNext]_AuditVars\n====\n"
    )
    code, text = run_tlc(
        tmp_path, config().replace("SPECIFICATION Spec", "SPECIFICATION AuditSpec"), "EnqueueBeforeActivation"
    )
    assert code == 0, text
    assert "2 distinct states found" in text, text


def test_proxy_serial_and_cancel_paths_reach_completion(tmp_path):
    stage(tmp_path)
    fixture = ROOT / "tests/fixtures/libomp/LibompLifecycle.tla"
    shutil.copyfile(fixture, tmp_path / fixture.name)
    cfg = config(tasks=2).replace("SPECIFICATION Spec", "SPECIFICATION TraceSpec")
    cfg = cfg.replace("Task = {T0, T1}", "Task = {A, B}\n A = A\n B = B")
    cfg += "INVARIANT CompletedLifecycle\n"
    code, text = run_tlc(tmp_path, cfg, "LibompLifecycle")
    assert code == 0, text
    assert "31 distinct states found" in text, text


@pytest.mark.parametrize("bad_threads,bad_rounds", [("{1, 2}", "1"), ("{0, 1}", "-1")])
def test_invalid_execution_domains_are_rejected(tmp_path, bad_threads, bad_rounds):
    stage(tmp_path)
    cfg = config(rounds=1).replace("Thread = {0, 1}", f"Thread = {bad_threads}")
    if bad_rounds == "-1":
        (tmp_path / "InvalidDomain.tla").write_text(
            "---- MODULE InvalidDomain ----\nEXTENDS libompDefs\nBadRound == -1\n====\n"
        )
        cfg = cfg.replace("MaxBarriers = 1", "MaxBarriers <- BadRound")
        code, text = run_tlc(tmp_path, cfg, "InvalidDomain")
    else:
        code, text = run_tlc(tmp_path, cfg)
    assert code == 10, text
    assert "Assumption" in text and "is false" in text, text
    assert "Computing initial states" not in text, text


def test_missing_pending_work_check_reproduces_orphaned_queue(tmp_path):
    stage(tmp_path)
    modify_action(
        tmp_path / "libompRuntime.tla",
        "ThreadFinishTasksWeak",
        lambda s: s.replace("    /\\ pendingTasks[t] = {}\n", ""),
    )
    code, text = run_tlc(tmp_path, config(rounds=1, targets=("NoQueuedTasksAfterDeactivation",)))
    assert code == 12, text
    assert "Invariant NoQueuedTasksAfterDeactivation is violated" in text, text


def test_releasing_proxy_credit_too_early_reproduces_orphaned_cleanup(tmp_path):
    stage(tmp_path)

    def early_credit(text):
        text = text.replace(
            "taskRoot, pendingTasks, serialOwner, taskTeamRetired", "taskRoot, serialOwner, taskTeamRetired"
        )
        return text + "    /\\ pendingTasks' = [pendingTasks EXCEPT ![taskRoot[task]] = @ \\ {task}]\n\n"

    modify_action(tmp_path / "libompRuntime.tla", "FulfillEvent", early_credit)
    code, text = run_tlc(tmp_path, config(rounds=1, targets=("NoQueuedTasksAfterDeactivation",)))
    assert code == 12, text
    assert "Invariant NoQueuedTasksAfterDeactivation is violated" in text, text


def test_premature_deactivation_violates_executing_task_lifetime(tmp_path):
    stage(tmp_path)
    modify_action(
        tmp_path / "libompRuntime.tla",
        "PrimaryTaskTeamWait",
        lambda s: s.replace("          /\\ unfinished[slot] = 0\n", "          /\\ TRUE\n"),
    )
    code, text = run_tlc(tmp_path, config(rounds=1, targets=("ActiveTasksImplyActiveTeam",)))
    assert code == 12, text
    assert "Invariant ActiveTasksImplyActiveTeam is violated" in text, text


def test_wrong_serial_restore_violates_parallel_parity(tmp_path):
    stage(tmp_path)
    modify_action(
        tmp_path / "libompRuntime.tla", "SerializedParallelExit", lambda s: s.replace("![t] = savedSlot[t]", "![t] = 0")
    )
    code, text = run_tlc(tmp_path, config(targets=("ParityConsistency",)))
    assert code == 12, text
    assert "Invariant ParityConsistency is violated" in text, text


def test_cancelled_worker_must_not_toggle_parity(tmp_path):
    stage(tmp_path)

    def wrong_toggle(text):
        text = text.replace("parityVars,", "taskTeamActive, unfinished,")
        return text + "    /\\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = 1 - @]\n\n"

    modify_action(tmp_path / "libompRuntime.tla", "WorkerCancelledBarrier", wrong_toggle)
    code, text = run_tlc(tmp_path, config(rounds=1, targets=("ParityRestoredAfterCancel",)))
    assert code == 12, text
    assert "Invariant ParityRestoredAfterCancel is violated" in text, text


def test_module_has_exactly_the_four_selected_goals():
    manifest = json.loads((SUITE / "manifest.json").read_text())
    entry = next(e for e in manifest["module_tasks"] if e["spec"]["task_id"] == "libomp/libomp.tla")
    assert entry["spec"]["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    expected = {f"libomp/libomp_{name}Correct.tla" for name in TARGETS}
    assert {u["task_id"] for u in entry["spec"]["proof_units"]} == expected
    task = (SUITE / entry["spec"]["task_id"]).read_text()
    assert task.count("PROOF OMITTED") == 4
    for name in TARGETS:
        assert f"THEOREM {name}Correct == Spec => []{name}" in task


def test_complete_reference_proof_dependency_chain(tmp_path):
    prover = find_tlapm()
    if prover is None or not (ROOT / "lib/tlapm").is_dir():
        pytest.skip("The pinned TLAPS prover and proof libraries are required")
    reference = ROOT / "tests/fixtures/libomp/reference"
    receipt = json.loads((reference / "manifest.json").read_text())
    runtime = ROOT / "source/libomp/libompRuntime.tla"
    assert hashlib.sha256(runtime.read_bytes()).hexdigest() == receipt["runtime_sha256"]
    shutil.copyfile(runtime, tmp_path / runtime.name)
    for source in reference.glob("*.tla"):
        assert "PROOF OMITTED" not in source.read_text()
        shutil.copyfile(source, tmp_path / source.name)
    results = []
    for module in receipt["check_order"]:
        result = subprocess.run(
            [
                prover,
                "--strict",
                "--nofp",
                "--threads",
                "2",
                "-I",
                str(ROOT / "lib/tlapm"),
                "-I",
                str(ROOT / "lib/community"),
                f"{module}.tla",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        text = result.stdout + result.stderr
        (tmp_path / f"{module}.log").write_text(text)
        assert result.returncode == 0, f"{module}:\n{text}"
        match = re.search(r"All (\d+) obligations proved", text)
        assert match, text
        results.append({"module": module, "obligations": int(match[1])})
    (tmp_path / "verification.json").write_text(json.dumps(results, indent=2))

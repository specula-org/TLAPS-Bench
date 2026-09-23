"""Reachable Sailfish traces distinguish valid certificates from task defects."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MODEL = REPO / "benchmark/proof-from-scratch-module/tlaplus_examples_dag-consensus"
FIXTURES = REPO / "tests/fixtures/sailfish"

CONSTANTS = """CONSTANTS
 a = a b = b c = c d = d e = e
 N <- MCN
 F <- MCF
 R <- MCR
 IsQuorum <- MCIsQuorum
 IsBlocking <- MCIsBlocking
 Leader <- MCLeader
 GST <- MCGST
"""


def stage(tmp_path):
    jar = REPO / "lib/tla2tools.jar"
    if not jar.is_file() or not shutil.which("java"):
        pytest.skip("TLC and the pinned tla2tools.jar are required")
    for p in MODEL.glob("*.tla"):
        shutil.copyfile(p, tmp_path / p.name)
    for p in (MODEL / "Sailfish").glob("*.tla"):
        shutil.copyfile(p, tmp_path / p.name)
    for p in FIXTURES.glob("*.tla"):
        shutil.copyfile(p, tmp_path / p.name)
    return jar


def run_tlc(tmp_path, module, config):
    jar = stage(tmp_path) if not (tmp_path / "SailfishModel.tla").exists() else REPO / "lib/tla2tools.jar"
    (tmp_path / (module + ".cfg")).write_text(config)
    output = tmp_path / "spec/output"
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-Xmx2g",
            "-cp",
            str(jar),
            "tlc2.TLC",
            "-workers",
            "1",
            "-metadir",
            str(output / "states"),
            "-config",
            module + ".cfg",
            module + ".tla",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = result.stdout + result.stderr
    (output / "tlc.log").write_text(text)
    return result.returncode, text


def replay_config(*, live=False, good=False, monotone=True):
    return CONSTANTS + (
        f"LiveCase = {str(live).upper()}\nGoodLeader = {str(good).upper()}\n"
        f"Monotone = {str(monotone).upper()}\n"
        "SPECIFICATION ReplaySpec\nCHECK_DEADLOCK FALSE\n"
        "INVARIANTS TypeOK Agreement Liveness EndpointHasFirstLeader\n"
    )


def without_assumption(text):
    return re.sub(r"ASSUME QuorumsAreMonotone ==.*?\n\n", "", text, count=1, flags=re.S)


def test_invalid_byzantine_leader_is_rejected(tmp_path):
    code, out = run_tlc(tmp_path, "SailfishReplay", replay_config())
    assert code == 0, out
    assert "10 distinct states found" in out, out
    assert "No error has been found" in out, out


def test_missing_leader_validation_reproduces_agreement_failure(tmp_path):
    stage(tmp_path)
    p = tmp_path / "SailfishModel.tla"
    text = p.read_text()
    first = text.index("byzantineNode(self)")
    branch = text[first:]
    start = branch.index("                                              /\\ IF Leader(r) = self")
    end = branch.index("                                              /\\ vs'", start)
    p.write_text(text[:first] + branch[:start] + branch[end:])
    code, out = run_tlc(tmp_path, "SailfishReplay", replay_config())
    assert code == 12, out
    assert "Invariant Agreement is violated" in out, out


@pytest.mark.parametrize("live,good,states", [(False, True, 17), (True, False, 12)])
def test_repaired_schedules_reach_normal_commits(tmp_path, live, good, states):
    code, out = run_tlc(tmp_path, "SailfishReplay", replay_config(live=live, good=good))
    assert code == 0, out
    assert f"{states} distinct states found" in out, out
    assert "No error has been found" in out, out


def test_nonmonotone_quorums_rejected_before_initialization(tmp_path):
    code, out = run_tlc(tmp_path, "SailfishReplay", replay_config(live=True, monotone=False))
    assert code == 10, out
    assert "Assumption" in out and "is false" in out, out
    assert "Computing initial states" not in out, out


def test_missing_monotonicity_reproduces_liveness_failure(tmp_path):
    stage(tmp_path)
    p = tmp_path / "SailfishModel.tla"
    original = p.read_text()
    fixed = without_assumption(original)
    assert fixed != original
    p.write_text(fixed)
    code, out = run_tlc(tmp_path, "SailfishReplay", replay_config(live=True, monotone=False))
    assert code == 12, out
    assert "Invariant Liveness is violated" in out, out


@pytest.mark.parametrize("has_certificate,states", [(True, 7), (False, 5)])
def test_byzantine_leader_can_use_a_real_no_vote_certificate(tmp_path, has_certificate, states):
    config = replay_config().replace(" EndpointHasFirstLeader", "").replace("GST <- MCGST", "GST <- PreGST")
    config += f"CONSTANT HasCertificate = {str(has_certificate).upper()}\nSchedule <- CertificateSchedule\n"
    code, out = run_tlc(tmp_path, "SailfishNoVote", config)
    assert code == 0, out
    assert f"{states} distinct states found" in out, out


def test_linearization_preserves_causal_histories_and_genesis(tmp_path):
    config = CONSTANTS.replace(" c = c d = d e = e", "")
    config += "INIT InitCheck\nNEXT NextCheck\nINVARIANTS GenesisIsEmpty SamePositiveHistories ExpectedOrder\nCHECK_DEADLOCK FALSE\n"
    code, out = run_tlc(tmp_path, "SailfishLinearizeCheck", config)
    assert code == 0, out
    assert "No error has been found" in out, out


def test_task_statements_are_unchanged():
    manifest = json.loads((MODEL.parent / "manifest.json").read_text())
    entry = next(
        x for x in manifest["module_tasks"] if x["spec"]["task_id"] == "tlaplus_examples_dag-consensus/Sailfish.tla"
    )
    assert len(entry["spec"]["proof_units"]) == 3
    task = (MODEL / "Sailfish.tla").read_text()
    for name in ("TypeOK", "Agreement", "Liveness"):
        assert f"THEOREM {name}Correct == Spec => []{name}" in task
    assert task.count("PROOF OMITTED") == 3

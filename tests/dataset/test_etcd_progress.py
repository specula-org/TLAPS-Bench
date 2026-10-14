"""Reachable freshness witnesses and non-vacuous commit-progress checks."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "lib"
CONSTANTS = """
CONSTANTS
  Server = {1,2,3}
  InitServer = {1,2,3}
  ValueEntry = ValueEntry
  ConfigEntry = ConfigEntry
  Follower = Follower
  Candidate = Candidate
  Leader = Leader
  Nil = Nil
  RequestVoteRequest = RequestVoteRequest
  RequestVoteResponse = RequestVoteResponse
  AppendEntriesRequest = AppendEntriesRequest
  AppendEntriesResponse = AppendEntriesResponse
CHECK_DEADLOCK FALSE
"""


def stage(tmp_path, fixture, layout="module"):
    if not shutil.which("java") or not (LIB / "tla2tools.jar").is_file():
        pytest.skip("TLC dependencies are not installed")
    text = (REPO / "tests/fixtures/etcd_raft" / f"{fixture}.tla").read_text()
    if layout == "source":
        model = tmp_path / "etcd_raft.tla"
        shutil.copyfile(REPO / "source/etcd_raft/etcd_raft.tla", model)
        text = text.replace("EXTENDS etcd_raftDefs", "EXTENDS etcd_raft")
    else:
        context = (
            REPO
            / "benchmark"
            / ("proof-from-scratch-module" if layout == "module" else "proof-from-scratch")
            / "etcd_raft"
        )
        model = tmp_path / "etcd_raftModel.tla"
        shutil.copyfile(context / model.name, model)
        defs = "etcd_raftDefs" if layout == "module" else "etcd_raft_MoreUpToDateDefs"
        shutil.copyfile(context / f"{defs}.tla", tmp_path / f"{defs}.tla")
        text = text.replace("EXTENDS etcd_raftDefs", f"EXTENDS {defs}")
    (tmp_path / f"{fixture}.tla").write_text(text)
    return model


def check(tmp_path, fixture, config):
    (tmp_path / f"{fixture}.cfg").write_text(config)
    cp = os.pathsep.join(str(LIB / n) for n in ["tla2tools.jar", "community", "tlapm"])
    result = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-Xmx1g",
            "-cp",
            cp,
            "tlc2.TLC",
            "-workers",
            "1",
            "-config",
            f"{fixture}.cfg",
            f"{fixture}.tla",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    output = result.stdout + result.stderr
    (tmp_path / "check.log").write_text(output)
    return result.returncode, output


@pytest.mark.parametrize("layout", ["source", "flat", "module"])
@pytest.mark.parametrize("case", ["fixed", "old", "fault"])
def test_quorum_freshness(tmp_path, layout, case):
    model = stage(tmp_path, "LogFreshness", layout)
    if case == "fault":
        text = model.read_text()
        guard = "                 /\\ logOk\n"
        assert text.count(guard) == 1
        model.write_text(text.replace(guard, "                 /\\ TRUE\n"))
    invariant = "PointwiseFreshness" if case == "old" else "MoreUpToDateCorrectInv"
    config = CONSTANTS.replace("{1,2,3}", "{a,b,c,d,e}")
    config += "\nCONSTANTS a=a b=b c=c d=d e=e\n"
    config += f"FaultyElection = {str(case == 'fault').upper()}\n"
    config += f"SPECIFICATION TraceSpec\nINVARIANTS {invariant} LateCommitWitness\nPROPERTY Spec\nPROPERTY EventuallyCompletes\n"
    code, output = check(tmp_path, "LogFreshness", config)
    assert code == (0 if case == "fixed" else 12), output
    if case != "fixed":
        assert f"Invariant {invariant} is violated" in output
    else:
        assert "71 distinct states found" in output


@pytest.mark.parametrize("entry", [1, 2])
@pytest.mark.parametrize("case", ["progress", "witness", "unfair", "fault"])
def test_commit_progress(tmp_path, entry, case):
    stage(tmp_path, "CommitProgress")
    defs = tmp_path / "etcd_raftDefs.tla"
    model = tmp_path / "etcd_raftModel.tla"
    if case == "unfair":
        text = defs.read_text()
        fair = "    /\\ WF_vars(AdvanceCommitIndex(l) /\\ RecordEvents)\n"
        assert fair in text
        defs.write_text(text.replace(fair, ""))
    elif case == "fault":
        text = model.read_text()
        commit = "        /\\ CommitTo(i, newCommitIndex)"
        assert commit in text
        model.write_text(text.replace(commit, "        /\\ UNCHANGED commitIndex"))
    spec = "WitnessSpec" if case == "witness" else "TestSpec"
    props = "WitnessAssumptions WitnessCompletes" if case == "witness" else "ProgressClaim NonVacuous"
    config = CONSTANTS + f"\nCONSTANT EntryIndex = {entry}\nSPECIFICATION {spec}\nPROPERTY Spec\nPROPERTY {props}\n"
    code, output = check(tmp_path, "CommitProgress", config)
    assert code == (13 if case in {"unfair", "fault"} else 0), output
    assert ("Temporal property ProgressClaim was violated" in output) == (case in {"unfair", "fault"})

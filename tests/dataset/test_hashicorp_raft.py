"""Reachable scenarios and fault controls for the HashiCorp Raft tasks."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmark/proof-from-scratch-module"
RUNTIME = ROOT / "source/HashicorpRaft/HashicorpRaftRuntime.tla"
SOURCE = ROOT / "source/HashicorpRaft/HashicorpRaft.tla"
FIXTURES = ROOT / "tests/fixtures/hashicorp_raft"
GOALS = (
    "LeaderCompleteness",
    "StateMachineSafety",
    "CommittedEntriesPreserved",
    "LogMatching",
    "ElectionSafety",
    "ConfigurationSafety",
)

CONFIG = """\
SPECIFICATION TraceSpec
CONSTANTS
 Server = {A, B, C}
 Values = {V, W}
 A = A
 B = B
 C = C
 V = V
 W = W
 Nil = Nil
 Follower = Follower
 Candidate = Candidate
 Leader = Leader
 ValueEntry = ValueEntry
 ConfigEntry = ConfigEntry
 RequestVoteRequest = RequestVoteRequest
 RequestVoteResponse = RequestVoteResponse
 AppendEntriesRequest = AppendEntriesRequest
 AppendEntriesResponse = AppendEntriesResponse
 Scenario = {scenario}
CHECK_DEADLOCK FALSE
INVARIANTS {invariants}
PROPERTY Spec
"""


def stage(path, layout="source"):
    if not (ROOT / "lib/tla2tools.jar").is_file() or not shutil.which("java"):
        pytest.skip("Java and the pinned tla2tools.jar are required")
    if layout == "source":
        shutil.copyfile(RUNTIME, path / RUNTIME.name)
    else:
        manifest = json.loads((SUITE / "manifest.json").read_text())
        task = next(t for t in manifest["module_tasks"] if t["spec"]["task_id"] == "HashicorpRaft/HashicorpRaft.tla")
        for rel in [task["spec"]["task_id"], *task["context"]]:
            shutil.copyfile(SUITE / rel, path / Path(rel).name)
    shutil.copyfile(FIXTURES / "HashicorpRaftScenarios.tla", path / "HashicorpRaftScenarios.tla")


def run_tlc(path, scenario, *, invariants=(*GOALS, "Completed"), config=None):
    if config is None:
        config = CONFIG.replace("{scenario}", str(scenario)).replace("{invariants}", " ".join(invariants))
    (path / "Check.cfg").write_text(config)
    result = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-Xmx1g",
            "-cp",
            str(ROOT / "lib/tla2tools.jar"),
            "tlc2.TLC",
            "-workers",
            "1",
            "-metadir",
            str(path / "states"),
            "-config",
            "Check.cfg",
            "HashicorpRaftScenarios.tla",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    (path / "tlc.log").write_text(output)
    return result.returncode, output


def change_action(path, action, old, new):
    text = path.read_text()
    match = re.search(rf"(?ms)^{action}(?:\([^\n]*\))?\s*==.*?(?=^[A-Za-z_]\w*(?:\([^\n]*\))?\s*==|\Z)", text)
    assert match, action
    body = match[0]
    assert body.count(old) == 1, (action, old)
    path.write_text(text[: match.start()] + body.replace(old, new) + text[match.end() :])


@pytest.mark.parametrize("layout", ["source", "module"])
@pytest.mark.parametrize("scenario,states", [(1, 51), (2, 17), (3, 11), (4, 28), (5, 3), (6, 22), (11, 12)])
def test_reachable_scenarios_preserve_all_goals(tmp_path, layout, scenario, states):
    stage(tmp_path, layout)
    code, output = run_tlc(tmp_path, scenario)
    assert code == 0, output
    assert "Model checking completed. No error has been found." in output
    assert f"{states} distinct states found, 0 states left on queue" in output


@pytest.mark.parametrize(
    "case,scenario,action,old,new,goal",
    [
        (
            "overstated_ack",
            2,
            "HandleAppendEntriesRequest",
            "mmatchIndex  |-> m.mprevLogIndex + Len(m.mentries)",
            "mmatchIndex  |-> newLastIdx",
            "Completed",
        ),
        (
            "stale_vote",
            3,
            "Crash",
            "IF persistedVoteTerm[i] = persistedTerm[i]\n                                            THEN persistedVotedFor[i] ELSE Nil",
            "persistedVotedFor[i]",
            "Completed",
        ),
        (
            "configuration_before_current_term_commit",
            4,
            "ProposeConfigChange",
            "    /\\ log[i][commitIndex[i]].term = currentTerm[i]\n",
            "",
            "Completed",
        ),
        (
            "multiple_pending_configurations",
            10,
            "ProposeConfigChange",
            "    /\\ committedConfigIndex[i] = latestConfigIndex[i]\n",
            "",
            "ConfigurationSafety",
        ),
        (
            "commit_without_quorum",
            7,
            "AdvanceCommitIndex",
            "IsQuorum(Agree(idx) \\cap latestConfig[i], latestConfig[i])",
            "TRUE",
            "StateMachineSafety",
        ),
        (
            "elect_without_log_freshness",
            9,
            "LogUpToDate",
            r"\/ cLastTerm > vLastTerm" + "\n    " + r"\/ (cLastTerm = vLastTerm /\ cLastIdx >= vLastIdx)",
            "TRUE",
            "LeaderCompleteness",
        ),
        (
            "lose_durable_log",
            1,
            "Crash",
            "    /\\ UNCHANGED <<log, messages, persistedTerm, persistedVoteTerm, persistedVotedFor>>",
            "    /\\ log' = [log EXCEPT ![i] = <<>>]\n"
            "    /\\ UNCHANGED <<messages, persistedTerm, persistedVoteTerm, persistedVotedFor>>",
            "CommittedEntriesPreserved",
        ),
        (
            "change_payload",
            1,
            "HandleAppendEntriesRequest",
            "log' = [log EXCEPT ![i] = newLog]",
            "log' = [log EXCEPT ![i] = IF Len(newLog) = 0 THEN newLog\n"
            "                       ELSE [newLog EXCEPT ![1].value = CHOOSE v \\in Values : v # @]]",
            "LogMatching",
        ),
    ],
)
def test_fault_controls_are_rejected(tmp_path, case, scenario, action, old, new, goal):
    stage(tmp_path)
    change_action(tmp_path / RUNTIME.name, action, old, new)
    code, output = run_tlc(tmp_path, scenario, invariants=(goal,))
    assert code == 12, (case, output)
    assert f"Invariant {goal} is violated" in output


def test_reply_before_persistence_allows_two_leaders(tmp_path):
    stage(tmp_path)
    change_action(
        tmp_path / RUNTIME.name,
        "HandleRequestVoteRequest",
        "/\\ Discard(m)",
        "/\\ Reply([mtype |-> RequestVoteResponse, mterm |-> mterm, mvoteGranted |-> TRUE,\n"
        "                      msource |-> i, mdest |-> m.msource], m)",
    )
    code, output = run_tlc(tmp_path, 8, invariants=("ElectionSafety",))
    assert code == 12, output
    assert "Invariant ElectionSafety is violated" in output


@pytest.mark.parametrize(
    "old,new",
    [("Nil = Nil", "Nil = A"), ("Candidate = Candidate", "Candidate = Leader"), ("Values = {V, W}", "Values = {}")],
)
def test_invalid_parameter_domains_are_rejected(tmp_path, old, new):
    stage(tmp_path)
    config = CONFIG.replace("{scenario}", "5").replace("{invariants}", "ElectionSafety").replace(old, new)
    code, output = run_tlc(tmp_path, 5, config=config)
    assert code == 10, output
    assert "Assumption" in output and "is false" in output
    assert "Computing initial states" not in output


def test_exactly_six_top_level_goals_and_observer_separation():
    source = SOURCE.read_text()
    names = re.findall(r"(?m)^THEOREM (\w+) == Spec => \[\](\w+)$", source)
    assert names == [(goal + "Correct", goal) for goal in GOALS]
    assert source.count("PROOF OMITTED") == 6
    runtime = RUNTIME.read_text()
    protocol = runtime.split("VARIABLE electionHistory", 1)[0]
    assert "electionHistory" not in protocol and "commitHistory" not in protocol
    assert not any(re.search(rf"\b{goal}\b", protocol) for goal in GOALS)
    assert not re.search(r"(?m)^(THEOREM|LEMMA|AXIOM)\b", runtime)
    manifest = json.loads((SUITE / "manifest.json").read_text())
    task = next(t for t in manifest["module_tasks"] if t["spec"]["task_id"] == "HashicorpRaft/HashicorpRaft.tla")
    assert task["spec"]["source_sha256"] == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert {u["task_id"] for u in task["spec"]["proof_units"]} == {
        f"HashicorpRaft/HashicorpRaft_{goal}Correct.tla" for goal in GOALS
    }

"""Regression coverage for etcd Raft assumptions, recovery and commit terms."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm, find_tlapm_lib

REPO = Path(__file__).resolve().parents[2]
TASK_DIR = REPO / "benchmark" / "proof-from-scratch" / "etcd_raft"
SOURCE = REPO / "source" / "etcd_raft" / "etcd_raft.tla"
MODEL = TASK_DIR / "etcd_raftModel.tla"
TLA2TOOLS = REPO / "lib" / "tla2tools.jar"
COMMUNITY = REPO / "lib" / "community"
SUBSET_ASSUMPTION = r"ASSUME InitServerSubset == InitServer \subseteq Server"
FINITE_ASSUMPTION = r"ASSUME FiniteServers == IsFiniteSet(InitServer)"
NIL_ASSUMPTION = r"ASSUME NilNotServer == Nil \notin Server"

CONFIG = """\
SPECIFICATION Spec
INVARIANT {invariant}
CHECK_DEADLOCK FALSE

CONSTANTS
  InitServer = {init_server}
  Server = {server}
  ValueEntry = "ValueEntry"
  ConfigEntry = "ConfigEntry"
  Follower = "Follower"
  Candidate = "Candidate"
  Leader = "Leader"
  Nil = {nil}
  RequestVoteRequest = "RequestVoteRequest"
  RequestVoteResponse = "RequestVoteResponse"
  AppendEntriesRequest = "AppendEntriesRequest"
  AppendEntriesResponse = "AppendEntriesResponse"
"""


def _run_tlc(
    tmp_path: Path,
    *,
    init_server: str,
    server: str,
    nil: str = "0",
    invariant: str = "QuorumLogInv",
    module: str = "etcd_raft_QuorumLog",
) -> str:
    tlapm = find_tlapm()
    tlapm_lib = find_tlapm_lib(tlapm) if tlapm else None
    if shutil.which("java") is None or not TLA2TOOLS.is_file() or not COMMUNITY.is_dir() or not tlapm_lib:
        pytest.skip("TLC dependencies are not installed; run make setup")

    tmp_path.mkdir()
    config = tmp_path / "QuorumLog.cfg"
    config.write_text(CONFIG.format(init_server=init_server, server=server, nil=nil, invariant=invariant))
    classpath = os.pathsep.join((str(TLA2TOOLS), str(COMMUNITY), str(TASK_DIR), tlapm_lib))
    result = subprocess.run(
        [
            "java",
            "-cp",
            classpath,
            "tlc2.TLC",
            "-config",
            str(config),
            module,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout + result.stderr


def test_source_and_generated_model_preserve_domain_assumptions():
    for path in (SOURCE, MODEL):
        contents = path.read_text()
        assert SUBSET_ASSUMPTION in contents
        assert FINITE_ASSUMPTION in contents
        assert NIL_ASSUMPTION in contents


def test_quorum_log_rejects_initial_servers_outside_server(tmp_path):
    invalid = _run_tlc(tmp_path / "invalid", init_server="{2}", server="{1}")
    assert "of module etcd_raftModel is false" in invalid
    assert "Computing initial states" not in invalid

    valid = _run_tlc(tmp_path / "valid", init_server="{}", server="{}")
    assert "Model checking completed. No error has been found." in valid


def test_more_than_one_leader_rejects_nil_server(tmp_path):
    invalid = _run_tlc(
        tmp_path / "invalid",
        init_server="{1, 2, 3}",
        server="{1, 2, 3}",
        nil="1",
        invariant="MoreThanOneLeaderInv",
        module="etcd_raft_MoreThanOneLeader",
    )
    assert "of module etcd_raftModel is false" in invalid
    assert "Computing initial states" not in invalid


@pytest.mark.parametrize("recovery_case", ["truncate", "replace", "persist"])
def test_restart_recovers_the_last_persisted_log(tmp_path, recovery_case):
    """A reachable conflict must not corrupt log contents restored after a crash."""
    if shutil.which("java") is None or not TLA2TOOLS.is_file() or not COMMUNITY.is_dir():
        pytest.skip("TLC dependencies are not installed; run make setup")
    fixture = REPO / "tests" / "fixtures" / "etcd_raft" / "DurableLogRecovery.tla"
    shutil.copy2(fixture, tmp_path / fixture.name)
    config = CONFIG.format(
        invariant="RecoveredLog",
        init_server="{s1, s2, s3}",
        server="{s1, s2, s3}",
        nil="Nil",
    ).replace("SPECIFICATION Spec", "SPECIFICATION SSpec")
    config += f'\nCONSTANTS s1 = s1 s2 = s2 s3 = s3\nRecoveryCase = "{recovery_case}"\nPROPERTY RefinesNext\n'
    for invariant in (
        "LogInv",
        "CommittedIsDurableInv",
        "ElectionSafetyInv",
        "LeaderCompletenessInv",
        "LogMatchingInv",
        "MoreThanOneLeaderInv",
        "MoreUpToDateCorrectInv",
        "QuorumLogInv",
    ):
        config += f"INVARIANT {invariant}\n"
    (tmp_path / "DurableLogRecovery.cfg").write_text(config)
    # The fixture extends the module-level definitions used by experiments.
    module_context = REPO / "benchmark" / "proof-from-scratch-module" / "etcd_raft"
    classpath = os.pathsep.join((str(TLA2TOOLS), str(COMMUNITY), str(module_context)))
    result = subprocess.run(
        [
            "java",
            "-Xmx1g",
            "-cp",
            classpath,
            "tlc2.TLC",
            "-workers",
            "1",
            "-config",
            "DurableLogRecovery.cfg",
            "DurableLogRecovery.tla",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Model checking completed. No error has been found." in output
    depth = re.search(r"depth of the complete state graph search is (\d+)", output)
    assert depth is not None and int(depth.group(1)) == 34, output


def _stage_leader_completeness(tmp_path, layout):
    if shutil.which("java") is None or not TLA2TOOLS.is_file() or not COMMUNITY.is_dir():
        pytest.skip("TLC dependencies are not installed; run make setup")
    fixture = REPO / "tests/fixtures/etcd_raft/LeaderCompleteness.tla"
    text = fixture.read_text()
    if layout == "source":
        shutil.copyfile(SOURCE, tmp_path / SOURCE.name)
        text = text.replace("EXTENDS etcd_raftDefs", "EXTENDS etcd_raft")
        model = tmp_path / SOURCE.name
    else:
        context = REPO / "benchmark/proof-from-scratch-module/etcd_raft" if layout == "module" else TASK_DIR
        defs = "etcd_raftDefs.tla" if layout == "module" else "etcd_raft_LeaderCompletenessDefs.tla"
        shutil.copyfile(context / "etcd_raftModel.tla", tmp_path / "etcd_raftModel.tla")
        shutil.copyfile(context / defs, tmp_path / defs)
        text = text.replace("EXTENDS etcd_raftDefs", f"EXTENDS {Path(defs).stem}")
        model = tmp_path / "etcd_raftModel.tla"
    (tmp_path / fixture.name).write_text(text)
    return model


def _check_leader_completeness(
    tmp_path, *, crash=False, follower=False, election_node=3, invariant="LeaderCompletenessInv", all_goals=True
):
    config = CONFIG.format(invariant=invariant, init_server="{1, 2, 3}", server="{1, 2, 3}", nil="0")
    config = config.replace("SPECIFICATION Spec", "SPECIFICATION TraceSpec")
    config += (
        f"\nCONSTANTS CrashBeforeElection = {str(crash).upper()}\n"
        f"CommitOnFollower = {str(follower).upper()}\nElectionNode = {election_node}\n"
        "PROPERTY Spec\nPROPERTY RefinesProtocol\nPROPERTY EventuallyCompletes\n"
        "INVARIANTS LateCommitWitness HistoryRetained Completed\n"
    )
    if invariant == "LeaderCompletenessInv" and election_node == 3 and all_goals:
        config += (
            "INVARIANTS LogInv CommittedIsDurableInv ElectionSafetyInv LogMatchingInv\n"
            "MoreThanOneLeaderInv MoreUpToDateCorrectInv QuorumLogInv\n"
        )
    (tmp_path / "LeaderCompleteness.cfg").write_text(config)
    classpath = os.pathsep.join((str(TLA2TOOLS), str(COMMUNITY)))
    result = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-Xmx1g",
            "-cp",
            classpath,
            "tlc2.TLC",
            "-workers",
            "1",
            "-config",
            "LeaderCompleteness.cfg",
            "LeaderCompleteness.tla",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    (tmp_path / "tlc.log").write_text(output)
    return result.returncode, output


@pytest.mark.parametrize("layout", ["source", "flat", "module"])
@pytest.mark.parametrize("crash,follower", [(False, False), (True, False), (False, True)])
def test_leader_completeness_uses_commit_terms_and_retains_history(tmp_path, layout, crash, follower):
    _stage_leader_completeness(tmp_path, layout)
    code, output = _check_leader_completeness(tmp_path, crash=crash, follower=follower, all_goals=layout != "flat")
    assert code == 0, output
    assert "Model checking completed. No error has been found." in output
    assert "67 distinct states found, 0 states left on queue" in output


@pytest.mark.parametrize("layout", ["source", "flat", "module"])
def test_creation_term_predicate_rejects_a_legal_late_commit(tmp_path, layout):
    _stage_leader_completeness(tmp_path, layout)
    code, output = _check_leader_completeness(tmp_path, invariant="CreationTermCompleteness")
    assert code == 12, output
    assert "Invariant CreationTermCompleteness is violated" in output
    assert "48 distinct states found, 0 states left on queue" in output


@pytest.mark.parametrize("layout", ["source", "flat", "module"])
def test_leader_completeness_rejects_election_without_log_freshness(tmp_path, layout):
    model = _stage_leader_completeness(tmp_path, layout)
    text = model.read_text()
    guard = "                 /\\ logOk\n"
    assert text.count(guard) == 1
    model.write_text(text.replace(guard, "                 /\\ TRUE\n"))
    code, output = _check_leader_completeness(tmp_path, election_node=2)
    assert code == 12, output
    assert "Invariant LeaderCompletenessInv is violated" in output

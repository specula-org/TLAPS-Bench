"""Retain snapshot positions, transaction identities, and write conflicts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/mongodb"
SOURCE = ROOT / "source/MongoDB"
GENERATED = ROOT / "benchmark/proof-from-scratch-module/MongoDB"
LIBS = [ROOT / "lib/tlapm", ROOT / "lib/community"]


def stage(tmp_path, layout):
    directory = SOURCE if layout == "source" else GENERATED
    for path in directory.rglob("*.tla"):
        shutil.copyfile(path, tmp_path / path.name)


def run_tlc(tmp_path, module, config, tag="check"):
    jar = ROOT / "lib/tla2tools.jar"
    if shutil.which("java") is None or not jar.is_file():
        pytest.skip("Java and the pinned tla2tools.jar are required")
    (tmp_path / "Check.cfg").write_text(config)
    output = tmp_path / "spec/output" / tag
    output.mkdir(parents=True)
    result = subprocess.run(
        [
            "java",
            "-XX:+UseParallelGC",
            "-Xmx1g",
            "-cp",
            os.pathsep.join(map(str, (jar, tmp_path, *LIBS))),
            "tlc2.TLC",
            "-workers",
            "1",
            "-metadir",
            str(output / "states"),
            "-config",
            "Check.cfg",
            "-dumpTrace",
            "json",
            str(output / "trace.json"),
            module,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    log = result.stdout + result.stderr
    (output / "tlc.log").write_text(log)
    return result.returncode, log, output


def constants(no_value=101, transactions="{1,2,3,100}"):
    return f"""CONSTANTS
 Keys = {{"a","b"}}
 TxId = {transactions}
 Router = {{"r"}}
 Shard = {{"s"}}
 NoValue = {no_value}
 Timestamps = {{0,1,2,3,4}}
 RC = "snapshot"
 IgnorePrepareBlocking = "false"
 IgnoreWriteConflicts = "false"
CHECK_DEADLOCK FALSE
"""


@pytest.mark.parametrize("layout", ["source", "generated"])
def test_snapshot_semantic_controls(tmp_path, layout):
    stage(tmp_path, layout)
    shutil.copyfile(FIXTURES / "IdentitySIControls.tla", tmp_path / "IdentitySIControls.tla")
    code, log, _ = run_tlc(tmp_path, "IdentitySIControls", (FIXTURES / "IdentitySIControls.cfg").read_text())
    assert code == 0, log
    assert "No error has been found" in log, log


@pytest.mark.parametrize("layout", ["source", "generated"])
@pytest.mark.parametrize("no_value", [100, 101])
def test_protocol_trace_preserves_occurrences_and_exposes_old_index(tmp_path, layout, no_value):
    stage(tmp_path, layout)
    # The protocol module has no benchmark wrapper assumptions. The colliding
    # sentinel remains a regression for the predicate, independently of its
    # exclusion by the new wrapper premise.
    shutil.copyfile(FIXTURES / "SnapshotPositionWitness.tla", tmp_path / "SnapshotPositionWitness.tla")
    # Keep the old predicate in a separate oracle: generated contexts prune
    # its unused definitions, so they must not be reintroduced into the target.
    legacy = (SOURCE / "ClientCentric.tla").read_text()
    legacy = legacy.replace("MODULE ClientCentric", "MODULE LegacyClientCentric")
    legacy = legacy.replace("FiniteSets, Util", "FiniteSets, LegacyUtil")
    (tmp_path / "LegacyClientCentric.tla").write_text(legacy)
    util = tmp_path / "LegacyUtil.tla"
    text = (SOURCE / "Util.tla").read_text().replace("MODULE Util", "MODULE LegacyUtil")
    old = r"Index(seq, e) ==  CHOOSE i \in 1..Len(seq): seq[i] = e"
    assert text.count(old) == 1
    util.write_text(text.replace(old, r"Index(seq, e) == max({i \in 1..Len(seq): seq[i] = e})"))
    config = (
        "SPECIFICATION TraceSpec\n"
        "PROPERTIES Spec ReachedEnd\n"
        "INVARIANTS SingleWritePerKey ExpectedHistory SnapshotIsolation ExpectedLegacyOutcome\n" + constants(no_value)
    )
    code, log, _ = run_tlc(tmp_path, "SnapshotPositionWitness", config)
    assert code == 0, log
    assert "43 distinct states found" in log, log
    if no_value == 100:
        code, log, output = run_tlc(
            tmp_path,
            "SnapshotPositionWitness",
            config + "INVARIANT LegacyFinalSI\n",
            "legacy-counterexample",
        )
        assert code == 12 and "Invariant LegacyFinalSI is violated" in log, log
        trace = json.loads((output / "trace.json").read_text())["counterexample"]["state"]
        assert len(trace) == 43 and trace[-1][1]["step"] == 42


@pytest.mark.parametrize("layout", ["source", "generated"])
@pytest.mark.parametrize(
    ("no_value", "transactions", "valid"), [(100, "{100}", False), (101, "{100}", True), (0, "{}", True)]
)
def test_sentinel_domain_and_initial_identity_mapping(tmp_path, layout, no_value, transactions, valid):
    stage(tmp_path, layout)
    (tmp_path / "SnapshotDomainCheck.tla").write_text(
        r"""---- MODULE SnapshotDomainCheck ----
EXTENDS MultiShardTxnSnapshot
Hold == UNCHANGED vars
InitiallyEmpty == SnapshotTransactions = {} /\ SnapshotIsolation
====
"""
    )
    code, log, _ = run_tlc(
        tmp_path,
        "SnapshotDomainCheck",
        "INIT Init\nNEXT Hold\nINVARIANT InitiallyEmpty\n" + constants(no_value, transactions),
    )
    if valid:
        assert code == 0 and "No error has been found" in log, log
    else:
        assert code != 0 and "Assumption" in log and "is false" in log, log


def test_empty_history_mapping_with_unbounded_parameters(tmp_path):
    binary = find_tlapm()
    if binary is None or not all(path.is_dir() for path in LIBS):
        pytest.skip("TLAPM and the pinned proof libraries are required")
    stage(tmp_path, "generated")
    (tmp_path / "SnapshotMappingCheck.tla").write_text(
        r"""---- MODULE SnapshotMappingCheck ----
EXTENDS MultiShardTxnSnapshotDefs, TLAPS
THEOREM EmptyHistory ==
  ops = [t \in TxId |-> <<>>] => SnapshotTransactions = {}
BY SMT DEF SnapshotTransactions
THEOREM InitialHistory == Init => SnapshotTransactions = {}
BY EmptyHistory, SMT DEF Init
THEOREM PreserveIdentity ==
  ASSUME NEW t, NEW u, t \in DOMAIN ops, u \in DOMAIN ops,
         t # u, ops[t] # <<>>, ops[u] # <<>>
  PROVE /\ [id |-> t, ops |-> ops[t]] \in SnapshotTransactions
        /\ [id |-> u, ops |-> ops[u]] \in SnapshotTransactions
        /\ [id |-> t, ops |-> ops[t]] # [id |-> u, ops |-> ops[u]]
BY SMT DEF SnapshotTransactions
====
"""
    )
    command = [binary, "--strict", "--nofp", "--threads", "1"]
    for path in LIBS:
        command += ["-I", str(path)]
    result = subprocess.run(
        command + [str(tmp_path / "SnapshotMappingCheck.tla")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    log = result.stdout + result.stderr
    (tmp_path / "tlapm.log").write_text(log)
    assert result.returncode == 0 and "obligations proved" in log, log

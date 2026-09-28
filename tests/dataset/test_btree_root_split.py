"""A root split must not inspect an unspecified parent or push it on the stack."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "benchmark/proof-from-scratch-module/tlaplus_examples_btree"
LIBS = [ROOT / "lib/tlapm", ROOT / "lib/community"]


def test_root_preserves_split_stack_for_arbitrary_parent(tmp_path):
    binary = find_tlapm()
    if binary is None or not all(path.is_dir() for path in LIBS):
        pytest.skip("TLAPM and the pinned proof libraries are required")
    probe = tmp_path / "RootCheck.tla"
    probe.write_text(
        r"""---- MODULE RootCheck ----
EXTENDS btreeModel, TLAPS
THEOREM RootStack ==
  WhichToSplit /\ Head(toSplit) = root => toSplit' = toSplit
BY SMT DEF WhichToSplit
====
"""
    )
    command = [binary, "--strict", "--nofp", "--threads", "1"]
    for path in (MODELS, *LIBS):
        command += ["-I", str(path)]
    result = subprocess.run(command + [str(probe)], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    log = result.stdout + result.stderr
    (tmp_path / "tlapm.log").write_text(log)
    assert result.returncode == 0 and "obligations proved" in log, log


@pytest.mark.parametrize("case", ["old-counterexample", "old-fair-witness", "repaired"])
def test_root_case_with_adversarial_choice_interpretation(tmp_path, case):
    jar = ROOT / "lib/tla2tools.jar"
    if shutil.which("java") is None or not jar.is_file():
        pytest.skip("Java and the pinned tla2tools.jar are required")
    model = (MODELS / "btreeModel.tla").read_text()
    guard = "splitParent == IF node = root THEN FALSE ELSE AtMaxOccupancy(parent)"
    assert model.count(guard) == 1
    if case != "repaired":
        model = model.replace(guard, "splitParent == AtMaxOccupancy(parent)")
    # Realize a fixed legal choice when a node has no parent. The out-of-domain
    # keysOf application may consistently return {1,2}. Reorder the overlapping
    # CASE arms so TLC exercises the other permitted value.
    old = r"""ParentOf(n) == CHOOSE p \in Nodes: \/ \E k \in Keys: n = childOf[p, k]
                                   \/ lastOf[p]=n"""
    assert model.count(old) == 1
    model = model.replace(
        old,
        r"""ParentOf(n) ==
 LET parents == {p \in Nodes : (\E k \in Keys : n = childOf[p,k]) \/ lastOf[p] = n}
 IN IF parents = {} THEN NIL ELSE CHOOSE p \in parents : TRUE""",
    )
    old = "AtMaxOccupancy(node) == Cardinality(keysOf[node]) = MaxOccupancy"
    assert model.count(old) == 1
    model = model.replace(
        old,
        r"AtMaxOccupancy(node) == Cardinality(IF node \in DOMAIN keysOf THEN keysOf[node] ELSE {1,2}) = MaxOccupancy",
    )
    old = "CASE node = root   -> toSplit\n             [] splitParent   -> <<parent>> \\o toSplit"
    assert model.count(old) == 1
    model = model.replace(old, "CASE splitParent   -> <<parent>> \\o toSplit\n             [] node = root   -> toSplit")
    (tmp_path / "btreeModel.tla").write_text(model)
    shutil.copyfile(MODELS / "btreeDefs.tla", tmp_path / "btreeDefs.tla")
    shutil.copyfile(Path(__file__).with_name("BTreeRootCaseWitness.tla"), tmp_path / "BTreeRootCaseWitness.tla")
    config = """SPECIFICATION TraceSpec
INVARIANT RootHasNoParent
CHECK_DEADLOCK FALSE
CONSTANTS
 Nodes = {"n1","n2","n3"}
 Keys = {1,2,3}
 Vals = {"v"}
 MaxOccupancy = 2
 NIL <- NoNode
 MISSING <- NoValue
"""
    states = (
        "READY",
        "GET_VALUE",
        "FIND_LEAF_TO_ADD",
        "WHICH_TO_SPLIT",
        "ADD_TO_LEAF",
        "SPLIT_LEAF",
        "SPLIT_INNER",
        "SPLIT_ROOT_LEAF",
        "SPLIT_ROOT_INNER",
        "UPDATE_LEAF",
    )
    config += "".join(f" {state} = {state}\n" for state in states)
    if case == "old-counterexample":
        config += "INVARIANT TypeOk\n"
    else:
        config += "PROPERTIES Spec ReachedEnd\n"
        config += "PROPERTY EventuallyBad\n" if case == "old-fair-witness" else "INVARIANTS TypeOk RootStackPreserved\n"
    (tmp_path / "Check.cfg").write_text(config)
    output = tmp_path / "spec/output"
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
            "BTreeRootCaseWitness",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    log = result.stdout + result.stderr
    (output / "tlc.log").write_text(log)
    if case == "old-counterexample":
        assert result.returncode == 12 and "Invariant TypeOk is violated" in log, log
        trace = json.loads((output / "trace.json").read_text())["counterexample"]["state"]
        assert len(trace) == 10 and trace[-1][1]["toSplit"][0] == "nil"
    else:
        assert result.returncode == 0 and "No error has been found" in log, log
    assert "10 distinct states found" in log, log

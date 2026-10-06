"""Check guarded key comparisons without narrowing the benchmark's key domain."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent
MODEL = ROOT / "benchmark/proof-from-scratch-module/tlaplus_examples_btree"
LIBS = [ROOT / "lib/tlapm", ROOT / "lib/community"]


def run_tlapm(tmp_path, filename, *includes):
    binary = find_tlapm()
    if binary is None or not all(path.is_dir() for path in LIBS):
        pytest.skip("TLAPM and the pinned proof libraries are required")
    command = [binary, "--strict", "--nofp", "--threads", "1"]
    for path in (*includes, *LIBS):
        command += ["-I", str(path)]
    result = subprocess.run(command + [str(filename)], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    output = result.stdout + result.stderr
    (tmp_path / "tlapm.log").write_text(output)
    return result.returncode, output


def test_comparison_rewrite_preserves_branches_and_sets_for_all_values(tmp_path):
    helper = re.search(
        r"(?m)^KeyAtLeast\(key, bound\) ==\n(?:[ \t].*\n)+",
        (ROOT / "source/tlaplus_examples_btree/btree.tla").read_text(),
    )
    assert helper is not None
    definition = helper[0].replace("KeyAtLeast", "GuardedGE")
    definition = definition.replace("key >= bound", "BookGE(key,bound)")
    definition = definition.replace("key < bound", "BookLT(key,bound)")
    fixture = (FIXTURES / "BTreeKeyOrderEquivalence.tla").read_text()
    fixture = re.sub(r"(?m)^GuardedGE\(a,b\) ==.*$", lambda _: definition.rstrip(), fixture)
    path = tmp_path / "BTreeKeyOrderEquivalence.tla"
    path.write_text(fixture)
    code, output = run_tlapm(tmp_path, path)
    assert code == 0, output
    assert re.search(r"All [1-9]\d* obligations proved", output), output


def test_singleton_separator_uses_last_child_without_numeric_keys(tmp_path):
    path = tmp_path / "BTreeKeyProbe.tla"
    path.write_text(
        r"""---- MODULE BTreeKeyProbe ----
EXTENDS btreeModel, TLAPS
THEOREM SeparatorEquality ==
  ASSUME NEW n \in Nodes, NEW k \in Keys, keysOf[n] = {k}
  PROVE ChildNodeFor(n, k) = lastOf[n]
<1>1. Max({k}) = k
  BY Zenon DEF Max
<1>2. ~(k < k)
  BY KeysAreOrdered, Zenon
    DEF IsStrictlyTotallyOrderedUnder, IsStrictlyTotallyOrdered,
        IsStrictlyPartiallyOrdered, IsIrreflexive
<1> QED BY <1>1, <1>2, SMTT("r10") DEF ChildNodeFor, KeyAtLeast
====
"""
    )
    code, output = run_tlapm(tmp_path, path, MODEL)
    assert code == 0, output
    assert re.search(r"All [1-9]\d* obligations proved", output), output


def test_original_and_rewritten_transition_relations_agree(tmp_path):
    jar = ROOT / "lib/tla2tools.jar"
    if shutil.which("java") is None or not jar.is_file():
        pytest.skip("Java and the pinned tla2tools.jar are required")
    for name in ("btreeModel.tla", "btreeDefs.tla"):
        shutil.copyfile(MODEL / name, tmp_path / name)
    original = (MODEL / "btreeModel.tla").read_text().replace("MODULE btreeModel", "MODULE BTreeOriginal")
    assert original.count("KeyAtLeast(key, maxKey)") == 1
    assert original.count("KeyAtLeast(x, pivot)") == 2
    original = original.replace("KeyAtLeast(key, maxKey)", "key >= maxKey")
    original = original.replace("KeyAtLeast(x, pivot)", "x >= pivot")
    # Share the same TLC instantiations of the two non-enumerable choices.
    original = original.replace("CONSTANTS Vals,", "CONSTANTS OldNIL, OldMissing, Vals,")
    original = original.replace(r"NIL == CHOOSE x : x \notin Nodes", "NIL == OldNIL")
    original = original.replace(r"MISSING == CHOOSE v : v \notin Vals", "MISSING == OldMissing")
    (tmp_path / "BTreeOriginal.tla").write_text(original)
    (tmp_path / "BTreeCompareTransitions.tla").write_text(
        r"""---- MODULE BTreeCompareTransitions ----
EXTENDS btreeDefs
Old == INSTANCE BTreeOriginal WITH OldNIL <- NIL, OldMissing <- MISSING
VARIABLE same
NoNode == "nil"
NoValue == "missing"
CheckInit == /\ (Init \/ Old!Init) /\ same = (Init <=> Old!Init)
CheckNext == /\ (Next \/ Old!Next) /\ same' = (Next <=> Old!Next)
SameTransitions == same
====
"""
    )
    config = """INIT CheckInit
NEXT CheckNext
CHECK_DEADLOCK FALSE
INVARIANTS SameTransitions TypeOk InnersMustHaveLast LeavesCantHaveLast KeyOrderPreserved KeysInLeavesAreUnique
CONSTANTS
 Nodes = {n1,n2,n3}
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
    (tmp_path / "Check.cfg").write_text(config)
    output_dir = tmp_path / "spec/output"
    output_dir.mkdir(parents=True)
    classpath = os.pathsep.join(map(str, (jar, *LIBS, tmp_path)))
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
            "Check.cfg",
            "BTreeCompareTransitions",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output = result.stdout + result.stderr
    (output_dir / "tlc.log").write_text(output)
    assert result.returncode == 0, output
    assert "Model checking completed. No error has been found." in output, output
    assert "562 distinct states found" in output, output

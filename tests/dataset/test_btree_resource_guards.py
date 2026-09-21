"""B-tree splits preserve safety when their fixed node pool is exhausted."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent
MODELS = REPO / "benchmark/proof-from-scratch-module/tlaplus_examples_btree"
STATES = (
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


def test_empty_choice_normalization_is_provably_equivalent(tmp_path):
    tlapm = find_tlapm()
    if tlapm is None or not (REPO / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    source = FIXTURES / "BTreeChoiceNormalizationCheck.tla"
    result = subprocess.run(
        [
            tlapm,
            "--strict",
            "--nofp",
            "--threads",
            "1",
            "-I",
            str(REPO / "lib/tlapm"),
            "-I",
            str(REPO / "lib/community"),
            str(source),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All 12 obligations proved" in result.stdout + result.stderr


def _constants(node_count=1, key_count=3):
    return (
        "CONSTANTS\n Nodes = {" + ", ".join(f"n{i + 1}" for i in range(node_count)) + "}\n"
        " Keys = {" + ", ".join(str(i + 1) for i in range(key_count)) + "}\n"
        ' Vals = {"v"}\n MaxOccupancy = 2\n NIL <- NoNode\n MISSING <- NoValue\n'
        + "".join(f" {state} = {state}\n" for state in STATES)
    )


def _run_tlc(tmp_path, module):
    jar = REPO / "lib/tla2tools.jar"
    if shutil.which("java") is None or not jar.is_file():
        pytest.skip("TLC requires java and the pinned tla2tools.jar")
    output = tmp_path / "spec/output"
    output.mkdir(parents=True)
    classpath = os.pathsep.join(str(p) for p in (jar, MODELS, REPO / "lib/community", REPO / "lib/tlapm", tmp_path))
    result = subprocess.run(
        [
            "java",
            "-Xmx2g",
            "-cp",
            classpath,
            "tlc2.TLC",
            "-workers",
            "1",
            "-config",
            f"{module}.cfg",
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
    (output / "tlc.log").write_text(result.stdout + result.stderr)
    return result


@pytest.mark.parametrize(("node_count", "key_count"), [(1, 3), (2, 3), (3, 3), (5, 4), (7, 4)])
def test_original_safety_properties_with_finite_node_pools(tmp_path, node_count, key_count):
    (tmp_path / "BTreeResourceCheck.tla").write_text(
        '---- MODULE BTreeResourceCheck ----\nEXTENDS btreeDefs\nNoNode == "nil"\nNoValue == "missing"\n====\n'
    )
    (tmp_path / "BTreeResourceCheck.cfg").write_text(
        "INIT Init\nNEXT Next\nCHECK_DEADLOCK FALSE\n"
        "INVARIANTS TypeOk InnersMustHaveLast LeavesCantHaveLast KeyOrderPreserved KeysInLeavesAreUnique\n"
        + _constants(node_count, key_count)
    )
    result = _run_tlc(tmp_path, "BTreeResourceCheck")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Model checking completed. No error has been found." in result.stdout + result.stderr


def _unguarded_choice_model(tmp_path):
    """Recreate the pre-fix actions and expose their shared empty-choice value."""
    model = (MODELS / "btreeModel.tla").read_text()
    for guard, count in (("HasFreeNode", 1), ("HasTwoFreeNodes", 2)):
        line = f"    /\\ {guard}\n"
        assert model.count(line) == count
        model = model.replace(line, "")
    old = r"ChooseFreeNode == CHOOSE n \in Nodes : IsFree(n)"
    assert model.count(old) == 1
    model = model.replace(
        old,
        r"""EmptyChoice == CHOOSE x : FALSE
PickNode(S) == IF S = {} THEN EmptyChoice ELSE CHOOSE n \in S : TRUE
ChooseFreeNode == PickNode({n \in Nodes : IsFree(n)})""",
    )
    old = r"CHOOSE n \in Nodes : IsFree(n) /\ (n # n2)"
    assert model.count(old) == 2
    model = model.replace(old, r"PickNode({n \in Nodes : IsFree(n) /\ (n # n2)})")
    (tmp_path / "btreeModel.tla").write_text(model)
    shutil.copy2(MODELS / "btreeDefs.tla", tmp_path / "btreeDefs.tla")


@pytest.mark.parametrize(
    ("choice", "invariant"),
    [(r"CHOOSE n \in Nodes : TRUE", "LeavesCantHaveLast"), ('"lost-node"', "TypeOk")],
)
def test_unguarded_split_has_a_safety_counterexample(tmp_path, choice, invariant):
    _unguarded_choice_model(tmp_path)
    (tmp_path / "BTreeResourceCheck.tla").write_text(
        "---- MODULE BTreeResourceCheck ----\nEXTENDS btreeDefs\n"
        f'NoNode == "nil"\nNoValue == "missing"\nBadChoice == {choice}\n====\n'
    )
    (tmp_path / "BTreeResourceCheck.cfg").write_text(
        f"INIT Init\nNEXT Next\nCHECK_DEADLOCK FALSE\nINVARIANT {invariant}\n"
        + _constants()
        + " EmptyChoice <- BadChoice\n"
    )
    result = _run_tlc(tmp_path, "BTreeResourceCheck")
    assert result.returncode == 12, result.stdout + result.stderr
    assert f"Invariant {invariant} is violated." in result.stdout + result.stderr
    trace = json.loads((tmp_path / "spec/output/trace.json").read_text())["counterexample"]
    assert len(trace["state"]) == 11
    final = trace["state"][-1][1]
    assert final["state"] == "ADD_TO_LEAF"
    if invariant == "TypeOk":
        assert final["root"] == "lost-node"
    else:
        assert final["isLeaf"]["n1"] is True
        assert final["lastOf"]["n1"] == "n1"


def test_bad_leaf_witness_satisfies_the_original_fair_specification(tmp_path):
    _unguarded_choice_model(tmp_path)
    module = "BTreeResourceWitness"
    shutil.copy2(FIXTURES / f"{module}.tla", tmp_path / f"{module}.tla")
    (tmp_path / f"{module}.cfg").write_text(
        "SPECIFICATION WitnessSpec\nPROPERTY Spec\nPROPERTY EventuallyBadLeaf\nCHECK_DEADLOCK FALSE\n"
        + _constants()
        + " EmptyChoice <- BadChoice\n"
    )
    result = _run_tlc(tmp_path, module)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Model checking completed. No error has been found." in result.stdout + result.stderr
    assert "11 distinct states found" in result.stdout + result.stderr

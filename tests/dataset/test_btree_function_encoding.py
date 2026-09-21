"""Check B-tree table values and TLAPS support after binder normalization."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent
MODEL_DIR = REPO / "benchmark/proof-from-scratch-module/tlaplus_examples_btree"
TLA2TOOLS = REPO / "lib/tla2tools.jar"


def test_initial_tables_are_provable_with_the_supported_constructor(tmp_path):
    tlapm = find_tlapm()
    if tlapm is None or not (REPO / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    probe = tmp_path / "BTreeTableTyping.tla"
    probe.write_text(
        r"""---- MODULE BTreeTableTyping ----
EXTENDS btreeModel
LOCAL TL == INSTANCE TLAPS
THEOREM InitialTablesTyped ==
    Init => /\ childOf \in [Nodes \X Keys -> Nodes \cup {NIL}]
            /\ valOf \in [Nodes \X Keys -> Vals \cup {NIL}]
BY TL!SMTT("r30") DEF Init
====
"""
    )
    result = subprocess.run(
        [
            tlapm,
            "--strict",
            "--nofp",
            "--threads",
            "1",
            "-I",
            str(MODEL_DIR),
            "-I",
            str(REPO / "lib/tlapm"),
            "-I",
            str(REPO / "lib/community"),
            str(probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All 2 obligations proved" in result.stdout + result.stderr


def test_initialization_and_all_split_table_constructors_preserve_values(tmp_path):
    if shutil.which("java") is None or not TLA2TOOLS.is_file():
        pytest.skip("TLC requires java and the pinned tla2tools.jar")
    classpath = os.pathsep.join(
        str(path) for path in (TLA2TOOLS, MODEL_DIR, REPO / "lib/community", REPO / "lib/tlapm", FIXTURES)
    )
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
            str(FIXTURES / "BTreeFunctionEncodingCheck.cfg"),
            "BTreeFunctionEncodingCheck",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output_dir = tmp_path / "spec/output"
    output_dir.mkdir(parents=True)
    (output_dir / "tlc.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Model checking completed. No error has been found." in result.stdout + result.stderr
    assert "7 distinct states found" in result.stdout + result.stderr

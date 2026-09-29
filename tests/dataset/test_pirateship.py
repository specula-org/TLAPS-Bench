"""Check PirateShip's proof adaptation and source/generated behavior."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.source import strip_comments
from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source/PirateShip"
FIXTURES = ROOT / "tests/fixtures/pirateship"
SUITE = ROOT / "benchmark/proof-from-scratch-module"
TASK = "PirateShip/PirateShipProof.tla"
INVARIANTS = [
    "TypeOK",
    "IndexBoundsInv",
    "BranchInv",
    "AuditBranchInv",
    "OneLeaderPerViewInv",
    "WellFormedBranchInv",
    "ViewMonotonicInv",
    "ViewStabilizationInv",
]
PROPERTIES = ["CommittedBranchAppendOnlyProp", "AuditedBranchAppendOnlyProp", "MonotonicAuditedIndexProp"]
CONSTANTS = """CONSTANTS
    R = {0,1,2,3}
    BR = {3}
    u = 1
    fsafe = 1
    Txs = {1,2}
    MaxByzActions = 2
"""
CHECKS = "\nINVARIANTS\n    " + " ".join(INVARIANTS) + "\nPROPERTIES\n    " + " ".join(PROPERTIES) + "\n"


def stage(directory, context="source"):
    if context == "source":
        paths = [SOURCE / "PirateShip.tla", SOURCE / "PirateShipProof.tla"]
    elif context == "module":
        entry = next(
            t for t in json.loads((SUITE / "manifest.json").read_text())["module_tasks"] if t["spec"]["task_id"] == TASK
        )
        paths = [SUITE / p for p in [TASK, *entry["context"]]]
    else:
        flat = ROOT / "benchmark/proof-from-scratch"
        key = "PirateShip/PirateShipProof_TypeOKCorrect.tla"
        entry = json.loads((flat / "manifest.json").read_text())[key]
        paths = [flat / p for p in [key, *entry["context"]]]
    for path in paths:
        shutil.copyfile(path, directory / path.name)


def tlc(directory, module, config, extra=(), timeout=120):
    jar = ROOT / "lib/tla2tools.jar"
    if not jar.is_file() or not shutil.which("java"):
        pytest.skip("Java and the pinned tla2tools.jar are required")
    (directory / f"{module}.cfg").write_text(config)
    output = directory / "output"
    output.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "java",
            "-XX:ActiveProcessorCount=2",
            "-XX:+UseParallelGC",
            "-Xmx1g",
            f"-DTLA-Library={ROOT / 'lib/community'}",
            "-cp",
            str(jar),
            "tlc2.TLC",
            "-workers",
            "1",
            "-noGenerateSpecTE",
            "-metadir",
            str(output / "states"),
            *extra,
            "-config",
            f"{module}.cfg",
            f"{module}.tla",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    text = result.stdout + result.stderr
    (output / f"{module}.log").write_text(text)
    return result.returncode, text


def complete(code, text):
    assert code == 0, text
    assert "Model checking completed. No error has been found." in text, text
    assert "0 states left on queue" in text, text


def test_pinned_source_and_reproducible_adaptation():
    meta = json.loads((SOURCE / "upstream.json").read_text())
    raw = (SOURCE / "upstream/pirateship.tla").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == meta["files"]["upstream/pirateship.tla"]["sha256"]
    result = subprocess.run(
        ["python3", str(SOURCE / "prepare.py"), "--check"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RECURSIVE" not in (SOURCE / "PirateShip.tla").read_text()
    assert meta["license"]["status"] == "pending"


@pytest.mark.parametrize("context", ["source", "module", "flat"])
def test_invalid_transaction_domain_is_rejected(tmp_path, context):
    stage(tmp_path, context)
    code, text = tlc(
        tmp_path,
        "PirateShip",
        CONSTANTS.replace("Txs = {1,2}", "Txs = {2}") + "INIT Init\nNEXT Next\nINVARIANT TypeOK\n",
    )
    assert code != 0, text
    assert re.search(r"Assumption .* of module PirateShip is false", text), text
    assert "Computing initial states" not in text


def test_upstream_transaction_domain_counterexample(tmp_path):
    shutil.copyfile(SOURCE / "upstream/pirateship.tla", tmp_path / "pirateship.tla")
    code, text = tlc(
        tmp_path,
        "pirateship",
        CONSTANTS.replace("Txs = {1,2}", "Txs = {2}") + "INIT Init\nNEXT Next\nINVARIANT TypeOK\n",
    )
    assert code == 12, text
    assert "Invariant TypeOK is violated" in text
    assert "SendEntries(3)" in text and "ByzLeaderEquivocate(3)" in text


@pytest.mark.parametrize("budget", ["-1", "{}"])
def test_invalid_byzantine_budget_is_rejected(tmp_path, budget):
    stage(tmp_path)
    (tmp_path / "BadBudget.tla").write_text(
        f"---- MODULE BadBudget ----\nEXTENDS PirateShip\nBudget == {budget}\n====\n"
    )
    code, text = tlc(
        tmp_path,
        "BadBudget",
        CONSTANTS.replace("MaxByzActions = 2", "MaxByzActions <- Budget") + "INIT Init\nNEXT Next\n",
    )
    assert code != 0, text
    assert re.search(r"(?:Assumption .* is false|Evaluating assumption .* failed)", text), text
    assert "Computing initial states" not in text


@pytest.mark.parametrize("context", ["source", "module"])
@pytest.mark.parametrize("scenario", ["ViewChange", "Byzantine"])
def test_reachable_protocol_scenarios(tmp_path, context, scenario):
    stage(tmp_path, context)
    shutil.copyfile(FIXTURES / "PirateShipScenarios.tla", tmp_path / "PirateShipScenarios.tla")
    config = (
        CONSTANTS
        + f'CONSTANT Scenario = "{scenario}"\nSPECIFICATION ScenarioSpec\n'
        + CHECKS
        + "INVARIANTS AuditedBeforeViewChange AuditedAfterViewChange ByzantineActionsExercised\n"
        + "PROPERTIES Allowed Completion\nCHECK_DEADLOCK FALSE\n"
    )
    complete(*tlc(tmp_path, "PirateShipScenarios", config))


@pytest.mark.parametrize("configuration", ["Crash", "Byzantine"])
def test_complete_small_models(tmp_path, configuration):
    stage(tmp_path)
    shutil.copyfile(SOURCE / "validation/SmallPirateShip.tla", tmp_path / "SmallPirateShip.tla")
    complete(*tlc(tmp_path, "SmallPirateShip", (SOURCE / f"validation/{configuration}.cfg").read_text(), timeout=180))


def test_recursive_functions_match_upstream_operators(tmp_path):
    stage(tmp_path)
    shutil.copyfile(SOURCE / "upstream/pirateship.tla", tmp_path / "pirateship.tla")
    shutil.copyfile(FIXTURES / "RecursionComparison.tla", tmp_path / "RecursionComparison.tla")
    config = (
        CONSTANTS.replace("R = {0,1,2,3}", "R = {0,1,2}")
        .replace("BR = {3}", "BR = {}")
        .replace("fsafe = 1", "fsafe = 0")
        + "INIT InitCheck\nNEXT NextCheck\nINVARIANT Matches\nCHECK_DEADLOCK FALSE\n"
    )
    complete(*tlc(tmp_path, "RecursionComparison", config))


@pytest.mark.parametrize("context", ["source", "module"])
def test_tlaps_recursion_unfolding_and_boundaries(tmp_path, context):
    tlapm = find_tlapm()
    if tlapm is None or not (ROOT / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    stage(tmp_path, context)
    shutil.copyfile(FIXTURES / "RecursionProof.tla", tmp_path / "RecursionProof.tla")
    result = subprocess.run(
        [
            tlapm,
            "--strict",
            "--nofp",
            "--threads",
            "1",
            "-I",
            str(ROOT / "lib/tlapm"),
            "-I",
            str(ROOT / "lib/community"),
            "RecursionProof.tla",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    text = result.stdout + result.stderr
    (tmp_path / "tlapm.log").write_text(text)
    assert result.returncode == 0, text
    assert "All 20 obligations proved" in text, text


def test_eleven_targets_retain_context_and_scope():
    document = json.loads((SUITE / "manifest.json").read_text())
    entry = next(t for t in document["module_tasks"] if t["spec"]["task_id"] == TASK)
    assert len(entry["spec"]["proof_units"]) == 11
    text = (SUITE / TASK).read_text()
    names = re.findall(r"THEOREM (\w+) ==", text)
    assert set(names) == {f"{name}Correct" for name in INVARIANTS + PROPERTIES}
    assert text.count("PROOF OMITTED") == 11
    assert not any("validation" in path or "upstream" in path or "RecursionProof" in path for path in entry["context"])
    models = [SUITE / p for p in entry["context"] if Path(p).name == "PirateShip.tla"]
    assert len(models) == 1

    def normalize(s):
        return " ".join(strip_comments(s).split())

    assert normalize(models[0].read_text()) == normalize((SOURCE / "PirateShip.tla").read_text())

"""Finite Wildfire regressions; these do not prove Alpha refinement."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/wildfire"
TASK = "Wildfire/WildfireProof_Refinement.tla"
SPEC = "Wildfire/WildfireProof.tla"


def stage(directory, layout="module"):
    jar = ROOT / "lib/tla2tools.jar"
    if not jar.is_file() or not shutil.which("java"):
        pytest.skip("TLC and the pinned tla2tools.jar are required")
    if layout == "source":
        paths = (ROOT / "source/Wildfire").glob("*.tla")
    else:
        suite = ROOT / "benchmark" / ("proof-from-scratch" if layout == "layered" else "proof-from-scratch-module")
        manifest = json.loads((suite / "manifest.json").read_text())
        entry = (
            manifest[TASK]
            if layout == "layered"
            else next(e for e in manifest["module_tasks"] if e["spec"]["task_id"] == SPEC)
        )
        paths = [suite / p for p in entry["context"]]
    for p in paths:
        shutil.copy2(p, directory / p.name)
    for p in FIXTURES.iterdir():
        if p.suffix in {".tla", ".cfg"}:
            shutil.copy2(p, directory / p.name)
    return jar


def run_tlc(directory, name, config=None):
    if config is not None:
        (directory / f"{name}.cfg").write_text(config)
    output = directory / "spec/output"
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "java",
            "-XX:ActiveProcessorCount=2",
            "-XX:+UseParallelGC",
            "-Xmx1g",
            "-cp",
            str(ROOT / "lib/tla2tools.jar"),
            "tlc2.TLC",
            "-workers",
            "1",
            "-metadir",
            str(output / "states"),
            "-config",
            f"{name}.cfg",
            f"{name}.tla",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=90,
    )
    text = result.stdout + result.stderr
    (output / "tlc.log").write_text(text)
    return result.returncode, text


@pytest.mark.parametrize("layout", ["source", "layered", "module"])
@pytest.mark.parametrize("litmus", ["LLSC", "ShadowEntry", "ProbeOrder"])
def test_repaired_litmus(tmp_path, layout, litmus):
    stage(tmp_path, layout)
    code, out = run_tlc(tmp_path, litmus)
    assert code == 0, out
    assert "No error has been found" in out, out
    assert "0 states left on queue" in out, out


@pytest.mark.parametrize(
    ("litmus", "invariant"),
    [
        ("LLSC", "No_LLSC_violation"),
        ("ShadowEntry", "No_shadow_entry_violation"),
        ("ProbeOrder", "No_probe_ordering_violation"),
    ],
)
def test_old_ordering_reproduces_forbidden_history(tmp_path, litmus, invariant):
    stage(tmp_path)
    path = tmp_path / "Wildfire.tla"
    text = path.read_text()
    if litmus == "LLSC":
        text = text.replace('(req.type \\in {"LL", "SC"}) =>', '(req.type = "LL") =>')
        text = text.replace('reqQ[p][i].type \\notin {"LL", "SC"}', 'reqQ[p][i].type # "LL"')
    else:
        # Probe ordering can also block the shadow-entry witness. Revert both
        # ordering changes for that historical witness; do not claim isolation.
        # Generated context drops comments, so identify the semantic clause.
        clause = '/\\ q = "GSToLS"\n     /\\ m1 \\in Q0Message\n     /\\ m2 \\in Inval \\cup ForwardedGet'
        start = text.index(clause)
        disjunction = text.rfind("\\/", 0, start)
        text = text[:disjunction] + text[start + len(clause) :]
        if litmus == "ShadowEntry":
            text = text.replace("m \\in fgetSet \\cup invalSet", "m \\in fgetSet")
    assert text != path.read_text()
    path.write_text(text)
    code, out = run_tlc(tmp_path, litmus)
    assert code == 12, out
    assert f"Invariant {invariant} is violated" in out, out


@pytest.mark.parametrize("sender_local", [False, True])
@pytest.mark.parametrize("shadowed", [False, True])
def test_victim_ack_routing(tmp_path, sender_local, shadowed):
    stage(tmp_path)
    config = (tmp_path / "ShadowEntry.cfg").read_text()
    config = config[: config.index("INVARIANT")].replace("SPECIFICATION VSpec", "INIT RoutingInit\nNEXT RoutingNext")
    config += (
        f"CONSTANTS SenderLocal = {str(sender_local).upper()} Shadowed = {str(shadowed).upper()}\n"
        "INVARIANT RoutingCorrect\nCHECK_DEADLOCK FALSE\n"
    )
    code, out = run_tlc(tmp_path, "VictimRouting", config)
    assert code == 0, out
    assert "2 distinct states found" in out, out


@pytest.mark.parametrize("operator", ["ProcLS", "AdrLS"])
def test_invalid_topology_is_rejected(tmp_path, operator):
    stage(tmp_path)
    (tmp_path / "InvalidTopology.tla").write_text(
        '---- MODULE InvalidTopology ----\nEXTENDS LLSC\nBadHome(x) == "outside"\n====\n'
    )
    config = (tmp_path / "LLSC.cfg").read_text().replace(f"{operator} <- V{operator}", f"{operator} <- BadHome")
    code, out = run_tlc(tmp_path, "InvalidTopology", config)
    assert code == 10, out
    assert "Assumption" in out and "is false" in out, out
    assert "Computing initial states" not in out, out


@pytest.mark.parametrize("layout", ["source", "layered", "module"])
def test_refinement_loads_in_tlapm(tmp_path, layout):
    tlapm = find_tlapm()
    if tlapm is None:
        pytest.skip("TLAPM is required")
    stage(tmp_path, layout)
    if layout == "source":
        task = ROOT / "source" / SPEC
    elif layout == "layered":
        task = ROOT / "benchmark/proof-from-scratch" / TASK
    else:
        task = ROOT / "benchmark/proof-from-scratch-module" / SPEC
    # Load the exact goal with an unresolved proof, without trying to prove it.
    (tmp_path / task.name).write_text(task.read_text().replace("PROOF OBVIOUS", "PROOF OMITTED"))
    result = subprocess.run(
        [tlapm, "--strict", "--nofp", "--threads", "1", task.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = result.stdout + result.stderr
    assert "1 omitted proof step(s)" in out, out
    assert "ending abnormally" not in out, out


def test_refinement_task_has_no_admitted_dependencies():
    suite = ROOT / "benchmark/proof-from-scratch-module"
    manifest = json.loads((suite / "manifest.json").read_text())
    entry = next(e for e in manifest["module_tasks"] if e["spec"]["task_id"] == SPEC)
    assert [u["task_id"] for u in entry["spec"]["proof_units"]] == [TASK]
    assert "(Spec /\\ []ResponseReceptive) => AlphaModel!Spec" in (suite / SPEC).read_text()
    for rel in entry["context"]:
        text = (suite / rel).read_text()
        assert "THEOREM" not in text and "PROOF OMITTED" not in text, rel
    alpha = next(suite / p for p in entry["context"] if p.endswith("/Alpha.tla"))
    assert "\\EE reqSeq, beforeOrder" in alpha.read_text()


def stage_response_environment(directory, layout):
    stage(directory, layout)
    definitions = {
        "source": "WildfireProof",
        "layered": "WildfireProof_RefinementDefs",
        "module": "WildfireProofDefs",
    }[layout]
    path = directory / "ResponseEnvironment.tla"
    path.write_text(path.read_text().replace("EXTENDS WildfireProofDefs", f"EXTENDS {definitions}"))
    return (directory / "ResponseEnvironment.cfg").read_text()


@pytest.mark.parametrize("layout", ["source", "layered", "module"])
def test_blocked_environment_reproduces_old_liveness_failure(tmp_path, layout):
    config = stage_response_environment(tmp_path, layout)
    config = config.replace("AcceptResponses = TRUE", "AcceptResponses = FALSE")
    config = config.replace("INVARIANT ResponseReceptive", "INVARIANT NotReceptive")
    config = config.replace("PROPERTY ConditionalCompletion", "PROPERTY Completion")
    code, out = run_tlc(tmp_path, "ResponseEnvironment", config)
    assert code == 13, out
    assert "Temporal property Completion was violated" in out, out
    assert "Stuttering" in out, out


@pytest.mark.parametrize("layout", ["source", "layered", "module"])
def test_blocked_environment_is_outside_the_repaired_premise(tmp_path, layout):
    config = stage_response_environment(tmp_path, layout)
    config = config.replace("AcceptResponses = TRUE", "AcceptResponses = FALSE")
    config = config.replace("INVARIANT ResponseReceptive", "INVARIANT NotReceptive")
    code, out = run_tlc(tmp_path, "ResponseEnvironment", config)
    assert code == 0, out
    assert "9 distinct states found" in out, out


@pytest.mark.parametrize("layout", ["source", "layered", "module"])
def test_receptive_environment_completes_under_original_fairness(tmp_path, layout):
    config = stage_response_environment(tmp_path, layout)
    code, out = run_tlc(tmp_path, "ResponseEnvironment", config)
    assert code == 0, out
    assert "13 distinct states found" in out, out
    assert "No error has been found" in out, out


@pytest.mark.parametrize("layout", ["source", "layered", "module"])
def test_receptiveness_does_not_assume_protocol_progress(tmp_path, layout):
    config = stage_response_environment(tmp_path, layout)
    path = tmp_path / "Wildfire.tla"
    text = path.read_text()
    fairness = "      /\\ WF_wVars((respQ[p] # <<>>) /\\ ProcSendResponse(p, 1))\n"
    assert text.count(fairness) == 1
    path.write_text(text.replace(fairness, ""))
    code, out = run_tlc(tmp_path, "ResponseEnvironment", config)
    assert code == 13, out
    assert "Temporal property ConditionalCompletion was violated" in out, out

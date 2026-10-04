"""Validate CCF's protocol premises and reachable safety scenarios."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source/CCF"
MODULE_SUITE = ROOT / "benchmark/proof-from-scratch-module"
FLAT_SUITE = ROOT / "benchmark/proof-from-scratch"
TASK = "CCF/CCFProof.tla"
GOALS = ("CommittedLogsAgree", "CommittedLogsAppendOnly")


def stage(directory, context):
    if context == "source":
        for name in ("CCFProof", "ccfraft", "Network", "abs"):
            shutil.copyfile(SOURCE / f"{name}.tla", directory / f"{name}.tla")
        module = "CCFProof"
    else:
        suite = MODULE_SUITE if context == "module" else FLAT_SUITE
        document = json.loads((suite / "manifest.json").read_text())
        if context == "module":
            entry = next(item for item in document["module_tasks"] if item["spec"]["task_id"] == TASK)
            task = TASK
        else:
            task = f"CCF/CCFProof_{context}.tla"
            entry = document[task]
        for relative in [task, *entry["context"]]:
            shutil.copyfile(suite / relative, directory / Path(relative).name)
        module = Path(task).stem
    config = (SOURCE / "validation/CCFProof.cfg").read_text()
    # These optional upstream diagnostics are intentionally not proof targets
    # and are pruned from generated task contexts.
    config = config.replace("    TypeInv\n", "").replace("    SignatureInv\n", "")
    if context == "CommittedLogsAgree":
        config = config.replace("PROPERTY CommittedLogAppendOnlyProp\n", "")
    elif context == "CommittedLogsAppendOnly":
        config = config.replace("INVARIANTS\n    LogInv\n", "")
    return module, config


def run_tlc(directory, module, config):
    jar = ROOT / "lib/tla2tools.jar"
    if not jar.is_file() or not shutil.which("java"):
        pytest.skip("Java and the pinned TLA+ tools are required")
    (directory / f"{module}.cfg").write_text(config)
    output = directory / "output"
    output.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "java",
            "-XX:ActiveProcessorCount=2",
            "-XX:+UseParallelGC",
            "-Xmx768m",
            "-Dtlc2.tool.impl.Tool.cdot=true",
            "-cp",
            f"{jar}:{ROOT / 'lib/community'}",
            "tlc2.TLC",
            "-workers",
            "1",
            "-metadir",
            str(output / "states"),
            "-config",
            f"{module}.cfg",
            f"{module}.tla",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = result.stdout + result.stderr
    (output / "tlc.log").write_text(text)
    return result.returncode, text


@pytest.mark.parametrize("context", ["source", "module", *GOALS])
@pytest.mark.parametrize("scenario", ["election", "retirement"])
def test_reconfiguration_election_and_retirement(tmp_path, context, scenario):
    module, config = stage(tmp_path, context)
    fixture = (ROOT / "tests/fixtures/ccf/CCFScenario.tla").read_text()
    (tmp_path / "CCFScenario.tla").write_text(fixture.replace("EXTENDS CCFProof", f"EXTENDS {module}"))
    config = config.replace("SPECIFICATION Spec", "SPECIFICATION ScenarioSpec")
    config += f'\nCONSTANTS First = n1 Second = n2 Scenario = "{scenario}"\n'
    config += "\nINVARIANT Outcome\nPROPERTY FollowsProtocol\n"
    code, text = run_tlc(tmp_path, "CCFScenario", config)
    assert code == 0, text
    assert "Model checking completed. No error has been found." in text, text
    assert "0 states left on queue" in text, text
    # A disabled step must not make the scenario pass vacuously.
    code, text = run_tlc(tmp_path, "CCFScenario", config + "\nINVARIANT NotDone\n")
    assert code != 0, text
    assert "Invariant NotDone is violated." in text, text


BAD_PARAMETERS = [
    ("Follower = L_Follower", "Follower = L_Leader"),
    ("Active = R_Active", "Active = R_RetirementOrdered"),
    ("RequestVoteRequest = M_RequestVoteRequest", "RequestVoteRequest = M_AppendEntriesRequest"),
    ("TypeEntry = T_Entry", "TypeEntry = T_Signature"),
    ("PreVoteEnabled = PV_PreVoteEnabled", "PreVoteEnabled = PV_PreVoteDisabled"),
    ("Ordered = N_Ordered", "Ordered = N_OrderedNoDup"),
    ("Guarantee = N_OrderedNoDup", "Guarantee = N_ReorderedNoDup"),
    ("Guarantee = N_OrderedNoDup", "Guarantee = UnknownNetwork"),
    ("Servers = {n1, n2, n3}", "Servers = {}"),
]


@pytest.mark.parametrize("context", ["source", "module"])
@pytest.mark.parametrize("old,new", BAD_PARAMETERS)
def test_invalid_protocol_parameters_are_rejected(tmp_path, context, old, new):
    module, config = stage(tmp_path, context)
    assert old in config
    code, text = run_tlc(tmp_path, module, config.replace(old, new))
    assert code != 0, text
    assert "Error: Assumption " in text and "is false" in text, text
    assert "Computing initial states" not in text, text


@pytest.mark.parametrize("context", ["source", "module"])
@pytest.mark.parametrize("servers", ["{n1}", "{n1, n2, n3, n4, n5}"])
def test_parameterized_initialization(tmp_path, context, servers):
    module, config = stage(tmp_path, context)
    (tmp_path / "InitProbe.tla").write_text(
        f"---- MODULE InitProbe ----\nEXTENDS {module}\nProbeNext == UNCHANGED vars\n====\n"
    )
    config = config.replace("SPECIFICATION Spec", "INIT Init\nNEXT ProbeNext")
    config = config.replace("Servers = {n1, n2, n3}", f"Servers = {servers}")
    code, text = run_tlc(tmp_path, "InitProbe", config)
    assert code == 0, text
    assert "Model checking completed. No error has been found." in text, text


@pytest.mark.parametrize("context", ["source", "module"])
@pytest.mark.parametrize("fault", ["agreement", "append_only"])
@pytest.mark.parametrize("corrupt", [False, True])
def test_safety_goals_reject_committed_log_corruption(tmp_path, context, fault, corrupt):
    module, config = stage(tmp_path, context)
    fixture = (ROOT / "tests/fixtures/ccf/CCFSafetyFault.tla").read_text()
    (tmp_path / "CCFSafetyFault.tla").write_text(fixture.replace("EXTENDS CCFProof", f"EXTENDS {module}"))
    config = config.replace("SPECIFICATION Spec", "SPECIFICATION FaultSpec")
    config += f'\nCONSTANTS First = n1 Second = n2 Fault = "{fault}" Corrupt = {str(corrupt).upper()}\n'
    code, text = run_tlc(tmp_path, "CCFSafetyFault", config)
    if corrupt:
        assert code != 0, text
        expected = "Invariant LogInv" if fault == "agreement" else "Action property CommittedLogAppendOnlyProp"
        assert f"{expected} is violated" in text, text
    else:
        assert code == 0, text
        assert "Model checking completed. No error has been found." in text, text


def test_upstream_bytes_and_two_targets():
    metadata = json.loads((SOURCE / "upstream.json").read_text())
    repairs = {entry["file"]: entry for entry in metadata.get("local_repairs", [])}
    for local, entry in metadata["files"].items():
        content = (SOURCE / local).read_bytes()
        if local in repairs:
            repair = repairs[local]
            assert hashlib.sha256(content).hexdigest() == repair["local_sha256"]
            for name in repair.get("named_assumptions", []):
                pattern = rb"(?m)^ASSUME " + re.escape(name.encode()) + rb" == "
                content, count = re.subn(pattern, b"ASSUME ", content)
                assert count == 1, name
            for name in repair.get("exported_operators", []):
                pattern = rb"(?m)^" + re.escape(name.encode()) + rb"(?=\s|\()"
                content, count = re.subn(pattern, lambda match: b"LOCAL " + match[0], content)
                assert count == 1, name
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
    for entry in metadata["licenses"]:
        assert hashlib.sha256((ROOT / entry["local_path"]).read_bytes()).hexdigest() == entry["sha256"]
    document = json.loads((MODULE_SUITE / "manifest.json").read_text())
    entry = next(item for item in document["module_tasks"] if item["spec"]["task_id"] == TASK)
    assert len(entry["spec"]["proof_units"]) == 2
    text = (MODULE_SUITE / TASK).read_text()
    assert re.findall(r"^THEOREM (\w+)", text, re.M) == list(GOALS)
    for relative in entry["context"]:
        text = (MODULE_SUITE / relative).read_text()
        assert not re.search(r"(?m)^\s*(THEOREM|LEMMA|PROOF|OMITTED)\b", text)


@pytest.mark.parametrize("context", ["module", *GOALS])
def test_tlapm_loads_context_and_network_premise(tmp_path, context):
    tlapm = find_tlapm()
    if tlapm is None or not (ROOT / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    module, _ = stage(tmp_path, context)
    # Use the immutable definition layer, without admitting the task goals.
    probe = tmp_path / "NetworkPremise.tla"
    probe.write_text(
        f"---- MODULE NetworkPremise ----\nEXTENDS {module}Defs\n"
        "LOCAL TL == INSTANCE TLAPS\nVARIABLE probeValue\n"
        "THEOREM ConfiguredNetwork == Guarantee = OrderedNoDup\n"
        "BY OrderedNetwork\n"
        "THEOREM CompositionSupport ==\n"
        "    probeValue \\in Nat /\\\n"
        "    ((probeValue' = probeValue + 1) \\cdot (probeValue' = probeValue + 1))\n"
        "    => probeValue' = probeValue + 2\n"
        "BY TL!SMT, TL!ExpandCdot, TL!AutoUSE\n====\n"
    )
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
            str(probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = result.stdout + result.stderr
    assert result.returncode == 0, text
    assert "All " in text and " obligations proved" in text, text


@pytest.mark.parametrize("context", ["source", "module", *GOALS])
@pytest.mark.parametrize(
    "module,proof",
    [
        (
            "ccfraft",
            "THEOREM ServerDomain == Servers /= {} /\\ IsFiniteSet(Servers)\nBY ServerSetAssumption\n",
        ),
        (
            "Network",
            "THEOREM GuaranteeDomain == Guarantee \\in {OrderedNoDup, Ordered, ReorderedNoDup, Reordered}\n"
            "BY NetworkGuaranteeAssumption\n",
        ),
        (
            "abs",
            "THEOREM ServerDomain == IsFiniteSet(Servers)\n"
            "BY FiniteServersAssumption\n"
            "THEOREM TermOrder == /\\ IsStrictlyTotallyOrderedUnder(<, Terms)\n"
            "                     /\\ \\E min \\in Terms : \\A t \\in Terms : min <= t\n"
            "BY OrderedTermsAssumption\n"
            "THEOREM InitialTerm == /\\ StartTerm \\in Terms\n"
            "                       /\\ \\A t \\in Terms : StartTerm <= t\n"
            "BY StartTermAssumption\n",
        ),
    ],
)
def test_upstream_assumptions_can_be_cited(tmp_path, context, module, proof):
    tlapm = find_tlapm()
    if tlapm is None or not (ROOT / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    stage(tmp_path, context)
    # Extend each owning module: INSTANCE does not import its assumptions.
    probe = tmp_path / "NamedAssumptions.tla"
    probe.write_text(f"---- MODULE NamedAssumptions ----\nEXTENDS {module}\n{proof}====\n")
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
            str(probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = result.stdout + result.stderr
    assert result.returncode == 0, text
    assert "All " in text and " obligations proved" in text, text


def check_network_visibility(directory, context, restore_local=False):
    tlapm = find_tlapm()
    if tlapm is None or not (ROOT / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    module, _ = stage(directory, context)
    if restore_local:
        metadata = json.loads((SOURCE / "upstream.json").read_text())
        repair = next(entry for entry in metadata["local_repairs"] if entry["file"] == "Network.tla")
        path = directory / "Network.tla"
        text = path.read_text()
        for name in repair["exported_operators"]:
            text = re.sub(r"(?m)^" + re.escape(name) + r"(?=\s|\()", "LOCAL " + name, text)
        path.write_text(text)
    fixture = (ROOT / "tests/fixtures/ccf/NetworkVisibility.tla").read_text()
    parent = "ccfraft" if context == "source" else f"{module}Defs"
    probe = directory / "NetworkVisibility.tla"
    probe.write_text(fixture.replace("EXTENDS CCFProofDefs", f"EXTENDS {parent}"))
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
            str(probe),
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=120,
    )
    text = result.stdout + result.stderr
    (directory / "network-visibility.log").write_text(text)
    return result.returncode, text


@pytest.mark.parametrize("context", ["source", "module", *GOALS])
def test_network_helpers_can_be_unfolded_in_proofs(tmp_path, context):
    code, text = check_network_visibility(tmp_path, context)
    assert code == 0, text
    assert "All " in text and " obligations proved" in text, text


@pytest.mark.parametrize("context", ["source", "module"])
def test_original_local_network_helpers_reproduce_the_proof_obstacle(tmp_path, context):
    code, text = check_network_visibility(tmp_path, context, restore_local=True)
    assert code != 0, text
    assert 'Operator "Network!OrderNoDupInitMessageVar" not found' in text, text

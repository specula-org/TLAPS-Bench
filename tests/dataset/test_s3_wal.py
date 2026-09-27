"""Check the WAL proof contexts, manifest repair, and parameter domains."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmark/proof-from-scratch-module"
SPECS = {
    "SlateDBWAL": ("SlateDBWAL", 4),
    "OSWALD": ("Oswald", 3),
    "Walgit": ("Walgit", 7),
}


def stage(directory, group, context="module", processes=2, values=1):
    name, _ = SPECS[group]
    if context == "source":
        for path in (ROOT / "source" / group).glob("*.tla"):
            shutil.copyfile(path, directory / path.name)
    else:
        document = json.loads((SUITE / "manifest.json").read_text())
        task_id = f"{group}/{name}Proof.tla"
        entry = next(item for item in document["module_tasks"] if item["spec"]["task_id"] == task_id)
        for relative in [task_id, *entry["context"]]:
            shutil.copyfile(SUITE / relative, directory / Path(relative).name)
    config = (ROOT / "source" / group / "validation" / f"{name}.cfg").read_text()
    process_set = "{" + ", ".join(f"p{i}" for i in range(processes)) + "}"
    value_set = "{" + ", ".join(f"v{i}" for i in range(values)) + "}"
    config = re.sub(r"(Writers|Replicas) = \{[^}]*\}", lambda m: f"{m[1]} = {process_set}", config)
    config = re.sub(r"GarbageCollectors = \{[^}]*\}", "GarbageCollectors = {gc0}", config)
    config = re.sub(r"Values = \{[^}]*\}", f"Values = {value_set}", config)
    config = re.sub(r"(?m)^SYMMETRY.*$", "", config)
    return name, config


def run_tlc(directory, name, config, module=None):
    jar = ROOT / "lib/tla2tools.jar"
    if not jar.is_file() or not shutil.which("java"):
        pytest.skip("Java and tla2tools.jar are required")
    module = module or f"{name}Proof"
    (directory / f"{module}.cfg").write_text(config)
    output = directory / "output"
    output.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "java",
            f"-DTLA-Library={ROOT / 'lib/community'}",
            "-XX:+UseParallelGC",
            "-Xmx2g",
            "-cp",
            str(jar),
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
        timeout=180,
    )
    text = result.stdout + result.stderr
    (output / "tlc.log").write_text(text)
    return result.returncode, text


@pytest.mark.parametrize("group", SPECS)
@pytest.mark.parametrize("context", ["source", "module"])
def test_selected_invariants_on_complete_small_instances(tmp_path, group, context):
    name, config = stage(tmp_path, group, context, values=2 if group == "Walgit" else 1)
    code, text = run_tlc(tmp_path, name, config)
    assert code == 0, text
    assert "Model checking completed. No error has been found." in text, text
    assert "0 states left on queue" in text, text


def replace_head_coverage(directory, replacement):
    path = directory / "Walgit.tla"
    text = path.read_text()
    start = text.index("    /\\ LET cpSeq ==", text.index("ValidManifest =="))
    end = text.index("    /\\ ~\\E s \\in manifest.logSegments", start)
    path.write_text(text[:start] + replacement + text[end:])


def test_original_manifest_requirement_fails_in_initial_state(tmp_path):
    name, config = stage(tmp_path, "Walgit", context="source", processes=1)
    replace_head_coverage(
        tmp_path,
        "    /\\ \\E s \\in manifest.logSegments : s.lastSeq = manifest.headSeq\n",
    )
    code, text = run_tlc(tmp_path, name, config)
    assert code != 0, text
    assert "Invariant ValidManifest is violated by the initial state" in text, text


def test_empty_log_exception_alone_still_fails_after_checkpoint(tmp_path):
    name, config = stage(tmp_path, "Walgit", context="source", processes=1)
    replace_head_coverage(
        tmp_path,
        "    /\\ (manifest.headSeq > 0 =>\n          \\E s \\in manifest.logSegments : s.lastSeq = manifest.headSeq)\n",
    )
    code, text = run_tlc(tmp_path, name, config)
    assert code != 0, text
    assert "Invariant ValidManifest is violated." in text, text
    assert "CommitCheckpoint" in text, text


def test_repaired_manifest_still_rejects_a_missing_tail_segment(tmp_path):
    name, config = stage(tmp_path, "Walgit", context="source", processes=1)
    path = tmp_path / "Walgit.tla"
    text = path.read_text()
    old = "!.logSegments = @ \\union {segRef}"
    assert text.count(old) == 1
    path.write_text(text.replace(old, "!.logSegments = {}"))
    code, text = run_tlc(tmp_path, name, config)
    assert code != 0, text
    assert "Invariant ValidManifest is violated." in text, text


@pytest.mark.parametrize("group", SPECS)
def test_empty_process_domain_is_rejected(tmp_path, group):
    name, config = stage(tmp_path, group, processes=0)
    code, text = run_tlc(tmp_path, name, config)
    assert code != 0, text
    assert "Error: Assumption " in text and "is false" in text, text
    assert "Computing initial states" not in text, text


@pytest.mark.parametrize("group", SPECS)
def test_colliding_control_labels_are_rejected(tmp_path, group):
    name, config = stage(tmp_path, group)
    other = "SNAPSHOT_RECOVERY" if group == "OSWALD" else "IDLE"
    config = config.replace("READY = READY", f"READY = {other}")
    code, text = run_tlc(tmp_path, name, config)
    assert code != 0, text
    assert "Error: Assumption " in text and "is false" in text, text
    assert "Computing initial states" not in text, text


def test_oswald_missing_chunk_sentinel_cannot_be_a_payload(tmp_path):
    name, config = stage(tmp_path, "OSWALD")
    code, text = run_tlc(tmp_path, name, config.replace("NIL = NIL", "NIL = v0"))
    assert code != 0, text
    assert "Error: Assumption " in text and "is false" in text, text
    assert "Computing initial states" not in text, text


@pytest.mark.parametrize(
    "group,sentinel,value",
    [
        ("SlateDBWAL", "NIL", "<<>>"),
        ("Walgit", "None", "[id |-> [seq |-> 1, attemptKey |-> 2], seq |-> 1]"),
    ],
)
def test_absence_sentinel_cannot_alias_a_stored_object(tmp_path, group, sentinel, value):
    name, config = stage(tmp_path, group)
    (tmp_path / "SentinelProbe.tla").write_text(
        f"---- MODULE SentinelProbe ----\nEXTENDS {name}Proof\nBadSentinel == {value}\n====\n"
    )
    config = config.replace(f"{sentinel} = {sentinel}", f"{sentinel} <- BadSentinel")
    code, text = run_tlc(tmp_path, name, config, module="SentinelProbe")
    assert code != 0, text
    assert "Error: Assumption " in text and "is false" in text, text
    assert "Computing initial states" not in text, text


def test_exactly_four_three_seven_targets_are_preserved():
    document = json.loads((SUITE / "manifest.json").read_text())
    for group, (name, count) in SPECS.items():
        task_id = f"{group}/{name}Proof.tla"
        entry = next(item for item in document["module_tasks"] if item["spec"]["task_id"] == task_id)
        assert len(entry["spec"]["proof_units"]) == count
        assert (SUITE / task_id).read_text().count("PROOF OMITTED") == count

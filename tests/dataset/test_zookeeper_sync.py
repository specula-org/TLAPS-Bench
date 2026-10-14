"""Interrupted snapshot replay against the original election and sync actions."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "lib"


@pytest.mark.parametrize("layout", ["source", "flat", "module"])
@pytest.mark.parametrize("scenario", ["leader-crash", "follower-crash", "partition", "completed"])
@pytest.mark.parametrize("restore", [True, False])
def test_snapshot_recovery(tmp_path, layout, scenario, restore):
    if not shutil.which("java") or not (LIB / "tla2tools.jar").is_file():
        pytest.skip("TLC dependencies are not installed")
    fixture = (REPO / "tests/fixtures/zookeeper_sync/SnapshotRecovery.tla").read_text()
    shutil.copyfile(REPO / "source/ZooKeeper_LowLevel/FastLeaderElection.tla", tmp_path / "FastLeaderElection.tla")
    if layout == "source":
        model = tmp_path / "ZkV3_7_0.tla"
        shutil.copyfile(REPO / "source/ZooKeeper_LowLevel/ZkV3_7_0.tla", model)
        fixture = fixture.replace("EXTENDS ZkV3_7_0Defs", "EXTENDS ZkV3_7_0")
    else:
        context = (
            REPO
            / "benchmark"
            / ("proof-from-scratch-module" if layout == "module" else "proof-from-scratch")
            / "ZooKeeper_LowLevel"
        )
        model = tmp_path / "ZkV3_7_0Model.tla"
        shutil.copyfile(context / "ZkV3_7_0Model.tla", model)
        if layout == "module":
            shutil.copyfile(context / "ZkV3_7_0Defs.tla", tmp_path / "ZkV3_7_0Defs.tla")
        else:
            fixture = fixture.replace("EXTENDS ZkV3_7_0Defs", "EXTENDS ZkV3_7_0Model")
    if not restore:
        text = model.read_text()
        assert "THEN connectInfo[s].backup.history ELSE history[s]" in text
        model.write_text(
            text.replace(
                "THEN connectInfo[s].backup.history ELSE history[s]", "THEN history[s] ELSE history[s]"
            ).replace(
                "THEN connectInfo[s].backup.committed ELSE lastCommitted[s]",
                "THEN lastCommitted[s] ELSE lastCommitted[s]",
            )
        )
    (tmp_path / "SnapshotRecovery.tla").write_text(fixture)
    config = f"""
CONSTANTS s1=s1 s2=s2 s3=s3 Server={{s1,s2,s3}} NullPoint=NullPoint MAXEPOCH=5
Scenario = "{scenario}"
Value <- MCValue
SPECIFICATION TraceSpec
CHECK_DEADLOCK FALSE
PROPERTY Spec Completed
INVARIANTS Restored KeptCompleted IndexBounds
"""
    if layout == "source":
        config += "INVARIANT TypeOK\n"
    if layout != "flat":
        config += "INVARIANTS Leadership1 Leadership2 PrefixConsistency Integrity Agreement TotalOrder LocalPrimaryOrder GlobalPrimaryOrder PrimaryIntegrity\n"
    (tmp_path / "SnapshotRecovery.cfg").write_text(config)
    cp = os.pathsep.join(str(LIB / name) for name in ["tla2tools.jar", "community", "tlapm"])
    result = subprocess.run(
        ["java", "-XX:+UseParallelGC", "-Xmx1g", "-cp", cp, "tlc2.TLC", "-workers", "1", "SnapshotRecovery"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    (tmp_path / "check.log").write_text(output)
    if not restore and scenario != "completed":
        assert result.returncode == 12, output
        assert "Invariant Restored is violated" in output
    else:
        assert result.returncode == 0, output
        assert "127 distinct states found" in output


@pytest.mark.parametrize("edge", ["reject", "truncate", "snapshot"])
def test_sync_handler_edges(tmp_path, edge):
    if not shutil.which("java") or not (LIB / "tla2tools.jar").is_file():
        pytest.skip("TLC dependencies are not installed")
    context = REPO / "benchmark/proof-from-scratch-module/ZooKeeper_LowLevel"
    for name in ["ZkV3_7_0Model.tla", "ZkV3_7_0Defs.tla"]:
        shutil.copyfile(context / name, tmp_path / name)
    shutil.copyfile(REPO / "source/ZooKeeper_LowLevel/FastLeaderElection.tla", tmp_path / "FastLeaderElection.tla")
    for name in ["SnapshotRecovery.tla", "HandlerEdges.tla"]:
        shutil.copyfile(REPO / "tests/fixtures/zookeeper_sync" / name, tmp_path / name)
    config = f'''CONSTANTS s1=s1 s2=s2 s3=s3 Server={{s1,s2,s3}} NullPoint=NullPoint MAXEPOCH=5
Scenario="completed"
Edge="{edge}"
Value <- MCValue
SPECIFICATION EdgeSpec
CHECK_DEADLOCK FALSE
PROPERTY HandlerRefinesNext EdgeCompletes
INVARIANTS Rejected Replaced IndexBounds
'''
    (tmp_path / "HandlerEdges.cfg").write_text(config)
    cp = os.pathsep.join(str(LIB / name) for name in ["tla2tools.jar", "community", "tlapm"])
    result = subprocess.run(
        ["java", "-XX:+UseParallelGC", "-Xmx1g", "-cp", cp, "tlc2.TLC", "-workers", "1", "HandlerEdges"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    (tmp_path / "check.log").write_text(output)
    assert result.returncode == 0, output
    assert "128 distinct states found" in output

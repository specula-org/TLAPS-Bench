"""Keep the queue's blocking predicate identical across TLA+ front ends."""

import shutil
import subprocess
from pathlib import Path

import pytest

from tlacore.tlapm.locate import find_tlapm

ROOT = Path(__file__).resolve().parents[2]
CONTEXTS = [
    "source/DiskStateQueue",
    "benchmark/proof-from-scratch/DiskStateQueue/DiskStateQueueProof_DeadlockFreedom",
    "benchmark/proof-from-scratch-module/DiskStateQueue/DiskStateQueueProof",
]


@pytest.mark.parametrize("context", CONTEXTS)
def test_blocked_preserves_thread_identities(tmp_path, context):
    tlapm = find_tlapm()
    if tlapm is None or not (ROOT / "lib/tlapm").is_dir():
        pytest.skip("TLAPM and the pinned proof libraries are required")
    shutil.copy2(ROOT / context / "DiskStateQueue.tla", tmp_path / "DiskStateQueue.tla")
    probe = tmp_path / "BlockedMeaning.tla"
    probe.write_text(
        r"""---- MODULE BlockedMeaning ----
EXTENDS DiskStateQueue
LOCAL TL == INSTANCE TLAPS
THEOREM BlockedKeepsThreads ==
    Blocked =
      (UNION {waiters[m] : m \in Monitors}) \cup
      {p \in Threads :
        \/ \E m \in Monitors : RequiredMonitor(p, m) /\ ~CanAcquire(p, m)
        \/ p = Cleaner /\ ~cleaner.done /\ ~cleaner.ready}
BY TL!SMTT("r1") DEF Blocked
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
            str(ROOT / "lib/tlapm"),
            "-I",
            str(ROOT / "lib/community"),
            str(probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All 2 obligations proved" in result.stdout + result.stderr

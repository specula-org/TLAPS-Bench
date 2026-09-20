"""Timeout cleanup — `run_killgroup` must kill tlapm's escaped backends.

tlapm's Isabelle backend `setsid`s into its own session, so `killpg` alone
leaves polyml and any z3 it holds running. The reaper snapshots the PPid chain
before killing, which needs a portable `pid -> ppid` source.

Run: PYTHONPATH=src python3 -m pytest tests/common/test_process_reaping.py
"""

import os
import subprocess
import sys
import time

import pytest

from common import check_proof
from common.check_proof import _descendant_pids, _parent_pids


def test_parent_map_reports_this_process_chain():
    parents = _parent_pids()
    assert parents, "the reaper cannot find escapees without a process table"
    assert parents.get(os.getpid()) == os.getppid()


def test_parent_map_falls_back_when_proc_is_absent(monkeypatch):
    """Regression: reading /proc unconditionally crashed the timeout handler.

    On a platform without /proc (macOS) the FileNotFoundError escaped
    `run_killgroup`'s `except TimeoutExpired` block, so the first tlapm timeout
    aborted the whole run — a dataset generation died mid-gate instead of
    recording one slow task.
    """
    monkeypatch.setattr(check_proof.os.path, "isdir", lambda path: False if path == "/proc" else os.path.isdir(path))
    parents = _parent_pids()
    assert parents.get(os.getpid()) == os.getppid()


def test_descendants_are_found_leaves_first():
    child = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & wait"])
    try:
        time.sleep(0.5)  # let the shell fork its own `sleep`
        descendants = _descendant_pids(os.getpid())
        assert child.pid in descendants, "a direct child must be reapable"
        grandchildren = [pid for pid in descendants if pid != child.pid]
        if grandchildren:
            assert descendants.index(grandchildren[0]) < descendants.index(child.pid), "leaves die first"
    finally:
        child.kill()
        child.wait()


def test_interrupt_kills_running_verifier_before_check_can_resume(tmp_path, monkeypatch):
    real_popen = subprocess.Popen
    processes = []

    def interrupted_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        communicate = process.communicate
        first = True

        def interrupted(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                raise KeyboardInterrupt
            return communicate(*args, **kwargs)

        process.communicate = interrupted
        return process

    monkeypatch.setattr(check_proof.subprocess, "Popen", interrupted_popen)
    with pytest.raises(KeyboardInterrupt):
        check_proof.run_killgroup([sys.executable, "-c", "import time; time.sleep(30)"], 60, str(tmp_path))
    assert len(processes) == 1 and processes[0].poll() is not None

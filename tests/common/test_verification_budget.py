"""Short real-process checks for examination budgets and nested CPU limits."""

import json
import os
import subprocess
import sys
import time

import pytest

from common.verification_budget import (
    POLICY_ENV,
    CheckSession,
    VerificationPolicy,
    cpu_command,
    policy_for_check,
    scaled_timeout,
)


@pytest.mark.parametrize("count,multiplier", [(1, 1), (2, 1.25), (3, 1.5), (5, 2), (9, 3), (100, 3)])
def test_formula(count, multiplier):
    assert scaled_timeout(3600, count) == 3600 * multiplier


@pytest.mark.parametrize("base,count,expected", [(1, 2, 2), (3, 2, 4), (5, 3, 8), (1, 9, 3)])
def test_rounding(base, count, expected):
    assert scaled_timeout(base, count) == expected


@pytest.mark.parametrize("base,count", [(0, 1), (-1, 1), (1, 0), (1, -1), (True, 1), (1, True), (1.5, 1), (1, 1.5)])
def test_invalid_formula_arguments(base, count):
    with pytest.raises(ValueError):
        scaled_timeout(base, count)


@pytest.mark.parametrize("cpus", [0, -1, 9, 1.5, True])
def test_invalid_cpu_caps(cpus):
    with pytest.raises(ValueError):
        VerificationPolicy.create(60, ("A",), cpus)


def test_checker_consumes_effective_budget_without_scaling_again(monkeypatch):
    policy = VerificationPolicy.create(3600, ("A", "B", "C", "D", "E"))
    monkeypatch.setenv(POLICY_ENV, json.dumps(policy.as_dict()))
    checked = policy_for_check(7200, policy.proof_unit_ids)
    assert checked == policy
    assert checked.as_dict()["local_limits"] is None
    with pytest.raises(ValueError, match="frozen"):
        policy_for_check(14400, policy.proof_unit_ids)


def test_examinations_are_independent_but_resume_spends_remaining_budget(tmp_path):
    identity = {"candidate": "same"}
    with CheckSession(tmp_path / "self-check", identity, 0.4) as session:
        time.sleep(0.13)
        remaining = session.remaining()
    with CheckSession(tmp_path / "self-check", identity, 0.4) as session:
        assert 0 < session.remaining() <= remaining
        time.sleep(session.remaining() + 0.01)
        assert session.remaining() == 0
    for name in ("grader", "next-self-check"):
        with CheckSession(tmp_path / name, identity, 0.4) as session:
            assert session.remaining() > 0.3
    with CheckSession(tmp_path / "self-check", identity, 0.4) as session:
        assert session.remaining() == 0


@pytest.mark.parametrize("field", ["candidate", "canonical", "toolchain", "policy"])
def test_incompatible_resume_is_rejected(tmp_path, field):
    identity = dict.fromkeys(("candidate", "canonical", "toolchain", "policy"), "original")
    with CheckSession(tmp_path, identity, 1):
        pass
    with (
        pytest.raises(ValueError, match="different candidate"),
        CheckSession(tmp_path, {**identity, field: "changed"}, 1),
    ):
        pass


def test_concurrent_resume_is_rejected(tmp_path):
    with CheckSession(tmp_path, {}, 1), pytest.raises(BlockingIOError), CheckSession(tmp_path, {}, 1):
        pass


def test_hard_restart_does_not_erase_unfinished_check_time(tmp_path):
    script = """
import sys, time
from pathlib import Path
from common.verification_budget import CheckSession
with CheckSession(Path(sys.argv[1]), {}, 1) as session:
    print('started', flush=True)
    time.sleep(30)
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "started"
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    with CheckSession(tmp_path, {}, 1) as session:
        assert session.remaining() <= 0.8
        assert session.metrics()["cpu_complete"] is False


@pytest.mark.skipif(not hasattr(os, "sched_getaffinity"), reason="Linux native containment")
def test_cpu_limit_is_inherited_by_nested_workers():
    script = """
import os, subprocess, sys
print(len(os.sched_getaffinity(0)), flush=True)
subprocess.run([sys.executable, '-c', 'import os; print(len(os.sched_getaffinity(0)))'], check=True)
"""
    result = subprocess.run(
        cpu_command([sys.executable, "-c", script], 2, "one-module"),
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    assert all(0 < int(line) <= 2 for line in result.stdout.splitlines())


def test_records_wall_and_reaped_child_cpu_time(tmp_path):
    with CheckSession(tmp_path, {}, 2) as session:
        subprocess.run(
            [sys.executable, "-c", "import time; t=time.process_time();\nwhile time.process_time()-t < .1: pass"],
            check=True,
            timeout=2,
        )
        metrics = session.metrics()
        assert metrics["cpu_secs"] >= 0.1
        assert metrics["wall_secs"] >= 0.1
        assert metrics["cpu_complete"]

"""Opt-in local Docker freezer smoke; uses no model or network requests."""

import json
import os
import select
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from common.active_clock import CLOCK_ENV, CLOCK_LABEL, CLOCK_MOUNT, ActiveClock
from common.container import ContainerConfig, ContainerRunner
from common.pause_control import control


@pytest.mark.skipif(os.environ.get("TLAPS_TEST_DOCKER_PAUSE") != "1", reason="opt-in Docker freezer smoke")
def test_real_docker_pause_preserves_running_checker_budget(tmp_path):
    clock = ActiveClock.create(tmp_path / "clock")
    name = "tlaps-pause-test-" + uuid.uuid4().hex[:10]
    repo = Path(__file__).resolve().parents[2]
    script = """
import json, sys
from pathlib import Path
from common.verification_budget import CheckSession
from common.check_proof import run_killgroup
with CheckSession(Path('/tmp/check'), {}, 3) as session:
    print('ready', flush=True)
    out, err, rc = run_killgroup(
        [sys.executable, '-c',
         'import time; start=time.process_time();\\nwhile time.process_time()-start < 1.5: pass'],
        session.remaining(), '/tmp')
    assert rc == 0, (out, err)
    assert session.remaining() > 0
    print(json.dumps(session.metrics()), flush=True)
"""
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--label",
        f"{CLOCK_LABEL}={clock.path.parent}",
        "-v",
        f"{clock.path.parent}:{CLOCK_MOUNT}:ro",
        "-v",
        f"{repo / 'src'}:/code:ro",
        "-e",
        "PYTHONPATH=/code",
        "-e",
        f"{CLOCK_ENV}={CLOCK_MOUNT}/state.json",
        "--entrypoint",
        "python3",
        os.environ.get("TLAPS_PAUSE_TEST_IMAGE", "tlaps-bench-base:latest"),
        "-c",
        script,
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 20)
        assert ready, "container did not start"
        first_line = process.stdout.readline().strip()
        assert first_line == "ready", (first_line, process.stderr.read())
        time.sleep(0.1)
        assert control(name, pause=True) == "paused"
        time.sleep(4)
        assert control(name, pause=False) == "resumed"
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        metrics = json.loads(stdout.strip())
        assert metrics["wall_secs"] > 4
        assert metrics["paused_secs"] >= 4
        assert 1 < metrics["active_secs"] < 3
        assert metrics["wall_secs"] == pytest.approx(metrics["active_secs"] + metrics["paused_secs"])
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


@pytest.mark.skipif(os.environ.get("TLAPS_TEST_DOCKER_PAUSE") != "1", reason="opt-in Docker freezer smoke")
def test_host_container_wait_and_checker_share_the_active_clock(tmp_path):
    name = "tlaps-pause-host-test-" + uuid.uuid4().hex[:10]
    repo = Path(__file__).resolve().parents[2]
    clock = ActiveClock.create(tmp_path / "clock")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ready = workspace / "ready"
    script = """
import json, sys
from pathlib import Path
from common.verification_budget import CheckSession
from common.check_proof import run_killgroup
with CheckSession(Path('/tmp/check'), {}, 3) as session:
    Path('/workspace/ready').touch()
    out, err, rc = run_killgroup(
        [sys.executable, '-c',
         'import time; start=time.process_time();\\nwhile time.process_time()-start < 1.5: pass'],
        session.remaining(), '/tmp')
    assert rc == 0, (out, err)
    print(json.dumps(session.metrics()), flush=True)
"""

    def quota_guard():
        deadline = time.monotonic() + 15
        while not ready.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("test child did not start")
            time.sleep(0.02)
        control(name, pause=True)
        time.sleep(4)
        control(name, pause=False)

    config = ContainerConfig(
        image=os.environ.get("TLAPS_PAUSE_TEST_IMAGE", "tlaps-bench-base:latest"),
        workspace=str(workspace),
        read_only_files=[(str(repo / "src"), "/code")],
        env={"PYTHONPATH": "/code"},
        keep_container=True,
        container_name=name,
        pause_accounting=True,
        active_clock=clock,
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            guard = executor.submit(quota_guard)
            code, stdout, stderr = ContainerRunner().run_with_output(
                config,
                ["python3", "-c", script],
                timeout=3,
            )
            guard.result(timeout=10)
        assert code == 0, stderr
        metrics = json.loads(stdout.strip())
        assert metrics["wall_secs"] > 4
        assert metrics["paused_secs"] >= 4
        assert 1 < metrics["active_secs"] < 3
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)

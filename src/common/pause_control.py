"""Host-only, durable pause/resume control for benchmark containers."""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import time
from pathlib import Path

from common.active_clock import CLOCK_LABEL, CLOCK_MOUNT, ActiveClock, write_state


def inspect_container(name: str) -> dict:
    completed = subprocess.run(
        ["docker", "inspect", "--", name], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(completed.stdout)[0]


def control(name: str, *, pause: bool) -> str:
    info = inspect_container(name)
    directory = info["Config"].get("Labels", {}).get(CLOCK_LABEL)
    if not directory:
        raise ValueError(
            "container has no managed active clock; requires a new Linux-host run with a rebuilt checker image"
        )
    if not any(
        mount.get("Source") == directory and mount.get("Destination") == CLOCK_MOUNT and mount.get("RW") is False
        for mount in info.get("Mounts", [])
    ):
        raise ValueError("container has no read-only active-clock mount")
    clock = ActiveClock(Path(directory) / "state.json")
    with (Path(directory) / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = clock.read_state()
        clock._read_snapshot()  # Already holding the exclusive controller lock.
        if not state["pause_supported"]:
            raise ValueError("this backend propagates absolute deadlines and does not support managed pauses")
        info = inspect_container(info["Id"])
        if not info["State"]["Running"]:
            raise ValueError("container is not running")
        frozen = info["State"]["Paused"]
        recorded = bool(state["pauses"] and state["pauses"][-1][1] is None)
        if recorded and not frozen:
            raise ValueError("container was thawed outside the pause controller; accounting is invalid")
        if pause:
            if recorded:
                return "already paused"
            if not frozen:
                subprocess.run(["docker", "pause", info["Id"]], check=True, capture_output=True, timeout=30)
            # Freeze first. A controller crash before this write conservatively
            # charges the gap until recovery rather than granting free runtime.
            state["pauses"].append([time.monotonic(), None])
            write_state(clock.path, state)
            return "paused" if not frozen else "paused; unrecorded frozen time before recovery remains charged"
        if not frozen:
            return "already running"
        if recorded:
            # Publish the complete interval BEFORE unpause: no checker can wake
            # and accidentally charge the entire frozen interval against its budget.
            state["pauses"][-1][1] = time.monotonic()
            write_state(clock.path, state)
        subprocess.run(["docker", "unpause", info["Id"]], check=True, capture_output=True, timeout=30)
        return "resumed" if recorded else "resumed; unrecorded frozen time remains charged"


def main(*, pause: bool) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("container", help="benchmark Docker container name or ID")
    args = parser.parse_args()
    try:
        print(control(args.container, pause=pause))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"pause control failed: {exc}\n")

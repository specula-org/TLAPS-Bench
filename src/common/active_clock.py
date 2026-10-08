"""Elapsed wall time minus explicitly recorded, host-controlled container pauses."""

from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

CLOCK_ENV = "TLAPS_ACTIVE_CLOCK"
CLOCK_MOUNT = "/run/tlaps-bench-clock"
CLOCK_LABEL = "org.specula.tlaps-bench.active-clock"
POLL_SECS = 0.1


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def write_state(path: Path, state: dict) -> None:
    """Publish before thawing; fsync both the file and its directory."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(state, stream, allow_nan=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ClockReading:
    wall: float
    paused: float

    @property
    def active(self) -> float:
        return self.wall - self.paused


class ActiveClock:
    def __init__(self, path: Path | None = None, *, verify_host_boot: bool = True):
        self.path = path
        self._host_reader = verify_host_boot
        self._boot_id = boot_id() if path and verify_host_boot else None

    @classmethod
    def from_environment(cls):
        value = os.environ.get(CLOCK_ENV)
        # A container's proc namespace can expose a different boot ID even
        # while sharing CLOCK_MONOTONIC with the host. The host controller
        # validates the host boot; readers pin the ledger's initial identity.
        return cls(Path(value) if value else None, verify_host_boot=False)

    @classmethod
    def create(cls, directory: Path, *, pause_supported: bool = True):
        directory.mkdir(parents=True, exist_ok=False)
        directory.chmod(0o755)
        path = directory / "state.json"
        (directory / "control.lock").touch(mode=0o644)
        write_state(
            path,
            {
                "version": 1,
                "boot_id": boot_id(),
                "pauses": [],
                "pause_supported": pause_supported,
                "monotonic_origin": time.monotonic(),
                "wall_origin": time.time(),
            },
        )
        return cls(path)

    def read_state(self) -> dict:
        try:
            state = json.loads(self.path.read_text())
            if state["version"] != 1 or not isinstance(state["boot_id"], str) or not state["boot_id"]:
                raise ValueError("incompatible clock or host reboot")
            if self._boot_id is None:
                self._boot_id = state["boot_id"]
            elif state["boot_id"] != self._boot_id:
                raise ValueError("incompatible clock or host reboot")
            if type(state["pause_supported"]) is not bool or type(state["pauses"]) is not list:
                raise ValueError("invalid pause ledger")
            for field in ("monotonic_origin", "wall_origin"):
                if type(state[field]) not in (float, int) or not math.isfinite(state[field]):
                    raise ValueError("invalid clock origin")
            previous = 0.0
            for index, interval in enumerate(state["pauses"]):
                start, end = interval
                if type(start) not in (float, int) or not math.isfinite(start) or start < previous:
                    raise ValueError("invalid pause start")
                if end is None:
                    if index != len(state["pauses"]) - 1:
                        raise ValueError("unfinished pause is not last")
                elif type(end) not in (float, int) or not math.isfinite(end) or end < start:
                    raise ValueError("invalid pause end")
                previous = end if end is not None else start
            return state
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise OSError(f"cannot read trusted active clock: {exc}") from exc

    def read(self) -> ClockReading:
        if self.path is None:
            return ClockReading(time.monotonic(), 0.0)
        if self._host_reader:
            # Host observations must not race a controller's sampled timestamp
            # and its durable publication. Container readers cannot take this
            # lock: freezing a shared-lock holder would deadlock the controller.
            with (self.path.parent / "control.lock").open("r") as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                return self._read_snapshot()
        return self._read_snapshot()

    def _read_snapshot(self) -> ClockReading:
        # A container may freeze between *any* two instructions, including
        # between reading the ledger and sampling monotonic. Verify the same
        # durable state on both sides of the timestamp before using it.
        while True:
            state = self.read_state()
            now = time.monotonic()
            wall = time.time()
            if state == self.read_state():
                break
        if abs((now - state["monotonic_origin"]) - (wall - state["wall_origin"])) > 5:
            raise OSError("active clock has a different monotonic epoch or the host wall clock changed by over 5s")
        paused = 0.0
        for start, end in state["pauses"]:
            if start > now or (end is not None and end > now):
                raise OSError("active-clock interval lies in the future")
            paused += (now if end is None else end) - start
        return ClockReading(now, paused)

    def now(self) -> float:
        return self.read().active


def communicate(proc, timeout, *, clock: ActiveClock | None = None, input=None):
    """Drain pipes while bounding active elapsed, including ordinary idle/API waits.

    A short wall-clock poll may expire while the container is frozen. Recheck
    the host ledger before deciding that the actual budget has expired.
    """
    clock = clock or ActiveClock.from_environment()
    if clock.path is None or timeout is None:
        return proc.communicate(input=input, timeout=timeout)
    deadline = clock.now() + timeout
    while True:
        remaining = deadline - clock.now()
        try:
            return proc.communicate(input=input, timeout=max(0, min(POLL_SECS, remaining)))
        except subprocess.TimeoutExpired as exc:
            input = None  # Popen retains partially written input across calls.
            if clock.now() >= deadline:
                raise subprocess.TimeoutExpired(exc.cmd, timeout, output=exc.output, stderr=exc.stderr) from exc

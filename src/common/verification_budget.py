"""Per-examination PFS budgets, CPU containment, and durable check progress."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import resource
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

POLICY_VERSION = "pfs-module-budget-v1"
POLICY_ENV = "TLAPS_VERIFICATION_POLICY"
TOOLCHAIN_ENV = "TLAPS_VERIFICATION_TOOLCHAIN"
VERIFICATION_RESULT_PREFIX = "VERIFICATION-RESULT: "
DEFAULT_CPUS = 8
HEARTBEAT_SECS = 0.25


def validate_cpus(cpus: int) -> None:
    if type(cpus) is not int or not 1 <= cpus <= DEFAULT_CPUS:
        raise ValueError("PFS check CPUs must be an integer from 1 to 8")


@dataclass(frozen=True)
class VerificationPolicy:
    base_timeout_secs: int | None
    proof_unit_ids: tuple[str, ...]
    effective_timeout_secs: int
    cpus: int = DEFAULT_CPUS
    version: str = POLICY_VERSION

    def __post_init__(self):
        if self.version != POLICY_VERSION:
            raise ValueError("incompatible PFS verification policy version")
        if not self.proof_unit_ids or any(type(x) is not str or not x for x in self.proof_unit_ids):
            raise ValueError("PFS verification requires selected original proof-unit IDs")
        if len(set(self.proof_unit_ids)) != len(self.proof_unit_ids):
            raise ValueError("PFS proof-unit IDs must be unique")
        if type(self.effective_timeout_secs) is not int or self.effective_timeout_secs <= 0:
            raise ValueError("PFS check timeout must be a positive integer")
        validate_cpus(self.cpus)
        if self.base_timeout_secs is not None:
            expected = scaled_timeout(self.base_timeout_secs, len(self.proof_unit_ids))
            if self.effective_timeout_secs != expected:
                raise ValueError("PFS effective timeout does not match its frozen base and target count")

    @classmethod
    def create(cls, base_timeout: int, proof_unit_ids, cpus: int = DEFAULT_CPUS):
        ids = tuple(proof_unit_ids)
        return cls(base_timeout, ids, scaled_timeout(base_timeout, len(ids)), cpus)

    def as_dict(self):
        return {
            **asdict(self),
            "proof_unit_ids": list(self.proof_unit_ids),
            "target_count": len(self.proof_unit_ids),
            "local_limits": None,
        }

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or type(value.get("target_count")) is not int:
            raise ValueError("invalid PFS verification policy")
        try:
            policy = cls(
                value["base_timeout_secs"],
                tuple(value["proof_unit_ids"]),
                value["effective_timeout_secs"],
                value["cpus"],
                value["version"],
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("invalid PFS verification policy") from exc
        if policy.as_dict() != value:
            raise ValueError("invalid PFS verification policy fields")
        return policy


def scaled_timeout(base: int, targets: int) -> int:
    if type(base) is not int or base <= 0:
        raise ValueError("PFS --check-timeout must be a positive integer")
    if type(targets) is not int or targets <= 0:
        raise ValueError("PFS target count must be a positive integer")
    # Exact integer arithmetic: ceil(base * min((N + 3) / 4, 3)).
    return (base * min(targets + 3, 12) + 3) // 4


def policy_for_check(timeout: int, proof_unit_ids, cpus: int | None = None) -> VerificationPolicy:
    raw = os.environ.get(POLICY_ENV)
    if raw:
        policy = VerificationPolicy.from_dict(json.loads(raw))
        if tuple(proof_unit_ids) != policy.proof_unit_ids or timeout != policy.effective_timeout_secs:
            raise ValueError("checker inputs differ from the runner's frozen verification policy")
        if cpus is not None and cpus != policy.cpus:
            raise ValueError("checker CPUs differ from the runner's frozen verification policy")
        return policy
    # Standalone checker --timeout is already effective, never scale it here.
    return VerificationPolicy(None, tuple(proof_unit_ids), timeout, DEFAULT_CPUS if cpus is None else cpus)


def cpu_set(cpus: int, key: str) -> list[int]:
    validate_cpus(cpus)
    if not hasattr(os, "sched_getaffinity"):
        raise ValueError("native PFS CPU containment requires Linux; use the Docker runner on this platform")
    available = sorted(os.sched_getaffinity(0))
    count = min(cpus, len(available))
    # Spread independent modules across a large host; never pin every module
    # to the same first eight CPUs. Affinity is inherited by nested processes.
    offset = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(available)
    return sorted(available[(offset + i) % len(available)] for i in range(count))


def cpu_command(command: list[str], cpus: int, key: str) -> list[str]:
    taskset = shutil.which("taskset")
    if not taskset:
        raise ValueError("native PFS CPU containment requires taskset; use the Docker runner")
    return [taskset, "--cpu-list", ",".join(map(str, cpu_set(cpus, key))), *command]


@contextlib.contextmanager
def cpu_limit(cpus: int, key: str):
    selected = cpu_set(cpus, key)
    previous = os.sched_getaffinity(0)
    os.sched_setaffinity(0, selected)
    try:
        yield
    finally:
        os.sched_setaffinity(0, previous)


def cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def content_digest(paths) -> str:
    digest = hashlib.sha256()
    for name, path in sorted(paths):
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        with Path(path).open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class CheckSession:
    """One examination, optionally resumed, never a candidate lifetime quota.

    An exclusive lock prevents simultaneous resumes. A write-ahead heartbeat
    charges at most one extra tick on a hard crash, so repeated restarts cannot
    obtain free checking time. Graceful exits reconcile to measured wall time.
    Completed units and SANY dumps are stored only within this input-bound
    session; a new examination starts with its own budget and cache namespace.
    """

    def __init__(self, directory: Path, identity: dict, timeout: float):
        self.directory = directory
        self.identity = identity
        self.timeout = timeout
        self._mutex = threading.RLock()
        self._stop = threading.Event()
        self._error = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = (self.directory / "lock").open("a")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.path = self.directory / "state.json"
            if self.path.exists():
                self.state = json.loads(self.path.read_text())
                if (
                    type(self.state) is not dict
                    or not {"identity", "wall_secs", "cpu_secs", "cpu_complete", "active"} <= self.state.keys()
                ):
                    raise ValueError("invalid check-session state")
                if type(self.state["cpu_complete"]) is not bool or type(self.state["active"]) is not bool:
                    raise ValueError("invalid check-session state flags")
                if self.state.get("identity") != self.identity:
                    raise ValueError("cannot resume check with different candidate, canonical inputs, tools, or policy")
                for field in ("wall_secs", "cpu_secs"):
                    value = self.state[field]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError(f"invalid check-session {field}")
                if self.state.get("active"):
                    self.state["cpu_complete"] = False
            else:
                self.state = {"identity": self.identity, "wall_secs": 0.0, "cpu_secs": 0.0, "cpu_complete": True}
            self.prior_wall = self.state["wall_secs"]
            self.prior_cpu = self.state["cpu_secs"]
            self.started = time.monotonic()
            self.cpu_started = cpu_seconds()
            self.deadline = self.started + max(0, self.timeout - self.prior_wall)
            self._save(active=True)
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()
            return self
        except BaseException:
            self._lock.close()
            raise

    def _save(self, *, active: bool):
        with self._mutex:
            wall = self.prior_wall + time.monotonic() - self.started
            self.state.update(
                wall_secs=wall + (min(HEARTBEAT_SECS, max(0, self.timeout - wall)) if active else 0),
                cpu_secs=self.prior_cpu + max(0, cpu_seconds() - self.cpu_started),
                active=active,
            )
            atomic_json(self.path, self.state)

    def _heartbeat(self):
        while not self._stop.wait(HEARTBEAT_SECS):
            try:
                self._save(active=True)
            except Exception as exc:
                self._error = exc
                return

    def remaining(self) -> float:
        if self._error:
            raise OSError(f"cannot persist check budget: {self._error}")
        return max(0, self.deadline - time.monotonic())

    def metrics(self) -> dict:
        return {
            "wall_secs": self.prior_wall + time.monotonic() - self.started,
            "cpu_secs": self.prior_cpu + max(0, cpu_seconds() - self.cpu_started),
            "cpu_complete": self.state["cpu_complete"],
            "cpu_source": "getrusage_self_and_reaped_children",
        }

    def load(self, name: str):
        path = self.directory / f"{name}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def save(self, name: str, value):
        self.remaining()
        atomic_json(self.directory / f"{name}.json", value)

    def __exit__(self, *_exc):
        self._stop.set()
        self._thread.join()
        try:
            self._save(active=False)
            if self._error:
                raise OSError(f"cannot persist check budget: {self._error}")
        finally:
            self._lock.close()

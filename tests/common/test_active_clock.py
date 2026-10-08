"""Managed pauses preserve active deadlines without exempting ordinary waits."""

import copy
import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from common import active_clock, container, pause_control
from common.active_clock import CLOCK_ENV, CLOCK_LABEL, CLOCK_MOUNT, ActiveClock, communicate, write_state
from common.container import ContainerConfig, ContainerRunner
from common.verification_budget import CheckSession


@pytest.fixture
def controlled_clock(tmp_path, monkeypatch):
    now = SimpleNamespace(value=1000.0)
    monkeypatch.setattr(active_clock.time, "monotonic", lambda: now.value)
    monkeypatch.setattr(active_clock.time, "time", lambda: now.value + 1700000000)
    clock = ActiveClock.create(tmp_path / "clock")
    monkeypatch.setenv(CLOCK_ENV, str(clock.path))
    return clock, now


def add_pause(clock, start, end):
    state = clock.read_state()
    state["pauses"].append([start, end])
    write_state(clock.path, state)


def test_multiple_pauses_cross_deadline_but_do_not_spend_check_budget(controlled_clock, tmp_path):
    clock, now = controlled_clock
    with CheckSession(tmp_path / "session", {}, 10) as session:
        now.value += 2
        add_pause(clock, now.value, now.value + 100)
        now.value += 103
        add_pause(clock, now.value, now.value + 200)
        now.value += 200
        assert session.remaining() == 5
        metrics = session.metrics()
        assert metrics["wall_secs"] == 305
        assert metrics["paused_secs"] == 300
        assert metrics["active_secs"] == 5
    with CheckSession(tmp_path / "session", {}, 10) as resumed:
        assert resumed.remaining() == 5
        now.value += 5
        assert resumed.remaining() == 0
        assert resumed.metrics()["active_secs"] == 10


def test_freeze_between_ledger_read_and_timestamp_does_not_charge_pause(controlled_clock, monkeypatch):
    clock, now = controlled_clock
    read_state = clock.read_state
    calls = 0

    def freeze_after_read():
        nonlocal calls
        calls += 1
        state = read_state()
        if calls == 1:
            updated = copy.deepcopy(state)
            updated["pauses"].append([now.value, now.value + 100])
            write_state(clock.path, updated)
            now.value += 100
        return state

    monkeypatch.setattr(clock, "read_state", freeze_after_read)
    assert clock.now() == 1000
    assert calls == 4


def test_active_idle_counts_and_no_ledger_keeps_legacy_clock(tmp_path, monkeypatch):
    monkeypatch.delenv(CLOCK_ENV, raising=False)
    with CheckSession(tmp_path / "session", {}, 1) as session:
        before = session.remaining()
        time.sleep(0.05)
        assert session.remaining() <= before - 0.04
        assert session.metrics()["paused_secs"] == 0


def test_hard_restart_keeps_reserved_active_budget_after_a_pause(controlled_clock, tmp_path):
    clock, now = controlled_clock
    directory = tmp_path / "session"
    with CheckSession(directory, {}, 10) as session:
        now.value += 2
        add_pause(clock, now.value, now.value + 100)
        now.value += 100
        session._save(active=True)
        crash_state = copy.deepcopy(session.state)
    # Simulate the last durable write surviving SIGKILL instead of graceful exit.
    (directory / "state.json").write_text(json.dumps(crash_state))
    now.value += 1000  # No examination runs during restart downtime.
    with CheckSession(directory, {}, 10) as resumed:
        assert resumed.remaining() == 7.75
        assert resumed.metrics()["paused_secs"] == 100
        assert resumed.metrics()["cpu_complete"] is False
        now.value += 1
    with CheckSession(directory, {}, 10) as resumed_again:
        assert resumed_again.remaining() == 6.75


def test_legacy_resume_conservatively_charges_all_recorded_wall(controlled_clock, tmp_path):
    directory = tmp_path / "session"
    directory.mkdir()
    (directory / "state.json").write_text(
        json.dumps(
            {
                "identity": {},
                "wall_secs": 7,
                "cpu_secs": 0,
                "cpu_complete": True,
                "active": False,
            }
        )
    )
    with CheckSession(directory, {}, 10) as resumed:
        assert resumed.remaining() == 3
        assert resumed.metrics()["paused_secs"] == 0


def test_subprocess_wait_rechecks_active_budget_after_frozen_wall_poll(controlled_clock):
    clock, now = controlled_clock

    class Child:
        calls = 0

        def communicate(self, *, input, timeout):
            self.calls += 1
            if self.calls == 1:
                add_pause(clock, now.value, now.value + 100)
                now.value += 100
                raise subprocess.TimeoutExpired("child", timeout)
            now.value += 0.5
            return "done", ""

    child = Child()
    assert communicate(child, 1, clock=clock) == ("done", "")
    assert child.calls == 2


def test_subprocess_wait_does_expire_on_active_idle(controlled_clock):
    clock, now = controlled_clock

    class Child:
        def communicate(self, *, input, timeout):
            now.value += timeout
            raise subprocess.TimeoutExpired("child", timeout, output="partial output", stderr="partial error")

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        communicate(Child(), 1, clock=clock)
    assert now.value == 1001
    assert raised.value.timeout == 1
    assert raised.value.output == "partial output"
    assert raised.value.stderr == "partial error"


def test_real_idle_subprocess_timeout_is_still_enforced(tmp_path, monkeypatch):
    clock = ActiveClock.create(tmp_path / "clock")
    monkeypatch.setenv(CLOCK_ENV, str(clock.path))
    from common.check_proof import run_killgroup

    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_killgroup([sys.executable, "-c", "import time; time.sleep(10)"], 0.15, str(tmp_path))
    assert time.monotonic() - start < 2


def test_managed_sany_timeout_stops_children_holding_output_pipes(tmp_path, monkeypatch):
    # Import the module explicitly: tlacore.sany exports a function called dump.
    import importlib

    sany_dump = importlib.import_module("tlacore.sany.dump")
    clock = ActiveClock.create(tmp_path / "clock")
    monkeypatch.setenv(CLOCK_ENV, str(clock.path))
    script = tmp_path / "sany"
    script.write_text(
        f"#!{sys.executable}\nimport subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3)'])\n"
        "time.sleep(3)\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(sany_dump, "_RUN_SH", str(script))
    started = time.monotonic()
    result = sany_dump.run_raw("unused.tla", timeout=0.15)
    assert result.status == sany_dump.SanyStatus.UNAVAILABLE
    assert "timed out" in result.detail
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state.update(boot_id="previous-boot"),
        lambda state: state.update(pauses=[[2, 1]]),
        lambda state: state.update(pauses=[[1, None], [2, 3]]),
        lambda state: state.update(pauses=[[float("inf"), None]]),
    ],
)
def test_invalid_ledger_is_rejected(controlled_clock, mutation):
    clock, _now = controlled_clock
    state = clock.read_state()
    mutation(state)
    clock.path.write_text(json.dumps(state))
    with pytest.raises(OSError):
        clock.read()


def test_clock_domain_mismatch_fails_closed(controlled_clock, monkeypatch):
    clock, now = controlled_clock
    monkeypatch.setattr(active_clock.time, "monotonic", lambda: now.value + 100)
    with pytest.raises(OSError, match="different monotonic epoch"):
        clock.now()


@pytest.fixture
def docker_control(controlled_clock, monkeypatch):
    clock, now = controlled_clock
    info = {
        "Id": "container-id",
        "Config": {"Labels": {CLOCK_LABEL: str(clock.path.parent)}},
        "State": {"Running": True, "Paused": False},
        "Mounts": [{"Source": str(clock.path.parent), "Destination": CLOCK_MOUNT, "RW": False}],
    }
    events = []

    def docker(args, **_kwargs):
        action = args[1]
        events.append(action)
        if action == "pause":
            info["State"]["Paused"] = True
        elif action == "unpause":
            # Critically, the close must already be durable when Docker thaws.
            assert clock.read_state()["pauses"][-1][1] is not None
            info["State"]["Paused"] = False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pause_control, "inspect_container", lambda _name: copy.deepcopy(info))
    monkeypatch.setattr(pause_control.subprocess, "run", docker)
    return clock, now, info, events


def test_controller_is_idempotent_and_publishes_before_thaw(docker_control):
    clock, now, _info, events = docker_control
    assert pause_control.control("test", pause=True) == "paused"
    assert pause_control.control("test", pause=True) == "already paused"
    now.value += 100
    assert clock.now() == 1000
    assert pause_control.control("test", pause=False) == "resumed"
    assert pause_control.control("test", pause=False) == "already running"
    assert clock.now() == 1000
    now.value += 1
    assert clock.now() == 1001
    assert events == ["pause", "unpause"]


def test_host_reader_cannot_observe_unpublished_pause_timestamp(docker_control, monkeypatch):
    clock, now, _info, _events = docker_control
    read_done = threading.Event()
    readings = []

    def reader():
        readings.append(clock.now())
        read_done.set()

    thread = threading.Thread(target=reader)
    original_write = pause_control.write_state

    def slow_publish(path, state):
        now.value += 3  # fsync/publication stalls after sampling pause start.
        thread.start()
        assert not read_done.wait(0.05), "host clock observed a half-published transition"
        original_write(path, state)

    monkeypatch.setattr(pause_control, "write_state", slow_publish)
    pause_control.control("test", pause=True)
    thread.join(timeout=2)
    assert read_done.is_set()
    assert readings == [1000]


def test_failed_freeze_never_grants_unrecorded_pause_time(docker_control, monkeypatch):
    clock, now, _info, _events = docker_control

    def failed_freeze(command, **_kwargs):
        now.value += 3
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(pause_control.subprocess, "run", failed_freeze)
    with pytest.raises(subprocess.CalledProcessError):
        pause_control.control("test", pause=True)
    assert clock.read_state()["pauses"] == []
    assert clock.now() == 1003


def test_controller_recovers_pause_crash_conservatively(docker_control):
    clock, now, info, events = docker_control
    info["State"]["Paused"] = True  # Crash after freeze, before durable pause write.
    now.value += 100
    assert "remains charged" in pause_control.control("test", pause=True)
    assert clock.now() == 1100
    assert events == []


def test_controller_recovers_resume_crash_without_reopening_old_pause(docker_control):
    clock, now, info, _events = docker_control
    pause_control.control("test", pause=True)
    now.value += 100
    state = clock.read_state()
    state["pauses"][-1][1] = now.value
    write_state(clock.path, state)  # Crash after closing pause, before Docker thaw.
    now.value += 20
    # Recovery does not subtract this ambiguous gap, which may include runtime.
    info["State"]["Paused"] = True
    assert "remains charged" in pause_control.control("test", pause=False)
    assert info["State"]["Paused"] is False
    assert clock.now() == 1020


def test_controller_rejects_out_of_band_thaw(docker_control):
    _clock, _now, info, _events = docker_control
    pause_control.control("test", pause=True)
    info["State"]["Paused"] = False
    with pytest.raises(ValueError, match="outside"):
        pause_control.control("test", pause=False)


def test_controller_rejects_unadapted_backend(docker_control):
    clock, _now, _info, _events = docker_control
    state = clock.read_state()
    state["pause_supported"] = False
    write_state(clock.path, state)
    with pytest.raises(ValueError, match="absolute deadlines"):
        pause_control.control("test", pause=True)


def test_container_clock_mount_is_read_only_and_separate_from_results(controlled_clock):
    clock, _now = controlled_clock
    config = ContainerConfig(workspace="/work", result_dir="/results", active_clock=clock)
    args, _cid = ContainerRunner().build_docker_args(config)
    assert f"{clock.path.parent}:{CLOCK_MOUNT}:ro" in args
    assert f"{CLOCK_LABEL}={clock.path.parent}" in args
    assert f"{CLOCK_ENV}={CLOCK_MOUNT}/state.json" in args


def test_non_linux_docker_host_keeps_legacy_wallclock(monkeypatch):
    monkeypatch.setattr(container.sys, "platform", "darwin")
    config = ContainerConfig(pause_accounting=True)
    ContainerRunner._prepare_active_clock(config)
    assert config.active_clock is None

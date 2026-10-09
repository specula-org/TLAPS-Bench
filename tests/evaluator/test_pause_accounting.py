"""Runner deadline and error-path checks with a controlled host clock."""

import tempfile
from types import SimpleNamespace

import pytest

from common.active_clock import ActiveClock, ClockReading
from evaluator import runner
from evaluator.backends.claude_code import ClaudeCodeBackend


@pytest.fixture
def pipe_output():
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stream:
        yield stream


@pytest.mark.parametrize("audit_error", [False, True])
@pytest.mark.parametrize("delayed_initial_read", [False, True])
def test_host_deadline_excludes_pause_and_cleanup_survives_audit_failure(
    tmp_path, monkeypatch, audit_error, pipe_output, delayed_initial_read
):
    state = SimpleNamespace(wall=1000.0, paused=0.0, reads=0, cleaned=False)
    path = tmp_path / "ledger.json"
    path.write_text("{}")

    class Clock(ActiveClock):
        initialized = False

        def read(self):
            if delayed_initial_read and not self.initialized:
                self.initialized = True
                state.wall += 100
                state.paused += 100
            return ClockReading(state.wall, state.paused)

    clock = Clock(path)
    output = pipe_output
    process = SimpleNamespace(stdout=output, stderr=None, returncode=0)
    process.poll = lambda: 0 if state.reads >= 2 else None
    chunks = []

    class Container:
        def run(self, config, _cmd, stdin_data=None):
            assert config.pause_accounting
            chunks.extend([(config.agent_start_marker + "\n").encode(), b'{"type":"result"}\n', b""])
            return SimpleNamespace(proc=process, active_clock=clock)

        def kill(self, _run):
            pytest.fail("a managed pause must not exhaust the two-second active deadline")

        def cleanup_credential_tmps(self):
            state.cleaned = True

    def read(_fd, _size):
        value = chunks[state.reads]
        state.reads += 1
        if state.reads == 2:
            # The agent performed one second of work around a 100s freeze.
            state.wall += 101
            state.paused += 100
        return value

    monkeypatch.setattr(runner, "ContainerRunner", Container)
    monkeypatch.setattr(runner, "STREAM_AGENT_OUTPUT", False)
    monkeypatch.setattr(runner.select, "select", lambda streams, *_args: (streams, [], []))
    monkeypatch.setattr(runner.os, "read", read)
    monkeypatch.setattr(runner.time, "time", lambda: 1700000000 + state.wall)
    if audit_error:

        def fail_copy(*_args):
            raise OSError("test audit write failure")

        monkeypatch.setattr(runner.shutil, "copyfile", fail_copy)
    item = SimpleNamespace(
        benchmark_path=str(tmp_path / "Task.tla"),
        timeout=2,
        check_timeout=10,
        keep_container=False,
        session_dir="",
        container_image="unused",
        mode=SimpleNamespace(canonical_replay_required=False),
    )
    result = {}
    duration = runner._run_backend_container(
        item,
        ClaudeCodeBackend(),
        str(tmp_path),
        str(tmp_path),
        str(tmp_path / "output.jsonl"),
        "",
        result,
    )
    assert state.cleaned
    if audit_error:
        assert duration is None
        assert result["agent_exit"] == -2
        assert result["agent_paused_time_secs"] is None
        assert "audit write failure" in result["error"]
    else:
        assert result["agent_exit"] == 0
        assert duration == 1
        assert result["agent_wall_time_secs"] == 101
        assert result["agent_paused_time_secs"] == 100
        assert result["_container_paused_secs"] == (200 if delayed_initial_read else 100)

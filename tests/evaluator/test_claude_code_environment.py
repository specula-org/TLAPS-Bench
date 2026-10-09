"""Claude print-mode background work follows the benchmark's execution limit."""

import json
import os
import sys
import time
from types import SimpleNamespace

import pytest

from evaluator import runner
from evaluator.backends.agentic import AgenticBackend
from evaluator.backends.claude_code import ClaudeCodeBackend

BACKGROUND_CEILING = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"


def test_execution_environment_preserves_parent_fields_without_mutating_caller(monkeypatch):
    monkeypatch.setenv(BACKGROUND_CEILING, "600000")
    inherited = {"EXISTING_BACKEND_FIELD": "keep", BACKGROUND_CEILING: "123"}
    calls = []

    def parent_environment(self, result_dir):
        calls.append(result_dir)
        return inherited

    monkeypatch.setattr(AgenticBackend, "execution_environment", parent_environment)
    before = dict(os.environ)
    result = ClaudeCodeBackend().execution_environment("/results")

    assert result == {"EXISTING_BACKEND_FIELD": "keep", BACKGROUND_CEILING: "0"}
    assert calls == ["/results"]
    assert inherited[BACKGROUND_CEILING] == "123"
    assert dict(os.environ) == before


@pytest.mark.parametrize("hang", [False, True])
def test_local_cli_child_receives_disabled_ceiling_but_runner_timeout_still_applies(tmp_path, monkeypatch, hang):
    monkeypatch.setenv(BACKGROUND_CEILING, "600000")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    stub = tmp_path / "claude_stub.py"
    stub.write_text(
        "import json, os, time\n"
        f"print(json.dumps({{'background_ceiling': os.environ.get({BACKGROUND_CEILING!r})}}), flush=True)\n"
        + ("time.sleep(10)\n" if hang else "")
    )
    backend = ClaudeCodeBackend()
    monkeypatch.setattr(backend, "build_command", lambda *_args: [sys.executable, str(stub)])
    item = SimpleNamespace(timeout=2 if hang else 0, check_timeout=10, tlapm_lib="")
    mode = SimpleNamespace(canonical_replay_required=False)
    result = {}
    output = agent_dir / "output.jsonl"
    started = time.monotonic()
    runner._run_backend_local(
        item,
        backend,
        mode,
        str(workspace),
        str(agent_dir),
        str(output),
        "prompt",
        result,
        "/bin/true",
    )
    assert json.loads(output.read_text())["background_ceiling"] == "0"
    assert os.environ[BACKGROUND_CEILING] == "600000"
    if hang:
        assert result["agent_exit"] == -1
        assert "timeout after 2s" in result["error"]
        assert time.monotonic() - started < 5
    else:
        assert result["agent_exit"] == 0

"""Credential discovery must not inherit expensive experiment effort settings."""

import os
import subprocess
from unittest.mock import MagicMock

import pytest

from evaluator.backends.claude_code import ClaudeCodeBackend


@pytest.fixture(autouse=True)
def direct_claude_credentials(monkeypatch):
    for name in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_MANTLE", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"])
def test_explicit_credentials_skip_host_model_probe(monkeypatch, name):
    monkeypatch.setenv(name, "test-credential")
    probe = MagicMock()
    monkeypatch.setattr(subprocess, "run", probe)

    assert ClaudeCodeBackend().check_auth() is None
    probe.assert_not_called()


def test_cached_credential_probe_overrides_only_its_own_effort(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
    probe = MagicMock(return_value=subprocess.CompletedProcess([], 0, "ok", ""))
    monkeypatch.setattr(subprocess, "run", probe)
    backend = ClaudeCodeBackend()
    backend.set_reasoning_effort("max")

    assert backend.check_auth() is None
    assert probe.call_args.kwargs["env"]["CLAUDE_CODE_EFFORT_LEVEL"] == "low"
    assert probe.call_args.kwargs["timeout"] == 30
    assert "--no-session-persistence" in probe.call_args.args[0]
    assert os.environ["CLAUDE_CODE_EFFORT_LEVEL"] == "xhigh"
    command = backend.build_command("/workspace", "/results")
    assert command[command.index("--effort") + 1] == "max"


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (subprocess.CompletedProcess([], 1, "", "Invalid bearer token"), "auth probe failed"),
        (subprocess.TimeoutExpired("claude", 30), "auth probe timed out"),
    ],
)
def test_auth_probe_errors_still_fail(monkeypatch, outcome, expected):
    probe = MagicMock(**({"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}))
    monkeypatch.setattr(subprocess, "run", probe)
    assert expected in ClaudeCodeBackend().check_auth()

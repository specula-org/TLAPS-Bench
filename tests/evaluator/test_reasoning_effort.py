"""Reasoning-effort CLI plumbing across evaluator backends."""

import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from evaluator import runner
from evaluator.backends import get_backend, litellm_agent

EXPECTED_EFFORT_VALUES = {
    "codex": ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
    "codex_single_turn": ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
    "claude_code": ("low", "medium", "high", "xhigh", "max"),
    "copilot": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
    "copilot_oneshot": ("low", "medium", "high", "xhigh"),
    "litellm": ("none", "minimal", "low", "medium", "high", "xhigh", "max", "default"),
    "litellm_oneshot": ("none", "minimal", "low", "medium", "high", "xhigh", "max", "default"),
    "pi": ("off", "minimal", "low", "medium", "high", "xhigh", "max"),
}


class NonEmptyMode:
    name = "proof-completion"

    def get_benchmark_files(self, filter_pattern=None):
        return ["/benchmarks/proof-completion/GCD/GCD_GCD3.tla"]


def _has_option(command: list[str], option: str, value: str) -> bool:
    return any(command[index : index + 2] == [option, value] for index in range(len(command) - 1))


@pytest.mark.parametrize(
    ("backend_name", "option", "value"),
    [
        ("codex", "-c", "model_reasoning_effort=low"),
        ("codex_single_turn", "-c", "model_reasoning_effort=low"),
        ("claude_code", "--effort", "low"),
        ("copilot", "--reasoning-effort", "low"),
        ("litellm", "--reasoning-effort", "low"),
        ("copilot_oneshot", "--reasoning-effort", "low"),
        ("litellm_oneshot", "--reasoning-effort", "low"),
    ],
)
def test_explicit_reasoning_effort_reaches_backend_command(backend_name, option, value):
    backend = get_backend(backend_name, model="test-model")
    backend.set_reasoning_effort("low")

    command = backend.build_command("/workspace", "/results")

    assert _has_option(command, option, value)
    assert backend.initial_result_metadata()["reasoning_effort"] == "low"


def test_explicit_reasoning_effort_reaches_pi_command():
    backend = get_backend("pi", model="anthropic/claude-sonnet-4-6")
    backend.set_reasoning_effort("low")

    command = backend.build_command("/workspace", "/results")

    assert "--thinking low" in command[2]
    assert backend.initial_result_metadata()["reasoning_effort"] == "low"


@pytest.mark.parametrize(("backend_name", "values"), EXPECTED_EFFORT_VALUES.items())
def test_backend_reasoning_effort_contract(backend_name, values):
    backend = get_backend(backend_name)

    assert backend.reasoning_effort_values == values
    for value in values:
        backend.set_reasoning_effort(value)
        assert backend.reasoning_effort == value


@pytest.mark.parametrize("backend_name", EXPECTED_EFFORT_VALUES)
def test_backend_rejects_unknown_reasoning_effort(backend_name):
    backend = get_backend(backend_name)

    with pytest.raises(ValueError, match="invalid --reasoning-effort 'definitely-invalid'"):
        backend.set_reasoning_effort("definitely-invalid")


@pytest.mark.parametrize("backend_name", EXPECTED_EFFORT_VALUES)
def test_backend_rejects_empty_reasoning_effort(backend_name):
    backend = get_backend(backend_name)

    with pytest.raises(ValueError, match="--reasoning-effort cannot be empty"):
        backend.set_reasoning_effort("")


@pytest.mark.parametrize(
    ("backend_name", "reasoning_effort"),
    [
        ("codex", "minimal"),
        ("litellm", "default"),
        ("litellm_oneshot", "default"),
    ],
)
def test_backend_accepts_supported_edge_reasoning_effort(backend_name, reasoning_effort):
    backend = get_backend(backend_name)

    backend.set_reasoning_effort(reasoning_effort)

    assert backend.reasoning_effort == reasoning_effort


def test_litellm_agent_completion_error_exits_nonzero(monkeypatch, capsys, tmp_path):
    completion_options = {}

    def reject_completion(**kwargs):
        completion_options.update(kwargs)
        raise RuntimeError("reasoning effort is unsupported for this model")

    monkeypatch.setattr(litellm_agent.litellm, "completion", reject_completion)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Return a short answer."))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "litellm_agent",
            "--workspace",
            str(tmp_path),
            "--skills-dir",
            ".agents/skills",
            "--model",
            "gpt-5.5",
            "--reasoning-effort",
            "minimal",
            "--max-iterations",
            "1",
        ],
    )

    assert litellm_agent.main() == 1
    assert completion_options["reasoning_effort"] == "minimal"
    assert completion_options["num_retries"] == 0
    assert "temperature" not in completion_options
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["type"] for event in events] == ["error", "usage"]
    assert events[-1] == {"type": "usage", "input_tokens": 0, "output_tokens": 0, "model_requests": 1}


def test_litellm_agent_success_exits_zero(monkeypatch, capsys, tmp_path):
    message = SimpleNamespace(
        content="ok",
        tool_calls=None,
        model_dump=lambda: {"role": "assistant", "content": "ok"},
    )
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=1),
        choices=[SimpleNamespace(message=message)],
    )
    monkeypatch.setattr(litellm_agent.litellm, "completion", lambda **_kwargs: response)
    monkeypatch.setattr(sys, "stdin", io.StringIO("Return a short answer."))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "litellm_agent",
            "--workspace",
            str(tmp_path),
            "--skills-dir",
            ".agents/skills",
            "--model",
            "gpt-5.5",
            "--max-iterations",
            "1",
        ],
    )

    assert litellm_agent.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["type"] for event in events] == ["request_usage", "response", "usage"]
    assert events[-1] == {"type": "usage", "input_tokens": 4, "output_tokens": 1, "model_requests": 1}


def test_omitted_reasoning_effort_preserves_existing_defaults():
    codex = get_backend("codex")
    claude = get_backend("claude_code")
    copilot = get_backend("copilot")
    litellm = get_backend("litellm")
    copilot_oneshot = get_backend("copilot_oneshot")
    litellm_oneshot = get_backend("litellm_oneshot")
    pi = get_backend("pi")

    assert not any(value.startswith("model_reasoning_effort=") for value in codex.build_command("/w", "/r"))
    assert _has_option(claude.build_command("/w", "/r"), "--effort", "max")
    assert _has_option(copilot.build_command("/w", "/r"), "--reasoning-effort", "max")
    assert "--reasoning-effort" not in litellm.build_command("/w", "/r")
    assert "--reasoning-effort" not in copilot_oneshot.build_command("/w", "/r")
    assert "--reasoning-effort" not in litellm_oneshot.build_command("/w", "/r")
    assert "--thinking" not in pi.build_command("/w", "/r")[2]
    for backend in (codex, claude, copilot, litellm, copilot_oneshot, litellm_oneshot, pi):
        assert "reasoning_effort" not in backend.initial_result_metadata()


@pytest.mark.parametrize(
    ("backend_name", "effort_args", "expected_error"),
    [
        ("litellm", ["--reasoning-effort", "definitely-invalid"], "invalid --reasoning-effort"),
        ("claude_code", ["--reasoning-effort="], "--reasoning-effort cannot be empty"),
    ],
)
def test_invalid_cli_effort_fails_before_auth_image_or_preflight(
    monkeypatch, capsys, backend_name, effort_args, expected_error
):
    backend = get_backend(backend_name)
    check_auth = MagicMock()
    ensure_image = MagicMock()
    preflight = MagicMock()
    monkeypatch.setattr(backend, "check_auth", check_auth)
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "get_mode", lambda *args, **kwargs: NonEmptyMode())
    monkeypatch.setattr(runner, "ensure_image", ensure_image)
    monkeypatch.setattr(runner, "_run_preflight", preflight)
    monkeypatch.setattr(
        sys,
        "argv",
        ["tlaps-bench run", "--backend", backend_name, *effort_args, "--filter", "GCD_GCD3"],
    )

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 2
    assert expected_error in capsys.readouterr().err
    check_auth.assert_not_called()
    ensure_image.assert_not_called()
    preflight.assert_not_called()

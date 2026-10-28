"""Exercise the blocking checker transport without paid model requests."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, McpError, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from evaluator.backends import codex_proof_check as tool
from evaluator.backends.codex import CodexBackend
from evaluator.backends.codex_usage_wrapper import _tool_dispatch
from evaluator.toolcalls import classify_command


@pytest.fixture
def anyio_backend():
    return "asyncio"


def executable(path, body):
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "Target.tla").write_text("---- MODULE Target ----\n====\n")
    return tmp_path


@pytest.fixture
def checker(workspace):
    return executable(
        workspace / "check_proof_bin",
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "Path('started').write_text(str(os.getpid()))\n"
        "print('Checking...', flush=True)\n"
        "while not Path('release').exists(): time.sleep(.01)\n"
        "print(json.dumps({'argv':sys.argv[1:], 'policy':os.environ.get('TLAPS_VERIFICATION_POLICY'), "
        "'canonical':os.environ.get('TLAPS_BENCHMARK_DIR'), 'clock':os.environ.get('TLAPS_ACTIVE_CLOCK')}))\n"
        "print('checker stderr', file=sys.stderr)\n"
        "sys.exit(int(os.environ.get('CHECKER_EXIT', '0')))\n",
    )


def test_non_pfs_launch_is_unchanged(monkeypatch):
    monkeypatch.delenv(tool.POLICY_ENV, raising=False)
    command = ["codex", "exec", "--", "prompt"]
    assert tool.configure_codex(command, "/missing") is command


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_registration_preserves_feature_state_and_checker_environment(workspace, checker, monkeypatch, enabled):
    codex = executable(workspace / "codex", f"print('code_mode under development {enabled}')\n")
    monkeypatch.setenv("PATH", f"{workspace}:{os.environ['PATH']}")
    monkeypatch.setenv(tool.POLICY_ENV, '{"effective_timeout_secs":7200}')
    monkeypatch.setenv("TLAPS_ACTIVE_CLOCK", "/trusted/clock.json")
    monkeypatch.setenv("TLAPS_CHECK_TIMEOUT", "7200")
    monkeypatch.setenv("TLAPS_BENCHMARK_DIR", "/trusted/canonical")
    monkeypatch.setenv("OPENAI_API_KEY", "not-for-checker")
    command = tool.configure_codex([codex, "exec", "-C", str(workspace)], str(workspace))
    overrides = {part.split("=", 1)[0]: part.split("=", 1)[1] for part in command if "=" in part}
    assert overrides["features.code_mode.enabled"] == enabled
    assert json.loads(overrides["features.code_mode.direct_only_tool_namespaces"]) == [tool.TOOL_NAMESPACE]
    server = tomllib.loads("server=" + overrides["mcp_servers.tlaps_check"])["server"]
    assert server["args"][-1] == checker
    assert server["env"]["TLAPS_VERIFICATION_POLICY"] == os.environ[tool.POLICY_ENV]
    assert server["env"]["TLAPS_CHECK_TIMEOUT"] == "7200"
    assert server["env"]["TLAPS_ACTIVE_CLOCK"] == "/trusted/clock.json"
    assert server["env"]["TLAPS_BENCHMARK_DIR"] == "/trusted/canonical"
    assert "OPENAI_API_KEY" not in server["env"]
    assert server["required"] is True
    assert server["tool_timeout_sec"] > 7200


def test_registration_rejects_unknown_feature_state(workspace, checker, monkeypatch):
    codex = executable(workspace / "codex", "print('code_mode unknown maybe')\n")
    monkeypatch.setenv("PATH", f"{workspace}:{os.environ['PATH']}")
    monkeypatch.setenv(tool.POLICY_ENV, "{}")
    with pytest.raises(ValueError, match="Code Mode state"):
        tool.configure_codex([codex, "exec"], str(workspace))


@pytest.mark.anyio
@pytest.mark.parametrize("exit_code", [0, 1, 3])
@pytest.mark.parametrize("tool_name", ["check_proof", "run_tlapm"])
async def test_mcp_waits_for_checker_and_preserves_output(workspace, checker, exit_code, tool_name):
    (workspace / "tlapm").symlink_to(checker)
    env = {
        "PATH": str(workspace) + os.pathsep + os.environ["PATH"],
        tool.POLICY_ENV: '{"effective_timeout_secs":7200}',
        "TLAPS_BENCHMARK_DIR": "/canonical",
        "TLAPS_ACTIVE_CLOCK": "/clock",
        "CHECKER_EXIT": str(exit_code),
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(tool.__file__)), "--workspace", str(workspace), "--checker", checker],
        env=env,
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        assert {item.name for item in (await client.list_tools()).tools} == {"check_proof", "run_tlapm"}
        arguments = {"file": "Target.tla", "check_session": "verification"}
        expected_argv = [
            str(workspace / "Target.tla"),
            "--mode",
            "proof-from-scratch",
            "--check-session",
            str(workspace / "verification"),
        ]
        if tool_name == "run_tlapm":
            expected_argv = ["--strict", "--toolbox", "4", "8", "-I", "library with spaces", "scratch/Part.tla"]
            arguments = {"args": expected_argv}
        pending = asyncio.create_task(
            client.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=timedelta(seconds=10),
            )
        )
        async with asyncio.timeout(5):
            while not (workspace / "started").exists():
                await asyncio.sleep(0.01)
        assert not pending.done()
        (workspace / "release").touch()
        result = await pending
        text = result.content[0].text
        prefix = "CHECKER" if tool_name == "check_proof" else "TLAPM"
        assert f"{prefix}-EXIT-CODE: {exit_code}" in text
        if tool_name == "run_tlapm":
            assert "LOCAL TLAPM RESULT" in text
            assert "TLAPM-TIMED-OUT: false" in text
        assert "checker stderr" in text
        receipt = next(json.loads(line) for line in text.splitlines() if line.startswith("{"))
        assert receipt == {
            "argv": expected_argv,
            "policy": env[tool.POLICY_ENV],
            "canonical": "/canonical",
            "clock": "/clock",
        }


@pytest.mark.anyio
async def test_syntax_check_and_workspace_paths(workspace, checker):
    (workspace / "release").touch()
    output = await tool.run_check(workspace, checker, "Target.tla", sany_only=True)
    assert '"--sany-only"' in output
    with pytest.raises(ValueError, match="existing .tla"):
        await tool.run_check(workspace, checker, "../outside.tla")
    with pytest.raises(ValueError, match="check_session"):
        await tool.run_check(workspace, checker, "Target.tla", check_session="../cache")


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", ["check_proof", "run_tlapm"])
async def test_mcp_cancellation_stops_check_and_keeps_server_usable(workspace, checker, tool_name):
    (workspace / "tlapm").symlink_to(checker)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(tool.__file__)), "--workspace", str(workspace), "--checker", checker],
        env={"PATH": str(workspace) + os.pathsep + os.environ["PATH"]},
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        request_id = client._request_id
        arguments = {"file": "Target.tla"} if tool_name == "check_proof" else {"args": ["Target.tla"]}
        pending = asyncio.create_task(client.call_tool(tool_name, arguments))
        async with asyncio.timeout(5):
            while not (workspace / "started").exists():
                await asyncio.sleep(0.01)
        pid = int((workspace / "started").read_text())
        # Cancelling the Python client coroutine alone does not notify the server.
        await client.send_notification(
            types.ClientNotification(
                types.CancelledNotification(params=types.CancelledNotificationParams(requestId=request_id))
            )
        )
        with pytest.raises(McpError):
            await pending
        async with asyncio.timeout(5):
            while Path(f"/proc/{pid}").exists():
                await asyncio.sleep(0.01)
        (workspace / "release").touch()
        result = await client.call_tool(tool_name, arguments)
        assert "EXIT-CODE: 0" in result.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("local_timeout", [False, True])
async def test_cancel_stops_checker_and_solver_in_separate_session(workspace, monkeypatch, local_timeout):
    checker = executable(
        workspace / "check_proof_bin",
        "import os, subprocess, sys, time\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
        "Path('pids').write_text(f'{os.getpid()} {child.pid}')\n"
        "print('partial diagnostic', flush=True)\n"
        "time.sleep(60)\n",
    )
    if local_timeout:
        (workspace / "tlapm").symlink_to(checker)
        monkeypatch.setenv("PATH", str(workspace) + os.pathsep + os.environ["PATH"])
        pending = asyncio.create_task(tool.run_tlapm(workspace, ["Target.tla"], timeout_seconds=1))
    else:
        pending = asyncio.create_task(tool.run_check(workspace, checker, "Target.tla"))
    async with asyncio.timeout(5):
        while not (workspace / "pids").exists():
            await asyncio.sleep(0.01)
    pids = [int(pid) for pid in (workspace / "pids").read_text().split()]
    if local_timeout:
        output = await pending
        assert "TLAPM-TIMED-OUT: true" in output
        assert "partial diagnostic" in output
    else:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    for pid in pids:
        stat = Path(f"/proc/{pid}/stat")
        assert not stat.exists() or stat.read_text().rpartition(") ")[2].split()[0] == "Z"


@pytest.mark.parametrize(
    "tool_name,arguments,category",
    [
        ("check_proof", {"file": "Target.tla"}, "tlaps"),
        ("check_proof", {"file": "Target.tla", "sany_only": True}, "other"),
        ("run_tlapm", {"args": ["--strict", "--toolbox", "4", "8", "scratch/Part.tla"]}, "tlaps"),
        ("run_tlapm", {"args": ["--help"]}, "tlaps"),
    ],
)
def test_direct_tool_is_counted_in_rollout_and_cli(workspace, tool_name, arguments, category):
    dispatch = _tool_dispatch(
        {
            "type": "function_call",
            "name": f"mcp__tlaps_check__{tool_name}",
            "call_id": "c",
            "arguments": json.dumps(arguments),
        }
    )
    assert classify_command(dispatch[1]) == category
    item = {"id": "c", "type": "mcp_tool_call", "server": "tlaps_check", "tool": tool_name, "arguments": arguments}
    events = [
        {"type": "thread.started", "thread_id": "r"},
        {"type": "turn.started"},
        {"type": "item.started", "item": item},
        {"type": "item.completed", "item": item},
        {"type": "turn.completed"},
    ]
    path = workspace / "events.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events))
    summary = CodexBackend().parse_run_metadata(str(path))["tool_calls"]
    assert summary["total"] == summary[category] == 1
    assert summary["complete"]


@pytest.mark.skipif(shutil.which("codex") is None, reason="requires native Codex CLI; no model request")
@pytest.mark.parametrize("config", ["code_mode=true", "code_mode=false", "code_mode={enabled=true}"])
def test_native_codex_loads_direct_tool_without_changing_feature_state(workspace, checker, monkeypatch, config):
    profile = workspace / "profile"
    profile.mkdir()
    configuration = f"[features]\n{config}\n"
    (profile / "config.toml").write_text(configuration)
    monkeypatch.setenv("CODEX_HOME", str(profile))
    monkeypatch.setenv("PATH", f"{workspace}:{os.environ['PATH']}")
    monkeypatch.setenv(tool.POLICY_ENV, "{}")
    command = tool.configure_codex([shutil.which("codex"), "exec"], str(workspace))
    loaded = subprocess.run(
        [command[0], "features", "list", *command[2:]], cwd=workspace, capture_output=True, text=True, timeout=15
    )
    assert loaded.returncode == 0, loaded.stderr
    state = next(line.split()[-1] for line in loaded.stdout.splitlines() if line.split()[:1] == ["code_mode"])
    assert state == ("false" if "false" in config else "true")
    assert (profile / "config.toml").read_text() == configuration

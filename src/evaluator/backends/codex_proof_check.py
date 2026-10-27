"""Direct, blocking access to the existing PFS checker for Codex runs."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

SERVER_NAME = "tlaps_check"
TOOL_NAMESPACE = "mcp__tlaps_check"
POLICY_ENV = "TLAPS_VERIFICATION_POLICY"
# The checker and runner own the actual deadlines, including managed pauses.
# A short MCP transport deadline would expire while a container is frozen.
TRANSPORT_TIMEOUT_SECONDS = 2_147_483_647
CHECKER_ENV = (
    "PATH",
    "JAVA_HOME",
    "TMPDIR",
    "TLAPS_LIB",
    "COMMUNITY_LIB",
    "SANY_RUN_SH",
    "TLAPS_IN_CONTAINER",
    "TLAPS_BENCHMARK_DIR",
    "TLAPS_PROOF_LIBRARY_CATALOG",
    "TLAPS_CANONICAL_REPLAY_REQUIRED",
    "TLAPS_CHECK_TIMEOUT",
    POLICY_ENV,
    "TLAPS_VERIFICATION_TOOLCHAIN",
    "TLAPS_ACTIVE_CLOCK",
    "TLAPS_NO_GIT_TRACK",
)


def configure_codex(command: list[str], workspace: str) -> list[str]:
    """Register the tool at launch, after native/container environment setup."""
    if not os.environ.get(POLICY_ENV):
        return command  # Proof completion and model preflights keep their tools.
    checker = shutil.which("check_proof_bin")
    if checker is None:
        raise ValueError("blocking proof tool requires check_proof_bin on PATH")
    overrides = []
    for index, argument in enumerate(command[:-1]):
        if argument == "-c":
            overrides.extend([argument, command[index + 1]])
    probe = subprocess.run(
        [command[0], "features", "list", *overrides],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    enabled = next((line.split()[-1] for line in probe.stdout.splitlines() if line.split()[:1] == ["code_mode"]), "")
    if enabled not in {"true", "false"}:
        raise ValueError("cannot resolve Codex Code Mode state for the blocking proof tool")
    env = ",".join(f"{json.dumps(key)}={json.dumps(os.environ[key])}" for key in CHECKER_ENV if key in os.environ)
    args = [str(Path(__file__).resolve()), "--workspace", workspace, "--checker", checker]
    server = (
        f"{{command={json.dumps(sys.executable)},args={json.dumps(args)},env={{{env}}},"
        f"tool_timeout_sec={TRANSPORT_TIMEOUT_SECONDS},required=true}}"
    )
    return [
        *command,
        "-c",
        f"mcp_servers.{SERVER_NAME}={server}",
        "-c",
        f"features.code_mode.direct_only_tool_namespaces={json.dumps([TOOL_NAMESPACE])}",
        "-c",
        f"features.code_mode.enabled={enabled}",
    ]


def _kill_check(pid: int) -> None:
    """Include solver descendants that TLAPM starts in separate sessions."""
    parents = {}
    for entry in Path("/proc").glob("[0-9]*/stat"):
        with contextlib.suppress(OSError, ValueError, IndexError):
            parents[int(entry.parent.name)] = int(entry.read_text().rpartition(") ")[2].split()[1])
    descendants = [pid]
    for parent in descendants:
        descendants.extend(child for child, owner in parents.items() if owner == parent and child not in descendants)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)
    for child in reversed(descendants[1:]):
        with contextlib.suppress(ProcessLookupError):
            os.kill(child, signal.SIGKILL)


async def run_check(
    workspace: Path, checker: str, file: str, *, sany_only: bool = False, check_session: str | None = None
) -> str:
    """Wait for one checker invocation without returning intermediate statuses."""
    from anyio import CancelScope

    candidate = (workspace / file).resolve()
    if not candidate.is_relative_to(workspace.resolve()) or not candidate.is_file() or candidate.suffix != ".tla":
        raise ValueError("file must be an existing .tla file in the task workspace")
    command = [checker, str(candidate), "--mode", "proof-from-scratch"]
    if sany_only:
        command.append("--sany-only")
    if check_session is not None:
        session = (workspace / check_session).resolve()
        if not session.is_relative_to(workspace.resolve()):
            raise ValueError("check_session must be inside the task workspace")
        command.extend(["--check-session", str(session)])
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = await process.communicate()
    finally:
        if process.returncode is None:
            _kill_check(process.pid)
            with CancelScope(shield=True):
                await process.wait()
    return f"CHECKER-EXIT-CODE: {process.returncode}\n{output.decode('utf-8', errors='replace')}"


async def serve(workspace: Path, checker: str) -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)

    @server.tool(structured_output=False)
    async def check_proof(file: str, sany_only: bool = False, check_session: str | None = None) -> str:
        """Run check_proof_bin in proof-from-scratch mode and wait for its result.

        Prefer this direct tool call to shell execution or Code Mode exec/wait.
        The checker retains the run's frozen budget, canonical context and all
        integrity checks. No polling is needed. sany_only checks syntax only.
        Use check_session only to resume an interrupted check of unchanged input.
        Cancelling this call stops the checker and its solvers. The returned
        exit code and checker output determine the result, not MCP call success.
        """
        return await run_check(workspace, checker, file, sany_only=sany_only, check_session=check_session)

    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    await server.run_stdio_async()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--checker", required=True)
    args = parser.parse_args()
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(serve(args.workspace.resolve(), args.checker))


if __name__ == "__main__":
    main()

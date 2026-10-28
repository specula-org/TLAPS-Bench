"""Direct, blocking access to the PFS checker and native TLAPM for Codex runs."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

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
    returncode, output, _ = await _run_command(workspace, command)
    return f"CHECKER-EXIT-CODE: {returncode}\n{output}"


async def _run_command(
    workspace: Path, command: list[str], timeout_seconds: float | None = None
) -> tuple[int, str, bool]:
    """Wait for output, retaining diagnostics when a local timeout stops a run."""
    from anyio import CancelScope

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    communication = asyncio.create_task(process.communicate())
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.shield(communication), timeout_seconds)
    except TimeoutError:
        timed_out = True
    finally:
        if process.returncode is None:
            _kill_check(process.pid)
        with CancelScope(shield=True):
            output, _ = await communication
    return process.returncode, output.decode("utf-8", errors="replace"), timed_out


_TLAPM_SUMMARY = re.compile(
    r"^(?:\[INFO\]: All \d+ obligations? proved\."
    r"|\[ERROR\]: \d+/\d+ obligations? failed\."
    r"|\[ERROR\]: Proof incomplete in module [^\r\n]+: \d+ missing, \d+ omitted proof step\(s\)\."
    r"|\[ERROR\]: No proof obligation found for the selected target\.)$",
    re.MULTILINE,
)


async def run_tlapm(
    workspace: Path,
    args: list[str],
    timeout_seconds: float | None = None,
    output: Literal["summary", "full"] = "summary",
) -> str:
    """Forward native arguments without expanding the requested proof scope."""
    if not args:
        raise ValueError("provide TLAPM arguments, including a file or --help")
    if output not in {"summary", "full"}:
        raise ValueError("output must be summary or full")
    if timeout_seconds is not None and (not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError("timeout_seconds must be positive and finite")
    executable = shutil.which("tlapm")
    if executable is None:
        executable = next(
            (str(path) for path in (Path("/opt/tlapm/bin/tlapm"), Path.home() / ".tlapm/bin/tlapm") if path.is_file()),
            None,
        )
    if executable is None:
        raise ValueError("tlapm is not installed")
    log_root = workspace.resolve() / ".tlacache" / "tool-output"
    log_root.mkdir(parents=True, exist_ok=True)
    log_dir = Path(tempfile.mkdtemp(prefix="run-", dir=log_root))
    full_log, summary_file = log_dir / "full.log", log_dir / "summary.txt"
    returncode, raw_output, timed_out = await _run_command(workspace, [executable, *args], timeout_seconds)
    full_log.write_text(raw_output, encoding="utf-8")
    header = (
        "LOCAL TLAPM RESULT: dependencies and submission integrity are not certified.\n"
        f"TLAPM-TIMED-OUT: {str(timed_out).lower()}\nTLAPM-EXIT-CODE: {returncode}\n"
        f"TLAPM-SUMMARY-FILE: {summary_file}\nTLAPM-FULL-LOG: {full_log}\n"
    )
    native_summary = "\n".join(_TLAPM_SUMMARY.findall(raw_output))
    summary = header + "TLAPM-SUMMARY: " + (native_summary or "unavailable; read the full log.") + "\n"
    summary_file.write_text(summary, encoding="utf-8")
    return summary if output == "summary" else header + raw_output


async def serve(workspace: Path, checker: str) -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)

    @server.tool(structured_output=False)
    async def check_proof(file: str, sany_only: bool = False, check_session: str | None = None) -> str:
        """Run check_proof_bin in proof-from-scratch mode and wait for its result.

        Prefer this direct tool for full checks and syntax checks. For local
        TLAPM checks, use run_tlapm with native range-selection arguments.
        The checker retains the run's frozen budget, canonical context and all
        integrity checks. No polling is needed. sany_only checks syntax only.
        Use check_session only to resume an interrupted check of unchanged input.
        Cancelling this call stops the checker and its solvers. The returned
        exit code and checker output determine the result, not MCP call success.
        """
        return await run_check(workspace, checker, file, sany_only=sany_only, check_session=check_session)

    @server.tool(name="run_tlapm", structured_output=False)
    async def local_tlapm(
        args: list[str], timeout_seconds: float | None = None, output: Literal["summary", "full"] = "summary"
    ) -> str:
        """Run native TLAPM in the task workspace and wait without polling.

        Prefer this direct tool to shell or Code Mode exec/wait for local checks.
        Pass the arguments after the tlapm executable unchanged, including -I
        search paths and the submitted or scratch filename. For example, use
        --strict --toolbox START END to check a chosen line range. No dependencies
        are automatically added to that scope. Arguments are passed directly,
        so shell variables, redirection and pipelines are not expanded.
        timeout_seconds optionally sets a wall-clock limit for this local call;
        omit it to wait until completion or cancellation by the caller/runner.
        Timeout or cancellation stops TLAPM and its solvers. Local success does
        not replace the authoritative check_proof self-check before submission.

        output defaults to summary: exit code, timeout, native result summary
        when available, and paths to summary.txt and full.log. No summary means
        read the full log; diagnostics are not automatically expanded. Use full
        to return all output, or read/search either saved file after completion
        for any part you need. Reading saved output does not rerun verification.
        """
        return await run_tlapm(workspace, args, timeout_seconds, output)

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

"""Run SANY over a .tla file and return its semantic model.

Thin wrapper around ``DumpSemantics`` (the tla2sany-based dumper). Reuses the
existing ``run.sh`` plumbing, which compiles the Java if needed and sets up the
TLA-Library search path (TLAPS stdlib + the input file's own directory so that
sibling-module EXTENDS/INSTANCE resolve).

This is the single entry point both the benchmark generator and the checker use
to get a parsed view of a module — no regex parsing of TLA+ source anywhere.
"""

from __future__ import annotations

import contextlib
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum

from common.active_clock import ActiveClock, communicate

from ..model import Module

_HERE = os.path.dirname(os.path.abspath(__file__))
# run.sh lives under the sany-dump location; we shell out to it rather than
# duplicating the build/launch logic. The path is overridable via SANY_RUN_SH so
# a frozen (PyInstaller) build — where __file__ points into the bundle, not the
# repo — can point at the run.sh baked into the image.
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_RUN_SH = os.environ.get(
    "SANY_RUN_SH",
    os.path.join(_REPO_ROOT, "src", "dataset", "sany-dump", "run.sh"),
)

_MARKER = "--- BEGIN SANY-DUMP JSON ---"


class SanyStatus(StrEnum):
    """Outcome of invoking the standalone SANY parser."""

    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SanyRun:
    """Complete, auditable outcome of one SANY invocation."""

    status: SanyStatus
    command: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    detail: str
    raw: dict | None = None


class SanyError(RuntimeError):
    """Base class for a non-valid SANY invocation."""

    def __init__(self, run: SanyRun):
        self.run = run
        super().__init__(run.detail)


class SanyInvalid(SanyError):
    """SANY ran and rejected the TLA+ module."""


class SanyUnavailable(SanyError):
    """SANY could not produce a trustworthy parse verdict."""


def _captured_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _unavailable_run(tla_path: str, detail: str) -> SanyRun:
    return SanyRun(
        status=SanyStatus.UNAVAILABLE,
        command=(_RUN_SH, tla_path),
        returncode=None,
        stdout="",
        stderr="",
        detail=detail,
    )


def run_raw(tla_path: str, timeout: int = 180) -> SanyRun:
    """Run SANY and return its three-way status plus complete process evidence."""

    command = (_RUN_SH, tla_path)
    try:
        clock = ActiveClock.from_environment()
        if clock.path is None:
            res = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        else:
            with subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
            ) as proc:
                try:
                    stdout, stderr = communicate(proc, timeout, clock=clock)
                except BaseException:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
                    raise
                res = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = _captured_text(exc.stdout)
        stderr = _captured_text(exc.stderr)
        return SanyRun(
            status=SanyStatus.UNAVAILABLE,
            command=command,
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            detail=f"SANY timed out after {timeout}s for {tla_path}",
        )
    except OSError as exc:
        return _unavailable_run(tla_path, f"SANY could not run for {tla_path}: {type(exc).__name__}: {exc}")

    out = res.stdout or ""
    err = res.stderr or ""
    idx = out.find(_MARKER)
    if idx < 0:
        status = SanyStatus.INVALID if res.returncode == 3 else SanyStatus.UNAVAILABLE
        return SanyRun(
            status=status,
            command=command,
            returncode=res.returncode,
            stdout=out,
            stderr=err,
            detail=(f"SANY produced no dump for {tla_path} (exit {res.returncode}). stderr: {err.strip()}"),
        )
    if res.returncode != 0:
        return SanyRun(
            status=SanyStatus.UNAVAILABLE,
            command=command,
            returncode=res.returncode,
            stdout=out,
            stderr=err,
            detail=f"SANY produced a dump but exited {res.returncode} for {tla_path}",
        )
    try:
        raw = json.loads(out[idx + len(_MARKER) :])
    except json.JSONDecodeError as exc:
        return SanyRun(
            status=SanyStatus.UNAVAILABLE,
            command=command,
            returncode=res.returncode,
            stdout=out,
            stderr=err,
            detail=f"Could not parse SANY dump for {tla_path}: {exc}",
        )
    return SanyRun(
        status=SanyStatus.VALID,
        command=command,
        returncode=res.returncode,
        stdout=out,
        stderr=err,
        detail="",
        raw=raw,
    )


def dump_raw(tla_path: str, timeout: int = 180) -> dict:
    """Run SANY on ``tla_path`` and return the raw JSON dict."""
    run = run_raw(tla_path, timeout=timeout)
    if run.status is SanyStatus.INVALID:
        raise SanyInvalid(run)
    if run.status is SanyStatus.UNAVAILABLE:
        raise SanyUnavailable(run)
    assert run.raw is not None
    return run.raw


def dump(tla_path: str, timeout: int = 180) -> Module:
    """Run SANY on ``tla_path`` and return a typed :class:`Module`."""
    return Module.parse(dump_raw(tla_path, timeout=timeout))


def try_dump(tla_path: str, timeout: int = 180) -> Module | None:
    """Like :func:`dump` but returns ``None`` on any SANY failure.

    Useful when scanning a set of files where some may legitimately fail to
    parse in isolation (e.g. a dependency missing its own deps).
    """
    try:
        return dump(tla_path, timeout=timeout)
    except (SanyError, OSError):
        return None


_MODULE_DECL = re.compile(r"^-+\s*MODULE\s+(\w+)", re.MULTILINE)


def module_name_of(tla_path: str) -> str | None:
    """Read the declared module name from a .tla file's header."""
    try:
        with open(tla_path, encoding="utf-8", errors="ignore") as f:
            m = _MODULE_DECL.search(f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def _as_dep_dirs(dep_dir, dep_dirs) -> list:
    if dep_dirs:
        return list(dep_dirs)
    if dep_dir:
        return [dep_dir]
    return []


def dump_normalized(
    tla_path: str, dep_dir: str | None = None, timeout: int = 180, dep_dirs: list | None = None
) -> Module:
    """Parse ``tla_path`` robustly: correct filename + supply dependency modules.

    Two real-world hurdles this clears:
      * TLA+/SANY requires the file name to match the declared module name, but
        submissions are often stored as ``solution.tla``.
      * An archived result dir frequently keeps only ``benchmark.tla`` +
        ``solution.tla`` and drops the dependency modules (Voting.tla,
        PConProof.tla, ...). SANY then fails with "Cannot find source for
        module X" — which looks like a parse failure but is just a missing dep.

    We copy every ``*.tla`` from each ``dep_dirs`` entry (later entries win on
    name clashes, so the submission's own copy overrides a canonical one) into a
    temp dir, rename the target to ``<module>.tla``, and parse there. Pass both
    the canonical ``benchmark/<level>/<module>/`` dir (for the given deps) and
    the result dir (for the submission + any agent-created modules).
    """
    run = run_normalized(tla_path, dep_dir=dep_dir, timeout=timeout, dep_dirs=dep_dirs)
    if run.status is SanyStatus.INVALID:
        raise SanyInvalid(run)
    if run.status is SanyStatus.UNAVAILABLE:
        raise SanyUnavailable(run)
    assert run.raw is not None
    return Module.parse(run.raw)


def run_normalized(
    tla_path: str, dep_dir: str | None = None, timeout: int = 180, dep_dirs: list | None = None
) -> SanyRun:
    """Run SANY with normalized filename and dependency staging."""

    mod = module_name_of(tla_path)
    dirs = _as_dep_dirs(dep_dir, dep_dirs) or [os.path.dirname(os.path.abspath(tla_path))]
    base = os.path.basename(tla_path)
    # Fast path: filename matches AND a single dep dir == the file's own dir.
    if (
        mod
        and base == f"{mod}.tla"
        and len(dirs) == 1
        and os.path.abspath(dirs[0]) == os.path.dirname(os.path.abspath(tla_path))
    ):
        return run_raw(tla_path, timeout=timeout)

    try:
        tmp = tempfile.mkdtemp(prefix="tlacore_sany_")
    except OSError as exc:
        return _unavailable_run(
            tla_path,
            f"SANY staging failed for {tla_path}: {type(exc).__name__}: {exc}",
        )
    try:
        try:
            for d in dirs:
                for dep in glob.glob(os.path.join(d, "*.tla")):
                    shutil.copy2(dep, os.path.join(tmp, os.path.basename(dep)))
            target = os.path.join(tmp, f"{mod}.tla") if mod else os.path.join(tmp, base)
            shutil.copy2(tla_path, target)
        except OSError as exc:
            return _unavailable_run(
                tla_path,
                f"SANY staging failed for {tla_path}: {type(exc).__name__}: {exc}",
            )
        return run_raw(target, timeout=timeout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def try_dump_normalized(
    tla_path: str, dep_dir: str | None = None, timeout: int = 180, dep_dirs: list | None = None
) -> Module | None:
    try:
        return dump_normalized(tla_path, dep_dir=dep_dir, timeout=timeout, dep_dirs=dep_dirs)
    except (SanyError, OSError):
        return None

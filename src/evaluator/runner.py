"""
Run evaluator backends on TLAPS benchmarks to attempt automated proof writing.

For each benchmark:
1. Creates an isolated workspace (fresh git repo with only benchmark files)
2. Runs the chosen backend (codex / claude_code / copilot) with a proof-writing prompt
3. Validates the result with the mode's checker
4. Saves all outputs

Usage:
    python3 runner.py [--backend codex|claude_code|copilot|litellm|pi] [--mode proof-completion|proof-from-scratch] \\
                      [--model NAME] [--reasoning-effort VALUE] [--jobs N] \\
                      [--filter PATTERN | --task-list NAME_OR_FILE] \\
                      [--timeout SECS] [--check-timeout SECS] [--output-dir DIR]
"""

import argparse
import contextlib
import copy
import fcntl
import glob
import hashlib
import json
import math
import os
import random
import re
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from common.container import (
    IMAGE_TAG,
    ContainerConfig,
    ContainerRunner,
    DockerUnavailableError,
    _image_source_fingerprint,
    ensure_image,
    forward_env,
)
from common.proof_libraries import (
    CATALOG_ENV,
    CATALOG_FILENAME,
    OfficialLibraryCatalog,
    ProofLibraryError,
    scan_official_libraries,
)
from common.task_contract import TaskContractError
from common.verification_toolchain import (
    VerificationToolchainError,
    validate_toolchain_identity,
    verification_toolchain_identity,
)
from evaluator import quota, toolcalls
from evaluator.agent_skills import discover_agent_skills
from evaluator.backends import get_backend, list_backends
from evaluator.backends.base import Backend, SubmissionDisposition
from evaluator.cost import calculate_equivalent_cost_usd, public_price_error
from evaluator.modes import get_mode, list_modes
from evaluator.modes.base import Mode
from evaluator.proof_module_artifact import (
    ModuleArtifactError,
    publish_module_artifact,
    read_module_artifact,
    result_module_artifact,
)
from evaluator.proof_module_checkpoint import (
    ModuleCheckpointError,
    ModuleCheckpointIdentity,
    prepare_module_checkpoints,
    write_module_checkpoint,
)
from evaluator.proof_module_checkpoint import (
    run_identity_sha256 as module_run_identity_sha256,
)
from evaluator.proof_module_result import MODULE_RESULT_PREFIX, ModuleResultError, parse_module_result_json
from evaluator.score import (
    SCORERS,
    applicable_manifest_results,
    continuation_interrupted,
    continuation_rate_line,
    is_non_genuine,
    is_pass_with_continuations,
    is_skipped,
    n_non_genuine,
    n_skipped,
    proof_unit_rate_line,
    scope_specification_ids,
    specification_score_lines,
    weighted_score,
)
from evaluator.termination import TerminationContext, TerminationReason, classify, startup_error_snippet
from evaluator.usage import (
    UsageSummary,
    aggregate_token_usage,
    format_token_usage,
    nonnegative_float,
    nonnegative_int,
    result_token_usage,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# File at <repo>/src/evaluator/runner.py — ascend two levels for repo root.
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
TASK_LIST_RECORD = "task-list.json"
RUN_MANIFEST_RECORD = "run-manifest.json"
NAMED_TASK_LISTS = {"core": "core.txt"}
SESSION_KEY_SCHEME = "mode-relative-task-v1"

VERDICT_ICONS = {"PASS": "✅", "FAIL": "❌", "CHEATING": "⚠️", "TIMEOUT": "⏱️", "ERROR": "💥"}

# Set to True to stream agent output to terminal during container runs
STREAM_AGENT_OUTPUT = True

# Backoff between infra retries (seconds); the last value repeats. Short: the
# observed startup blips clear within seconds-to-minutes.
INFRA_RETRY_BACKOFF = (15, 30, 60)

_USAGE_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
)
_COST_TIME_BACKENDS = frozenset(
    {
        "codex",
        "codex_single_turn",
        "claude_code",
        "copilot",
        "copilot_oneshot",
        "cursor",
        "litellm",
        "litellm_oneshot",
        "pi",
    }
)
_RUNNER_OWNED_ACCOUNTING_KEYS = frozenset(
    {
        "usage",
        "input_tokens",
        "output_tokens",
        "agent_time_secs",
        "grading_time_secs",
        "grader_error_time_secs",
        "logical_timeout_used_secs",
        "time_secs",
        "equivalent_cost_usd",
    }
)


def _supports_cost_time(backend: Backend) -> bool:
    return backend.name in _COST_TIME_BACKENDS


def _pricing_provider(backend: Backend) -> str | None:
    """Return only provider hints that the public price library understands."""

    if backend.name.startswith("copilot"):
        return None
    if backend.name.startswith("litellm"):
        return "litellm"
    if backend.name.startswith("codex"):
        uses_bedrock = getattr(backend, "_uses_bedrock", None)
        if callable(uses_bedrock) and uses_bedrock():
            return "amazon-bedrock"
    return backend.provider


def _confirm_public_pricing(
    backend: Backend,
    *,
    allow_unpriced_model: bool,
    use_container: bool = False,
) -> bool:
    """Fail before an expensive run unless the user accepts a blank cost."""

    if not backend.requires_public_pricing:
        return True
    model = getattr(backend, "model", None)
    configuration_error = None
    configuration_check = getattr(backend, "public_pricing_configuration_error", None)
    if not use_container and callable(configuration_check):
        configuration_error = configuration_check()
    error = configuration_error or public_price_error(model, _pricing_provider(backend))
    if error is None:
        return True

    print(f"ERROR: no reliable public API price for model {model!r}: {error}")
    proceed = allow_unpriced_model
    if not proceed and sys.stdin.isatty():
        answer = input("Continue with equivalent_cost_usd left blank? [y/N] ").strip().lower()
        proceed = answer in {"y", "yes"}
    if not proceed:
        print("Aborting before the run. Re-run with --allow-unpriced-model to continue with blank cost.")
        return False

    backend._equivalent_cost_disabled = True
    print("WARNING: continuing without reliable pricing; equivalent_cost_usd will be blank.")
    return True


def _attach_equivalent_cost(
    result: dict,
    usage: UsageSummary,
    backend: Backend,
) -> UsageSummary:
    """Calculate one execution lifecycle's complete equivalent USD cost."""

    if not _supports_cost_time(backend):
        result["usage"] = usage.to_dict()
        return usage
    if getattr(backend, "_equivalent_cost_disabled", False):
        warning = "equivalent cost unavailable: public pricing was unavailable before the run"
        usage = replace(usage, warnings=tuple(dict.fromkeys((*usage.warnings, warning))))
        result["equivalent_cost_usd"] = None
        result["usage"] = usage.to_dict()
        return usage

    amount, warning = calculate_equivalent_cost_usd(
        usage,
        getattr(backend, "model", None),
        _pricing_provider(backend),
    )
    if warning is not None:
        prefix = "equivalent cost unavailable" if amount is None else "equivalent cost warning"
        warning = f"{prefix}: {warning}"
        usage = replace(usage, warnings=tuple(dict.fromkeys((*usage.warnings, warning))))
    result["equivalent_cost_usd"] = amount
    result["usage"] = usage.to_dict()
    return usage


def _write_attempt_accounting(
    directory: str,
    *,
    time_secs: float | None,
    usage: UsageSummary,
    backend: Backend,
) -> None:
    """Store non-experiment accounting beside an infra/quota attempt."""

    if not _supports_cost_time(backend):
        return
    os.makedirs(directory, exist_ok=True)
    diagnostic: dict[str, object] = {"time_secs": time_secs}
    _attach_equivalent_cost(diagnostic, usage, backend)
    with open(os.path.join(directory, "accounting.json"), "w") as stream:
        json.dump(diagnostic, stream, indent=2)


def _sum_accounting_values(left: object, right: object) -> float | None:
    left_value = nonnegative_float(left)
    right_value = nonnegative_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value + right_value


def _recompute_task_time(result: dict[str, object]) -> None:
    """Keep total task time equal to agent plus grading time."""

    result["time_secs"] = _sum_accounting_values(
        result.get("agent_time_secs"),
        result.get("grading_time_secs"),
    )


def _ensure_time_breakdown(result: dict[str, object]) -> None:
    """Adapt a legacy total-only result before adding new accounting."""

    total = nonnegative_float(result.get("time_secs"))
    grading = nonnegative_float(result.get("grading_time_secs")) or 0.0
    agent = nonnegative_float(result.get("agent_time_secs"))
    if agent is not None and "grading_time_secs" in result:
        return
    result["grading_time_secs"] = grading
    result["agent_time_secs"] = total - grading if total is not None and total >= grading else None


def _set_agent_time(result: dict[str, object], value: object) -> None:
    result["agent_time_secs"] = nonnegative_float(value)
    result.setdefault("grading_time_secs", 0.0)
    _recompute_task_time(result)


def _add_grading_time(result: dict[str, object], elapsed: float) -> float:
    """Accumulate one grading attempt and return the amount added."""

    _ensure_time_breakdown(result)
    prior_grading = nonnegative_float(result.get("grading_time_secs"))
    if prior_grading is None:
        prior_grading = 0.0
    result["grading_time_secs"] = prior_grading + elapsed
    _recompute_task_time(result)
    return elapsed


def _add_child_grading_time(result: dict[str, object], elapsed: float) -> None:
    """Add a continuation grader's time to the run-level aggregate."""

    prior = nonnegative_float(result.get("grading_time_secs"))
    result["grading_time_secs"] = None if prior is None else prior + elapsed
    _recompute_task_time(result)


def _retry_may_duplicate_model_work(
    backend: Backend,
    jsonl_path: str,
    usage: UsageSummary,
    legacy_output_tokens: int,
) -> bool:
    """Return whether replacing this launch could duplicate model work."""

    if legacy_output_tokens > 0:
        return True
    if (usage.output_tokens or 0) > 0 or (usage.reasoning_output_tokens or 0) > 0:
        return True
    # One-shot backends audit whether a transient failure occurred before any
    # response. Forwarded request/input evidence from failed native attempts is
    # retained in aggregate usage, but the audited terminal decides whether a
    # replay is safe. Agentic backends need the stricter all-evidence policy.
    if backend.approach == "one_shot":
        return backend.retry_may_duplicate_model_work(jsonl_path)
    if any((getattr(usage, field) or 0) > 0 for field in _USAGE_TOKEN_FIELDS):
        return True
    if (usage.model_requests or 0) > 0 or bool(usage.requests):
        return True
    if any(
        isinstance(cost.amount, (int, float)) and not isinstance(cost.amount, bool) and cost.amount > 0
        for cost in usage.costs
    ):
        return True
    return backend.retry_may_duplicate_model_work(jsonl_path)


def _parse_backend_usage(
    backend: Backend,
    jsonl_path: str,
    *,
    attempt: int,
) -> tuple[str, int, int, UsageSummary]:
    """Read one launch's transcript and usage before its artifacts can move."""

    transcript, input_tokens, output_tokens = backend.parse_output(jsonl_path)
    try:
        usage = backend.parse_usage(
            jsonl_path,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ).with_context(attempt=attempt)
    except Exception as exc:
        usage = replace(
            UsageSummary.from_legacy(
                input_tokens,
                output_tokens,
                source=f"{backend.name}_usage_parser_fallback",
            ),
            warnings=(f"structured usage parser failed: {type(exc).__name__}: {exc}",),
        )
    return transcript, input_tokens, output_tokens, usage


def _apply_submission_metadata(result: dict, metadata: dict[str, object]) -> None:
    """Apply backend metadata without allowing it to replace accounting data."""

    conflicts = sorted(_RUNNER_OWNED_ACCOUNTING_KEYS.intersection(metadata))
    result.update({key: value for key, value in metadata.items() if key not in _RUNNER_OWNED_ACCOUNTING_KEYS})
    if not conflicts or "usage" not in result:
        return
    usage = UsageSummary.from_dict(result["usage"])
    warning = f"ignored submission metadata for runner-owned fields: {', '.join(conflicts)}"
    result["usage"] = replace(usage, warnings=tuple(dict.fromkeys((*usage.warnings, warning)))).to_dict()


def resolve_paths():
    """Return (benchmark_root, checker_binary) based on environment.

    Docker: /benchmark + /usr/local/bin/check_proof_bin (set by docker-compose).
    Host:   <repo>/benchmark + <repo>/check_proof_bin.
    """
    if os.path.isdir("/benchmark"):
        return "/benchmark", "/usr/local/bin/check_proof_bin"
    return os.path.join(REPO_ROOT, "benchmark"), os.path.join(REPO_ROOT, "check_proof_bin")


# Persistent tlapm location — /opt/tlapm in docker, ~/.tlapm on host.
TLAPM_PERSISTENT = "/opt/tlapm" if os.path.isdir("/opt/tlapm") else os.path.expanduser("~/.tlapm")
TLAPM_SOURCE = "/tmp/tlapm"


def ensure_tlapm():
    """Ensure tlapm is available at TLAPM_PERSISTENT (host-only fallback)."""
    if os.path.isfile(os.path.join(TLAPM_PERSISTENT, "bin", "tlapm")):
        print(f"tlapm at {TLAPM_PERSISTENT}")
        return
    if not os.path.isdir(TLAPM_SOURCE):
        print(f"ERROR: tlapm not found at {TLAPM_PERSISTENT} or {TLAPM_SOURCE}")
        sys.exit(1)
    print(f"Copying tlapm to {TLAPM_PERSISTENT}...")
    shutil.copytree(TLAPM_SOURCE, TLAPM_PERSISTENT)
    print("Done.")


def find_tlapm_lib(tlapm_path: str) -> str | None:
    """Derive lib path from tlapm binary path. Supports 1.5 and 1.6 layouts."""
    base = os.path.dirname(os.path.dirname(tlapm_path))
    for sub in ["lib/tlapm/stdlib", "lib/tlaps", "lib/tlapm", "lib"]:
        path = os.path.join(base, sub)
        if os.path.isdir(path):
            return path
    return None


def _proc_descendants(root_pid: int) -> list:
    """All live descendant PIDs of root_pid, via a /proc ppid walk."""
    children: dict = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as f:
                data = f.read().decode("latin1")
            # comm (field 2) is parenthesised and may contain spaces; ppid is
            # the 2nd field after the closing ')'.
            ppid = int(data[data.rindex(")") + 2 :].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    out, stack = [], [root_pid]
    while stack:
        for c in children.get(stack.pop(), []):
            out.append(c)
            stack.append(c)
    return out


def _procs_with_cwd_under(path: str) -> list:
    """PIDs whose cwd is at/under `path`. Catches Isabelle/poly that detach
    from the process group but still run in the benchmark's workspace."""
    base = os.path.realpath(path)
    out = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return out
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            cwd = os.readlink(f"/proc/{entry}/cwd")
        except OSError:
            continue
        if cwd == base or cwd.startswith(base + os.sep):
            out.append(int(entry))
    return out


def kill_agent_tree(proc, workspace: str):
    """SIGKILL the agent's whole process tree plus any process whose cwd is in
    `workspace` (detached Isabelle/poly). Scoped to THIS benchmark only — it
    never touches processes from other runs (e.g. a concurrent codex run), so
    it is safe to run on a shared host. This is what reliably reaps tlapm's
    Isabelle backend, which leaks `poly` children that the process-group kill
    alone leaves behind."""
    try:
        pid = proc.pid
    except Exception:
        return
    targets = set()
    with contextlib.suppress(Exception):
        targets.update(_proc_descendants(pid))
    with contextlib.suppress(Exception):
        targets.update(_procs_with_cwd_under(workspace))
    targets.add(pid)
    # Local backends are launched with start_new_session=True, so their PID is
    # also the process-group ID. Use the saved ID directly: the group can still
    # contain background children after the reaped leader no longer exists.
    with contextlib.suppress(Exception):
        os.killpg(pid, signal.SIGKILL)
    for t in targets:
        with contextlib.suppress(Exception):
            os.kill(t, signal.SIGKILL)


def _mem_available_gb() -> float | None:
    """MemAvailable in GiB from /proc/meminfo, or None if unreadable."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def wait_for_memory(min_free_gb: float, max_waits: int, log_prefix: str = "") -> bool:
    """Block until MemAvailable >= min_free_gb before launching a heavy agent.

    Guards a no-swap host against OOM when this run shares the machine with
    another memory-hungry run (e.g. concurrent codex): a single ByzantinePaxos
    Isabelle proof can hold ~150GB, so we hold off launching until there's room.
    Returns True once memory is free (or the check is disabled / unreadable),
    False after max_waits (caller proceeds anyway rather than abort)."""
    if min_free_gb <= 0:
        return True
    waits = 0
    while True:
        avail = _mem_available_gb()
        if avail is None or avail >= min_free_gb:
            return True
        waits += 1
        if waits > max_waits:
            print(
                f"{log_prefix}low memory ({avail:.0f}GB < {min_free_gb:.0f}GB) "
                f"after {max_waits} waits — launching anyway",
                flush=True,
            )
            return True
        print(
            f"{log_prefix}waiting for memory: {avail:.0f}GB free < "
            f"{min_free_gb:.0f}GB needed (wait {waits}/{max_waits})",
            flush=True,
        )
        time.sleep(60)


_summary_lock = threading.Lock()


MODULE_RESUME_RETRY_FIRST = "retry-first-attempt"
MODULE_RESUME_GRADE_SAVED = "grade-saved-submission"
MODULE_RESUME_CONTINUE = "run-next-continuation"
MODULE_RESUME_COMPLETE = "complete"


@dataclass(frozen=True)
class ModuleResume:
    """Validated durable state needed to resume one module task exactly."""

    action: str
    result: dict[str, object]
    submission: bytes | None
    artifact_receipt: dict[str, object] | None
    checkpoint_sequence: int

    def __post_init__(self) -> None:
        if self.action not in {
            MODULE_RESUME_RETRY_FIRST,
            MODULE_RESUME_GRADE_SAVED,
            MODULE_RESUME_CONTINUE,
            MODULE_RESUME_COMPLETE,
        }:
            raise ValueError(f"unknown module resume action {self.action!r}")
        if self.checkpoint_sequence <= 0:
            raise ValueError("module resume checkpoint sequence must be positive")


@dataclass
class WorkItem:
    """A single (benchmark, backend, mode) task fed to the worker pool."""

    benchmark_path: str
    output_dir: str
    timeout: int
    check_timeout: int
    backend: Backend
    mode: Mode
    tlapm_path: str
    tlapm_lib: str
    # Quota gate (Claude Max subscription). usage_script=None disables it.
    usage_script: str | None = None
    quota_5h: float = 0
    quota_7d: float = 0
    quota_max_waits: int = 0
    # Memory gate: hold off launching the agent until this many GB are free
    # (0 = off). Guards a no-swap host against OOM under concurrent heavy runs.
    min_free_gb: float = 0
    # Container mode: run agent inside Docker container
    use_container: bool = False
    # Immutable build-specific image tag selected before worker processes start.
    container_image: str = f"{IMAGE_TAG}:latest"
    # Extra agent attempts after a backend-approved transient infrastructure
    # failure with no evidence of model work; 0 disables retrying (the failure
    # still ends ERROR).
    infra_retries: int | None = None
    # Continuation rounds after a genuine non-PASS: re-run the agent in the SAME
    # workspace so it builds on its own partial proof (see _run_continuations).
    # 0 disables. pass@1 (check_verdict) is unaffected either way.
    max_continuations: int = 0
    # Debugging: retain each agent container (drop --rm) for inspection/resume.
    keep_container: bool = False
    # Debugging: persistent host dir for agent session state ("" = off).
    session_dir: str = ""
    # Replay-required modes capture every task before the worker pool starts.
    canonical_inputs: "CanonicalInputs | None" = None
    # One process-wide byte snapshot is shared by every work item so parallel
    # modules and a resume cannot observe different project skill inputs.
    agent_skills_snapshot: "AgentSkillsSnapshot | None" = None
    run_identity: dict[str, object] | None = None
    module_resume: ModuleResume | None = None
    module_checkpoint_identity: ModuleCheckpointIdentity | None = None


_LOGICAL_PROOF_EVIDENCE_KEYS = (
    "module_result",
    "trusted_proof_unit_count",
    "trusted_proof_unit_ids",
    "obligations",
    "obligations_complete",
    "obligations_failed",
    "obligations_total",
    "sany_status",
    "sany_valid",
    "failed_gates",
    "cheat_checks",
)
_LOGICAL_ATTEMPT_OUTCOME_KEYS = (
    *_LOGICAL_PROOF_EVIDENCE_KEYS,
    "graded_after_interruption",
    "invalid_submission_after_interruption",
    "grader_error",
    "infra_retries",
    "infra_retry_reasons",
)


def _result_usage_summary(result: dict[str, object]) -> UsageSummary:
    usage = result.get("usage")
    if isinstance(usage, dict):
        return UsageSummary.from_dict(usage)
    input_tokens = nonnegative_int(result.get("input_tokens", 0))
    output_tokens = nonnegative_int(result.get("output_tokens", 0))
    if input_tokens is None or output_tokens is None:
        raise ModuleCheckpointError("logical attempt has invalid legacy token accounting")
    return UsageSummary.from_legacy(input_tokens, output_tokens, source="runner.legacy_logical_attempt")


def _logical_attempt_has_accounted_work(result: dict[str, object]) -> bool:
    _ensure_time_breakdown(result)
    if (nonnegative_float(result.get("logical_timeout_used_secs")) or 0.0) > 0:
        return True
    if (nonnegative_float(result.get("agent_time_secs")) or 0.0) > 0:
        return True
    if any(
        result.get(field) is not None
        for field in ("module_artifact", "graded_after_interruption", "invalid_submission_after_interruption")
    ):
        return True
    usage = _result_usage_summary(result)
    if (usage.model_requests or 0) > 0 or usage.requests:
        return True
    return any((getattr(usage, field) or 0) > 0 for field in _USAGE_TOKEN_FIELDS)


def _logical_timeout_budget(result: dict[str, object], configured_timeout: float) -> float:
    raw = result.get("logical_timeout_secs", configured_timeout)
    budget = nonnegative_float(raw)
    configured = nonnegative_float(configured_timeout)
    if budget is None or configured is None:
        raise ModuleCheckpointError("logical attempt timeout must be a finite non-negative number")
    if not math.isclose(budget, configured, rel_tol=0, abs_tol=1e-9):
        raise ModuleCheckpointError("logical attempt timeout differs from the recorded run configuration")
    result["logical_timeout_secs"] = budget
    return budget


def _remaining_logical_timeout(result: dict[str, object], configured_timeout: float) -> float | None:
    """Return None for unlimited, otherwise the unspent agent-time budget."""

    budget = _logical_timeout_budget(result, configured_timeout)
    if budget == 0:
        result["logical_timeout_remaining_secs"] = None
        return None
    _ensure_time_breakdown(result)
    spent = nonnegative_float(result.get("logical_timeout_used_secs"))
    if spent is None:
        spent = nonnegative_float(result.get("agent_time_secs"))
    if spent is None:
        if _logical_attempt_has_accounted_work(result):
            raise ModuleCheckpointError("cannot resume a timed logical attempt with unavailable agent time")
        spent = 0.0
    remaining = max(0.0, budget - spent)
    result["logical_timeout_remaining_secs"] = remaining
    return remaining


def _mark_logical_attempt_timeout(result: dict[str, object]) -> None:
    result["agent_exit"] = -1
    result["check_verdict"] = "TIMEOUT"
    result["termination_reason"] = TerminationReason.TIMEOUT
    result["error"] = "logical attempt timeout exhausted before resume"
    result["logical_timeout_remaining_secs"] = 0.0
    result.pop("graded_after_interruption", None)
    result.pop("invalid_submission_after_interruption", None)


def _refresh_logical_timeout_remaining(result: dict[str, object]) -> None:
    budget = nonnegative_float(result.get("logical_timeout_secs"))
    if budget is None:
        return
    if budget == 0:
        result["logical_timeout_remaining_secs"] = None
        return
    spent = nonnegative_float(result.get("logical_timeout_used_secs"))
    if spent is None:
        spent = nonnegative_float(result.get("agent_time_secs"))
    result["logical_timeout_remaining_secs"] = None if spent is None else max(0.0, budget - spent)


def _reset_logical_attempt_segment(result: dict[str, object], backend: Backend) -> None:
    """Clear one interrupted segment while retaining its durable task state."""

    for key in _LOGICAL_ATTEMPT_OUTCOME_KEYS:
        result.pop(key, None)
    result["agent_exit"] = -1
    result["check_verdict"] = "ERROR"
    result["termination_reason"] = TerminationReason.OK
    result["error"] = ""
    result["agent_time_secs"] = None if _supports_cost_time(backend) else 0.0
    result["grading_time_secs"] = 0.0
    result["logical_timeout_used_secs"] = 0.0
    result["time_secs"] = None if _supports_cost_time(backend) else 0.0
    result["usage"] = UsageSummary(
        input_tokens=0,
        output_tokens=0,
        model_requests=0,
        sources=("runner.logical_attempt_segment",),
        available=True,
        complete=True,
    ).to_dict()
    result["input_tokens"] = 0
    result["output_tokens"] = 0
    result.pop("tool_calls", None)
    result.pop("grader_error_time_secs", None)
    if _supports_cost_time(backend):
        result["equivalent_cost_usd"] = None


def _merge_logical_attempt_accounting(
    result: dict[str, object],
    previous: dict[str, object],
    segment_usage: UsageSummary,
    *,
    include_segment: bool,
    backend: Backend,
) -> None:
    """Merge process segments without creating a new benchmark attempt."""

    resume_count = previous.get("logical_resume_count", 0)
    if type(resume_count) is not int or resume_count < 0:
        raise ModuleCheckpointError("logical attempt has an invalid resume count")
    result["logical_resume_count"] = resume_count + 1
    if not include_segment:
        for key in _RUNNER_OWNED_ACCOUNTING_KEYS:
            if key in previous:
                result[key] = copy.deepcopy(previous[key])
            else:
                result.pop(key, None)
        for key in _LOGICAL_PROOF_EVIDENCE_KEYS:
            if key in previous:
                result[key] = copy.deepcopy(previous[key])
        _refresh_logical_timeout_remaining(result)
        return

    previous_has_work = _logical_attempt_has_accounted_work(previous)
    if not previous_has_work:
        _refresh_logical_timeout_remaining(result)
        return

    _ensure_time_breakdown(previous)
    aggregate_usage = _result_usage_summary(previous).merge(segment_usage)
    result["usage"] = aggregate_usage.to_dict()
    result["input_tokens"] = aggregate_usage.legacy_input_tokens
    result["output_tokens"] = aggregate_usage.legacy_output_tokens
    result["agent_time_secs"] = _sum_accounting_values(previous.get("agent_time_secs"), result.get("agent_time_secs"))
    result["grading_time_secs"] = _sum_accounting_values(
        previous.get("grading_time_secs"), result.get("grading_time_secs")
    )
    previous_timeout_used = nonnegative_float(previous.get("logical_timeout_used_secs"))
    if previous_timeout_used is None:
        previous_timeout_used = previous.get("agent_time_secs")
    segment_timeout_used = nonnegative_float(result.get("logical_timeout_used_secs"))
    if segment_timeout_used is None:
        segment_timeout_used = result.get("agent_time_secs")
    result["logical_timeout_used_secs"] = _sum_accounting_values(previous_timeout_used, segment_timeout_used)
    _recompute_task_time(result)
    if _supports_cost_time(backend):
        result["equivalent_cost_usd"] = _sum_accounting_values(
            previous.get("equivalent_cost_usd"), result.get("equivalent_cost_usd")
        )
    if "tool_calls" in previous or "tool_calls" in result:
        result["tool_calls"] = (
            toolcalls.ToolCallSummary.from_dict(previous.get("tool_calls"))
            .merge(toolcalls.ToolCallSummary.from_dict(result.get("tool_calls")))
            .to_dict()
        )
    previous_grader_error_time = nonnegative_float(previous.get("grader_error_time_secs")) or 0.0
    segment_grader_error_time = nonnegative_float(result.get("grader_error_time_secs")) or 0.0
    if previous_grader_error_time or segment_grader_error_time:
        result["grader_error_time_secs"] = previous_grader_error_time + segment_grader_error_time
    _refresh_logical_timeout_remaining(result)


def _logical_attempt_execution_item(item: WorkItem, result: dict[str, object]) -> WorkItem | None:
    remaining = _remaining_logical_timeout(result, item.timeout)
    if remaining is not None and remaining <= 0:
        return None
    return item if remaining is None else replace(item, timeout=remaining)


@dataclass(frozen=True)
class CanonicalInputs:
    """Task and dependency bytes captured before an agent process can mutate them."""

    target_name: str
    target_bytes: bytes
    dependencies: tuple[tuple[str, bytes], ...]
    proof_library_catalog: bytes | None = None

    @classmethod
    def capture(
        cls,
        benchmark_path: str,
        basename: str,
        deps: list[str],
        *,
        proof_library_catalog: bytes | None = None,
    ) -> "CanonicalInputs":
        dependencies = tuple((os.path.basename(path), _read_bytes(path)) for path in deps)
        names = [basename, *(name for name, _content in dependencies)]
        if len(names) != len(set(names)):
            raise ValueError(f"canonical inputs contain duplicate basenames: {names}")
        return cls(basename, _read_bytes(benchmark_path), dependencies, proof_library_catalog)

    def materialize(self, destination: str, *, target_name: str | None = None) -> None:
        _write_bytes(os.path.join(destination, target_name or self.target_name), self.target_bytes)
        for name, content in self.dependencies:
            _write_bytes(os.path.join(destination, name), content)
        if self.proof_library_catalog is not None:
            _write_bytes(os.path.join(destination, CATALOG_FILENAME), self.proof_library_catalog)

    def digest(self) -> str:
        digest = hashlib.sha256()

        def update(value: bytes) -> None:
            digest.update(len(value).to_bytes(8, byteorder="big"))
            digest.update(value)

        update(b"proof-module-canonical-input-v1")
        update(self.target_name.encode())
        update(self.target_bytes)
        for name, content in self.dependencies:
            update(name.encode())
            update(content)
        update(self.proof_library_catalog or b"")
        return digest.hexdigest()


@dataclass(frozen=True)
class AgentSkillFile:
    """One regular file in a frozen project Agent Skill catalog."""

    relative_path: str
    content: bytes
    mode: int


@dataclass(frozen=True)
class AgentSkillsSnapshot:
    """Portable, immutable bytes supplied to every agent in one run."""

    names: tuple[str, ...]
    directories: tuple[tuple[str, int], ...]
    files: tuple[AgentSkillFile, ...]

    @classmethod
    def capture(cls, backend: Backend, root: str | Path) -> "AgentSkillsSnapshot":
        if backend.project_skills_dir is None:
            return cls((), (), ())

        root = Path(root)
        skills = discover_agent_skills(root)
        directories: list[tuple[str, int]] = []
        files: list[AgentSkillFile] = []
        for skill in skills:
            paths = [skill.source_dir, *skill.source_dir.rglob("*")]
            for path in sorted(paths, key=lambda candidate: candidate.relative_to(root).as_posix()):
                relative = path.relative_to(root).as_posix()
                if path.is_symlink():
                    raise ValueError(f"Agent Skill snapshots do not allow symlinks: {path}")
                metadata = path.stat()
                mode = stat.S_IMODE(metadata.st_mode)
                if stat.S_ISDIR(metadata.st_mode):
                    directories.append((relative, mode))
                elif stat.S_ISREG(metadata.st_mode):
                    files.append(AgentSkillFile(relative, path.read_bytes(), mode))
                else:
                    raise ValueError(f"Agent Skill snapshots require regular files and directories: {path}")
        return cls(
            tuple(skill.name for skill in skills),
            tuple(directories),
            tuple(files),
        )

    def digest(self) -> str:
        digest = hashlib.sha256()
        _update_identity_digest(digest, b"agent-skills-snapshot-v1")
        for name in self.names:
            _update_identity_digest(digest, b"name")
            _update_identity_digest(digest, name.encode())
        for relative, mode in self.directories:
            _update_identity_digest(digest, b"directory")
            _update_identity_digest(digest, relative.encode())
            _update_identity_digest(digest, mode.to_bytes(4, byteorder="big"))
        for skill_file in self.files:
            _update_identity_digest(digest, b"file")
            _update_identity_digest(digest, skill_file.relative_path.encode())
            _update_identity_digest(digest, skill_file.mode.to_bytes(4, byteorder="big"))
            _update_identity_digest(digest, skill_file.content)
        return digest.hexdigest()

    def materialize(self, destination: str | Path) -> None:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise ValueError(f"Agent Skill snapshot destination must be empty: {destination}")
        for relative, mode in self.directories:
            path = destination / relative
            path.mkdir(parents=True, exist_ok=False)
            path.chmod(mode)
        for skill_file in self.files:
            path = destination / skill_file.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(skill_file.content)
            path.chmod(skill_file.mode)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as stream:
        return stream.read()


def _write_bytes(path: str, content: bytes) -> None:
    with open(path, "wb") as stream:
        stream.write(content)


def _snapshot_agent_skills(
    backend: Backend,
    destination: str,
    snapshot: AgentSkillsSnapshot | None = None,
) -> list[str]:
    """Capture the catalog this backend can discover and return its skill names."""

    snapshot = snapshot or AgentSkillsSnapshot.capture(backend, SKILLS_DIR)
    snapshot.materialize(destination)
    return list(snapshot.names)


def _copy_skills_to_workspace(skills_snapshot_dir: str, workspace: str, project_skills_dir: str) -> None:
    """Copy one immutable input snapshot to a client's project discovery path."""

    workspace = os.path.abspath(workspace)
    destination = os.path.abspath(os.path.join(workspace, project_skills_dir))
    if not project_skills_dir or os.path.commonpath((workspace, destination)) != workspace or destination == workspace:
        raise ValueError(f"project skills directory must stay inside the workspace: {project_skills_dir!r}")
    shutil.copytree(skills_snapshot_dir, destination)


def _build_prompt_from_canonical_inputs(
    backend: Backend,
    mode: Mode,
    canonical_inputs: CanonicalInputs,
    benchmark_basename: str,
    tlapm_path: str,
    tlapm_lib: str,
) -> str:
    prompt_dir = tempfile.mkdtemp(prefix="prompt_inputs_")
    try:
        canonical_inputs.materialize(prompt_dir)
        return backend.build_prompt(
            mode,
            os.path.join(prompt_dir, canonical_inputs.target_name),
            [os.path.join(prompt_dir, name) for name, _content in canonical_inputs.dependencies],
            benchmark_basename,
            tlapm_path,
            tlapm_lib,
        )
    finally:
        shutil.rmtree(prompt_dir, ignore_errors=True)


def _make_canonical_dir(name_no_ext: str, canonical_inputs: CanonicalInputs) -> str:
    canonical_dir = tempfile.mkdtemp(prefix=f"canon_{name_no_ext}_")
    try:
        canonical_inputs.materialize(canonical_dir)
        return canonical_dir
    except Exception:
        shutil.rmtree(canonical_dir, ignore_errors=True)
        raise


@contextlib.contextmanager
def _module_grading_inputs(
    item: WorkItem,
    attempt: dict[str, object],
    canonical_inputs: CanonicalInputs,
    basename: str,
    name_no_ext: str,
):
    """Yield an artifact-only submission workspace and independent canonical copy."""

    if canonical_inputs.target_name != basename:
        raise ModuleArtifactError("module artifact target name does not match its canonical input")
    submission = read_module_artifact(item.output_dir, attempt.get("module_artifact"))
    grading_workspace = _make_canonical_dir(f"{name_no_ext}_grading", canonical_inputs)
    canonical_dir = None
    try:
        _write_bytes(os.path.join(grading_workspace, basename), submission)
        canonical_dir = _make_canonical_dir(name_no_ext, canonical_inputs)
        yield grading_workspace, canonical_dir
    finally:
        shutil.rmtree(grading_workspace, ignore_errors=True)
        if canonical_dir is not None:
            shutil.rmtree(canonical_dir, ignore_errors=True)


@contextlib.contextmanager
def _standard_grading_inputs(
    item: WorkItem,
    workspace: str,
    canonical_inputs: CanonicalInputs,
    name_no_ext: str,
    canonical_dir: str | None,
):
    """Yield the existing workspace and an independent canonical copy when required."""

    grading_canonical_dir = canonical_dir
    created_canonical_dir = False
    if getattr(item.mode, "canonical_replay_required", False):
        grading_canonical_dir = _make_canonical_dir(name_no_ext, canonical_inputs)
        created_canonical_dir = True
    try:
        yield workspace, grading_canonical_dir
    finally:
        if created_canonical_dir:
            shutil.rmtree(grading_canonical_dir, ignore_errors=True)


def _make_workspace(
    backend_name: str,
    name_no_ext: str,
    canonical_inputs: CanonicalInputs,
    *,
    skills_snapshot_dir: str | None = None,
    project_skills_dir: str | None = None,
    read_only_dependencies: bool = False,
    initial_target_bytes: bytes | None = None,
) -> str:
    """Create a fresh Git workspace with canonical inputs and project skills.

    The baseline commit is the cheating check's reference point.
    """
    workspace = tempfile.mkdtemp(prefix=f"{backend_name}_bench_{name_no_ext}_")
    try:
        canonical_inputs.materialize(workspace)
        if initial_target_bytes is not None:
            _write_bytes(os.path.join(workspace, canonical_inputs.target_name), initial_target_bytes)
        if project_skills_dir is not None:
            if skills_snapshot_dir is None:
                raise ValueError("a skills snapshot is required when project skill discovery is enabled")
            _copy_skills_to_workspace(skills_snapshot_dir, workspace, project_skills_dir)
        subprocess.run(["git", "init"], capture_output=True, cwd=workspace)
        subprocess.run(["git", "add", "--force", "."], capture_output=True, cwd=workspace)
        subprocess.run(
            ["git", "commit", "-m", "initial benchmark"],
            capture_output=True,
            cwd=workspace,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "bench",
                "GIT_AUTHOR_EMAIL": "bench@bench",
                "GIT_COMMITTER_NAME": "bench",
                "GIT_COMMITTER_EMAIL": "bench@bench",
            },
        )
        if read_only_dependencies:
            target_path = os.path.join(workspace, canonical_inputs.target_name)
            os.chmod(target_path, os.stat(target_path).st_mode | stat.S_IWUSR)
            for dep_name, _content in canonical_inputs.dependencies:
                os.chmod(os.path.join(workspace, dep_name), 0o444)
            if canonical_inputs.proof_library_catalog is not None:
                os.chmod(os.path.join(workspace, CATALOG_FILENAME), 0o444)
        return workspace
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise


@dataclass
class ExecutionOutcome:
    """What one backend execution leaves behind for grading and recording."""

    workspace: str
    canonical_dir: str
    transcript: str
    quota_exhausted: bool
    quota_retry_suppressed: bool
    infra_retriable: bool  # still a no-model-work infra failure after all retries
    model_work_observed: bool
    infra_reasons: list[str]
    usage: UsageSummary


def _run_backend_with_retries(
    item: WorkItem,
    prompt: str,
    agent_dir: str,
    agent_jsonl: str,
    agent_stderr: str,
    result: dict,
    checker_bin: str,
    canonical_inputs: CanonicalInputs,
    basename: str,
    name_no_ext: str,
    skills_snapshot_dir: str | None = None,
    fixed_workspace: str | None = None,
) -> ExecutionOutcome:
    """One agent-run lifecycle, shared by the first attempt and continuation
    rounds: run the agent (sleeping through hard provider quota caps, see
    quota.run_with_quota_retry), parse its output, classify the termination,
    and retry with backoff while the run died before the model did ANY work
    (INFRA_ERROR with no structured or legacy evidence of a model call). A
    genuine attempt is never re-run.

    The runner captures canonical input bytes before the first agent starts.
    Every attempt gets a fresh copy of those bytes for self-checking. In local
    mode the agent can write to that host path, so a failed attempt's copy must
    never leak into a retry. Modes requiring canonical replay receive a separate
    fresh copy for grading.
    With fixed_workspace=None each attempt also gets a fresh workspace (a
    failed first attempt's partial edits can't leak into a retry); a
    continuation round passes its existing workspace instead — the partial
    proof in it IS the input, and a no-work startup death can't have touched it.

    Fills result's agent_time_secs / time_secs / usage / input_tokens / output_tokens / agent_exit /
    error / termination_reason (plus infra_retries / infra_retry_reasons after
    any retries); the caller owns quota/infra exhaustion verdicts and messages.
    agent_time_secs records only the final experiment attempt and time_secs is
    recomputed as agent plus grading time. Infra/quota launches are saved
    separately beside their raw artifacts and never enter the formal result.
    Returns the final attempt's workspace + canonical snapshot, which
    the caller must clean up (earlier attempts' dirs are cleaned here, including
    when an attempt raises).
    """
    backend = item.backend
    mode = item.mode
    read_only_dependencies = getattr(mode, "read_only_dependencies", False)
    workspace = fixed_workspace
    canonical_dir = None
    active_secs = 0.0
    attempt_secs: float | None = None
    attempt_timeout_used_secs: float | None = None
    quota_exhausted = False
    quota_retry_suppressed = False
    infra_retriable = False
    infra_reasons: list[str] = []
    transcript = ""
    attempt_usage = UsageSummary(available=False, warnings=("backend did not produce usage data",))
    aggregate_usage: UsageSummary | None = None
    result_baseline = result.copy()
    parsed_metadata_keys: set[str] = set()
    try:
        for attempt in range(max(item.infra_retries, 0) + 1):
            for key in parsed_metadata_keys:
                if key in result_baseline:
                    result[key] = result_baseline[key]
                else:
                    result.pop(key, None)
            parsed_metadata_keys.clear()

            canonical_dir = _make_canonical_dir(name_no_ext, canonical_inputs)
            if fixed_workspace is None:
                resume_submission = item.module_resume.submission if item.module_resume is not None else None
                workspace = _make_workspace(
                    backend.name,
                    name_no_ext,
                    canonical_inputs,
                    skills_snapshot_dir=skills_snapshot_dir,
                    project_skills_dir=backend.project_skills_dir,
                    read_only_dependencies=read_only_dependencies,
                    initial_target_bytes=resume_submission,
                )

            wait_for_memory(item.min_free_gb, 120, log_prefix=f"[{name_no_ext}] ")

            # Defaults keep the closure bound to this attempt.
            def _run_once(workspace=workspace, canonical_dir=canonical_dir):
                nonlocal active_secs, attempt_secs, attempt_timeout_used_secs
                result["error"] = ""
                # Establish a valid empty-stream marker before process/container
                # startup. A launch exception is then distinguishable from a
                # child that flushed a malformed or truncated event.
                with open(agent_jsonl, "w"):
                    pass
                with contextlib.suppress(FileNotFoundError):
                    os.remove(agent_stderr)
                t0 = time.monotonic()
                if item.use_container:
                    container_agent_secs = _run_backend_container(
                        item,
                        backend,
                        workspace,
                        agent_dir,
                        agent_jsonl,
                        prompt,
                        result,
                        canonical_dir,
                        read_only_files=(
                            [os.path.join(workspace, name) for name, _content in canonical_inputs.dependencies]
                            if read_only_dependencies
                            else None
                        ),
                    )
                else:
                    container_agent_secs = None
                    _run_backend_local(
                        item,
                        backend,
                        mode,
                        workspace,
                        agent_dir,
                        agent_jsonl,
                        prompt,
                        result,
                        checker_bin,
                        canonical_dir,
                    )
                wall_elapsed = time.monotonic() - t0
                elapsed = container_agent_secs if item.use_container and _supports_cost_time(backend) else wall_elapsed
                # Cooperative backends may spend a bounded grace period flushing
                # audit events after the logical deadline. That is not extra model
                # time and must not inflate the benchmark runtime metric.
                if (
                    elapsed is not None
                    and item.timeout > 0
                    and result.get("agent_exit") == -1
                    and "timeout after" in result.get("error", "")
                ):
                    elapsed = min(elapsed, item.timeout)
                    wall_elapsed = min(wall_elapsed, item.timeout)
                attempt_secs = elapsed
                attempt_timeout_used_secs = wall_elapsed
                if elapsed is not None:
                    active_secs += elapsed

            def _prepare_quota_retry(quota_attempt: int, infra_attempt: int = attempt) -> bool:
                nonlocal aggregate_usage, quota_retry_suppressed
                _quota_transcript, _quota_input, quota_output, quota_usage = _parse_backend_usage(
                    backend,
                    agent_jsonl,
                    attempt=infra_attempt,
                )
                if _retry_may_duplicate_model_work(backend, agent_jsonl, quota_usage, quota_output):
                    # Keep this launch in the canonical output path so the caller
                    # can report its partial usage; replacing it could double-charge
                    # the run and would destroy the only native evidence.
                    quota_retry_suppressed = True
                    return False
                if not _supports_cost_time(backend):
                    aggregate_usage = quota_usage if aggregate_usage is None else aggregate_usage.merge(quota_usage)
                _stash_quota_attempt(
                    agent_dir,
                    infra_attempt,
                    quota_attempt,
                    backend,
                    time_secs=attempt_secs,
                    usage=quota_usage,
                )
                return True

            quota_exhausted = not quota.run_with_quota_retry(
                _run_once,
                lambda: backend.detect_quota_block(agent_jsonl),
                log_prefix=f"[{name_no_ext}] ",
                prepare_retry=_prepare_quota_retry,
            )
            _set_agent_time(result, attempt_secs if _supports_cost_time(backend) else active_secs)
            result["logical_timeout_used_secs"] = attempt_timeout_used_secs

            # Parse agent output on every path — including quota exhaustion — so
            # the result records any tokens the agent did emit (rather than
            # forcing them to 0).
            transcript, _input_tokens, output_tokens, attempt_usage = _parse_backend_usage(
                backend,
                agent_jsonl,
                attempt=attempt,
            )
            parse_metadata = getattr(backend, "parse_run_metadata", None)
            if parse_metadata:
                runner_error = result.get("error", "")
                parsed_metadata = parse_metadata(agent_jsonl)
                parsed_metadata_keys.update(parsed_metadata)
                result.update(parsed_metadata)
                if runner_error:
                    result["error"] = runner_error
            published_usage = attempt_usage
            if not _supports_cost_time(backend):
                aggregate_usage = attempt_usage if aggregate_usage is None else aggregate_usage.merge(attempt_usage)
                published_usage = aggregate_usage
            result["input_tokens"] = published_usage.legacy_input_tokens
            result["output_tokens"] = published_usage.legacy_output_tokens
            published_usage = _attach_equivalent_cost(result, published_usage, backend)
            if _supports_cost_time(backend):
                attempt_usage = published_usage
            else:
                aggregate_usage = published_usage

            if quota_exhausted:
                # The final budgeted quota attempt has no following retry, so
                # run_with_quota_retry does not invoke its preparation hook.
                # Still classify the result accurately if that last launch did
                # model work before it hit the cap.
                quota_retry_suppressed = quota_retry_suppressed or _retry_may_duplicate_model_work(
                    backend,
                    agent_jsonl,
                    attempt_usage,
                    output_tokens,
                )
                break  # quota owns its own retry budget — never infra-retried

            # Tag how the run terminated so an INFRA_ERROR (agent cut short by
            # infrastructure, not a genuine attempt) is distinguishable from a
            # real FAIL — and, when the model did no work, retried right here.
            ctx = TerminationContext(
                backend=backend.name,
                jsonl_path=agent_jsonl,
                approach=backend.approach,
                provider=backend.provider,
                request_audit_validator=backend.validate_request_audit,
                agent_exit=result.get("agent_exit"),
                error=result.get("error", ""),
                stderr_path=agent_stderr,
            )
            result["termination_reason"] = classify(ctx)

            # Preserve the existing replay decision: only an approved infra
            # shape with no evidence of model work is retried.
            infra_retriable = (
                result["termination_reason"] == TerminationReason.INFRA_ERROR
                and backend.is_infra_retryable(ctx)
                and not _retry_may_duplicate_model_work(backend, agent_jsonl, attempt_usage, output_tokens)
            )
            if not infra_retriable:
                break
            infra_reasons.append(startup_error_snippet(ctx))
            if attempt >= item.infra_retries:
                break  # out of retries — the caller records the exhaustion

            _stash_failed_attempt(
                agent_dir,
                attempt,
                backend,
                time_secs=attempt_secs,
                usage=attempt_usage,
            )
            if fixed_workspace is None:
                shutil.rmtree(workspace, ignore_errors=True)
                workspace = None
            shutil.rmtree(canonical_dir, ignore_errors=True)
            canonical_dir = None
            base = INFRA_RETRY_BACKOFF[min(attempt, len(INFRA_RETRY_BACKOFF) - 1)]
            delay = base + random.uniform(0, base / 2)  # jitter: keep --jobs workers out of lockstep
            print(
                f"[{name_no_ext}] transient infra failure ({infra_reasons[-1]}) — "
                f"retrying in {delay:.0f}s (retry {attempt + 1}/{item.infra_retries})",
                flush=True,
            )
            time.sleep(delay)
    except BaseException:
        # An attempt blew up mid-flight: the caller only ever owns what we
        # return, so don't leak this attempt's dirs (never a fixed workspace).
        if fixed_workspace is None and workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        if canonical_dir:
            shutil.rmtree(canonical_dir, ignore_errors=True)
        raise

    if infra_reasons:
        result["infra_retries"] = attempt  # retries performed (0-based final attempt index)
        result["infra_retry_reasons"] = infra_reasons
    model_work_observed = _retry_may_duplicate_model_work(
        backend,
        agent_jsonl,
        attempt_usage,
        attempt_usage.legacy_output_tokens,
    )
    interrupted = quota_exhausted or result.get("termination_reason") == TerminationReason.INFRA_ERROR
    graded_module_progress = item.module_checkpoint_identity is not None and model_work_observed
    non_experiment_attempt = _supports_cost_time(backend) and interrupted and not graded_module_progress
    if non_experiment_attempt:
        category = "quota-attempts" if quota_exhausted else "attempts"
        _write_attempt_accounting(
            os.path.join(agent_dir, category, f"attempt-{attempt}"),
            time_secs=attempt_secs,
            usage=attempt_usage,
            backend=backend,
        )
        attempt_usage = UsageSummary(
            sources=("runner.non_experiment_attempt",),
            available=False,
            warnings=("infra/quota accounting is stored separately under agent artifacts",),
        )
        result["agent_time_secs"] = None
        result["logical_timeout_used_secs"] = 0.0
        result["time_secs"] = None
        result["equivalent_cost_usd"] = None
        result["usage"] = attempt_usage.to_dict()
        result["input_tokens"] = 0
        result["output_tokens"] = 0
    elif interrupted and not model_work_observed:
        result["logical_timeout_used_secs"] = 0.0
    outcome_usage = attempt_usage if _supports_cost_time(backend) else (aggregate_usage or attempt_usage)
    return ExecutionOutcome(
        workspace,
        canonical_dir,
        transcript,
        quota_exhausted,
        quota_retry_suppressed,
        infra_retriable,
        model_work_observed,
        infra_reasons,
        outcome_usage,
    )


def _resume_should_skip(result: dict) -> bool:
    """Resume skips genuine completed work: SKIP, first-attempt PASS, or continuation PASS."""
    return is_skipped(result) or (is_pass_with_continuations(result) and not is_non_genuine(result))


def _record_result(results: list[dict], new_result: dict) -> None:
    """Record the latest formal result, replacing a previous resume attempt."""
    benchmark = new_result["benchmark"]
    results[:] = [result for result in results if result.get("benchmark") != benchmark]
    results.append(new_result)


def _load_resume_results(output_dir: str) -> list[dict]:
    """Load a resumable result list without accepting ambiguous persisted data."""

    path = os.path.join(output_dir, "results.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read prior results {path!r}: {exc}") from exc
    if type(value) is not list or any(type(result) is not dict for result in value):
        raise ValueError(f"prior results {path!r} must be a JSON list of objects")
    benchmark_ids = [result.get("benchmark") for result in value]
    if any(type(benchmark) is not str or not benchmark for benchmark in benchmark_ids):
        raise ValueError(f"prior results {path!r} contain a missing or invalid benchmark ID")
    if len(benchmark_ids) != len(set(benchmark_ids)):
        raise ValueError(f"prior results {path!r} contain duplicate benchmark IDs")
    return value


def _validate_resume_result_accounting(results: list[dict], *, supports_cost_time: bool) -> None:
    """Reject values that would make cumulative resume reporting ambiguous."""

    totals: dict[str, list[float]] = {"time_secs": [], "equivalent_cost_usd": []}
    for result in results:
        benchmark = result["benchmark"]
        verdict = result.get("check_verdict")
        if type(verdict) is not str or not verdict:
            raise ValueError(f"prior result {benchmark!r} has no non-empty check_verdict")
        for field in ("input_tokens", "output_tokens"):
            value = result.get(field, 0)
            if type(value) is not int or value < 0:
                raise ValueError(f"prior result {benchmark!r} has invalid {field}: expected a non-negative integer")
        time_secs = result.get("time_secs")
        if time_secs is None:
            if not supports_cost_time:
                raise ValueError(f"prior result {benchmark!r} has invalid time_secs: expected a non-negative number")
        elif nonnegative_float(time_secs) is None or isinstance(time_secs, bool):
            raise ValueError(f"prior result {benchmark!r} has invalid time_secs: expected a finite non-negative number")
        else:
            totals["time_secs"].append(float(time_secs))
        split_times: dict[str, float] = {}
        for field in ("agent_time_secs", "grading_time_secs"):
            if field not in result:
                continue
            if result.get(field) is None and supports_cost_time and time_secs is None:
                continue
            value = nonnegative_float(result.get(field))
            if value is None or isinstance(result.get(field), bool):
                raise ValueError(f"prior result {benchmark!r} has invalid {field}")
            split_times[field] = value
        if (
            len(split_times) == 2
            and time_secs is not None
            and not math.isclose(
                split_times["agent_time_secs"] + split_times["grading_time_secs"],
                float(time_secs),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            raise ValueError(f"prior result {benchmark!r} has inconsistent split and total time")
        grader_error_time = result.get("grader_error_time_secs")
        if grader_error_time is not None and (
            nonnegative_float(grader_error_time) is None or isinstance(grader_error_time, bool)
        ):
            raise ValueError(f"prior result {benchmark!r} has invalid grader_error_time_secs")
        equivalent_cost = result.get("equivalent_cost_usd")
        if equivalent_cost is not None:
            if nonnegative_float(equivalent_cost) is None or isinstance(equivalent_cost, bool):
                raise ValueError(
                    f"prior result {benchmark!r} has invalid equivalent_cost_usd: expected a finite non-negative number"
                )
            totals["equivalent_cost_usd"].append(float(equivalent_cost))
    for field, values in totals.items():
        if not math.isfinite(sum(values)):
            raise ValueError(f"prior result {field} total is not finite")


def _recover_module_resume(
    output_dir: str,
    previous_results: list[dict],
    checkpoint_identities: dict[str, ModuleCheckpointIdentity],
    checkpoints: dict,
    *,
    max_continuations: int,
) -> tuple[list[dict], dict[str, ModuleResume], set[str]]:
    """Recover exact module stages rather than starting a new pass@1 attempt."""

    for result in previous_results:
        benchmark = result["benchmark"]
        if benchmark not in checkpoint_identities:
            raise ValueError(f"prior result {benchmark!r} is outside the selected module-task cohort")
        if benchmark not in checkpoints:
            raise ValueError(
                "cannot resume theorem-level or pre-checkpoint proof-from-scratch results; "
                f"module task {benchmark!r} has no durable module checkpoint"
            )

    results: list[dict] = []
    resumes: dict[str, ModuleResume] = {}
    completed: set[str] = set()
    for task_id, checkpoint in checkpoints.items():
        result = copy.deepcopy(checkpoint.result)
        receipt = result_module_artifact(result)
        content = read_module_artifact(output_dir, receipt) if receipt is not None else None
        action = _module_resume_action(result, max_continuations=max_continuations)
        state = ModuleResume(
            action=action,
            result=result,
            submission=content,
            artifact_receipt=dict(receipt) if receipt is not None else None,
            checkpoint_sequence=checkpoint.sequence,
        )
        _record_result(results, result)
        if action == MODULE_RESUME_COMPLETE:
            completed.add(task_id)
        else:
            resumes[task_id] = state
    return results, resumes, completed


def _module_resume_action(result: dict[str, object], *, max_continuations: int) -> str:
    """Return the next exact action without discarding prior attempt evidence.

    A pending-grading marker is written immediately after publishing an
    artifact, so a restart grades those saved bytes before any model call. A
    completed first attempt is never rewritten as pass@1. An interrupted
    attempt resumes from its saved bytes with cumulative accounting and only
    its remaining timeout; it does not gain another attempt or continuation.
    """

    if result.get("module_grading_pending") is not None:
        return MODULE_RESUME_GRADE_SAVED
    if _resume_should_skip(result):
        return MODULE_RESUME_COMPLETE
    if is_non_genuine(result):
        return MODULE_RESUME_RETRY_FIRST

    raw_rounds = result.get("continuations")
    rounds = raw_rounds if isinstance(raw_rounds, list) else []
    if rounds and isinstance(rounds[-1], dict) and is_non_genuine(rounds[-1]):
        # Resume the same logical round and budget slot. Its prior process
        # segment remains visible for diagnostics, while accounting and timeout
        # stay cumulative on the active round.
        return MODULE_RESUME_CONTINUE

    if len(rounds) < max_continuations:
        return MODULE_RESUME_CONTINUE
    return MODULE_RESUME_COMPLETE


def _resume_done_benchmarks(results: list[dict]) -> set[str]:
    return {r["benchmark"] for r in results if _resume_should_skip(r)}


def _load_task_list(path: str) -> list[str]:
    """Load exact mode-relative task IDs, preserving the requested order."""

    try:
        with open(path, encoding="utf-8") as f:
            task_ids = [line.strip() for line in f if line.strip()]
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read task list {path!r}: {exc}") from exc

    if not task_ids:
        raise ValueError(f"task list {path!r} is empty")

    seen: set[str] = set()
    duplicates: list[str] = []
    for task_id in task_ids:
        if task_id in seen and task_id not in duplicates:
            duplicates.append(task_id)
        seen.add(task_id)
    if duplicates:
        rendered = ", ".join(repr(task_id) for task_id in duplicates)
        raise ValueError(f"task list {path!r} contains duplicate task ID(s): {rendered}")
    return task_ids


def _resolve_task_list(value: str, mode: Mode) -> str:
    """Resolve a registered cohort name or preserve an explicit file path."""

    if not value:
        raise ValueError("--task-list requires a non-empty name or path")
    filename = NAMED_TASK_LISTS.get(value)
    if filename is None:
        return value
    path = os.path.join(mode.benchmark_dir(), filename)
    if not os.path.isfile(path):
        raise ValueError(f"named task list {value!r} is not available for mode {mode.name!r}")
    return path


def _select_exact_tasks(mode: Mode, task_ids: list[str]) -> list[str]:
    """Resolve exact task IDs against the mode's complete discovered cohort."""

    tasks_by_id = {
        os.path.relpath(benchmark_path, mode.benchmark_dir()): benchmark_path
        for benchmark_path in mode.get_benchmark_files()
    }
    unknown = [task_id for task_id in task_ids if task_id not in tasks_by_id]
    if unknown:
        rendered = ", ".join(repr(task_id) for task_id in unknown)
        raise ValueError(f"unknown task ID(s) for mode {mode.name!r}: {rendered}")
    return [tasks_by_id[task_id] for task_id in task_ids]


def _task_list_record_payload(mode_name: str, task_ids: list[str]) -> dict:
    return {"mode": mode_name, "tasks": sorted(task_ids)}


def _validate_resume_task_list(output_dir: str, mode_name: str, task_ids: list[str] | None) -> None:
    """Reject resumes whose recorded cohort differs from the current selection."""

    record_path = os.path.join(output_dir, TASK_LIST_RECORD)
    results_path = os.path.join(output_dir, "results.json")
    if not os.path.isfile(record_path):
        if task_ids is not None and os.path.isfile(results_path):
            raise ValueError(
                f"cannot resume with --task-list: {output_dir!r} has results.json but no {TASK_LIST_RECORD}"
            )
        return

    if task_ids is None:
        raise ValueError(f"cannot resume without --task-list: {output_dir!r} was created with a recorded task list")

    try:
        with open(record_path, encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read recorded task list {record_path!r}: {exc}") from exc

    expected = _task_list_record_payload(mode_name, task_ids)
    if recorded != expected:
        raise ValueError(f"cannot resume with a different task list or mode; recorded cohort is in {record_path!r}")


def _write_task_list_record(output_dir: str, mode_name: str, task_ids: list[str] | None) -> None:
    """Persist task-list provenance, or clear stale provenance for a new Full/filter run."""

    record_path = os.path.join(output_dir, TASK_LIST_RECORD)
    if task_ids is None:
        if os.path.isfile(record_path):
            os.remove(record_path)
        return
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(_task_list_record_payload(mode_name, task_ids), f, indent=2)
        f.write("\n")


def _update_identity_digest(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, byteorder="big"))
    digest.update(value)


def _corpus_digest(mode: Mode, proof_library_digest: str) -> str:
    root = os.path.abspath(mode.benchmark_dir())
    paths = [os.path.join(root, "manifest.json")]
    paths.extend(path for path in glob.glob(os.path.join(root, "**", "*.tla"), recursive=True) if os.path.isfile(path))
    digest = hashlib.sha256()
    _update_identity_digest(digest, b"proof-from-scratch-corpus-v1")
    _update_identity_digest(digest, proof_library_digest.encode())
    for path in sorted(set(paths)):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        _update_identity_digest(digest, relative.encode())
        _update_identity_digest(digest, _read_bytes(path))
    return digest.hexdigest()


def _benchmark_revision() -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    value = revision.stdout.strip() if revision.returncode == 0 else "unknown"
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return f"{value}-dirty" if dirty.returncode == 0 and dirty.stdout.strip() else value


def _container_verification_environment(
    image: str,
) -> tuple[OfficialLibraryCatalog, dict[str, object]]:
    """Read the proof libraries and verifier identity from the selected image."""

    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from common.verification_toolchain import verification_toolchain_identity",
            "catalog = json.loads(Path('/opt/proof-libraries/proof-library-catalog.json').read_bytes())",
            "toolchain = verification_toolchain_identity(",
            "    Path('/opt/tlapm/bin/tlapm'),",
            "    Path('/opt/sany/lib/tla2tools.jar'),",
            "    lock_path=Path('/opt/tlaps-bench/config/verification-toolchain.json'),",
            "    platform_key='linux-x86_64',",
            ")",
            "print(json.dumps({'catalog': catalog, 'toolchain': toolchain}, sort_keys=True))",
        )
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python3",
                "--env",
                "PYTHONPATH=/opt/tlaps-bench/src",
                image,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"cannot inspect proof environment in Docker image {image}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValueError(f"cannot inspect proof environment in Docker image {image}: {detail or 'unknown error'}")
    try:
        value = json.loads(result.stdout)
        if type(value) is not dict or set(value) != {"catalog", "toolchain"}:
            raise ValueError("unexpected proof environment shape")
        catalog = OfficialLibraryCatalog.from_bytes(
            (json.dumps(value["catalog"], sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        toolchain = validate_toolchain_identity(value["toolchain"])
    except (json.JSONDecodeError, ProofLibraryError, VerificationToolchainError, ValueError) as exc:
        raise ValueError(f"invalid proof environment from Docker image {image}: {exc}") from exc
    return catalog, toolchain


def _native_verification_environment() -> tuple[OfficialLibraryCatalog, dict[str, object]]:
    ensure_tlapm()
    tlapm_library = os.path.join(REPO_ROOT, "lib", "tlapm")
    if not os.path.isdir(tlapm_library):
        raise ValueError(f"pinned official tlapm library not found at {tlapm_library}; run make setup")
    catalog = scan_official_libraries()
    toolchain = verification_toolchain_identity(
        Path(TLAPM_PERSISTENT) / "bin" / "tlapm",
        Path(REPO_ROOT) / "lib" / "tla2tools.jar",
    )
    return catalog, toolchain


def _proof_from_scratch_run_identity(
    mode: Mode,
    catalog: OfficialLibraryCatalog,
    toolchain: dict[str, object],
    execution_policy: dict[str, object],
    agent_skills_snapshot: AgentSkillsSnapshot,
) -> dict[str, object]:
    return {
        "schema_version": 5,
        "mode": mode.name,
        "benchmark_revision": _benchmark_revision(),
        "execution_source_digest": _image_source_fingerprint(),
        "agent_skills_digest": agent_skills_snapshot.digest(),
        "agent_skills": list(agent_skills_snapshot.names),
        "corpus_digest": _corpus_digest(mode, catalog.digest),
        "proof_library_digest": catalog.digest,
        "proof_library_sources": {name: dict(source) for name, source in catalog.sources.items()},
        "verification_toolchain_digest": toolchain["digest"],
        "verification_toolchain": toolchain,
        "execution_policy": execution_policy,
    }


def _execution_policy_identity(
    backend: Backend,
    *,
    use_container: bool,
    timeout: int,
    check_timeout: int,
    infra_retries: int,
    max_continuations: int,
    session_dir: str,
) -> dict[str, object]:
    """Freeze every option that can change an attempt or its reported score."""

    return {
        "backend": backend.name,
        "approach": backend.approach,
        "model": getattr(backend, "model", None),
        "reasoning_effort": backend.reasoning_effort,
        "max_output_tokens": backend.max_output_tokens,
        "environment": "container" if use_container else "local",
        "timeout": timeout,
        "check_timeout": check_timeout,
        "infra_retries": infra_retries,
        "max_continuations": max_continuations,
        # A resumed module must see the same backend state tree. Unlike the
        # task artifact, this mutable CLI state is not copied into the output
        # checkpoint; pre-existing contents remain an operator-controlled input.
        "session": {
            "persistence": bool(session_dir),
            "root": session_dir or None,
            "key_scheme": SESSION_KEY_SCHEME,
        },
    }


def _validate_resume_run_manifest(output_dir: str, expected: dict[str, object] | None) -> None:
    if expected is None:
        return
    record_path = os.path.join(output_dir, RUN_MANIFEST_RECORD)
    results_path = os.path.join(output_dir, "results.json")
    if not os.path.isfile(record_path):
        if os.path.isfile(results_path):
            raise ValueError(f"cannot resume proof-from-scratch results without the recorded {RUN_MANIFEST_RECORD}")
        return
    try:
        with open(record_path, encoding="utf-8") as stream:
            recorded = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read recorded run identity {record_path!r}: {exc}") from exc
    # Keep the Git revision as provenance, but do not make it a resume gate:
    # unrelated commits can preserve every run input, while dirty edits to
    # prompts/checker sources are captured by execution_source_digest.
    comparable_recorded = {key: value for key, value in recorded.items() if key != "benchmark_revision"}
    comparable_expected = {key: value for key, value in expected.items() if key != "benchmark_revision"}
    if comparable_recorded != comparable_expected:
        raise ValueError(
            "cannot resume with different benchmark, execution, official proof-library, or verification-toolchain "
            "inputs; "
            f"recorded identity is in {record_path!r}"
        )


def _write_run_manifest(output_dir: str, identity: dict[str, object] | None) -> None:
    if identity is None:
        return
    with open(os.path.join(output_dir, RUN_MANIFEST_RECORD), "w", encoding="utf-8") as stream:
        json.dump(identity, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _total_benchmark_count(results: list[dict], selected_benchmarks: set[str]) -> int:
    """Count unique benchmarks in the cumulative results and current selection."""
    return len(selected_benchmarks | {result["benchmark"] for result in results})


def _continuation_note(result: dict) -> str:
    """One-phrase outcome of a result's continuation rounds ("" without any):
    the round that recovered a PASS, a chain infra/quota-cut before resolving,
    or how many genuine rounds still didn't pass."""
    rounds = result.get("continuations") or []
    if not rounds:
        return ""
    passed = next((r["round"] for r in rounds if r.get("check_verdict") == "PASS"), None)
    if passed is not None:
        return f"PASS on continuation {passed}"
    if continuation_interrupted(result):
        return f"continuation chain cut at round {len(rounds)} (excluded — re-run)"
    return f"no PASS after {len(rounds)} continuation(s)"


def _sum_required_metric(results: list[dict], field: str) -> float | None:
    if not results:
        return None
    values = [nonnegative_float(result.get(field)) for result in results]
    return sum(value for value in values if value is not None) if all(value is not None for value in values) else None


def _formal_results(results: list[dict]) -> list[dict]:
    """Results whose accounting belongs to the benchmark experiment."""

    return [result for result in results if not is_skipped(result) and not is_non_genuine(result)]


def _equivalent_cost_warnings(results: list[dict]) -> list[tuple[str, str]]:
    warnings: list[tuple[str, str]] = []
    for result in _formal_results(results):
        usage = result.get("usage")
        raw_warnings = usage.get("warnings") if isinstance(usage, dict) else None
        if not isinstance(raw_warnings, list):
            continue
        benchmark = str(result.get("benchmark", "?"))
        warnings.extend(
            (benchmark, warning)
            for warning in raw_warnings
            if isinstance(warning, str) and warning.startswith("equivalent cost ")
        )
    return warnings


def _format_task_time(value: object) -> str:
    parsed = nonnegative_float(value)
    return "unavailable" if parsed is None else f"{parsed:,.1f}s"


def _format_equivalent_cost(value: object) -> str:
    parsed = nonnegative_float(value)
    if parsed is None:
        return "unavailable"
    if parsed == 0 or parsed >= 0.000001:
        return f"${parsed:,.6f}"
    return f"${parsed:.6g}"


def update_summary(results, output_dir, total_benchmarks, backend_name, mode_name, specification_ids=None):
    """Incrementally update summary.md + results.json with current results."""
    with _summary_lock:
        supports_cost_time = backend_name in _COST_TIME_BACKENDS
        total = len(results)
        verdicts = {}
        for r in results:
            v = r["check_verdict"]
            verdicts[v] = verdicts.get(v, 0) + 1

        total_tokens = aggregate_token_usage(results)
        formal_results = _formal_results(results)
        total_agent_time = _sum_required_metric(formal_results, "agent_time_secs")
        total_grading_time = _sum_required_metric(formal_results, "grading_time_secs")
        total_task_time = _sum_required_metric(formal_results, "time_secs")
        total_equivalent_cost = (
            _sum_required_metric(formal_results, "equivalent_cost_usd") if supports_cost_time else None
        )

        lines = []
        lines.append(f"# {backend_name} on {mode_name}\n")
        lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Progress**: {total}/{total_benchmarks}")
        corpus_digests = {result.get("corpus_digest") for result in results if result.get("corpus_digest")}
        library_digests = {
            result.get("proof_library_digest") for result in results if result.get("proof_library_digest")
        }
        if len(corpus_digests) == 1:
            lines.append(f"**Corpus digest**: `{next(iter(corpus_digests))}`")
        if len(library_digests) == 1:
            lines.append(f"**Official proof libraries**: `{next(iter(library_digests))}`")
        diagnostic_score_lines: list[str] = []
        if specification_ids is None:
            # Generic/custom modes may not expose a specification identity map.
            pass_pct, n_pass, scored = weighted_score(results, SCORERS["equal"])
            n_skip = n_skipped(results)
            non_genuine = n_non_genuine(results)
            pass_line = f"**Pass rate**: {n_pass}/{scored} ({pass_pct:.1f}%)"
            if n_skip:
                pass_line += f" · {n_skip} skipped"
            if non_genuine:
                pass_line += f" · {non_genuine} error/interrupted (excluded — re-run)"
            diagnostic_score_lines.append(pass_line)
            continuation_results = results
        else:
            score_lines, specification_score = specification_score_lines(results, specification_ids)
            if total < total_benchmarks:
                score_lines[0] = (
                    "**Specification pass rate**: pending until the run completes "
                    f"({total}/{total_benchmarks} tasks finished)"
                )
            diagnostic_score_lines.extend(score_lines)
            n_pass = specification_score.tasks_passed
            continuation_results = applicable_manifest_results(results, specification_ids)
        # One module scores k/n trusted theorems (#132), so this is the primary
        # proof-from-scratch metric. Whole-module PASS remains a diagnostic.
        unit_line = proof_unit_rate_line(continuation_results)
        if unit_line:
            lines.append(unit_line)
        lines.extend(diagnostic_score_lines)
        # Separate, clearly-labeled continuation metrics; pass@1 stays intact.
        cont_line = continuation_rate_line(continuation_results, SCORERS["equal"], n_pass)
        if cont_line:
            lines.append(cont_line)
        continuation_unit_line = proof_unit_rate_line(continuation_results, with_continuations=True)
        if continuation_unit_line and any(result.get("continuations") for result in continuation_results):
            lines.append(continuation_unit_line)
        lines.append(f"**Total tokens**: {format_token_usage(total_tokens, verbose=True)}")
        lines.append(f"**Total agent time**: {_format_task_time(total_agent_time)}")
        lines.append(f"**Total grading time**: {_format_task_time(total_grading_time)}")
        lines.append(f"**Total task time**: {_format_task_time(total_task_time)}")
        if supports_cost_time:
            lines.append(f"**Equivalent cost**: {_format_equivalent_cost(total_equivalent_cost)}\n")
        else:
            lines.append("")

        lines.append("## Summary\n")
        lines.append("| Verdict | Count |")
        lines.append("|---------|-------|")
        for v in ["PASS", "FAIL", "CHEATING", "TIMEOUT", "ERROR"]:
            count = verdicts.get(v, 0)
            if count > 0:
                icon = VERDICT_ICONS[v]
                lines.append(f"| {icon} {v} | {count} |")
        lines.append("")

        lines.append("## Details\n")
        if supports_cost_time:
            lines.append(
                "| Benchmark | Verdict | Agent | Grading | Total | Equivalent cost | Obligations | Tokens (in/out) | Notes |"
            )
            lines.append(
                "|-----------|---------|------:|--------:|------:|----------------:|-------------|-----------------|-------|"
            )
        else:
            lines.append("| Benchmark | Verdict | Agent | Grading | Total | Obligations | Tokens (in/out) | Notes |")
            lines.append("|-----------|---------|------:|--------:|------:|-------------|-----------------|-------|")
        for r in sorted(results, key=lambda x: x["benchmark"]):
            icon = VERDICT_ICONS.get(r["check_verdict"], "❓")
            notes = r.get("error", "")
            # Flag a SANY-invalid FAIL distinctly (solution rejected by the
            # canonical parser, vs a proof that simply didn't verify).
            if r.get("sany_status") == "invalid":
                notes = ("SANY✗ " + notes).strip()
            elif r.get("sany_status") == "unavailable":
                notes = ("SANY unavailable " + notes).strip()
            if is_non_genuine(r):
                reason = r.get("termination_reason", "non-genuine")
                notes = (f"{reason} (excluded — re-run) " + notes).strip()
            # Name the tamper/admit check(s) behind a CHEATING verdict so a cheat
            # is distinguishable from an honest incomplete FAIL at a glance.
            if r.get("check_verdict") == "CHEATING" and r.get("cheat_checks"):
                notes = (",".join(r["cheat_checks"]) + " " + notes).strip()
            cont = _continuation_note(r)
            if cont:
                notes = (cont + " " + notes).strip()
            if r.get("proof_unit_count"):
                trusted_count = r.get("trusted_proof_unit_count", 0)
                unit_note = f"pass@1 trusted {trusted_count}/{r['proof_unit_count']} proof units"
                graded_rounds = [
                    round_result
                    for round_result in (r.get("continuations") or [])
                    if isinstance(round_result, dict) and "trusted_proof_unit_count" in round_result
                ]
                if graded_rounds:
                    latest_count = graded_rounds[-1]["trusted_proof_unit_count"]
                    unit_note += f"; latest continuation trusted {latest_count}/{r['proof_unit_count']}"
                notes = (unit_note + " " + notes).strip()
            tokens = format_token_usage(result_token_usage(r))
            if "obligations" in r:
                prefix = "≥" if r.get("obligations_complete") is False else ""
                obs = f"{prefix}{r['obligations']}"
            elif "obligations_failed" in r:
                obs = f"{r['obligations_failed']}/{r['obligations_total']} failed"
            else:
                obs = ""
            if supports_cost_time:
                lines.append(
                    f"| `{r['benchmark']}` | {icon} {r['check_verdict']} | "
                    f"{_format_task_time(r.get('agent_time_secs'))} | "
                    f"{_format_task_time(r.get('grading_time_secs'))} | "
                    f"{_format_task_time(r.get('time_secs'))} | "
                    f"{_format_equivalent_cost(r.get('equivalent_cost_usd'))} | {obs} | {tokens} | {notes} |"
                )
            else:
                lines.append(
                    f"| `{r['benchmark']}` | {icon} {r['check_verdict']} | "
                    f"{_format_task_time(r.get('agent_time_secs'))} | "
                    f"{_format_task_time(r.get('grading_time_secs'))} | "
                    f"{_format_task_time(r.get('time_secs'))} | {obs} | {tokens} | {notes} |"
                )
        lines.append("")
        cost_warnings = _equivalent_cost_warnings(results) if supports_cost_time else []
        if cost_warnings:
            lines.append("## Cost warnings\n")
            lines.extend(f"- `{benchmark}`: {warning}" for benchmark, warning in cost_warnings)
            lines.append("")

        report = "\n".join(lines)
        report_path = os.path.join(output_dir, "summary.md")
        with open(report_path, "w") as f:
            f.write(report)

        _atomic_json_write(os.path.join(output_dir, "results.json"), results)


def _atomic_json_write(path: str, value: object) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _persist_work_item_result(item: WorkItem, result_dir: str, result: dict) -> bool:
    checkpointed = True
    if item.module_checkpoint_identity is not None:
        try:
            write_module_checkpoint(item.output_dir, item.module_checkpoint_identity, result)
        except ModuleCheckpointError as exc:
            checkpointed = False
            result["check_verdict"] = "ERROR"
            result["error"] = f"cannot checkpoint module progress: {exc}"
            result["termination_reason"] = TerminationReason.INFRA_ERROR
    _atomic_json_write(os.path.join(result_dir, "result.json"), result)
    return checkpointed


def _preserve_module_submission(
    item: WorkItem,
    solution_path: str,
    *,
    disposition: str,
    copy_solution: bool,
    submission_error: str | None = None,
) -> tuple[str | None, dict | None]:
    """Preserve a submitted module, or report a model-owned invalid submission.

    A workspace starts with the canonical task file.  A backend that cannot
    materialize a response must therefore not let that untouched file become
    the module artifact (or the input to grading).  Missing and empty files
    and non-regular target paths are ordinary failed submissions; failures to
    publish otherwise valid bytes remain infrastructure errors at the call site.
    """
    if item.module_checkpoint_identity is None:
        return None, None

    if disposition != SubmissionDisposition.GRADE or not copy_solution:
        if os.path.lexists(solution_path):
            if os.path.islink(solution_path) or os.path.isfile(solution_path):
                os.unlink(solution_path)
        return (
            submission_error or "module submission was not materialized",
            None,
        )

    if os.path.islink(solution_path):
        return "module submission path is a symlink", None
    try:
        metadata = os.lstat(solution_path)
    except FileNotFoundError:
        return "module submission is missing", None
    if not stat.S_ISREG(metadata.st_mode):
        return "module submission path is not a regular file", None
    descriptor = os.open(
        solution_path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return "module submission path is not a regular file", None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not content:
        return "module submission is empty", None
    return None, publish_module_artifact(item.output_dir, content)


def _restore_latest_durable_module(
    item: WorkItem,
    solution_path: str,
    result: dict,
    canonical_inputs: CanonicalInputs,
) -> None:
    """Match the workspace state a resume reconstructs after invalid output."""

    receipt = result_module_artifact(result)
    content = read_module_artifact(item.output_dir, receipt) if receipt is not None else canonical_inputs.target_bytes
    if os.path.lexists(solution_path):
        if os.path.islink(solution_path) or not os.path.isdir(solution_path):
            os.unlink(solution_path)
        else:
            shutil.rmtree(solution_path)
    _write_bytes(solution_path, content)


def _grade_resumed_module_submission(
    item: WorkItem,
    workspace: str,
    result: dict,
    result_dir: str,
    grading_dir: str,
    basename: str,
    name_no_ext: str,
    canonical_inputs: CanonicalInputs,
) -> None:
    """Grade the exact artifact named by a pending checkpoint, without an agent."""

    pending_round = result.get("module_grading_pending")
    if type(pending_round) is not int or pending_round < 0:
        raise ModuleCheckpointError("resumed module has no valid pending grading round")
    if pending_round == 0:
        attempt = result
        attempt_dir = grading_dir
    else:
        rounds = result.get("continuations")
        if not isinstance(rounds, list) or pending_round != len(rounds) or not isinstance(rounds[-1], dict):
            raise ModuleCheckpointError("resumed module pending grading does not identify its latest continuation")
        attempt = rounds[-1]
        attempt_dir = os.path.join(result_dir, "continuations", f"round-{pending_round}")
        os.makedirs(attempt_dir, exist_ok=True)

    solution_path = os.path.join(workspace, basename)
    if not os.path.isfile(solution_path):
        raise ModuleArtifactError("resumed module artifact did not materialize as a regular task file")
    shutil.copy2(solution_path, os.path.join(attempt_dir, "solution.tla"))
    grading_before = nonnegative_float(attempt.get("grading_time_secs")) or 0.0
    _grade_submission(
        item,
        attempt,
        workspace,
        attempt_dir,
        os.path.join(attempt_dir, "check.result"),
        basename,
        name_no_ext,
        canonical_inputs,
        None,
    )
    if pending_round > 0:
        _ensure_time_breakdown(result)
        latest_grading = nonnegative_float(attempt.get("grading_time_secs"))
        prior_grading = nonnegative_float(result.get("grading_time_secs"))
        if latest_grading is not None and prior_grading is not None:
            _add_child_grading_time(result, latest_grading - grading_before)
    if isinstance(attempt.get("module_result"), dict) and attempt.get("check_verdict") != "ERROR":
        result.pop("module_grading_pending", None)


def run_single_benchmark(item: WorkItem):
    """Run one evaluator backend on a single benchmark. Returns result dict."""
    backend = item.backend
    mode = item.mode

    # Enforce backend capabilities at the actual execution boundary, before an
    # invalid direct Python call can clear prior artifacts or touch quota/state.
    item.infra_retries = backend.validate_options(item.infra_retries, item.max_continuations)

    rel_path = os.path.relpath(item.benchmark_path, mode.benchmark_dir()).replace(os.sep, "/")
    module_dir = os.path.dirname(rel_path).replace(os.sep, "/")
    basename = os.path.basename(item.benchmark_path)
    name_no_ext = os.path.splitext(basename)[0]

    # Structured result directory: input/, agent/, grading/
    result_dir = os.path.join(item.output_dir, os.path.splitext(rel_path)[0])
    input_dir = os.path.join(result_dir, "input")
    agent_dir = os.path.join(result_dir, "agent")
    grading_dir = os.path.join(result_dir, "grading")
    _reset_benchmark_artifacts(
        item.output_dir,
        result_dir,
        resume_checkpoint_sequence=(item.module_resume.checkpoint_sequence if item.module_resume is not None else None),
    )
    for d in (input_dir, agent_dir, grading_dir):
        os.makedirs(d, exist_ok=True)

    result = {
        "benchmark": rel_path,
        "module": module_dir,
        "theorem": name_no_ext,
        "backend": backend.name,
        "mode": mode.name,
        "agent_exit": -1,
        "check_verdict": "ERROR",
        "agent_time_secs": None if _supports_cost_time(backend) else 0,
        "grading_time_secs": 0.0,
        "logical_timeout_used_secs": 0.0,
        "time_secs": None if _supports_cost_time(backend) else 0,
        "logical_timeout_secs": item.timeout,
        "error": "",
        # Skill availability, not evidence that the client invoked a skill.
        "agent_skills": [],
        # How the agent run ended; reclassified after the run (see termination.py).
        # INFRA_ERROR marks a result that was cut short by infrastructure rather
        # than a genuine model attempt, so a FAIL can be filtered/retried.
        "termination_reason": TerminationReason.OK,
        **backend.initial_result_metadata(),
    }
    module_resume = item.module_resume
    recovered_result = module_resume is not None and module_resume.action in {
        MODULE_RESUME_RETRY_FIRST,
        MODULE_RESUME_GRADE_SAVED,
        MODULE_RESUME_CONTINUE,
    }
    control_flow_resume = module_resume is not None and module_resume.action in {
        MODULE_RESUME_GRADE_SAVED,
        MODULE_RESUME_CONTINUE,
    }
    retrying_first_attempt = module_resume is not None and module_resume.action == MODULE_RESUME_RETRY_FIRST
    if recovered_result:
        result = copy.deepcopy(module_resume.result)
    module_spec_loader = getattr(mode, "module_task_spec", None)
    if module_spec_loader is not None:
        module_spec = module_spec_loader(item.benchmark_path)
        result["proof_unit_ids"] = list(module_spec.proof_unit_ids)
        result["proof_unit_count"] = len(module_spec.proof_unit_ids)
        result.setdefault("trusted_proof_unit_count", 0)
    if module_resume is not None:
        result["resumed_from_checkpoint"] = True
        result["resume_checkpoint_sequence"] = module_resume.checkpoint_sequence
        if module_resume.submission is not None:
            result["resume_submission_sha256"] = hashlib.sha256(module_resume.submission).hexdigest()
        if module_resume.artifact_receipt is not None:
            result["resume_artifact_sha256"] = module_resume.artifact_receipt["sha256"]
    if item.run_identity is not None:
        result["corpus_digest"] = item.run_identity["corpus_digest"]
        result["proof_library_digest"] = item.run_identity["proof_library_digest"]
    if _supports_cost_time(backend) and not recovered_result:
        result["equivalent_cost_usd"] = None
    # Usage is runner-owned structured evidence; backend metadata must not
    # accidentally replace it with a similarly named custom field.
    if not recovered_result:
        result["usage"] = UsageSummary(
            input_tokens=0,
            output_tokens=0,
            model_requests=0,
            sources=("runner",),
            available=True,
            complete=True,
        ).to_dict()
    if item.max_continuations > 0 and not recovered_result:
        # Run-level config, stamped on EVERY result — first-attempt PASSes and
        # non-genuine early exits included — so the continuation metric can
        # state its ≤N budget without guessing from the chains that happened to run.
        result["max_continuations"] = item.max_continuations

    skills_snapshot_dir = os.path.join(input_dir, "skills")
    current_agent_skills = _snapshot_agent_skills(
        backend,
        skills_snapshot_dir,
        item.agent_skills_snapshot,
    )
    if not recovered_result:
        result["agent_skills"] = current_agent_skills

    logical_execution_item = item
    first_attempt_timeout_exhausted = False
    if retrying_first_attempt:
        maybe_item = _logical_attempt_execution_item(item, result)
        if maybe_item is None:
            _mark_logical_attempt_timeout(result)
            if item.max_continuations <= 0:
                _persist_work_item_result(item, result_dir, result)
                return result
            first_attempt_timeout_exhausted = True
        else:
            logical_execution_item = maybe_item

    grading_only_resume = control_flow_resume and module_resume.action == MODULE_RESUME_GRADE_SAVED
    quota_available = grading_only_resume or quota.wait_for_quota(
        item.usage_script,
        item.quota_5h,
        item.quota_7d,
        item.quota_max_waits,
        log_prefix=f"[{name_no_ext}] ",
    )
    if not quota_available:
        if recovered_result:
            _persist_work_item_result(item, result_dir, result)
            return result
        result["agent_exit"] = -3
        result["error"] = "quota exceeded (max waits reached); skipped"
        result["input_tokens"] = 0
        result["output_tokens"] = 0
        result["termination_reason"] = TerminationReason.QUOTA_EXHAUSTED
        if item.module_checkpoint_identity is not None:
            _persist_work_item_result(item, result_dir, result)
        return result

    workspace = None
    canonical_dir = None
    try:
        canonical_inputs = item.canonical_inputs
        if canonical_inputs is None:
            deps = mode.get_dependencies(item.benchmark_path)
            canonical_inputs = CanonicalInputs.capture(item.benchmark_path, basename, deps)

        checker_bin = mode.checker_binary_path()

        # Save input artifacts
        canonical_inputs.materialize(input_dir, target_name="benchmark.tla")
        if module_resume is not None and module_resume.submission is not None:
            _write_bytes(os.path.join(input_dir, "resume.tla"), module_resume.submission)

        if first_attempt_timeout_exhausted:
            workspace = _make_workspace(
                backend.name,
                name_no_ext,
                canonical_inputs,
                skills_snapshot_dir=skills_snapshot_dir,
                project_skills_dir=backend.project_skills_dir,
                read_only_dependencies=getattr(mode, "read_only_dependencies", False),
                initial_target_bytes=module_resume.submission,
            )
            if not _persist_work_item_result(item, result_dir, result):
                return result
            _run_continuations(
                item,
                workspace,
                result,
                result_dir,
                basename,
                name_no_ext,
                canonical_inputs,
                checker_bin,
            )
            return result

        if control_flow_resume:
            workspace = _make_workspace(
                backend.name,
                name_no_ext,
                canonical_inputs,
                skills_snapshot_dir=skills_snapshot_dir,
                project_skills_dir=backend.project_skills_dir,
                read_only_dependencies=getattr(mode, "read_only_dependencies", False),
                initial_target_bytes=module_resume.submission,
            )
            if module_resume.action == MODULE_RESUME_GRADE_SAVED:
                _grade_resumed_module_submission(
                    item,
                    workspace,
                    result,
                    result_dir,
                    grading_dir,
                    basename,
                    name_no_ext,
                    canonical_inputs,
                )
                if not _persist_work_item_result(item, result_dir, result):
                    return result
                if result.get("module_grading_pending") is not None:
                    return result
            if module_resume.action == MODULE_RESUME_CONTINUE or (
                not is_pass_with_continuations(result) and not is_non_genuine(result)
            ):
                if module_resume.action == MODULE_RESUME_GRADE_SAVED and not quota.wait_for_quota(
                    item.usage_script,
                    item.quota_5h,
                    item.quota_7d,
                    item.quota_max_waits,
                    log_prefix=f"[{name_no_ext}] ",
                ):
                    return result
                _run_continuations(
                    item,
                    workspace,
                    result,
                    result_dir,
                    basename,
                    name_no_ext,
                    canonical_inputs,
                    checker_bin,
                )
            return result

        prompt = _build_prompt_from_canonical_inputs(
            backend,
            mode,
            canonical_inputs,
            basename,
            item.tlapm_path,
            item.tlapm_lib,
        )
        if module_resume is not None and module_resume.submission is not None:
            prompt += (
                "\n\n# Resumed progress\n\n"
                "The editable task file already contains the last durably saved partial module from this run. "
                "Continue from that work and keep any proof units that are already correct.\n"
            )
        with open(os.path.join(input_dir, "prompt.txt"), "w") as f:
            f.write(prompt)

        # Run the agent
        agent_jsonl = os.path.join(agent_dir, "output.jsonl")
        agent_stderr = os.path.join(agent_dir, "stderr.txt")

        # Infra retry loop: a run cut short before the model did ANY work says
        # nothing about the model, so it is retried on a fresh workspace instead
        # of graded. Structured usage is authoritative when available.
        previous_logical_attempt = copy.deepcopy(result) if retrying_first_attempt else None
        if previous_logical_attempt is not None:
            _reset_logical_attempt_segment(result, backend)
        run = _run_backend_with_retries(
            logical_execution_item,
            prompt,
            agent_dir,
            agent_jsonl,
            agent_stderr,
            result,
            checker_bin,
            canonical_inputs,
            basename,
            name_no_ext,
            skills_snapshot_dir=skills_snapshot_dir,
        )
        workspace, canonical_dir = run.workspace, run.canonical_dir
        attempt_interrupted = run.quota_exhausted or result.get("termination_reason") == TerminationReason.INFRA_ERROR
        if previous_logical_attempt is not None:
            _merge_logical_attempt_accounting(
                result,
                previous_logical_attempt,
                run.usage,
                include_segment=run.model_work_observed or not attempt_interrupted,
                backend=backend,
            )
        else:
            _refresh_logical_timeout_remaining(result)
        interrupted_after_model_work = run.model_work_observed and attempt_interrupted
        if interrupted_after_model_work:
            # The flag is checkpointed with a pending artifact. It only makes
            # the attempt genuine after a module_result is also present, so a
            # crash between publication and grading still resumes safely.
            result["graded_after_interruption"] = True

        destination = os.path.join(workspace, basename)
        submission = backend.prepare_submission(
            agent_jsonl,
            destination,
            result["termination_reason"],
            result.get("error", ""),
            allow_materialization=not attempt_interrupted or run.model_work_observed,
        )
        _apply_submission_metadata(result, submission.metadata)
        if submission.error is not None:
            result["error"] = submission.error

        with open(os.path.join(agent_dir, "transcript.txt"), "w") as f:
            f.write(f"Benchmark: {rel_path}\n")
            f.write(f"Agent time: {_format_task_time(result.get('agent_time_secs'))}\n")
            if _supports_cost_time(backend):
                f.write(f"Equivalent cost: {_format_equivalent_cost(result.get('equivalent_cost_usd'))}\n")
            f.write(f"Tokens: {format_token_usage(result_token_usage(result), verbose=True)}\n")
            f.write("=" * 60 + "\n\n")
            f.write(run.transcript)

        solution_path = os.path.join(workspace, basename)
        module_submission_failure = None
        has_new_module_submission = not attempt_interrupted or run.model_work_observed
        if item.module_checkpoint_identity is not None and has_new_module_submission:
            try:
                module_submission_failure, module_artifact = _preserve_module_submission(
                    item,
                    solution_path,
                    disposition=submission.disposition,
                    copy_solution=submission.copy_solution,
                    submission_error=submission.error,
                )
                if module_artifact is not None:
                    result["module_artifact"] = module_artifact
                    result["module_grading_pending"] = 0
                    if not _persist_work_item_result(item, result_dir, result):
                        return result
                elif module_submission_failure is not None and interrupted_after_model_work:
                    # Missing/empty output after observed model work has no new
                    # bytes to grade. Keep the marker so resume retains its
                    # accounting while continuing the same logical pass@1; an
                    # existing module_artifact remains the durable fallback.
                    result.pop("graded_after_interruption", None)
                    result["invalid_submission_after_interruption"] = True
            except (OSError, ModuleArtifactError) as exc:
                result["check_verdict"] = "ERROR"
                result["error"] = f"cannot preserve submitted module: {exc}"
                result["termination_reason"] = TerminationReason.INFRA_ERROR
                return result

        if submission.copy_solution and os.path.isfile(solution_path):
            shutil.copy2(solution_path, os.path.join(agent_dir, "solution.tla"))

        agent_check_file = os.path.join(workspace, name_no_ext + ".result")
        if os.path.isfile(agent_check_file):
            shutil.copy2(agent_check_file, os.path.join(grading_dir, "agent_check.result"))

        if run.quota_exhausted:
            # The provider cap either persisted through the retry budget or arrived
            # after paid work, making an automatic retry unsafe. Mark ERROR
            # (retriable via --resume) and skip grading; the artifacts above keep
            # the result directory consistent with a normal run. The runner owns
            # this signal, so tag QUOTA_EXHAUSTED directly instead of classifying
            # the blocked stream as a generic INFRA_ERROR.
            result["agent_exit"] = -3
            result["check_verdict"] = "ERROR"
            result["error"] = (
                "provider usage limit with possible prior model activity; automatic retry suppressed"
                if run.quota_retry_suppressed
                else "provider usage limit; exhausted quota retries"
            )
            result["termination_reason"] = TerminationReason.QUOTA_EXHAUSTED
            if item.module_checkpoint_identity is None or (
                result.get("module_artifact") is None and module_submission_failure is None
            ):
                return result

        if attempt_interrupted and not run.model_work_observed:
            # No formal attempt was made. Whether this particular interruption
            # qualified for an inline retry does not change that fact: never
            # materialize or grade the untouched canonical workspace.
            result["check_verdict"] = "ERROR"
            if not result.get("error"):
                if run.infra_reasons:
                    result["error"] = f"startup/infra failure ({run.infra_reasons[-1]}); exhausted infra retries"
                else:
                    result["error"] = "agent run ended before any model work was observed"
            return result

        if module_submission_failure is not None:
            result["check_verdict"] = "FAIL"
            result["error"] = module_submission_failure
            if item.module_checkpoint_identity is not None and not _persist_work_item_result(item, result_dir, result):
                return result
            if not run.quota_exhausted and item.max_continuations > 0 and not is_non_genuine(result):
                _restore_latest_durable_module(item, solution_path, result, canonical_inputs)
                _run_continuations(
                    item,
                    workspace,
                    result,
                    result_dir,
                    basename,
                    name_no_ext,
                    canonical_inputs,
                    checker_bin,
                )
            return result

        if submission.disposition != SubmissionDisposition.GRADE:
            result["check_verdict"] = submission.disposition
            return result

        # Run grader
        check_result_path = os.path.join(grading_dir, "check.result")
        _grade_submission(
            item,
            result,
            workspace,
            grading_dir,
            check_result_path,
            basename,
            name_no_ext,
            canonical_inputs,
            canonical_dir,
        )
        if interrupted_after_model_work and result.get("module_result") is not None:
            result["graded_after_interruption"] = True
        if isinstance(result.get("module_result"), dict) and result.get("check_verdict") != "ERROR":
            result.pop("module_grading_pending", None)
        if item.module_checkpoint_identity is not None and not _persist_work_item_result(item, result_dir, result):
            return result
        if result.get("module_grading_pending") is not None:
            return result

        # Opt-in continuation rounds: a genuine non-PASS keeps its workspace and
        # the agent is asked to build on its own partial proof. The pass@1 fields
        # above stay untouched; rounds are recorded under result["continuations"].
        if item.max_continuations > 0 and result["check_verdict"] != "PASS" and not is_non_genuine(result):
            _run_continuations(
                item,
                workspace,
                result,
                result_dir,
                basename,
                name_no_ext,
                canonical_inputs,
                checker_bin,
            )

    finally:
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        if canonical_dir:
            shutil.rmtree(canonical_dir, ignore_errors=True)
        _persist_work_item_result(item, result_dir, result)

    return result


def _reset_benchmark_artifacts(
    output_dir: str,
    result_dir: str,
    *,
    resume_checkpoint_sequence: int | None = None,
) -> None:
    """Remove runner-owned artifacts without following generated-path symlinks."""
    output_root = os.path.abspath(output_dir)
    result_path = os.path.abspath(result_dir)
    if os.path.commonpath((output_root, result_path)) != output_root:
        raise RuntimeError(f"benchmark result path escapes output directory: {result_dir}")

    # The user may intentionally make --output-dir itself a symlink, but the
    # runner-generated module/theorem components must be real directories. A
    # symlink there could redirect cleanup into unrelated data outside the run.
    current = output_root
    for component in os.path.relpath(result_path, output_root).split(os.sep):
        if component == ".":
            continue
        current = os.path.join(current, component)
        if os.path.islink(current):
            raise RuntimeError(f"refusing to clean symlinked benchmark result path: {current}")

    resolved_root = os.path.realpath(output_root)
    resolved_result = os.path.realpath(result_path)
    if os.path.commonpath((resolved_root, resolved_result)) != resolved_root:
        raise RuntimeError(f"benchmark result path resolves outside output directory: {result_dir}")

    os.makedirs(result_dir, exist_ok=True)
    owned_names = ("input", "agent", "grading", "continuations", "result.json")
    if resume_checkpoint_sequence is not None:
        if resume_checkpoint_sequence <= 0:
            raise RuntimeError("resume checkpoint sequence must be positive")
        history_root = os.path.join(result_dir, "resume-history")
        if os.path.islink(history_root) or (os.path.lexists(history_root) and not os.path.isdir(history_root)):
            raise RuntimeError(f"refusing unsafe resume history path: {history_root}")
        existing = [name for name in owned_names if os.path.lexists(os.path.join(result_dir, name))]
        if existing:
            os.makedirs(history_root, exist_ok=True)
            prefix = f"checkpoint-{resume_checkpoint_sequence}"
            history_dir = os.path.join(history_root, prefix)
            suffix = 1
            while os.path.lexists(history_dir):
                history_dir = os.path.join(history_root, f"{prefix}-resume-{suffix}")
                suffix += 1
            os.mkdir(history_dir)
            for name in existing:
                os.replace(os.path.join(result_dir, name), os.path.join(history_dir, name))
        return

    for name in owned_names:
        path = os.path.join(result_dir, name)
        if not os.path.lexists(path):
            continue
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def _stash_failed_attempt(
    agent_dir: str,
    attempt: int,
    backend: Backend,
    *,
    time_secs: float | None,
    usage: UsageSummary,
) -> None:
    """Move a failed attempt's raw outputs to agent/attempts/attempt-N/: the
    retry starts clean (no stale stderr.txt) and the evidence stays debuggable."""
    dest = os.path.join(agent_dir, "attempts", f"attempt-{attempt}")
    os.makedirs(dest, exist_ok=True)
    for fname in ("output.jsonl", "stderr.txt", *backend.attempt_output_files()):
        src = os.path.join(agent_dir, fname)
        if os.path.isfile(src):
            shutil.move(src, os.path.join(dest, fname))
    _write_attempt_accounting(dest, time_secs=time_secs, usage=usage, backend=backend)


def _stash_quota_attempt(
    agent_dir: str,
    infra_attempt: int,
    quota_attempt: int,
    backend: Backend,
    *,
    time_secs: float | None,
    usage: UsageSummary,
) -> None:
    """Preserve a no-model-work hard-cap launch before the next launch replaces it."""

    dest = os.path.join(
        agent_dir,
        "quota-attempts",
        f"infra-{infra_attempt}-quota-{quota_attempt}",
    )
    os.makedirs(dest, exist_ok=True)
    for fname in ("output.jsonl", "stderr.txt", *backend.attempt_output_files()):
        src = os.path.join(agent_dir, fname)
        if os.path.isfile(src):
            shutil.move(src, os.path.join(dest, fname))
    _write_attempt_accounting(dest, time_secs=time_secs, usage=usage, backend=backend)


def _run_continuations(
    item: WorkItem,
    workspace: str,
    result: dict,
    result_dir: str,
    basename: str,
    name_no_ext: str,
    canonical_inputs: CanonicalInputs,
    checker_bin: str,
) -> None:
    """Continuation rounds (--max-continuations, off by default).

    A genuine non-PASS mixes two outcomes: the agent stopped early (declared
    itself done with a repairable partial proof still in the file) or it truly
    cannot solve the task. Each round re-runs the agent in the SAME workspace —
    the partial proof is still there — with a continuation prompt telling it to
    build on that prior work, then re-grades; rounds stop at the first PASS, at
    the --max-continuations budget, or when a round is cut short by infra/quota.
    A cut round is unresolved: scoring excludes it, and --resume continues that
    same logical round with its saved proof, accumulated accounting, and
    remaining timeout.

    The top-level result keeps the FIRST attempt's verdict, so pass@1 is
    reported unchanged; each round's verdict/cost is appended to
    result["continuations"] (the run's ≤N budget is stamped on every result as
    max_continuations at init) and the round's tokens/time accumulate into the
    top-level cost fields (the true cost of the whole chain). Artifacts land in
    <result_dir>/continuations/round-N/, shaped like the agent/ + grading/ dirs.
    """
    mode = item.mode
    _ensure_time_breakdown(result)
    prompt = mode.build_continuation_prompt(basename, item.tlapm_path, item.tlapm_lib)
    agent_check_file = os.path.join(workspace, name_no_ext + ".result")
    rounds: list[dict] = result.setdefault("continuations", [])
    retry_round = None
    retry_attempt: dict[str, object] | None = None
    if rounds and is_non_genuine(rounds[-1]):
        interrupted = rounds.pop()
        retry_round = interrupted.get("round")
        if type(retry_round) is not int or retry_round <= 0:
            raise ModuleCheckpointError("interrupted continuation has no valid round number")
        result.setdefault("interrupted_continuations", []).append(interrupted)
        retry_attempt = copy.deepcopy(interrupted)
    first_round = retry_round if retry_round is not None else len(rounds) + 1
    for rnd in range(first_round, item.max_continuations + 1):
        prev_verdict = rounds[-1]["check_verdict"] if rounds else result["check_verdict"]
        print(
            f"[{name_no_ext}] {prev_verdict} — continuing in same workspace (round {rnd}/{item.max_continuations})",
            flush=True,
        )
        round_dir = os.path.join(result_dir, "continuations", f"round-{rnd}")
        os.makedirs(round_dir, exist_ok=True)
        with open(os.path.join(round_dir, "prompt.txt"), "w") as f:
            f.write(prompt)
        agent_jsonl = os.path.join(round_dir, "output.jsonl")
        agent_stderr = os.path.join(round_dir, "stderr.txt")
        previous_logical_attempt = retry_attempt if retry_attempt is not None and retry_round == rnd else None
        execution_item = item
        if previous_logical_attempt is not None:
            round_result = copy.deepcopy(previous_logical_attempt)
            maybe_item = _logical_attempt_execution_item(item, round_result)
            if maybe_item is None:
                _mark_logical_attempt_timeout(round_result)
                rounds.append(round_result)
                if item.module_checkpoint_identity is not None:
                    if not _persist_work_item_result(item, result_dir, result):
                        break
                retry_attempt = None
                continue
            execution_item = maybe_item
            _reset_logical_attempt_segment(round_result, item.backend)
            retry_attempt = None
        else:
            round_result = {
                "round": rnd,
                "agent_exit": -1,
                "check_verdict": "ERROR",
                "agent_time_secs": 0,
                "grading_time_secs": 0.0,
                "logical_timeout_used_secs": 0.0,
                "time_secs": 0,
                "logical_timeout_secs": item.timeout,
                "error": "",
                "termination_reason": TerminationReason.OK,
            }
        # The in-workspace self-check file survives from the previous round (the
        # agent may want to read what failed), so note its state to copy it as
        # this round's evidence only if this round's agent (re)wrote it.
        check_mtime_before = os.stat(agent_check_file).st_mtime_ns if os.path.isfile(agent_check_file) else None

        run = _run_backend_with_retries(
            execution_item,
            prompt,
            round_dir,
            agent_jsonl,
            agent_stderr,
            round_result,
            checker_bin,
            canonical_inputs,
            basename,
            name_no_ext,
            fixed_workspace=workspace,
        )
        try:
            round_usage = run.usage.with_context(continuation_round=rnd)
            round_result["usage"] = round_usage.to_dict()
            round_result["input_tokens"] = round_usage.legacy_input_tokens
            round_result["output_tokens"] = round_usage.legacy_output_tokens
            segment_agent_time = round_result.get("agent_time_secs")
            segment_grading_time = round_result.get("grading_time_secs")
            segment_equivalent_cost = round_result.get("equivalent_cost_usd")
            segment_tool_calls = copy.deepcopy(round_result.get("tool_calls"))
            if run.quota_exhausted:
                round_result["agent_exit"] = -3
                round_result["error"] = (
                    "provider usage limit with possible prior model activity; automatic retry suppressed"
                    if run.quota_retry_suppressed
                    else "provider usage limit; exhausted quota retries"
                )
                round_result["termination_reason"] = TerminationReason.QUOTA_EXHAUSTED
            elif run.infra_retriable:
                round_result["error"] = f"startup/infra failure ({run.infra_reasons[-1]}); exhausted infra retries"

            round_interrupted = (
                run.quota_exhausted or round_result.get("termination_reason") == TerminationReason.INFRA_ERROR
            )
            if previous_logical_attempt is not None:
                _merge_logical_attempt_accounting(
                    round_result,
                    previous_logical_attempt,
                    round_usage,
                    include_segment=run.model_work_observed or not round_interrupted,
                    backend=item.backend,
                )
            else:
                _refresh_logical_timeout_remaining(round_result)

            formal_round = not round_interrupted or (
                item.module_checkpoint_identity is not None and run.model_work_observed
            )
            if formal_round or not _supports_cost_time(item.backend):
                aggregate_usage = UsageSummary.from_dict(result.get("usage")).merge(round_usage)
                result["usage"] = aggregate_usage.to_dict()
                if "tool_calls" in result or "tool_calls" in round_result:
                    result["tool_calls"] = (
                        toolcalls.ToolCallSummary.from_dict(result.get("tool_calls"))
                        .merge(toolcalls.ToolCallSummary.from_dict(segment_tool_calls))
                        .to_dict()
                    )
                result["agent_time_secs"] = _sum_accounting_values(
                    result.get("agent_time_secs"),
                    segment_agent_time,
                )
                result["grading_time_secs"] = _sum_accounting_values(
                    result.get("grading_time_secs"),
                    segment_grading_time,
                )
                _recompute_task_time(result)
                if _supports_cost_time(item.backend):
                    result["equivalent_cost_usd"] = _sum_accounting_values(
                        result.get("equivalent_cost_usd"),
                        segment_equivalent_cost,
                    )
                result["input_tokens"] = aggregate_usage.legacy_input_tokens
                result["output_tokens"] = aggregate_usage.legacy_output_tokens

            with open(os.path.join(round_dir, "transcript.txt"), "w") as f:
                f.write(run.transcript)
            solution_path = os.path.join(workspace, basename)
            if os.path.isfile(solution_path):
                shutil.copy2(solution_path, os.path.join(round_dir, "solution.tla"))
            check_mtime_after = os.stat(agent_check_file).st_mtime_ns if os.path.isfile(agent_check_file) else None
            if check_mtime_after is not None and check_mtime_after != check_mtime_before:
                shutil.copy2(agent_check_file, os.path.join(round_dir, "agent_check.result"))

            # A provider interruption can happen after the module was edited.
            # Preserve and grade those exact bytes for partial progress. A
            # zero-work startup failure still has no experiment to grade.
            cut_short = round_interrupted
            module_submission_failure = None
            has_new_module_submission = not round_interrupted or run.model_work_observed
            if item.module_checkpoint_identity is not None and has_new_module_submission:
                try:
                    module_submission_failure, module_artifact = _preserve_module_submission(
                        item,
                        solution_path,
                        disposition=SubmissionDisposition.GRADE,
                        copy_solution=True,
                    )
                    if module_artifact is not None:
                        round_result["module_artifact"] = module_artifact
                except (OSError, ModuleArtifactError) as exc:
                    round_result["check_verdict"] = "ERROR"
                    round_result["error"] = f"cannot preserve submitted module: {exc}"
                    round_result["termination_reason"] = TerminationReason.INFRA_ERROR
                    cut_short = True
            if module_submission_failure is not None:
                round_result["check_verdict"] = "FAIL"
                round_result["error"] = module_submission_failure
                if round_interrupted and run.model_work_observed:
                    round_result["invalid_submission_after_interruption"] = True

            grade_interrupted_module = (
                item.module_checkpoint_identity is not None
                and round_interrupted
                and run.model_work_observed
                and round_result.get("module_artifact") is not None
            )
            if grade_interrupted_module:
                # Preserve the model-work fact in the pending checkpoint. The
                # round remains non-genuine until a resumed grader supplies a
                # module_result, but that result must make the already-spent
                # formal round genuine instead of rerunning it.
                round_result["graded_after_interruption"] = True
            rounds.append(round_result)
            if module_submission_failure is not None:
                _restore_latest_durable_module(item, solution_path, result, canonical_inputs)
            if round_result.get("module_artifact") is not None:
                result["module_grading_pending"] = rnd
                if not _persist_work_item_result(item, result_dir, result):
                    cut_short = True
            if module_submission_failure is None and (not cut_short or grade_interrupted_module):
                check_result_path = os.path.join(round_dir, "check.result")
                grading_before = nonnegative_float(round_result.get("grading_time_secs")) or 0.0
                _grade_submission(
                    item,
                    round_result,
                    workspace,
                    round_dir,
                    check_result_path,
                    basename,
                    name_no_ext,
                    canonical_inputs,
                    run.canonical_dir,
                )
                grading_after = nonnegative_float(round_result.get("grading_time_secs"))
                if grading_after is not None:
                    _add_child_grading_time(result, grading_after - grading_before)
                if isinstance(round_result.get("module_result"), dict) and round_result.get("check_verdict") != "ERROR":
                    result.pop("module_grading_pending", None)
                elif result.get("module_grading_pending") == rnd:
                    cut_short = True
                if round_result.get("check_verdict") == "ERROR":
                    cut_short = True
        finally:
            shutil.rmtree(run.canonical_dir, ignore_errors=True)

        if item.module_checkpoint_identity is not None:
            _persist_work_item_result(item, result_dir, result)
        if round_result["check_verdict"] == "PASS":
            print(f"[{name_no_ext}] recovered: PASS on continuation round {rnd}", flush=True)
            break
        if cut_short:
            break


def _resolve_session_dir(session_dir_arg: str | None, keep_container: bool, use_container: bool) -> str:
    """Root dir for persisted agent session state: explicit --session-dir, or a
    default under --keep-container so debugging needs a single flag. "" = off."""
    if not use_container:
        return ""
    if session_dir_arg:
        return os.path.realpath(os.path.abspath(session_dir_arg))
    if keep_container:
        return os.path.realpath(os.path.expanduser(os.path.join("~", ".tlaps-bench", "sessions")))
    return ""


def _prepare_session_dir(session_dir: str) -> None:
    """Create the session root and, since session data can hold credentials,
    guard the tree with a .gitignore in case it lands inside a git repo."""
    os.makedirs(session_dir, exist_ok=True)
    gitignore = os.path.join(session_dir, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w") as f:
            f.write("# tlaps-bench session data (may contain credentials) — do not commit\n*\n")


def _work_item_session_key(item: WorkItem) -> str:
    """Return one collision-resistant persistent session key per physical task."""

    root = os.path.abspath(item.mode.benchmark_dir())
    task = os.path.abspath(item.benchmark_path)
    if os.path.commonpath((root, task)) != root:
        raise ValueError(f"benchmark task escapes its mode root: {item.benchmark_path}")
    relative = os.path.relpath(task, root).replace(os.sep, "/")
    stem = os.path.splitext(relative)[0].replace("/", "__")
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", stem).strip("._-") or "task"
    digest = hashlib.sha256(relative.encode()).hexdigest()[:12]
    return f"{slug[:80]}-{digest}"


def _run_backend_container(
    item: WorkItem,
    backend,
    workspace: str,
    agent_dir: str,
    agent_jsonl: str,
    prompt: str,
    result: dict,
    canonical_dir: str | None = None,
    read_only_files: list[str] | None = None,
) -> float | None:
    """Run a backend inside Docker with live output and timeout draining."""
    runner = ContainerRunner()
    timeout = item.timeout if item.timeout and item.timeout > 0 else None
    propagated_deadline = time.time() + timeout if timeout and backend.capabilities.cooperative_deadline else None
    cmd = _build_backend_command(backend, "/workspace", "/results", propagated_deadline)
    cmd, stdin_data = backend.prepare_invocation(cmd, prompt)
    backend_env = forward_env(backend.env_keys, model=getattr(backend, "model", None))
    backend_env.update(backend.execution_environment("/results"))

    config = ContainerConfig(
        image=item.container_image,
        workspace=workspace,
        result_dir=agent_dir,  # mount only agent/ subdir as /results
        # Canonical source snapshot for agent self-checking, bind-mounted read-only.
        # Canonical-replay modes receive a separate fresh snapshot for grading.
        benchmark_dir=canonical_dir or "",
        read_only_files=[(path, f"/workspace/{os.path.basename(path)}") for path in (read_only_files or [])],
        env=backend_env,
        firewall_hosts=backend.firewall_hosts(),
        dynamic_firewall=backend.dynamic_firewall,
        install_script=backend.install_script,
        credential_mounts=backend.get_credential_mounts(),
        keep_container=item.keep_container,
        agent_start_marker=(f"__TLAPS_BENCH_AGENT_START_{uuid.uuid4().hex}__" if _supports_cost_time(backend) else ""),
    )
    name_no_ext = os.path.splitext(os.path.basename(item.benchmark_path))[0]
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name_no_ext)
    if item.keep_container:
        # uuid suffix keeps retained containers unique across retries and jobs
        config.container_name = f"tlaps-bench-{safe}-{uuid.uuid4().hex[:8]}"
    if item.session_dir and backend.session_state_dir:
        # Every module owns one stable session across retries, continuations,
        # and --resume. The full mode-relative task identity prevents modules
        # with the same basename from sharing or concurrently mounting state.
        session_key = _work_item_session_key(item)
        host_session = os.path.join(item.session_dir, backend.name, session_key)
        config.session_dir = host_session
        config.session_container_path = backend.session_state_dir
        print(
            f"[session-dir] persisting {backend.name} session state for '{session_key}' "
            f"to {host_session} (restore with scripts/restore-session.sh)",
            flush=True,
        )
    if canonical_dir:
        config.env["TLAPS_BENCHMARK_DIR"] = "/benchmark"
        config.env[CATALOG_ENV] = f"/benchmark/{CATALOG_FILENAME}"
    if getattr(item.mode, "canonical_replay_required", False):
        config.env["TLAPS_CANONICAL_REPLAY_REQUIRED"] = "1"
    # Self-check uses the SAME tlapm budget as the grader (item.check_timeout),
    # so a proof near the time boundary can't pass the agent's check yet time out
    # at grading.
    config.env["TLAPS_CHECK_TIMEOUT"] = str(item.check_timeout)

    container_run = None
    agent_started_at: float | None = None
    agent_ended_at: float | None = None
    try:
        container_run = runner.run(config, cmd, stdin_data=stdin_data)
        if item.keep_container:
            name = config.container_name
            print(
                f"[keep-container] retaining container '{name}'. After it exits: "
                f"`docker exec -it {name} bash` to inspect (start it first if stopped: "
                f"`docker start {name}`), `docker commit {name} <img>` to snapshot, "
                f"`docker rm -f {name}` to remove.",
                flush=True,
            )
        proc = container_run.proc
        assert proc.stdout is not None  # Popen created with stdout=PIPE

        # Make stderr non-blocking to prevent pipe deadlock (>64KB stderr blocks agent)
        if proc.stderr:
            flags = fcntl.fcntl(proc.stderr, fcntl.F_GETFL)
            fcntl.fcntl(proc.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        stderr_chunks: list[str] = []
        logical_deadline = propagated_deadline or (time.time() + timeout if timeout else None)
        grace = backend.capabilities.timeout_drain_grace if propagated_deadline is not None else 0.0
        hard_deadline = logical_deadline + grace if logical_deadline is not None else None
        timed_out = False

        # Stream stdout to file in real-time (and stderr separately)
        with open(agent_jsonl, "w") as jsonl_f:
            while True:
                now = time.time()
                if logical_deadline is not None and now >= logical_deadline:
                    timed_out = True
                if timed_out and hard_deadline is not None and now >= hard_deadline:
                    runner.kill(container_run)
                    result["agent_exit"] = -1
                    result["error"] = f"{backend.name} timeout after {item.timeout}s"
                    agent_ended_at = time.monotonic()
                    return agent_ended_at - agent_started_at if agent_started_at is not None else None

                boundary = hard_deadline if timed_out else logical_deadline
                poll_timeout = min(5.0, max(boundary - now, 0.0)) if boundary is not None else 5.0
                ready, _, _ = select.select([proc.stdout], [], [], poll_timeout)
                # Drain stderr opportunistically
                if proc.stderr:
                    try:
                        chunk = proc.stderr.read()
                        if chunk:
                            stderr_chunks.append(chunk)
                    except (OSError, BlockingIOError, TypeError):
                        # Non-blocking read with no data: a text-mode pipe raises
                        # TypeError ("can't concat NoneType to bytes") from the
                        # codec when the raw read returns None, rather than
                        # BlockingIOError. Treat all three as "no data yet".
                        pass
                if ready:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        if agent_ended_at is None:
                            agent_ended_at = time.monotonic()
                        break
                    if line:
                        if config.agent_start_marker and line.rstrip("\r\n") == config.agent_start_marker:
                            if agent_started_at is None:
                                agent_started_at = time.monotonic()
                        else:
                            jsonl_f.write(line)
                            jsonl_f.flush()
                            if STREAM_AGENT_OUTPUT:
                                sys.stdout.write(line)
                                sys.stdout.flush()
                    if proc.poll() is not None and agent_ended_at is None:
                        agent_ended_at = time.monotonic()
                elif proc.poll() is not None:
                    if agent_ended_at is None:
                        agent_ended_at = time.monotonic()
                    break

        if agent_started_at is not None and agent_ended_at is None:
            agent_ended_at = time.monotonic()
        if logical_deadline is not None and time.time() >= logical_deadline:
            timed_out = True
        result["agent_exit"] = -1 if timed_out else proc.returncode
        # Drain any remaining stderr
        if proc.stderr:
            try:
                remaining = proc.stderr.read()
                if remaining:
                    stderr_chunks.append(remaining)
            except (OSError, BlockingIOError, TypeError):
                pass
        stderr = "".join(stderr_chunks)
        if stderr:
            with open(os.path.join(agent_dir, "stderr.txt"), "w") as f:
                f.write(stderr)
        if timed_out:
            result["error"] = f"{backend.name} timeout after {item.timeout}s"
        elif proc.returncode == 137:
            result["error"] = "container OOM killed (exit 137)"
    except Exception as e:
        result["agent_exit"] = -2
        result["error"] = str(e)
        if container_run:
            runner.kill(container_run)
        if agent_started_at is not None:
            agent_ended_at = time.monotonic()
    finally:
        # A retained container keeps its credential mount sources so a
        # `docker start` can still authenticate.
        if not item.keep_container:
            runner.cleanup_credential_tmps()
    if agent_started_at is None or agent_ended_at is None:
        return None
    return agent_ended_at - agent_started_at


def _run_backend_local(
    item: WorkItem,
    backend,
    mode,
    workspace: str,
    agent_dir: str,
    agent_jsonl: str,
    prompt: str,
    result: dict,
    checker_bin: str,
    canonical_dir: str | None = None,
) -> None:
    """Run a backend as a local subprocess with its declared timeout policy."""
    timeout = item.timeout if item.timeout and item.timeout > 0 else None
    propagated_deadline = time.time() + timeout if timeout and backend.capabilities.cooperative_deadline else None
    cmd = _build_backend_command(backend, workspace, agent_dir, propagated_deadline)
    cmd, stdin_data = backend.prepare_invocation(cmd, prompt)
    shell_cmd = "source ~/.zshrc 2>/dev/null; source ~/.bashrc 2>/dev/null; exec " + " ".join(
        shlex.quote(c) for c in cmd
    )

    timed_out = {"v": False}
    hard_kill_timer: threading.Timer | None = None
    proc = None

    agent_env = dict(os.environ)
    agent_env.update(backend.execution_environment(agent_dir))
    agent_env["TLAPS_LIB"] = item.tlapm_lib
    agent_env.setdefault("COMMUNITY_LIB", os.path.join(REPO_ROOT, "lib", "community"))
    checker_dir = os.path.dirname(os.path.abspath(checker_bin))
    agent_env["PATH"] = checker_dir + os.pathsep + agent_env.get("PATH", "")
    sany_run_sh = os.path.join(REPO_ROOT, "src", "dataset", "sany-dump", "run.sh")
    if os.path.isfile(sany_run_sh):
        agent_env["SANY_RUN_SH"] = sany_run_sh
    # Point the agent's own check_proof_bin at canonical source bytes (no host
    # /benchmark mount exists, so the env var is how the checker discovers them).
    if canonical_dir:
        agent_env["TLAPS_BENCHMARK_DIR"] = canonical_dir
        agent_env[CATALOG_ENV] = os.path.join(canonical_dir, CATALOG_FILENAME)
    if getattr(mode, "canonical_replay_required", False):
        agent_env["TLAPS_CANONICAL_REPLAY_REQUIRED"] = "1"
    # Same tlapm budget the grader uses, so the discharge verdict matches.
    agent_env["TLAPS_CHECK_TIMEOUT"] = str(item.check_timeout)

    try:
        with open(agent_jsonl, "w") as jsonl_f:
            proc = subprocess.Popen(
                ["bash", "-c", shell_cmd],
                stdin=subprocess.PIPE,
                stdout=jsonl_f,
                stderr=subprocess.PIPE,
                text=True,
                cwd=workspace,
                env=agent_env,
                start_new_session=True,
            )

            logical_deadline = propagated_deadline or (time.time() + timeout if timeout else None)
            grace = backend.capabilities.timeout_drain_grace if propagated_deadline is not None else 0.0

            def _hard_kill() -> None:
                timed_out["v"] = True
                kill_agent_tree(proc, workspace)

            def _logical_timeout() -> None:
                timed_out["v"] = True
                if grace <= 0:
                    _hard_kill()

            timer_delay = max(logical_deadline - time.time(), 0.0) if logical_deadline is not None else None
            timer = threading.Timer(timer_delay, _logical_timeout) if timer_delay is not None else None
            if timer:
                timer.daemon = True
                timer.start()
            if logical_deadline is not None and grace > 0:
                hard_delay = max(logical_deadline + grace - time.time(), 0.0)
                hard_kill_timer = threading.Timer(hard_delay, _hard_kill)
                hard_kill_timer.daemon = True
                hard_kill_timer.start()
            try:
                hard_wait = (
                    max(logical_deadline + grace - time.time(), 0.0) + 600 if logical_deadline is not None else None
                )
                _, stderr = proc.communicate(input=stdin_data, timeout=hard_wait)
            except subprocess.TimeoutExpired:
                timed_out["v"] = True
                kill_agent_tree(proc, workspace)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=30)
                stderr = ""
            finally:
                if logical_deadline is not None and time.time() >= logical_deadline:
                    timed_out["v"] = True
                if timer:
                    timer.cancel()
                if hard_kill_timer:
                    hard_kill_timer.cancel()
                # The backend leader may exit while leaving background helpers
                # in its session. Reap them before fresh canonical grading.
                kill_agent_tree(proc, workspace)
        result["agent_exit"] = proc.returncode
        if stderr:
            with open(os.path.join(agent_dir, "stderr.txt"), "w") as f:
                f.write(stderr)
        if timed_out["v"]:
            result["agent_exit"] = -1
            result["error"] = f"{backend.name} timeout after {item.timeout}s"
            kill_agent_tree(proc, workspace)
    except Exception as e:
        result["agent_exit"] = -2
        result["error"] = str(e)
        if proc is not None:
            kill_agent_tree(proc, workspace)


def _build_backend_command(
    backend: Backend,
    workspace: str,
    result_dir: str,
    deadline: float | None,
) -> list[str]:
    """Build a command through the backend's approach-specific lifecycle hook."""

    return backend.build_run_command(workspace, result_dir, deadline)


def _run_grader_container(
    item: WorkItem,
    workspace: str,
    basename: str,
    grading_dir: str,
    check_result_path: str,
    result: dict,
    canonical_dir: str | None = None,
) -> None:
    """Run grader inside a Docker container (check_proof_bin lives in the image)."""
    runner = ContainerRunner()
    mode = item.mode

    # Use container path for checker binary (not host path)
    old_binary = mode._checker_binary
    mode._checker_binary = "/usr/local/bin/check_proof_bin"
    check_cmd = mode.checker_command(
        "/workspace",
        basename,
        "/results/check.result",
        item.check_timeout,
        benchmark_dir="/benchmark",  # tamper-proof read-only mount
    )
    mode._checker_binary = old_binary
    config = ContainerConfig(
        image=item.container_image,
        workspace=workspace,
        result_dir=grading_dir,
        # Exactly {target}.tla + canonical deps. Replay-required modes pass a
        # grader-only fresh snapshot, never the one exposed to the agent.
        benchmark_dir=canonical_dir or os.path.dirname(item.benchmark_path),
    )
    config.env["GIT_CONFIG_COUNT"] = "1"
    config.env["GIT_CONFIG_KEY_0"] = "safe.directory"
    config.env["GIT_CONFIG_VALUE_0"] = "/workspace"
    config.env[CATALOG_ENV] = f"/benchmark/{CATALOG_FILENAME}"
    try:
        exit_code, stdout, stderr = runner.run_with_output(config, check_cmd, timeout=item.check_timeout + 60)
        with open(os.path.join(grading_dir, "check_debug.txt"), "w") as dbg:
            dbg.write(f"exit code: {exit_code}\n")
            dbg.write(f"stdout:\n{stdout}\n")
            dbg.write(f"stderr:\n{stderr}\n")
        module_spec = getattr(mode, "module_task_spec", None)
        expected_units = tuple(module_spec(item.benchmark_path).proof_unit_ids) if module_spec is not None else None
        _parse_grader_result(
            exit_code,
            stdout,
            result,
            expected_module_unit_ids=expected_units,
        )
    except subprocess.TimeoutExpired:
        result["check_verdict"] = "TIMEOUT"
    except Exception as e:
        result["check_verdict"] = "ERROR"
        result["error"] = str(e)
    finally:
        runner.cleanup_credential_tmps()


def _run_grader_local(
    item: WorkItem,
    workspace: str,
    basename: str,
    grading_dir: str,
    check_result_path: str,
    result: dict,
    canonical_dir: str | None = None,
) -> None:
    """Run grader on host (local mode)."""
    mode = item.mode
    sany_run_sh = os.path.join(REPO_ROOT, "src", "dataset", "sany-dump", "run.sh")

    check_cmd = mode.checker_command(
        workspace,
        basename,
        check_result_path,
        item.check_timeout,
        # Exactly {target}.tla + canonical deps. Replay-required modes pass a
        # grader-only fresh snapshot, never the one exposed to the agent.
        benchmark_dir=canonical_dir or os.path.dirname(item.benchmark_path),
    )
    try:
        check_env = dict(os.environ)
        check_env["TLAPS_LIB"] = item.tlapm_lib
        check_env.setdefault("COMMUNITY_LIB", os.path.join(REPO_ROOT, "lib", "community"))
        if canonical_dir:
            check_env[CATALOG_ENV] = os.path.join(canonical_dir, CATALOG_FILENAME)
        if os.path.isfile(sany_run_sh):
            check_env["SANY_RUN_SH"] = sany_run_sh
        check_proc = subprocess.run(
            check_cmd,
            capture_output=True,
            text=True,
            timeout=item.check_timeout + 60,
            cwd=workspace,
            env=check_env,
        )
        with open(os.path.join(grading_dir, "check_debug.txt"), "w") as dbg:
            dbg.write(f"exit code: {check_proc.returncode}\n")
            dbg.write(f"stdout:\n{check_proc.stdout}\n")
            dbg.write(f"stderr:\n{check_proc.stderr}\n")
        module_spec = getattr(mode, "module_task_spec", None)
        expected_units = tuple(module_spec(item.benchmark_path).proof_unit_ids) if module_spec is not None else None
        _parse_grader_result(
            check_proc.returncode,
            check_proc.stdout,
            result,
            expected_module_unit_ids=expected_units,
        )
    except subprocess.TimeoutExpired:
        result["check_verdict"] = "TIMEOUT"
    except Exception as e:
        result["check_verdict"] = "ERROR"
        result["error"] = str(e)


def _grade_submission(
    item: WorkItem,
    attempt: dict[str, object],
    workspace: str,
    grading_dir: str,
    check_result_path: str,
    basename: str,
    name_no_ext: str,
    canonical_inputs: CanonicalInputs,
    canonical_dir: str | None,
) -> None:
    """Grade a submission, isolating preserved module artifacts from scratch files."""

    previous_grader_error = attempt.pop("grader_error", None)
    if previous_grader_error and attempt.get("error") == previous_grader_error:
        attempt["error"] = ""
    for key in (
        "module_result",
        "trusted_proof_unit_ids",
        "obligations",
        "obligations_complete",
        "obligations_failed",
        "obligations_total",
        "sany_status",
        "sany_valid",
        "failed_gates",
        "cheat_checks",
    ):
        attempt.pop(key, None)
    if "trusted_proof_unit_count" in attempt:
        attempt["trusted_proof_unit_count"] = 0
    started = time.monotonic()
    try:
        if item.module_checkpoint_identity is not None:
            inputs = _module_grading_inputs(item, attempt, canonical_inputs, basename, name_no_ext)
        else:
            inputs = _standard_grading_inputs(item, workspace, canonical_inputs, name_no_ext, canonical_dir)
        with inputs as (grading_workspace, grading_canonical_dir):
            if item.use_container:
                _run_grader_container(
                    item,
                    grading_workspace,
                    basename,
                    grading_dir,
                    check_result_path,
                    attempt,
                    grading_canonical_dir,
                )
            else:
                _run_grader_local(
                    item,
                    grading_workspace,
                    basename,
                    grading_dir,
                    check_result_path,
                    attempt,
                    grading_canonical_dir,
                )
    except (OSError, ModuleArtifactError) as exc:
        attempt["check_verdict"] = "ERROR"
        attempt["error"] = f"cannot materialize grading inputs: {exc}"
    finally:
        elapsed = time.monotonic() - started
        if attempt.get("check_verdict") == "ERROR":
            attempt["grader_error"] = str(attempt.get("error", ""))
            prior = nonnegative_float(attempt.get("grader_error_time_secs")) or 0.0
            attempt["grader_error_time_secs"] = prior + elapsed
            _ensure_time_breakdown(attempt)
            _recompute_task_time(attempt)
        else:
            _add_grading_time(attempt, elapsed)


def _parse_grader_result(
    exit_code: int,
    stdout: str,
    result: dict,
    *,
    expected_module_unit_ids: tuple[str, ...] | None = None,
) -> None:
    """Parse grader exit code + stdout into result dict."""
    # The merged checker is binary: exit 0 = PASS, 1 = FAIL (a cheat is just a
    # FAIL, not a separate exit code). Anything else is unexpected → ERROR.
    if exit_code == 0:
        result["check_verdict"] = "PASS"
    elif exit_code == 1:
        result["check_verdict"] = "FAIL"
    else:
        result["check_verdict"] = "ERROR"
    sany_matches = re.findall(
        r"^SANY-STATUS:[ \t]*([^\r\n]*?)[ \t]*$",
        stdout or "",
        re.MULTILINE,
    )
    if not sany_matches:
        result["check_verdict"] = "ERROR"
        result["error"] = "grader did not report a SANY status"
        return
    if len(sany_matches) != 1:
        result["check_verdict"] = "ERROR"
        result["error"] = "grader reported multiple SANY status markers; expected exactly one"
        return
    sany_status = sany_matches[0]
    if sany_status not in {"valid", "invalid", "unavailable"}:
        result["check_verdict"] = "ERROR"
        result["error"] = f"grader reported an invalid SANY status marker: {sany_status!r}"
        return
    result["sany_status"] = sany_status
    result["sany_valid"] = sany_status == "valid"
    declared_timeout = bool(re.search(r"^CHECK-TIMEOUT:", stdout or "", re.MULTILINE))
    module_matches = re.findall(
        rf"^{re.escape(MODULE_RESULT_PREFIX)}(.+)$",
        stdout or "",
        re.MULTILINE,
    )
    if expected_module_unit_ids is not None:
        if len(module_matches) != 1:
            if len(module_matches) == 0 and exit_code not in (0, 1) and declared_timeout:
                result["check_verdict"] = "TIMEOUT"
                return
            result["check_verdict"] = "ERROR"
            result["error"] = "module grader did not report exactly one machine-readable module result"
            return
        try:
            module_result = parse_module_result_json(module_matches[0], expected_module_unit_ids)
        except ModuleResultError as exc:
            result["check_verdict"] = "ERROR"
            result["error"] = f"module grader reported an invalid result: {exc}"
            return
        result["module_result"] = module_result
        trusted = module_result["trusted_proof_unit_ids"]
        result["proof_unit_count"] = len(expected_module_unit_ids)
        result["trusted_proof_unit_count"] = len(trusted)
        result["trusted_proof_unit_ids"] = list(trusted)
        units = module_result["units"]
        if units and any("obligations" in unit for unit in units):
            known_obligations = [unit["obligations"] for unit in units if isinstance(unit.get("obligations"), int)]
            result["obligations"] = sum(known_obligations)
            result["obligations_complete"] = len(known_obligations) == len(units)
        if exit_code == 0 and not module_result["complete"]:
            result["check_verdict"] = "ERROR"
            result["error"] = "module grader exited PASS without trusting every proof unit"
            return
        if exit_code == 1 and module_result["complete"]:
            result["check_verdict"] = "ERROR"
            result["error"] = "module grader exited FAIL for a complete trusted module"
            return
        if exit_code not in (0, 1):
            raw_verdicts = {unit["raw_verdict"] for unit in module_result["units"]}
            result["check_verdict"] = "TIMEOUT" if "TIMEOUT" in raw_verdicts else "ERROR"
        if module_result["sany_status"] != sany_status:
            result["check_verdict"] = "ERROR"
            result["error"] = "module grader SANY status disagrees with SANY-STATUS marker"
            return

    # Which gate(s) failed (the grade is binary; this keeps the analysis signal).
    gm = re.search(r"GATES-FAILED:\s*([^\n]+)", stdout or "")
    if gm:
        result["failed_gates"] = [g.strip() for g in gm.group(1).split(",") if g.strip()]
    # A FAIL whose failing checks include an integrity (tamper/admit) check is a
    # cheat, not an honest incomplete proof — relabel it for the human-facing
    # report so the two are distinguishable at a glance. The checker emits
    # CHEAT-DETECTED with the failing integrity-check names; the grade itself
    # stays binary (the PASS/FAIL exit code is untouched).
    if result["check_verdict"] == "FAIL":
        cm = re.search(r"CHEAT-DETECTED:\s*([^\n]+)", stdout or "")
        if cm:
            result["check_verdict"] = "CHEATING"
            result["cheat_checks"] = [c.strip() for c in cm.group(1).split(",") if c.strip()]
    if expected_module_unit_ids is None:
        ob_matches = re.findall(r"All (\d+) obligation", stdout)
        if ob_matches:
            result["obligations"] = int(ob_matches[-1])
        else:
            fail_match = re.search(r"(\d+)/(\d+) obligation", stdout)
            if fail_match:
                result["obligations_failed"] = int(fail_match.group(1))
                result["obligations_total"] = int(fail_match.group(2))


# A one-word prompt that needs no tools and no workspace files — keeps the
# preflight model call as cheap and as deterministic as possible.
PREFLIGHT_PROMPT = "Reply with the single word: ok. Do not use any tools."
SANY_PREFLIGHT_MODULE = """---- MODULE SanyPreflight ----
THEOREM Ok == TRUE
PROOF OBVIOUS
====
"""


def _run_sany_preflight(*, use_container: bool, container_image: str) -> None:
    """Require a working standalone SANY before any model request."""

    with (
        tempfile.TemporaryDirectory(prefix="sany_preflight_ws_") as workspace,
        tempfile.TemporaryDirectory(prefix="sany_preflight_res_") as result_dir,
    ):
        module = os.path.join(workspace, "SanyPreflight.tla")
        with open(module, "w", encoding="utf-8") as stream:
            stream.write(SANY_PREFLIGHT_MODULE)

        if use_container:
            runner = ContainerRunner()
            config = ContainerConfig(image=container_image, workspace=workspace, result_dir=result_dir)
            cmd = [
                "/usr/local/bin/check_proof_bin",
                "/workspace/SanyPreflight.tla",
                "--no-container",
                "--no-git-track",
                "--sany-only",
                "--output",
                "/results/check.result",
            ]
            try:
                exit_code, stdout, stderr = runner.run_with_output(config, cmd, timeout=180)
            finally:
                runner.cleanup_credential_tmps()
        else:
            checker = os.path.join(REPO_ROOT, "check_proof_bin")
            env = dict(os.environ)
            env["SANY_RUN_SH"] = os.path.join(REPO_ROOT, "src", "dataset", "sany-dump", "run.sh")
            env["TLAPS_LIB"] = os.path.join(REPO_ROOT, "lib", "tlapm")
            env["COMMUNITY_LIB"] = os.path.join(REPO_ROOT, "lib", "community")
            try:
                completed = subprocess.run(
                    [
                        checker,
                        module,
                        "--no-container",
                        "--no-git-track",
                        "--sany-only",
                        "--output",
                        os.path.join(result_dir, "check.result"),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"SANY preflight could not run: {exc}") from exc
            exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr

        if exit_code != 0 or not re.search(r"^SANY-STATUS:\s*valid\s*$", stdout, re.MULTILINE):
            detail = (stderr or stdout or "no diagnostic output").strip()
            raise RuntimeError(f"SANY preflight failed (exit {exit_code}): {detail[:500]}")
        print("SANY preflight: OK")


def _run_preflight(backend, container_image: str) -> None:
    """Validate a backend end-to-end (install + auth + model + firewall) before
    the run, aborting the process on failure.

    Runs the backend's real build_command inside a throwaway container — same
    install script, env, credentials and firewall as a real run — on a one-word
    prompt. A broken model id, an unknown CLI flag, missing credentials, or an
    auth host the firewall blocks all surface here in ~1 min, instead of as a
    full sweep of silent 0-token FAILs.
    """
    runner = ContainerRunner()
    workspace = tempfile.mkdtemp(prefix="preflight_ws_")
    result_dir = tempfile.mkdtemp(prefix="preflight_res_")
    # Mirror a real run's workspace: the per-benchmark flow git-inits it, and
    # some CLIs (e.g. codex exec) refuse to run outside a git repo. Without this
    # the preflight would false-fail for those backends.
    subprocess.run(["git", "init"], capture_output=True, cwd=workspace)
    try:
        config = ContainerConfig(
            image=container_image,
            workspace=workspace,
            result_dir=result_dir,
            env=forward_env(backend.env_keys, model=getattr(backend, "model", None)),
            firewall_hosts=backend.firewall_hosts(),
            dynamic_firewall=backend.dynamic_firewall,
            install_script=backend.install_script,
            credential_mounts=backend.get_credential_mounts(),
        )
        cmd = backend.build_command("/workspace", "/results")
        cmd, stdin_data = backend.prepare_invocation(cmd, PREFLIGHT_PROMPT)
        print(f"Preflight: validating '{backend.name}' (install + auth + model + firewall)...", flush=True)
        runner.run_preflight(config, cmd, stdin_data)
        print("Preflight: OK", flush=True)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        print("Aborting before the run. Re-run with --skip-preflight to bypass this check.")
        sys.exit(1)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(result_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Run evaluator backends on TLAPS benchmarks")
    parser.add_argument(
        "--backend", default="codex", choices=list_backends(), help="Evaluator backend (default: codex)"
    )
    parser.add_argument(
        "--mode", default="proof-completion", choices=list_modes(), help="Benchmark mode (default: proof-completion)"
    )
    parser.add_argument("--model", default=None, help="Override the backend default model")
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Override backend/model reasoning effort; accepted values depend on --backend "
        "(default: preserve existing backend behavior)",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="Override the per-request model output token limit for supported backends",
    )
    parser.add_argument("--jobs", type=int, default=1, help="Parallel backend runs")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--filter", default=None, help="Only run benchmarks matching pattern")
    selection.add_argument(
        "--task-list",
        default=None,
        metavar="NAME_OR_FILE",
        help="Run exact mode-relative task IDs from a file or registered name such as 'core'",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=28800,
        help="Backend timeout per benchmark in seconds (default: 28800 = 8h; 0 = no limit)",
    )
    parser.add_argument(
        "--check-timeout", type=int, default=600, help="Checker timeout per benchmark in seconds (default: 600)"
    )
    parser.add_argument("--output-dir", default=None, help="Output directory")
    # Proactive quota gate. Before launching an agent, pause when the backend's
    # subscription usage is over threshold, sleeping until the window resets. The
    # backend supplies its own usage probe and default thresholds; --quota-5h/7d
    # override them, 0 disables a window's check.
    parser.add_argument(
        "--quota-5h",
        type=float,
        default=None,
        help="Pause when 5-hour usage exceeds this %% (default: backend-specific; 0 = off)",
    )
    parser.add_argument(
        "--quota-7d",
        type=float,
        default=None,
        help="Pause when 7-day usage exceeds this %% (default: backend-specific; 0 = off)",
    )
    parser.add_argument(
        "--quota-max-waits",
        type=int,
        default=6,
        help="Max window resets to sleep through before aborting a benchmark (default: 6)",
    )
    parser.add_argument(
        "--usage-script",
        default=None,
        help="Override the backend's usage probe with a custom script path",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse --output-dir: skip benchmarks already SKIP or genuinely passed there (first-attempt or continuation), run the rest",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=0,
        help="Hold off launching an agent until this many GB RAM are free "
        "(0 = off). Use on a no-swap host shared with another heavy run.",
    )
    parser.add_argument(
        "--infra-retries",
        type=int,
        default=None,
        help="Extra agent attempts after a transient startup/infrastructure failure "
        "that the backend approves as safe to replay, so 3 = up to 4 attempts total "
        "(default: 3; 0 = no retries, the failure still ends as ERROR)",
    )
    parser.add_argument(
        "--max-continuations",
        type=int,
        default=0,
        help="After a genuine non-PASS verdict, re-run the agent up to N more times in the "
        "SAME workspace with a continuation prompt (build on its own partial proof), "
        "stopping at the first PASS. The first attempt's verdict still scores pass@1; "
        "continuation rounds are recorded and reported separately (default: 0 = off)",
    )
    parser.add_argument(
        "--no-container",
        action="store_true",
        help="Run agent locally instead of inside a Docker container",
    )
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Retain each agent's Docker container after it exits (drop --rm) so its "
        "writable layer — where the agent's session state lives — survives for "
        "inspection or an interactive resume. Also persists session state to "
        "~/.tlaps-bench/sessions by default (override with --session-dir). Prints the "
        "container name to reattach with. Container mode only; remember to "
        "`docker rm` the containers when done.",
    )
    parser.add_argument(
        "--session-dir",
        default=None,
        help="Persist each run's agent session state under this PERSISTENT host path "
        "(default ~/.tlaps-bench/sessions when --keep-container is set) instead of a "
        "/tmp tempdir that a reboot clears, so it survives container removal and reboot "
        "and can be restored into another container with scripts/restore-session.sh. "
        "Container mode only.",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="Force rebuild the Docker base image before running",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip only the container backend/model preflight (install + auth + model + firewall). "
        "The mandatory SANY preflight is never skipped. Container mode only.",
    )
    parser.add_argument(
        "--allow-unpriced-model",
        action="store_true",
        help="Continue when public API pricing is unavailable; equivalent_cost_usd will be blank",
    )
    args = parser.parse_args()

    backend = get_backend(args.backend, model=args.model)
    # Container mode is default; --no-container disables it
    use_container = not args.no_container

    # Discover tasks before authentication, image setup, or the model preflight.
    # A misspelled filter must fail without doing expensive or externally-visible
    # work (building an image, installing an agent CLI, or making a model request).
    container_image = f"{IMAGE_TAG}:latest"
    if use_container:
        benchmark_root = os.path.join(REPO_ROOT, "benchmark")
        checker_binary = os.path.join(REPO_ROOT, "check_proof_bin")
    else:
        benchmark_root, checker_binary = resolve_paths()
    mode = get_mode(args.mode, benchmark_root, checker_binary)
    task_ids = None
    try:
        if args.task_list is not None:
            task_ids = _load_task_list(_resolve_task_list(args.task_list, mode))
            benchmark_files = _select_exact_tasks(mode, task_ids)
        else:
            benchmark_files = mode.get_benchmark_files(args.filter)
        identity_loader = getattr(mode, "specification_ids", None)
        task_specification_ids = identity_loader() if identity_loader is not None else None
    except (TaskContractError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")
    specification_ids = (
        scope_specification_ids(mode.name, task_specification_ids) if task_specification_ids is not None else None
    )
    if not benchmark_files:
        if args.filter:
            parser.exit(
                2,
                f"{parser.prog}: error: no benchmarks matched --filter {args.filter!r} in mode {mode.name!r}\n",
            )
        parser.exit(
            2, f"{parser.prog}: error: no benchmarks found for mode {mode.name!r} under {mode.benchmark_dir()}\n"
        )

    # Module runs always persist the exact selected cohort, including Full and
    # --filter runs. A resume must select the same physical module tasks.
    recorded_task_ids = task_ids
    if getattr(mode, "module_task_spec", None) is not None:
        recorded_task_ids = [
            os.path.relpath(path, mode.benchmark_dir()).replace(os.sep, "/") for path in benchmark_files
        ]

    if getattr(mode, "requires_workspace_tools", False) and not backend.capabilities.workspace_tools:
        parser.exit(
            2,
            f"{parser.prog}: error: backend {backend.name!r} is tool-free and does not support mode {mode.name!r}\n",
        )

    # Resolve and validate the selected cohort before Docker or native
    # verification-toolchain setup. A bad resume should remain a cheap CLI
    # error and must not build an image.
    if args.output_dir:
        output_dir = args.output_dir
    else:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        if os.path.isdir("/result"):
            output_dir = os.path.join("/result", mode.name, backend.name, timestamp)
        else:
            output_dir = os.path.join(REPO_ROOT, "results", mode.name, backend.name, timestamp)
    output_dir = os.path.abspath(output_dir)
    session_dir = _resolve_session_dir(args.session_dir, args.keep_container, use_container)
    if args.resume:
        try:
            _validate_resume_task_list(output_dir, mode.name, recorded_task_ids)
        except ValueError as exc:
            parser.exit(2, f"{parser.prog}: error: {exc}\n")

    proof_library_catalog = None
    run_identity = None
    container_ready = False
    native_toolchain_ready = False

    # Resolve backend-dependent defaults before freezing or comparing the run
    # identity. A resume may reuse progress only under the exact same model,
    # limits, retry policy, and continuation budget.
    try:
        backend.set_reasoning_effort(args.reasoning_effort)
        backend.set_max_output_tokens(args.max_output_tokens)
        args.infra_retries = backend.validate_options(args.infra_retries, args.max_continuations)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        agent_skills_snapshot = AgentSkillsSnapshot.capture(backend, SKILLS_DIR)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: error: cannot freeze project Agent Skills: {exc}\n")

    if mode.name == "proof-from-scratch":
        try:
            if use_container:
                container_image = ensure_image(force=args.force_build)
                container_ready = True
                proof_library_catalog, verification_toolchain = _container_verification_environment(container_image)
            else:
                proof_library_catalog, verification_toolchain = _native_verification_environment()
                native_toolchain_ready = True
            run_identity = _proof_from_scratch_run_identity(
                mode,
                proof_library_catalog,
                verification_toolchain,
                _execution_policy_identity(
                    backend,
                    use_container=use_container,
                    timeout=args.timeout,
                    check_timeout=args.check_timeout,
                    infra_retries=args.infra_retries,
                    max_continuations=args.max_continuations,
                    session_dir=session_dir,
                ),
                agent_skills_snapshot,
            )
        except (DockerUnavailableError, OSError, RuntimeError, ValueError) as exc:
            parser.exit(2, f"{parser.prog}: error: cannot freeze proof verification environment: {exc}\n")
    if args.resume:
        try:
            _validate_resume_run_manifest(output_dir, run_identity)
        except ValueError as exc:
            parser.exit(2, f"{parser.prog}: error: {exc}\n")

    canonical_inputs_by_path = {}
    if getattr(mode, "canonical_replay_required", False):
        try:
            for benchmark_path in benchmark_files:
                dependencies = mode.get_dependencies(benchmark_path)
                canonical_inputs_by_path[benchmark_path] = CanonicalInputs.capture(
                    benchmark_path,
                    os.path.basename(benchmark_path),
                    dependencies,
                    proof_library_catalog=(proof_library_catalog.to_bytes() if proof_library_catalog else None),
                )
        except (OSError, TaskContractError, ValueError) as exc:
            parser.exit(2, f"{parser.prog}: error: cannot capture canonical inputs: {exc}\n")

    module_checkpoint_identities: dict[str, ModuleCheckpointIdentity] = {}
    module_checkpoints = {}
    results: list[dict] = []
    done_pass: set[str] = set()
    module_resumes: dict[str, ModuleResume] = {}
    module_spec_loader = getattr(mode, "module_task_spec", None)
    if module_spec_loader is not None:
        if run_identity is None:
            parser.exit(2, f"{parser.prog}: error: module evaluation requires a frozen run identity\n")
        try:
            identity_digest = module_run_identity_sha256(run_identity)
            for benchmark_path in benchmark_files:
                relative = os.path.relpath(benchmark_path, mode.benchmark_dir()).replace(os.sep, "/")
                spec = module_spec_loader(benchmark_path)
                canonical_inputs = canonical_inputs_by_path[benchmark_path]
                module_checkpoint_identities[relative] = ModuleCheckpointIdentity(
                    task_id=relative,
                    proof_unit_ids=tuple(spec.proof_unit_ids),
                    canonical_input_sha256=canonical_inputs.digest(),
                    run_identity_sha256=identity_digest,
                )
            module_checkpoints = prepare_module_checkpoints(
                output_dir,
                module_checkpoint_identities,
                resume=args.resume,
            )
        except (KeyError, ModuleCheckpointError) as exc:
            parser.exit(2, f"{parser.prog}: error: cannot prepare module checkpoints: {exc}\n")

    if args.resume:
        try:
            previous_results = _load_resume_results(output_dir)
            if module_checkpoint_identities:
                (
                    results,
                    module_resumes,
                    done_pass,
                ) = _recover_module_resume(
                    output_dir,
                    previous_results,
                    module_checkpoint_identities,
                    module_checkpoints,
                    max_continuations=args.max_continuations,
                )
            else:
                for previous_result in previous_results:
                    _record_result(results, previous_result)
            _validate_resume_result_accounting(
                results,
                supports_cost_time=_supports_cost_time(backend),
            )
            if not module_checkpoint_identities:
                done_pass = _resume_done_benchmarks(results)
        except (ModuleArtifactError, ValueError) as exc:
            parser.exit(2, f"{parser.prog}: error: cannot recover prior results: {exc}\n")

        if module_checkpoint_identities:
            print(
                f"Resume: recovered {len(results)} durable module result(s), "
                f"skipping {len(done_pass)} completed module task(s)"
            )
        elif results:
            n_pass = sum(1 for result in results if _resume_should_skip(result) and not is_skipped(result))
            n_skip = n_skipped(results)
            non_genuine = n_non_genuine(results)
            msg = (
                f"Resume: loaded {len(results)} prior results, skipping {n_pass} genuine PASS "
                f"(first-attempt or continuation) + {n_skip} SKIP"
            )
            if non_genuine:
                msg += f"; {non_genuine} error/interrupted result(s) eligible for rerun"
            print(msg)
        else:
            print(f"Resume: no prior results.json or module checkpoints in {output_dir} — running all")

    if not _confirm_public_pricing(
        backend,
        allow_unpriced_model=args.allow_unpriced_model,
        use_container=use_container,
    ):
        sys.exit(1)

    # Establish the verification toolchain and prove that standalone SANY can
    # run before authentication or any model request. Task-level grading keeps
    # the same gate because a later timeout or tool failure must also fail closed.
    if use_container:
        if not container_ready:
            try:
                container_image = ensure_image(force=args.force_build)
                container_ready = True
            except DockerUnavailableError as exc:
                parser.exit(2, f"{parser.prog}: error: {exc}\n")
        tlapm_root = "/opt/tlapm"
        tlapm_lib = "/opt/proof-libraries/tlapm"
    else:
        if not native_toolchain_ready:
            ensure_tlapm()
            native_toolchain_ready = True
        tlapm_root = TLAPM_PERSISTENT
        tlapm_lib = os.path.join(REPO_ROOT, "lib", "tlapm")
        if not os.path.isdir(tlapm_lib):
            parser.exit(
                2,
                f"{parser.prog}: error: pinned official tlapm library not found at {tlapm_lib}; run make setup\n",
            )
    try:
        _run_sany_preflight(use_container=use_container, container_image=container_image)
    except (DockerUnavailableError, RuntimeError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")

    auth_err = backend.check_auth()
    if auth_err:
        print(f"ERROR: {auth_err}")
        sys.exit(1)

    if args.keep_container and not use_container:
        print("WARNING: --keep-container has no effect with --no-container (no container to retain)")
    if args.session_dir and not use_container:
        print("WARNING: --session-dir has no effect with --no-container (no container to mount into)")

    if session_dir:
        _prepare_session_dir(session_dir)

    if use_container:
        print(f"Container mode: ON (image: {container_image})")

        # Preflight: validate install + auth + model + firewall on a trivial
        # prompt before committing to the full run. A broken backend (bad model
        # id, unknown CLI flag, missing credentials, or an auth host the
        # firewall blocks) otherwise produces a whole sweep of silent 0-token
        # FAILs that look like honest "couldn't prove it" results.
        if not args.skip_preflight and backend.capabilities.model_preflight:
            _run_preflight(backend, container_image)
        elif not args.skip_preflight:
            print(f"Preflight: skipped — backend {backend.name!r} does not support a model preflight request")
    os.makedirs(output_dir, exist_ok=True)
    try:
        if not args.resume or not os.path.isfile(os.path.join(output_dir, TASK_LIST_RECORD)):
            _write_task_list_record(output_dir, mode.name, recorded_task_ids)
        if not args.resume or not os.path.isfile(os.path.join(output_dir, RUN_MANIFEST_RECORD)):
            _write_run_manifest(output_dir, run_identity)
    except OSError as exc:
        parser.exit(2, f"{parser.prog}: error: cannot record run inputs in {output_dir!r}: {exc}\n")

    print(f"Backend: {backend.name}" + (f" (model={args.model})" if args.model else ""))
    if backend.reasoning_effort is not None:
        print(f"Effort:  {backend.reasoning_effort}")
    if backend.max_output_tokens is not None:
        print(f"Max output tokens: {backend.max_output_tokens}")
    print(f"Mode:   {mode.name} — {mode.description}")
    print(f"Output:  {output_dir}")
    if run_identity is not None:
        print(f"Corpus:  {str(run_identity['corpus_digest'])[:12]}")
        print(f"Official proof libraries: {str(run_identity['proof_library_digest'])[:12]}")
        print(f"Verification toolchain: {str(run_identity['verification_toolchain_digest'])[:12]}")

    # Proactive quota gate. The backend supplies its usage probe and default
    # thresholds; --quota-5h/7d override them. Gating stays off when the backend
    # has no probe, both thresholds are 0, or the probe can't read usage (API-key
    # auth, no subscription) — it never blocks a run it can't measure.
    b5, b7 = backend.default_quota()
    quota_5h = b5 if args.quota_5h is None else args.quota_5h
    quota_7d = b7 if args.quota_7d is None else args.quota_7d
    usage_script = None
    script_rel = backend.usage_script()
    candidate = args.usage_script or (os.path.join(REPO_ROOT, script_rel) if script_rel else None)
    if candidate and (quota_5h > 0 or quota_7d > 0):
        if os.path.isfile(candidate):
            usage = quota.fetch_usage(candidate)
            if usage is not None:
                usage_script = candidate
                u5 = (usage.get("five_hour") or {}).get("utilization", 0)
                u7 = (usage.get("seven_day") or {}).get("utilization", 0)
                print(
                    f"Quota:   gate ON — now 5h={u5}% (limit {quota_5h}%), "
                    f"7d={u7}% (limit {quota_7d}%), max-waits={args.quota_max_waits}"
                )
            else:
                print(
                    "Quota:   gate OFF — usage probe returned no data (API-key auth or no subscription usage to read)"
                )
        else:
            print(f"Quota:   gate OFF — usage script not found at {candidate}")

    print(f"Found {len(benchmark_files)} benchmarks")

    selected_benchmarks = set()
    work_items = []
    for bf in benchmark_files:
        rel = os.path.relpath(bf, mode.benchmark_dir()).replace(os.sep, "/")
        selected_benchmarks.add(rel)
        if rel in done_pass:
            continue
        work_items.append(
            WorkItem(
                benchmark_path=bf,
                output_dir=output_dir,
                timeout=args.timeout,
                check_timeout=args.check_timeout,
                backend=backend,
                mode=mode,
                tlapm_path=tlapm_root,
                tlapm_lib=tlapm_lib,
                usage_script=usage_script,
                quota_5h=quota_5h,
                quota_7d=quota_7d,
                quota_max_waits=args.quota_max_waits,
                min_free_gb=args.min_free_gb,
                use_container=use_container,
                container_image=container_image,
                infra_retries=args.infra_retries,
                max_continuations=args.max_continuations,
                keep_container=use_container and args.keep_container,
                session_dir=session_dir,
                canonical_inputs=canonical_inputs_by_path.get(bf),
                agent_skills_snapshot=agent_skills_snapshot,
                run_identity=run_identity,
                module_resume=module_resumes.get(rel),
                module_checkpoint_identity=module_checkpoint_identities.get(rel),
            )
        )

    start_time = time.monotonic()
    # A filtered resume keeps results from the rest of the original run, so
    # the cumulative report's denominator must cover both sets of benchmarks.
    total_benchmarks = _total_benchmark_count(results, selected_benchmarks)
    prior_done = total_benchmarks - len(work_items)
    if args.resume:
        print(f"Resume: {len(work_items)} benchmarks left to run")

    if args.jobs == 1:
        for i, item in enumerate(work_items):
            r = run_single_benchmark(item)
            _record_result(results, r)
            icon = VERDICT_ICONS.get(r["check_verdict"], "❓")
            tokens = format_token_usage(result_token_usage(r))
            cont = _continuation_note(r)
            metrics = (
                f"{_format_task_time(r.get('time_secs'))}, {tokens} tok, "
                f"{_format_equivalent_cost(r.get('equivalent_cost_usd'))}"
                if _supports_cost_time(backend)
                else f"{r['time_secs']:.0f}s, {tokens} tok"
            )
            print(
                f"[{prior_done + i + 1}/{total_benchmarks}] {icon} {r['benchmark']} ({metrics})"
                + (f" — {cont}" if cont else "")
            )
            update_summary(results, output_dir, total_benchmarks, backend.name, mode.name, specification_ids)
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as executor:
            futures = {executor.submit(run_single_benchmark, item): item for item in work_items}
            for done_count, future in enumerate(as_completed(futures), start=1):
                r = future.result()
                _record_result(results, r)
                icon = VERDICT_ICONS.get(r["check_verdict"], "❓")
                tokens = format_token_usage(result_token_usage(r))
                cont = _continuation_note(r)
                metrics = (
                    f"{_format_task_time(r.get('time_secs'))}, {tokens} tok, "
                    f"{_format_equivalent_cost(r.get('equivalent_cost_usd'))}"
                    if _supports_cost_time(backend)
                    else f"{r['time_secs']:.0f}s, {tokens} tok"
                )
                print(
                    f"[{prior_done + done_count}/{total_benchmarks}] {icon} {r['benchmark']} ({metrics})"
                    + (f" — {cont}" if cont else "")
                )
                update_summary(results, output_dir, total_benchmarks, backend.name, mode.name, specification_ids)

    total_time = time.monotonic() - start_time

    update_summary(results, output_dir, total_benchmarks, backend.name, mode.name, specification_ids)
    report_path = os.path.join(output_dir, "summary.md")

    print(f"\n{'=' * 60}")
    if _supports_cost_time(backend):
        print(f"Run wall time: {total_time:.0f}s")
    else:
        print(f"Completed in {total_time:.0f}s")
    print(f"Report: {report_path}")

    verdicts = {}
    for r in results:
        v = r["check_verdict"]
        verdicts[v] = verdicts.get(v, 0) + 1
    for v in ["PASS", "FAIL", "CHEATING", "TIMEOUT", "ERROR"]:
        if v in verdicts:
            print(f"  {VERDICT_ICONS.get(v, '❓')} {v}: {verdicts[v]}")
    print(f"  Total tokens: {format_token_usage(aggregate_token_usage(results), verbose=True)}")
    formal_results = _formal_results(results)
    print(f"  Total agent time: {_format_task_time(_sum_required_metric(formal_results, 'agent_time_secs'))}")
    print(f"  Total grading time: {_format_task_time(_sum_required_metric(formal_results, 'grading_time_secs'))}")
    print(f"  Total task time: {_format_task_time(_sum_required_metric(formal_results, 'time_secs'))}")
    if _supports_cost_time(backend):
        print(
            f"  Equivalent cost: {_format_equivalent_cost(_sum_required_metric(formal_results, 'equivalent_cost_usd'))}"
        )
        for benchmark, warning in _equivalent_cost_warnings(results):
            print(f"  WARNING [{benchmark}]: {warning}")


if __name__ == "__main__":
    main()

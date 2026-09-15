"""runner infra-retry loop — retry transient startup failures, never real attempts.

A startup failure (INFRA_ERROR with no token, request, cost, or backend-native
activity evidence: the CLI died before the model did any work) must be retried
on a fresh workspace, and only the final genuine attempt graded; exhaustion is
ERROR/INFRA_ERROR, never a proof FAIL. Fakes stand in for the agent and grader,
so no container, real backend or tlapm is needed.

Run: PYTHONPATH=src python3 -m pytest tests/evaluator/test_infra_retry.py
"""

import json
import os

import pytest

from evaluator import runner
from evaluator.backends.agentic import AgenticBackend
from evaluator.backends.base import SubmissionPlan
from evaluator.backends.codex import CodexBackend
from evaluator.backends.copilot import CopilotBackend
from evaluator.backends.cursor import CursorBackend
from evaluator.backends.pi import PiBackend
from evaluator.termination import TerminationReason
from evaluator.usage import RequestUsage, UsageCost, UsageSummary

BENCH_TEXT = "---- MODULE Bar ----\n====\n"

# One clean copilot terminal event: classifies as a genuine, completed run.
CLEAN_EVENTS = [{"type": "result", "exitCode": 0}]

# The observed startup shape: nonzero exit, no events, error only on stderr.
STARTUP = {"exit": 1, "stderr": "Error: Failed to load models\n\nError: Failed to list models\n"}
# A genuine attempt whose proof simply didn't verify.
GENUINE_FAIL = {"exit": 0, "events": CLEAN_EVENTS, "out_tokens": 500}


class _ScriptedBackend(AgenticBackend):
    """Backend whose per-attempt behavior is scripted (see _install_agent)."""

    name = "copilot"

    def __init__(self):
        self.in_tokens = 0
        self.out_tokens = 0  # set by the fake agent for the current attempt
        self.reasoning_tokens = 0
        self.cost = 0.0
        self.submission_metadata = {}

    def parse_output(self, jsonl_path):
        return ("", self.in_tokens, self.out_tokens)

    def parse_usage(self, jsonl_path, *, input_tokens, output_tokens):
        if not (input_tokens or output_tokens or self.reasoning_tokens or self.cost):
            return UsageSummary.from_requests(
                [],
                source="scripted",
                complete=True,
                totals={"input_tokens": 0, "output_tokens": 0, "model_requests": 0},
            )
        costs = (UsageCost(self.cost, "provider_monetary", "test.cost"),) if self.cost else ()
        return UsageSummary.from_requests(
            [
                RequestUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reasoning_output_tokens=self.reasoning_tokens,
                    costs=costs,
                )
            ],
            source="scripted",
            complete=True,
        )

    def attempt_output_files(self):
        return ("copilot-otel.jsonl",)

    def build_command(self, workspace, result_dir):
        return ["fake-agent"]

    def detect_quota_block(self, jsonl_path):
        return None

    def prepare_submission(self, *args, **kwargs):
        return SubmissionPlan(metadata=self.submission_metadata)


class _FakeMode:
    name = "proof-completion"

    def __init__(self, bench_dir):
        self._bench_dir = bench_dir

    def benchmark_dir(self):
        return self._bench_dir

    def get_dependencies(self, benchmark_path):
        return []

    def checker_binary_path(self):
        return "/bin/true"

    def build_prompt(self, basename, tlapm_path, tlapm_lib):
        return "prove it"


def _work_item(tmp_path, backend, infra_retries=3):
    bench_dir = tmp_path / "bench"
    bench_path = bench_dir / "Foo" / "Bar.tla"
    os.makedirs(bench_path.parent, exist_ok=True)
    bench_path.write_text(BENCH_TEXT)
    return runner.WorkItem(
        benchmark_path=str(bench_path),
        output_dir=str(tmp_path / "out"),
        timeout=10,
        check_timeout=10,
        backend=backend,  # ty:ignore[invalid-argument-type]
        mode=_FakeMode(str(bench_dir)),  # ty:ignore[invalid-argument-type]
        tlapm_path="/bin/true",
        tlapm_lib="",
        infra_retries=infra_retries,
    )


def _install_agent(monkeypatch, backend, attempts):
    """Patch _run_backend_local with a scripted agent: one spec dict per attempt
    ({"exit": int, "events": [...], "stderr": str, "out_tokens": int,
    "error": str, "last_message": str, "mutate": fn(workspace)})."""
    calls = {"n": 0, "workspaces": [], "canonical_dirs": []}

    def fake_run(
        item, backend_, mode, workspace, agent_dir, agent_jsonl, prompt, result, checker_bin, canonical_dir=None
    ):
        spec = attempts[calls["n"]]
        calls["n"] += 1
        calls["workspaces"].append(workspace)
        calls["canonical_dirs"].append(canonical_dir)
        with open(agent_jsonl, "w") as f:
            for ev in spec.get("events", []):
                f.write(json.dumps(ev) + "\n")
        if spec.get("stderr"):
            with open(os.path.join(agent_dir, "stderr.txt"), "w") as f:
                f.write(spec["stderr"])
        result["agent_exit"] = spec.get("exit", 0)
        if spec.get("error"):
            result["error"] = spec["error"]
        backend.out_tokens = spec.get("out_tokens", 0)
        backend.in_tokens = spec.get("in_tokens", 0)
        backend.reasoning_tokens = spec.get("reasoning_tokens", 0)
        backend.cost = spec.get("cost", 0.0)
        if spec.get("otel"):
            with open(os.path.join(agent_dir, "copilot-otel.jsonl"), "w") as f:
                f.write(spec["otel"])
        if spec.get("last_message"):
            with open(os.path.join(agent_dir, "codex_last_message.txt"), "w") as f:
                f.write(spec["last_message"])
        if "mutate" in spec:
            spec["mutate"](workspace)
        if "mutate_canonical" in spec:
            spec["mutate_canonical"](canonical_dir)

    monkeypatch.setattr(runner, "_run_backend_local", fake_run)
    return calls


def _install_grader(monkeypatch, verdict="FAIL", inspect_canonical=None):
    calls = {"n": 0, "canonical_dirs": []}

    def fake_grader(item, workspace, basename, grading_dir, check_result_path, result, canonical_dir=None):
        calls["n"] += 1
        calls["canonical_dirs"].append(canonical_dir)
        if inspect_canonical:
            inspect_canonical(canonical_dir)
        result["check_verdict"] = verdict

    monkeypatch.setattr(runner, "_run_grader_local", fake_grader)
    return calls


def _no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(runner.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def _result(benchmark, verdict, termination_reason="OK", **kw):
    out = {
        "benchmark": benchmark,
        "check_verdict": verdict,
        "agent_time_secs": 0,
        "grading_time_secs": 0,
        "time_secs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "termination_reason": termination_reason,
    }
    out.update(kw)
    if "time_secs" in kw and "agent_time_secs" not in kw and "grading_time_secs" not in kw:
        out["agent_time_secs"] = kw["time_secs"]
    return out


def test_summary_excludes_non_genuine_results_from_pass_rate(tmp_path):
    results = [
        _result("genuine-pass.tla", "PASS"),
        _result("genuine-fail.tla", "FAIL"),
        _result("infra-pass.tla", "PASS", termination_reason=TerminationReason.INFRA_ERROR),
        _result("quota-error.tla", "ERROR", termination_reason=TerminationReason.QUOTA_EXHAUSTED),
        _result("skipped.tla", "SKIP"),
    ]
    runner.update_summary(
        results, str(tmp_path), total_benchmarks=5, backend_name="copilot", mode_name="proof-completion"
    )
    summary = (tmp_path / "summary.md").read_text()
    assert "**Pass rate**: 2/3 (66.7%) · 1 skipped · 1 error/interrupted (excluded — re-run)" in summary
    assert "`infra-pass.tla` | ✅ PASS" in summary
    assert "`quota-error.tla`" in summary and "QUOTA_EXHAUSTED (excluded — re-run)" in summary


def test_summary_uses_strict_specification_pass_rate_as_primary_for_manifest_suites(tmp_path):
    results = [
        _result("A/One.tla", "PASS", mode="proof-completion"),
        _result("A/Two.tla", "FAIL", mode="proof-completion"),
        _result("B/Only.tla", "PASS", mode="proof-completion"),
        _result("Removed/Old.tla", "PASS", mode="proof-completion"),
    ]
    specification_ids = {
        ("proof-completion", "A/One.tla"): "A/A.tla",
        ("proof-completion", "A/Two.tla"): "A/A.tla",
        ("proof-completion", "B/Only.tla"): "B/B.tla",
    }

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=4,
        backend_name="copilot",
        mode_name="proof-completion",
        specification_ids=specification_ids,
    )

    summary = (tmp_path / "summary.md").read_text()
    primary = "**Specification pass rate (all leaves complete)**: 1/2 resolved specifications (50.0%)"
    task_level = "**Task-micro pass rate**: 2/3 (66.7%)"
    specification_macro = "**Specification-macro pass rate**: 75.0% across 2 resolved specifications"
    assert primary in summary
    assert task_level in summary
    assert specification_macro in summary
    assert summary.index(primary) < summary.index(task_level) < summary.index(specification_macro)
    assert "**Non-applicable results**: 1 not present in the active manifest (excluded)" in summary


def test_incomplete_summary_defers_strict_specification_pass_rate(tmp_path):
    results = [_result("A/One.tla", "PASS", mode="proof-completion")]
    specification_ids = {
        ("proof-completion", "A/One.tla"): "A/A.tla",
        ("proof-completion", "A/Two.tla"): "A/A.tla",
    }

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=2,
        backend_name="copilot",
        mode_name="proof-completion",
        specification_ids=specification_ids,
    )

    summary = (tmp_path / "summary.md").read_text()
    assert "**Specification pass rate**: pending until the run completes (1/2 tasks finished)" in summary
    assert "**Specification pass rate (all leaves complete)**" not in summary
    assert "**Task-micro pass rate**: 1/1 (100.0%)" in summary


def test_summary_reports_time_and_equivalent_cost_without_zero_filling(tmp_path):
    results = [
        _result("priced.tla", "PASS", time_secs=1.25, equivalent_cost_usd=0.125),
        _result("legacy.tla", "FAIL", time_secs=2.75),
    ]

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=2,
        backend_name="copilot",
        mode_name="proof-completion",
    )

    summary = (tmp_path / "summary.md").read_text()
    assert "**Total task time**: 4.0s" in summary
    assert "**Equivalent cost**: unavailable" in summary
    assert "`priced.tla` | ✅ PASS | 1.2s | 0.0s | 1.2s | $0.125000" in summary
    assert "`legacy.tla` | ❌ FAIL | 2.8s | 0.0s | 2.8s | unavailable" in summary


def test_cursor_summary_uses_cost_time_format(tmp_path):
    results = [_result("cursor.tla", "PASS", time_secs=1.25)]

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=1,
        backend_name="cursor",
        mode_name="proof-completion",
    )

    summary = (tmp_path / "summary.md").read_text()
    assert "**Equivalent cost**: unavailable" in summary
    assert "**Total task time**: 1.2s" in summary
    assert "| Benchmark | Verdict | Agent | Grading | Total | Equivalent cost | Obligations |" in summary
    assert "`cursor.tla` | ✅ PASS | 1.2s | 0.0s | 1.2s | unavailable |" in summary


def test_summary_reports_cost_warning_and_excludes_infra_accounting(tmp_path):
    results = [
        _result(
            "formal.tla",
            "PASS",
            time_secs=2.0,
            equivalent_cost_usd=0.2,
            usage={"warnings": ["equivalent cost warning: native and calculated costs differ"]},
        ),
        _result(
            "infra.tla",
            "ERROR",
            termination_reason=TerminationReason.INFRA_ERROR,
            time_secs=100.0,
            equivalent_cost_usd=10.0,
        ),
    ]

    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=2,
        backend_name="copilot",
        mode_name="proof-completion",
    )

    summary = (tmp_path / "summary.md").read_text()
    assert "**Total task time**: 2.0s" in summary
    assert "**Equivalent cost**: $0.200000" in summary
    assert "## Cost warnings" in summary
    assert "`formal.tla`: equivalent cost warning:" in summary


def test_public_price_preflight_requires_explicit_noninteractive_override(monkeypatch, capsys):
    backend = _ScriptedBackend()
    backend.model = "future-model"
    backend.requires_public_pricing = True
    monkeypatch.setattr(runner, "public_price_error", lambda _model, _provider: "model price is unavailable")
    monkeypatch.setattr(runner.sys.stdin, "isatty", lambda: False)

    assert not runner._confirm_public_pricing(backend, allow_unpriced_model=False)
    assert runner._confirm_public_pricing(backend, allow_unpriced_model=True)
    assert backend._equivalent_cost_disabled is True
    assert "Aborting before the run" in capsys.readouterr().out


def test_public_price_preflight_can_continue_after_interactive_confirmation(monkeypatch):
    backend = _ScriptedBackend()
    backend.model = "future-model"
    backend.requires_public_pricing = True
    monkeypatch.setattr(runner, "public_price_error", lambda _model, _provider: "model price is unavailable")
    monkeypatch.setattr(runner.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    assert runner._confirm_public_pricing(backend, allow_unpriced_model=False)
    assert backend._equivalent_cost_disabled is True


def test_codex_nonstandard_service_tier_uses_existing_ask_or_blank_flow(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('service_tier = "priority"\n')
    backend = CodexBackend(model="gpt-5.6-sol")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(runner, "public_price_error", lambda _model, _provider: None)
    monkeypatch.setattr(runner.sys.stdin, "isatty", lambda: False)

    assert not runner._confirm_public_pricing(
        backend,
        allow_unpriced_model=False,
        use_container=False,
    )
    assert runner._confirm_public_pricing(
        backend,
        allow_unpriced_model=True,
        use_container=False,
    )
    assert backend._equivalent_cost_disabled is True


def test_codex_container_pricing_ignores_unmounted_host_service_tier(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('service_tier = "priority"\n')
    backend = CodexBackend(model="gpt-5.6-sol")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(runner, "public_price_error", lambda _model, _provider: None)

    assert runner._confirm_public_pricing(
        backend,
        allow_unpriced_model=False,
        use_container=True,
    )


def test_resume_skips_verified_pass_results_even_after_interruption():
    results = [
        _result("genuine-pass.tla", "PASS"),
        _result("legacy-pass.tla", "PASS", termination_reason=None),
        _result("infra-pass.tla", "PASS", termination_reason=TerminationReason.INFRA_ERROR),
        _result("quota-pass.tla", "PASS", termination_reason=TerminationReason.QUOTA_EXHAUSTED),
        _result("skipped.tla", "SKIP"),
        _result("failed.tla", "FAIL"),
    ]
    assert runner._resume_done_benchmarks(results) == {
        "genuine-pass.tla",
        "legacy-pass.tla",
        "infra-pass.tla",
        "quota-pass.tla",
        "skipped.tla",
    }


def test_resumed_result_replaces_non_genuine_attempt(tmp_path):
    results = [
        _result("already-passed.tla", "PASS"),
        _result("retry.tla", "ERROR", termination_reason=TerminationReason.INFRA_ERROR),
    ]

    runner._record_result(results, _result("retry.tla", "PASS"))
    total_benchmarks = runner._total_benchmark_count(results, {"retry.tla"})
    runner.update_summary(
        results,
        str(tmp_path),
        total_benchmarks=total_benchmarks,
        backend_name="copilot",
        mode_name="proof-completion",
    )

    assert [(r["benchmark"], r["check_verdict"]) for r in results] == [
        ("already-passed.tla", "PASS"),
        ("retry.tla", "PASS"),
    ]
    summary = (tmp_path / "summary.md").read_text()
    assert "**Progress**: 2/2" in summary
    assert "**Pass rate**: 2/2 (100.0%)" in summary
    assert json.loads((tmp_path / "results.json").read_text()) == results


def test_total_benchmark_count_includes_new_filtered_benchmark():
    results = [_result("already-recorded.tla", "PASS")]

    assert runner._total_benchmark_count(results, {"newly-selected.tla"}) == 2


def test_filtered_resume_keeps_cumulative_progress_total(tmp_path, monkeypatch):
    bench_dir = tmp_path / "bench"
    retry = bench_dir / "Suite" / "retry.tla"
    retry.parent.mkdir(parents=True)
    retry.write_text(BENCH_TEXT)

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    previous_results = [
        _result("Suite/already-passed.tla", "PASS"),
        _result("Suite/retry.tla", "PASS"),
    ]
    (output_dir / "results.json").write_text(json.dumps(previous_results))

    backend = _ScriptedBackend()
    mode = _FakeMode(str(bench_dir))
    mode.description = "test mode"
    mode.get_benchmark_files = lambda filter_pattern: [str(retry)]
    monkeypatch.setattr(backend, "check_auth", lambda: None, raising=False)
    monkeypatch.setattr(backend, "default_quota", lambda: (0, 0), raising=False)
    monkeypatch.setattr(backend, "usage_script", lambda: None, raising=False)
    monkeypatch.setattr(runner, "get_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr(runner, "ensure_tlapm", lambda: None)
    monkeypatch.setattr(runner, "find_tlapm_lib", lambda tlapm_bin: "/tmp/tlapm-lib")
    monkeypatch.setattr(runner, "resolve_paths", lambda: (str(tmp_path), "/bin/true"))
    monkeypatch.setattr(runner, "get_mode", lambda *args: mode)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "tlaps-bench-run",
            "--no-container",
            "--resume",
            "--filter",
            "retry.tla",
            "--output-dir",
            str(output_dir),
        ],
    )

    runner.main()

    summary = (output_dir / "summary.md").read_text()
    assert "**Progress**: 2/2" in summary
    assert "**Progress**: 2/1" not in summary
    assert json.loads((output_dir / "results.json").read_text()) == previous_results


def test_make_workspace_cleans_up_on_setup_failure(tmp_path, monkeypatch):
    # The temp dir must not leak when workspace setup dies half-way (disk full,
    # unreadable dep) — same guarantee _make_canonical_dir gives.
    created = []
    real_mkdtemp = runner.tempfile.mkdtemp

    def tracking_mkdtemp(**kw):
        d = real_mkdtemp(**kw)
        created.append(d)
        return d

    def broken_write(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(runner.tempfile, "mkdtemp", tracking_mkdtemp)
    monkeypatch.setattr(runner, "_write_bytes", broken_write)
    canonical_inputs = runner.CanonicalInputs("Bar.tla", BENCH_TEXT.encode(), ())
    with pytest.raises(OSError):
        runner._make_workspace("copilot", "Bar", canonical_inputs)
    assert created and not os.path.isdir(created[0])


def test_make_workspace_can_make_only_dependencies_read_only(tmp_path):
    benchmark = tmp_path / "Bar.tla"
    dependency = tmp_path / "Model.tla"
    benchmark.write_text(BENCH_TEXT)
    benchmark.chmod(0o444)
    dependency.write_text("---- MODULE Model ----\n====\n")

    canonical_inputs = runner.CanonicalInputs.capture(str(benchmark), benchmark.name, [str(dependency)])
    workspace = runner._make_workspace("copilot", "Bar", canonical_inputs, read_only_dependencies=True)
    try:
        assert os.stat(os.path.join(workspace, benchmark.name)).st_mode & 0o200
        assert os.stat(os.path.join(workspace, dependency.name)).st_mode & 0o777 == 0o444
    finally:
        runner.shutil.rmtree(workspace)


def test_startup_failure_retried_and_final_attempt_graded(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    agent = _install_agent(monkeypatch, backend, [STARTUP, GENUINE_FAIL])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend))
    assert agent["n"] == 2
    assert grader["n"] == 1  # only the genuine attempt is graded
    assert result["check_verdict"] == "FAIL"
    assert result["termination_reason"] == TerminationReason.OK
    assert result["infra_retries"] == 1
    assert result["infra_retry_reasons"] == ["Error: Failed to load models"]
    assert len(sleeps) == 1 and sleeps[0] >= 15  # first backoff step (plus jitter)
    # Failed attempt's evidence is stashed; the retry metadata reaches disk.
    out = tmp_path / "out" / "Foo" / "Bar"
    assert "Failed to load models" in (out / "agent" / "attempts" / "attempt-0" / "stderr.txt").read_text()
    saved = json.loads((out / "result.json").read_text())
    assert saved["infra_retries"] == 1


def test_retry_time_keeps_only_formal_attempt_and_separates_infra_time(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    _install_agent(monkeypatch, backend, [STARTUP, GENUINE_FAIL])
    _install_grader(monkeypatch, verdict="FAIL")
    _no_sleep(monkeypatch)
    clock = iter((10.0, 12.0, 20.0, 25.0, 30.0, 31.0))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert result["agent_time_secs"] == 5.0
    assert result["grading_time_secs"] == 1.0
    assert result["time_secs"] == 6.0
    diagnostic = json.loads(
        (tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-0" / "accounting.json").read_text()
    )
    assert diagnostic["time_secs"] == 2.0


def test_container_timeout_before_agent_marker_does_not_publish_setup_time(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    item = _work_item(tmp_path, backend, infra_retries=0)
    item.use_container = True

    def timeout_before_marker(
        item,
        backend,
        workspace,
        agent_dir,
        agent_jsonl,
        prompt,
        result,
        canonical_dir=None,
        read_only_files=None,
    ):
        result["agent_exit"] = -1
        result["error"] = f"{backend.name} timeout after {item.timeout}s"
        return None

    monkeypatch.setattr(runner, "_run_backend_container", timeout_before_marker)

    def fake_grader(_item, _workspace, _basename, _grading_dir, _check_result_path, result, _canonical_dir=None):
        result["check_verdict"] = "TIMEOUT"

    monkeypatch.setattr(runner, "_run_grader_container", fake_grader)

    result = runner.run_single_benchmark(item)

    assert result["termination_reason"] == TerminationReason.TIMEOUT
    assert result["time_secs"] is None


def test_reasoning_output_prevents_infrastructure_retry(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    agent = _install_agent(
        monkeypatch,
        backend,
        [{**STARTUP, "in_tokens": 100, "reasoning_tokens": 9}, GENUINE_FAIL],
    )
    grader = _install_grader(monkeypatch)
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert agent["n"] == 1
    assert grader["n"] == 1
    assert sleeps == []
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["check_verdict"] == "FAIL"
    assert result["time_secs"] is None
    assert result["equivalent_cost_usd"] is None
    assert result["usage"]["status"] == "unavailable"
    diagnostic = json.loads(
        (tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-0" / "accounting.json").read_text()
    )
    assert diagnostic["usage"]["reasoning_output_tokens"] == 9


def test_retry_keeps_only_formal_usage_and_stashes_provider_telemetry(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    startup_with_artifact = {
        **STARTUP,
        "otel": "first-attempt-telemetry\n",
    }
    recovered = {**GENUINE_FAIL, "in_tokens": 100, "out_tokens": 50, "cost": 0.02}
    _install_agent(monkeypatch, backend, [startup_with_artifact, recovered])
    _install_grader(monkeypatch, verdict="FAIL")
    _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert (result["input_tokens"], result["output_tokens"]) == (100, 50)
    assert result["usage"]["model_requests"] == 1
    assert result["usage"]["costs"] == [{"amount": 0.02, "unit": "provider_monetary", "source": "test.cost"}]
    assert [request["attempt"] for request in result["usage"]["requests"]] == [1]
    stashed = tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-0"
    assert (stashed / "copilot-otel.jsonl").read_text() == "first-attempt-telemetry\n"


def test_structured_input_and_cost_prevent_retry_when_legacy_output_is_zero(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    charged_failure = {**STARTUP, "in_tokens": 20, "out_tokens": 0, "cost": 0.002}
    agent = _install_agent(monkeypatch, backend, [charged_failure])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=3))

    assert agent["n"] == 1 and grader["n"] == 1
    assert (result["input_tokens"], result["output_tokens"]) == (0, 0)
    assert result["time_secs"] is None
    assert result["equivalent_cost_usd"] is None
    diagnostic = json.loads(
        (tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-0" / "accounting.json").read_text()
    )
    assert diagnostic["usage"]["input_tokens"] == 20
    assert diagnostic["usage"]["costs"] == [{"amount": 0.002, "unit": "provider_monetary", "source": "test.cost"}]
    assert "infra_retries" not in result
    assert sleeps == []


def test_codex_item_activity_prevents_retry_when_failed_turn_has_no_usage(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-test")
    failed_after_model_work = {
        "exit": 1,
        "events": [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {
                "type": "item.started",
                "item": {
                    "id": "item-1",
                    "type": "command_execution",
                    "command": "check-proof",
                    "status": "in_progress",
                },
            },
            {"type": "error", "message": "connection lost"},
            {"type": "turn.failed", "error": {"message": "connection lost"}},
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_after_model_work])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=3))

    assert agent["n"] == 1
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["usage"]["status"] == "unavailable"
    assert "infra_retries" not in result
    assert sleeps == []


def test_cursor_partial_edit_activity_prevents_retry_without_terminal_usage(tmp_path, monkeypatch):
    backend = CursorBackend(model="test-model")
    failed_after_edit = {
        "exit": 1,
        "events": [
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "I will update the proof."}]},
            },
            {
                "type": "tool_call",
                "subtype": "started",
                "call_id": "edit-1",
                "tool_call": {"editToolCall": {"args": {"path": "Bar.tla"}}},
            },
            {
                "type": "tool_call",
                "subtype": "completed",
                "call_id": "edit-1",
                "tool_call": {
                    "editToolCall": {
                        "args": {"path": "Bar.tla"},
                        "result": {"success": True},
                    }
                },
            },
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_after_edit])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=3))

    assert agent["n"] == 1
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["tool_calls"]["total"] == 1
    assert result["tool_calls"]["is_lower_bound"] is True
    assert "infra_retries" not in result
    assert sleeps == []


def test_copilot_partial_edit_activity_prevents_retry_without_terminal_otel(tmp_path, monkeypatch):
    backend = CopilotBackend(model="test-model")
    failed_after_edit = {
        "exit": 1,
        "events": [
            {
                "type": "assistant.message",
                "data": {
                    "content": "I will update the proof.",
                    "toolRequests": [
                        {
                            "toolCallId": "edit-1",
                            "name": "edit",
                            "arguments": {"path": "Bar.tla"},
                        }
                    ],
                },
            },
            {
                "type": "tool.execution_start",
                "data": {
                    "toolCallId": "edit-1",
                    "toolName": "edit",
                    "arguments": {"path": "Bar.tla"},
                },
            },
            {
                "type": "tool.execution_complete",
                "data": {
                    "toolCallId": "edit-1",
                    "success": True,
                    "result": {"content": "updated Bar.tla"},
                },
            },
            {
                "type": "session.error",
                "data": {"errorType": "query", "message": "stream closed"},
            },
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_after_edit])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=3))

    assert agent["n"] == 1
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["tool_calls"]["total"] == 1
    assert result["tool_calls"]["is_lower_bound"] is True
    assert "infra_retries" not in result
    assert sleeps == []


def test_pi_true_pre_stream_failure_is_retried(tmp_path, monkeypatch):
    backend = PiBackend(model="openai/gpt-test")
    zero_usage = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
    }
    failure_message = {
        "role": "assistant",
        "content": [{"type": "text", "text": ""}],
        "api": "openai-responses",
        "provider": "openai",
        "model": "gpt-test",
        "usage": zero_usage,
        "stopReason": "error",
        "errorMessage": "OAuth refresh failed before provider stream",
        "timestamp": 1,
    }
    failed_before_model_work = {
        "exit": 1,
        "stderr": "No API key found for openai.\n",
        "events": [
            {"type": "session", "version": 3, "id": "session-1"},
            {"type": "agent_start"},
            {"type": "turn_start"},
            {"type": "message_start", "message": failure_message},
            {"type": "message_end", "message": failure_message},
            {"type": "turn_end", "message": failure_message, "toolResults": []},
            {"type": "agent_end", "messages": [failure_message]},
            {"type": "agent_settled"},
        ],
    }
    recovered = {
        "exit": 0,
        "events": [
            {"type": "session", "version": 3, "id": "session-2"},
            {"type": "agent_start"},
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "finished"}],
                    "api": "openai-responses",
                    "provider": "openai",
                    "model": "gpt-test",
                    "usage": {
                        "input": 20,
                        "output": 5,
                        "cacheRead": 10,
                        "cacheWrite": 0,
                        "totalTokens": 35,
                        "cost": {
                            "input": 0.001,
                            "output": 0.002,
                            "cacheRead": 0.0001,
                            "cacheWrite": 0,
                            "total": 0.0031,
                        },
                    },
                    "stopReason": "stop",
                    "timestamp": 1,
                },
            },
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_before_model_work, recovered])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert agent["n"] == 2
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.OK
    assert result["infra_retries"] == 1
    assert result["infra_retry_reasons"] == ["No API key found for openai."]
    assert (result["input_tokens"], result["output_tokens"]) == (30, 5)
    assert result["usage"]["status"] == "complete"
    assert result["usage"]["costs"] == [{"amount": 0.0031, "unit": "usd", "source": "pi.usage.cost.total"}]
    assert result["equivalent_cost_usd"] == 0.0031
    assert len(sleeps) == 1


def test_pi_provider_adapter_error_without_stream_start_is_not_retried(tmp_path, monkeypatch):
    backend = PiBackend(model="openai/gpt-test")
    zero_usage = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
    }
    failed_after_model_work = {
        "exit": 0,
        "events": [
            {"type": "session", "version": 3, "id": "session-1"},
            {"type": "agent_start"},
            {
                "type": "message_start",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "api": "openai-responses",
                    "provider": "openai",
                    "model": "gpt-test",
                    "usage": zero_usage,
                    "stopReason": "error",
                    "errorMessage": "stream disconnected before response headers",
                    "timestamp": 1,
                },
            },
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "api": "openai-responses",
                    "provider": "openai",
                    "model": "gpt-test",
                    "usage": zero_usage,
                    "stopReason": "error",
                    "errorMessage": "stream disconnected",
                    "timestamp": 1,
                },
            },
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled"},
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_after_model_work])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=3))

    assert agent["n"] == 1
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["usage"]["status"] == "unavailable"
    diagnostic = json.loads(
        (tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-0" / "accounting.json").read_text()
    )
    assert diagnostic["usage"]["status"] == "lower_bound"
    assert diagnostic["usage"]["model_requests"] == 1
    assert "infra_retries" not in result
    assert sleeps == []


def test_codex_quota_after_model_work_is_not_retried_or_overwritten(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-test")
    backend._reset_at_from_probe = lambda: None
    capped_after_work = {
        "exit": 1,
        "events": [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"id": "item-1", "type": "agent_message", "text": "partial paid work"},
            },
            {"type": "error", "message": "You've hit your usage limit."},
            {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}},
        ],
    }
    agent = _install_agent(monkeypatch, backend, [capped_after_work])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=3))

    assert agent["n"] == 1
    assert grader["n"] == 0
    assert sleeps == []
    assert result["termination_reason"] == TerminationReason.QUOTA_EXHAUSTED
    assert result["usage"]["status"] == "unavailable"
    assert "automatic retry suppressed" in result["error"]
    output = tmp_path / "out" / "Foo" / "Bar" / "agent" / "output.jsonl"
    assert "partial paid work" in output.read_text()


def test_codex_no_work_quota_retry_preserves_artifacts_without_merging_usage(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-test")
    backend._reset_at_from_probe = lambda: None
    capped_before_work = {
        "exit": 1,
        "last_message": "stale blocked-attempt message\n",
        "events": [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "error", "message": "You've hit your usage limit."},
            {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}},
        ],
    }
    recovered = {
        "exit": 0,
        "last_message": "finished\n",
        "events": [
            {"type": "thread.started", "thread_id": "thread-2"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {"id": "item-2", "type": "agent_message", "text": "finished"},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 2,
                },
            },
        ],
    }
    agent = _install_agent(monkeypatch, backend, [capped_before_work, recovered])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=0))

    assert agent["n"] == 2
    assert grader["n"] == 1
    assert len(sleeps) == 1
    assert (result["input_tokens"], result["output_tokens"]) == (100, 10)
    assert result["usage"]["status"] == "incomplete"
    assert not any("part of the aggregate" in warning for warning in result["usage"]["warnings"])
    agent_dir = tmp_path / "out" / "Foo" / "Bar" / "agent"
    stashed = agent_dir / "quota-attempts" / "infra-0-quota-0"
    assert "usage limit" in (stashed / "output.jsonl").read_text()
    assert (stashed / "codex_last_message.txt").read_text() == "stale blocked-attempt message\n"
    assert (agent_dir / "codex_last_message.txt").read_text() == "finished\n"


def test_codex_warning_item_before_turn_does_not_suppress_startup_retry(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-test")
    failed_before_model_work = {
        "exit": 1,
        "events": [
            {"type": "thread.started", "thread_id": "thread-1"},
            {
                "type": "item.completed",
                "item": {"id": "item-warning", "type": "error", "message": "configuration warning"},
            },
            {"type": "error", "message": "local configuration rejected"},
        ],
    }
    recovered = {
        "exit": 0,
        "events": [
            {"type": "thread.started", "thread_id": "thread-2"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": "done"}},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 2,
                },
            },
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_before_model_work, recovered])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert agent["n"] == 2
    assert grader["n"] == 1
    assert result["infra_retries"] == 1
    assert len(sleeps) == 1


def test_codex_wrapper_marker_does_not_suppress_launch_failure_retry(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-test")
    launch_failure = {
        "exit": 127,
        "stderr": "codex: executable not found\n",
        "events": [{"type": "tlaps.codex_child_usage.started", "version": 1}],
    }
    recovered = {
        "exit": 0,
        "events": [
            {"type": "tlaps.codex_child_usage.started", "version": 1},
            {"type": "thread.started", "thread_id": "thread-2"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": "done"}},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 80,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 2,
                },
            },
            {
                "type": "tlaps.codex_child_usage",
                "version": 1,
                "root_thread_id": "thread-2",
                "child_count": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "complete": True,
                "warning_codes": [],
            },
        ],
    }
    agent = _install_agent(monkeypatch, backend, [launch_failure, recovered])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert agent["n"] == 2
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.OK
    assert result["infra_retries"] == 1
    assert (result["input_tokens"], result["output_tokens"]) == (100, 10)
    assert len(sleeps) == 1


def test_codex_ambiguous_failure_before_item_activity_is_not_retried(tmp_path, monkeypatch):
    backend = CodexBackend(model="gpt-test")
    failed_before_model_work = {
        "exit": 1,
        "events": [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "error", "message": "connection lost"},
            {"type": "turn.failed", "error": {"message": "connection lost"}},
        ],
    }
    agent = _install_agent(monkeypatch, backend, [failed_before_model_work])
    grader = _install_grader(monkeypatch, verdict="FAIL")
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=1))

    assert agent["n"] == 1
    assert grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert "infra_retries" not in result
    assert result["usage"]["status"] == "unavailable"
    assert sleeps == []


def test_submission_metadata_cannot_overwrite_runner_accounting(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    backend.submission_metadata = {
        "usage": {"complete": True, "input_tokens": 9999, "output_tokens": 9999},
        "input_tokens": 9999,
        "output_tokens": 9999,
        "time_secs": 9999,
        "equivalent_cost_usd": 9999,
        "backend_note": "retained",
    }
    _install_agent(monkeypatch, backend, [{**GENUINE_FAIL, "in_tokens": 100, "out_tokens": 50}])
    _install_grader(monkeypatch, verdict="FAIL")

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=0))

    assert (result["input_tokens"], result["output_tokens"]) == (100, 50)
    assert result["time_secs"] != 9999
    assert result["backend_note"] == "retained"
    assert result["usage"]["input_tokens"] == 100
    assert result["equivalent_cost_usd"] is None
    assert any(
        "ignored submission metadata for runner-owned fields" in warning for warning in result["usage"]["warnings"]
    )


def test_retry_exhaustion_is_error_not_fail(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    agent = _install_agent(monkeypatch, backend, [STARTUP] * 3)
    grader = _install_grader(monkeypatch)
    _no_sleep(monkeypatch)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=2))
    assert agent["n"] == 3
    assert grader["n"] == 0  # never grade a run the model never attempted
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["infra_retries"] == 2
    assert result["infra_retry_reasons"] == ["Error: Failed to load models"] * 3
    assert result["time_secs"] is None
    assert result["usage"]["status"] == "unavailable"
    assert result["equivalent_cost_usd"] is None
    diagnostic = json.loads(
        (tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-2" / "accounting.json").read_text()
    )
    assert diagnostic["usage"]["status"] == "complete"
    assert diagnostic["usage"]["model_requests"] == 0
    assert diagnostic["equivalent_cost_usd"] == 0
    assert "exhausted infra retries" in result["error"]


def test_genuine_attempt_never_retried(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    agent = _install_agent(monkeypatch, backend, [GENUINE_FAIL])
    grader = _install_grader(monkeypatch)
    sleeps = _no_sleep(monkeypatch)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend))
    assert agent["n"] == 1 and grader["n"] == 1
    assert result["check_verdict"] == "FAIL"
    assert "infra_retries" not in result
    assert sleeps == []


def test_midrun_infra_with_tokens_not_retried(tmp_path, monkeypatch):
    # INFRA_ERROR but the model DID work (tokens > 0): classified for downstream
    # filtering, but never re-run — the attempt was genuine.
    cut_off = {"exit": 1, "events": [{"type": "assistant.message", "data": {"content": "working"}}], "out_tokens": 42}
    backend = _ScriptedBackend()
    agent = _install_agent(monkeypatch, backend, [cut_off])
    grader = _install_grader(monkeypatch)
    _no_sleep(monkeypatch)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend))
    assert agent["n"] == 1 and grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert "infra_retries" not in result


def test_structured_output_usage_prevents_retry_when_jsonl_tokens_are_missing(tmp_path, monkeypatch):
    # Provider telemetry may be durable even when a dying CLI never flushes its
    # normal JSONL usage event. That still proves the model did real work, so a
    # retry would duplicate a charged attempt.
    backend = _ScriptedBackend()

    def structured_usage(_jsonl_path, *, input_tokens, output_tokens):
        assert (input_tokens, output_tokens) == (0, 0)
        return UsageSummary.from_requests(
            [RequestUsage(input_tokens=21, output_tokens=8)],
            source="provider_telemetry",
            complete=False,
            is_lower_bound=True,
        )

    monkeypatch.setattr(backend, "parse_usage", structured_usage)
    agent = _install_agent(monkeypatch, backend, [STARTUP, GENUINE_FAIL])
    grader = _install_grader(monkeypatch)
    sleeps = _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend))

    assert agent["n"] == 1 and grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert (result["input_tokens"], result["output_tokens"]) == (0, 0)
    diagnostic = json.loads(
        (tmp_path / "out" / "Foo" / "Bar" / "agent" / "attempts" / "attempt-0" / "accounting.json").read_text()
    )
    assert (diagnostic["usage"]["input_tokens"], diagnostic["usage"]["output_tokens"]) == (21, 8)
    assert "infra_retries" not in result
    assert sleeps == []


def test_wall_clock_timeout_not_retried(tmp_path, monkeypatch):
    backend = _ScriptedBackend()
    timeout = {"exit": -1, "error": "copilot timeout after 10s"}
    agent = _install_agent(monkeypatch, backend, [timeout])
    grader = _install_grader(monkeypatch)
    sleeps = _no_sleep(monkeypatch)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend))
    assert agent["n"] == 1 and grader["n"] == 1
    assert result["termination_reason"] == TerminationReason.TIMEOUT
    assert sleeps == []


def test_infra_retries_zero_disables_retrying(tmp_path, monkeypatch):
    # 0 = no retries, but the no-attempt run still ends ERROR, never a proof FAIL.
    backend = _ScriptedBackend()
    agent = _install_agent(monkeypatch, backend, [STARTUP])
    grader = _install_grader(monkeypatch)
    sleeps = _no_sleep(monkeypatch)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=0))
    assert agent["n"] == 1 and grader["n"] == 0
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["infra_retries"] == 0
    assert sleeps == []


def test_retry_runs_on_fresh_workspace(tmp_path, monkeypatch):
    # A failed attempt's partial edits must not leak into the retry: attempt 1
    # scribbles on the benchmark, attempt 2 must see a pristine copy.
    seen = []

    def scribble(workspace):
        path = os.path.join(workspace, "Bar.tla")
        with open(path) as f:
            seen.append(f.read())
        with open(path, "w") as f:
            f.write("TAMPERED")

    def check(workspace):
        with open(os.path.join(workspace, "Bar.tla")) as f:
            seen.append(f.read())

    backend = _ScriptedBackend()
    attempts = [dict(STARTUP, mutate=scribble), dict(GENUINE_FAIL, mutate=check)]
    agent = _install_agent(monkeypatch, backend, attempts)
    _install_grader(monkeypatch)
    _no_sleep(monkeypatch)
    runner.run_single_benchmark(_work_item(tmp_path, backend))
    assert agent["workspaces"][0] != agent["workspaces"][1]
    assert seen == [BENCH_TEXT, BENCH_TEXT]


def test_retry_runs_on_fresh_canonical_snapshot(tmp_path, monkeypatch):
    # In local mode the agent can write to TLAPS_BENCHMARK_DIR. A failed
    # attempt's canonical snapshot must not leak into the retry or grader.
    seen = []

    def taint(canonical_dir):
        path = os.path.join(canonical_dir, "Bar.tla")
        with open(path) as f:
            seen.append(f.read())
        with open(path, "w") as f:
            f.write("TAINTED")

    def check(canonical_dir):
        with open(os.path.join(canonical_dir, "Bar.tla")) as f:
            seen.append(f.read())

    backend = _ScriptedBackend()
    attempts = [dict(STARTUP, mutate_canonical=taint), dict(GENUINE_FAIL, mutate_canonical=check)]
    agent = _install_agent(monkeypatch, backend, attempts)
    grader = _install_grader(monkeypatch, inspect_canonical=check)
    _no_sleep(monkeypatch)

    runner.run_single_benchmark(_work_item(tmp_path, backend))

    assert agent["canonical_dirs"][0] != agent["canonical_dirs"][1]
    assert grader["canonical_dirs"] == [agent["canonical_dirs"][1]]
    assert seen == [BENCH_TEXT, BENCH_TEXT, BENCH_TEXT]


def test_canonical_replay_uses_fresh_snapshot_not_exposed_to_agent(tmp_path, monkeypatch):
    seen = []

    def taint(canonical_dir):
        path = os.path.join(canonical_dir, "Bar.tla")
        with open(path, "w") as f:
            f.write("TAINTED")

    def inspect(canonical_dir):
        with open(os.path.join(canonical_dir, "Bar.tla")) as f:
            seen.append(f.read())

    backend = _ScriptedBackend()
    item = _work_item(tmp_path, backend)
    item.mode.canonical_replay_required = True
    agent = _install_agent(monkeypatch, backend, [dict(GENUINE_FAIL, mutate_canonical=taint)])
    grader = _install_grader(monkeypatch, inspect_canonical=inspect)

    runner.run_single_benchmark(item)

    assert grader["canonical_dirs"][0] != agent["canonical_dirs"][0]
    assert seen == [BENCH_TEXT]


def test_quota_exhaustion_is_not_infra_retried(tmp_path, monkeypatch):
    # Quota owns its own retry budget: once it reports exhaustion the infra loop
    # must stop dead — no reclassification, no extra attempts.
    backend = _ScriptedBackend()
    agent = _install_agent(monkeypatch, backend, [STARTUP] * 4)
    grader = _install_grader(monkeypatch)
    _no_sleep(monkeypatch)
    monkeypatch.setattr(runner.quota, "run_with_quota_retry", lambda run, block, **k: False)
    result = runner.run_single_benchmark(_work_item(tmp_path, backend))
    assert agent["n"] == 0  # the quota stub swallowed the run entirely
    assert grader["n"] == 0
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == TerminationReason.QUOTA_EXHAUSTED
    assert "infra_retries" not in result


def test_quota_retry_clears_stale_stderr_before_final_run(tmp_path, monkeypatch):
    # quota.run_with_quota_retry can invoke the agent multiple times inside one
    # infra attempt. Stderr from the quota-blocked run must not label the final run.
    backend = _ScriptedBackend()
    blocks = iter([1, None])
    monkeypatch.setattr(backend, "detect_quota_block", lambda _jsonl: next(blocks))
    agent = _install_agent(monkeypatch, backend, [{"exit": 1, "stderr": "old quota/stderr noise\n"}, {"exit": 1}])
    grader = _install_grader(monkeypatch)
    _no_sleep(monkeypatch)

    result = runner.run_single_benchmark(_work_item(tmp_path, backend, infra_retries=0))

    assert agent["n"] == 2
    assert grader["n"] == 0
    assert result["check_verdict"] == "ERROR"
    assert result["termination_reason"] == TerminationReason.INFRA_ERROR
    assert result["infra_retry_reasons"] == ["no stderr"]
    assert not (tmp_path / "out" / "Foo" / "Bar" / "agent" / "stderr.txt").exists()

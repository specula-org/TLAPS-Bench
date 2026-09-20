# Usage Guide

## Getting Started

Requirements: [uv](https://docs.astral.sh/uv/) and [Docker](https://docs.docker.com/get-docker/). Works on Linux x86-64 and Windows through WSL2; native Windows is not supported. macOS ARM works through Docker's emulation layer but is slower.

```bash
git clone https://github.com/specula-org/tlaps-bench.git
cd tlaps-bench
export OPENAI_API_KEY=sk-...
uv run tlaps-bench run --backend codex --model gpt-5.5 --filter GCD_GCD3
```

On the first run, the tool builds a Docker image that includes tlapm, SANY, and the proof checker. Subsequent runs reuse the cached image.

Results are saved to `results/proof-completion/codex/<timestamp>/`. Nothing else to install.

### Full benchmark suite

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --jobs 10 --timeout 7200
```

### Different backend and model

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run tlaps-bench run --backend claude_code --model claude-opus-4-8 --jobs 10
```

### Proof-from-scratch mode

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --mode proof-from-scratch --jobs 10
```

---

## Backends

A backend is the model integration that attempts the proof. Nine are included:

| Backend | CLI Name | Default Model |
|---------|----------|---------------|
| OpenAI Codex | `codex` | `gpt-5.5` |
| OpenAI Codex (single-turn approximation) | `codex_single_turn` | `gpt-5.5` |
| Claude Code | `claude_code` | `claude-opus-4-8` |
| Cursor | `cursor` | `sonnet-4.5` |
| GitHub Copilot | `copilot` | `claude-opus-4.8` |
| GitHub Copilot SDK (one-shot) | `copilot_oneshot` | `claude-opus-4.8` |
| LiteLLM | `litellm` | `claude-sonnet-4-6` |
| LiteLLM (one-shot) | `litellm_oneshot` | `claude-sonnet-4-6` |
| Pi | `pi` | `openai/gpt-5.5` |

Select a backend with `--backend`:

```bash
uv run tlaps-bench run --backend claude_code --model claude-opus-4-8
uv run tlaps-bench run --backend pi --model anthropic/claude-sonnet-4-6
uv run tlaps-bench run --backend litellm --model claude-sonnet-4-6
uv run tlaps-bench run --backend litellm_oneshot --model claude-sonnet-4-6
uv run tlaps-bench run --backend codex_single_turn --model gpt-5.6-sol
```

### Agent skills

The benchmark automatically makes the portable skills under `skills/` available to supported agentic backends in both proof modes:

| Backend | Project skills directory |
|---------|--------------------------|
| `codex` | `.agents/skills` |
| `claude_code` | `.claude/skills` |
| `cursor` | `.agents/skills` |
| `copilot` | `.github/skills` |
| `litellm` | `.agents/skills` |
| `pi` | `.agents/skills` |

Strict one-shot backends and `codex_single_turn` do not receive skills.
Proof-from-scratch requires a tool-using backend that can inspect the official
library interfaces and iterate with the checker, so strict one-shot backends
and `codex_single_turn` fail before making a model request in that mode.

### OpenAI-compatible endpoints

To target any OpenAI-compatible endpoint (a self-hosted gateway, a vendor's
inference API, etc.), use the LiteLLM backend with an `openai/<model>` model id
and point `OPENAI_API_BASE` (or `OPENAI_BASE_URL`) at the endpoint. The host is
forwarded into the container and automatically added to the firewall allow-list:

```bash
export OPENAI_API_KEY=...
export OPENAI_API_BASE=https://inference-api.somecompany.com/v1
uv run tlaps-bench run --backend litellm --model openai/somecompany/some-model
```

The leading `openai/` selects LiteLLM's OpenAI-compatible transport; everything
after it is sent to the endpoint as the wire model id.

### Reasoning effort

Use the optional `--reasoning-effort` flag to override a model's reasoning budget:

```bash
uv run tlaps-bench run --backend codex --model gpt-5.6-sol --reasoning-effort low
```

### Output token limit

`copilot_oneshot` accepts an explicit positive per-request output limit. When
set, the wire guard replaces the Copilot runtime's output limit and records
both values in the result audit:

```bash
uv run tlaps-bench run --backend copilot_oneshot --model claude-opus-4.8 --max-output-tokens 64000
```

Omit `--max-output-tokens` to preserve the runtime's default. Other backends
currently reject this option instead of silently ignoring it.

### Authentication

The runner passes credentials into the container in two ways:

1. **Environment variables** set on the host are forwarded into the container.
2. **Host credential directories** (`~/.aws/`, `~/.codex/`, `~/.pi/`, `~/.claude/`) are mounted into the container automatically when the backend needs them.

If you are already logged in to an agent on your host machine (e.g. `codex login`, or credentials saved in `~/.codex/`), the runner picks those up and transfers them to the container. You do not need to re-authenticate.

**Per-backend credentials:**

| Backend | Environment Variable | Host Credentials (auto-mounted) |
|---------|---------------------|----------------------------------|
| `codex` | `OPENAI_API_KEY` or `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_HOST` | `~/.codex/` (logged-in session) |
| `codex_single_turn` | Same as `codex` | `~/.codex/` (logged-in session, including ChatGPT subscription auth) |
| `claude_code` | `ANTHROPIC_API_KEY` | `~/.claude/` |
| `copilot` | `COPILOT_GITHUB_TOKEN` or `GH_TOKEN`. BYOK: `COPILOT_PROVIDER_BASE_URL` + `COPILOT_PROVIDER_API_KEY` + `COPILOT_PROVIDER_TYPE` | |
| `copilot_oneshot` | `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN` | |
| `litellm` | Model-dependent: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY` | `~/.aws/` (for Bedrock models) |
| `litellm_oneshot` | Model-dependent: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY` | `~/.aws/` (for Bedrock models) |
| `pi` | Provider-dependent: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. | `~/.pi/` (auth.json), `~/.aws/` (for Bedrock) |

For the `pi` backend, the model format is `provider/model` (e.g. `openai/gpt-5.5`, `anthropic/claude-sonnet-4-6`). The provider prefix determines which credentials are used.

### Strict one-shot backends

`litellm_oneshot` and `copilot_oneshot` use the same provider-neutral one-shot contract. The target module and its dependencies are embedded in one user prompt, which requests either one complete TLA+ module or exactly one `tla` code fence containing that module. The runner accepts and materializes at most one non-empty assistant response as `solution.tla`, then leaves syntax and proof validity to the normal grader; there is no agent tool loop or opportunity to inspect and edit the workspace.

These tool-free backends currently support proof-completion only. Use an
agentic backend for proof-from-scratch.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run tlaps-bench run --backend litellm_oneshot --model claude-sonnet-4-6 --filter GCD_GCD3

export COPILOT_GITHUB_TOKEN=github_pat_...
uv run tlaps-bench run --backend copilot_oneshot --model claude-opus-4.8 --max-output-tokens 64000 --filter GCD_GCD3
```

LiteLLM makes one completion call per outer attempt and disables adapter retries. Copilot makes one logical `send_and_wait` call; before a complete response, its native runtime may retry an identical transient request up to six total wire attempts. A complete response, permanent error, changed request, or deadline stops further requests. Native retries currently apply only to `copilot_oneshot`.

Copilot audits every forwarded request. Missing token or cost telemetry is marked as a lower bound, never treated as zero. Extra usage records are discarded.

Both backends default to three outer infrastructure retries, but only for explicitly transient failures with no model output. Copilot reasoning may continue through a native retry inside the same turn, but it prevents a fresh outer Agent attempt. Each outer retry uses a fresh workspace and preserves earlier evidence under `agent/attempts/`. `--max-continuations` must remain `0`.

Copilot uses the benchmark deadline for startup and inference, records `TIMEOUT` before bounded teardown, and blocks late requests. It accepts `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`; stored CLI sessions and agentic BYOK settings are not used.

With `--no-container`, the runner uses its source-tree path instead of `/opt`. LiteLLM is already a project dependency; native Copilot runs additionally require `github-copilot-sdk` and its runtime (`python3 -m copilot download-runtime`) in the active environment.

### Codex subscription single-turn approximation

`codex_single_turn` provides a subscription-compatible approximation when a
strict provider API one-shot is unavailable. It uses the official
[`codex exec`](https://learn.chatgpt.com/docs/non-interactive-mode) interface and
reuses the same [`codex login`](https://learn.chatgpt.com/docs/auth) credentials
as the agentic `codex` backend, including ChatGPT subscription authentication:

```bash
codex login
uv run tlaps-bench run --backend codex_single_turn --model gpt-5.6-sol --reasoning-effort medium --task-list core
```

OpenAI, ChatGPT, and Azure Codex authentication are supported. Amazon Bedrock
models are rejected because their user-level provider configuration is
intentionally ignored by this isolated mode.

Each benchmark starts one non-interactive Codex process, supplies the strict
one-shot prompt plus an explicit no-tools instruction on stdin, permits one
logical turn, disables project skills and Codex shell, code-mode, multi-agent,
app, browser, computer, image, and goal tool features, and uses a read-only
sandbox. The final message is materialized as the complete TLA+ module and
passed to the normal grader. User configuration and repository rules are
ignored so they cannot silently add tools, instructions, or a different
service tier. Continuations are disabled.

This backend is not labeled strict one-shot. The public Codex JSONL stream does
not expose the wire request or prove removal of Codex's built-in internal
instructions. The evaluator therefore records `one_shot: false`. It keeps the
Codex session long enough for the rollout wrapper to audit native token-count
deltas: a valid result records `model_request_count_visible: true`,
`model_request_count_source: codex_rollout_token_count`, and
`model_requests: 1`. It also records whether exactly one thread and turn
completed, whether a complete zero-tool session-tree audit was observed, event
counts, and the final message's presence. Multiple progress/final
`agent_message` events inside the same turn do not make it a multi-turn run.

An incomplete rollout audit, more than one model request, any child agent or
tool call, or a damaged turn is an infrastructure/contract failure and is
excluded from capability scoring. This keeps a normal SANY or TLAPS rejection
as a genuine model FAIL without treating a broken approximation as model
behavior.

---

## Modes

A mode defines what the agent is asked to do.

| Mode | What the agent sees | What it must do |
|------|---------------------|-----------------|
| `proof-completion` | A fixed target theorem plus its exact read-only model and scaffold context. Scaffold lemmas marked `PROOF OMITTED` are trusted givens. | Replace the marked target proof without changing the theorem, scaffold, imports, or context. |
| `proof-from-scratch` | An editable target theorem plus only its declared read-only model/definition context. | Invent the proof structure, including fresh helper definitions and proved lemmas. |

Select a mode with `--mode`:

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --mode proof-completion
uv run tlaps-bench run --backend codex --model gpt-5.5 --mode proof-from-scratch
```

Benchmark files live in `benchmark/proof-completion/` and `benchmark/proof-from-scratch-module/` respectively. The 276-task tree under `benchmark/proof-from-scratch/` is the module generator's read-only target-selection source, not the suite `run` loads.

### Layered-task trust boundary

For layered suites, `benchmark/<mode>/manifest.json` is the authority for task discovery, specification identity, and context. Each entry names the originating source module as `spec_id`, one editable target, and its complete local TLA+ dependency closure. The runner does not infer dependencies from neighboring filenames, so sibling tasks and unrelated definition modules never enter the workspace, prompt, input artifact, or verifier. An invalid manifest stops the run. See [`tlaps-bench score`](#tlaps-bench-score) for the grouping rule.

Proof-completion targets contain one `AGENT PROOF` marker pair. Only its interior may change; imports, the target theorem statement, marker lines, and all surrounding text remain canonical. Module-level declarations are rejected inside the proof region, while proof-local steps such as `DEFINE` and `USE` remain valid. Model and scaffold modules are read-only context; their admitted scaffold lemmas are allowed as givens.

Proof-from-scratch targets contain separate `AGENT HELPERS` and `AGENT PROOF` marker pairs. The helper region accepts fresh operator definitions, module-level `USE DEF` / `HIDE DEF`, fully proved named lemmas or theorems, and named `LOCAL <alias> == INSTANCE <module>` imports from the run's frozen official proof-library catalog. Unnamed instances, `WITH`, non-official modules, constants, variables, assumptions, nested modules, shadowed names, and module-level declarations in the proof region are rejected.

For both marked layouts, all fixed bytes must match the canonical target. Extra newlines at EOF are ignored; other newline-only differences fail but are not labeled cheating. Proof completion and proof from scratch both require a valid manifest; a missing or malformed manifest fails closed, with no heuristic evaluator fallback.

The runner captures canonical inputs before starting the agent and grades from a separate copy. Docker makes context read-only; native `--no-container` uses advisory `0444` permissions and is not a host-security boundary. Canonical validation failures are infrastructure errors.

---

## CLI Reference

### `tlaps-bench run`

Run one or more benchmarks with an evaluator backend.

```bash
uv run tlaps-bench run [flags]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--backend` | `codex` | Evaluator backend to use |
| `--mode` | `proof-completion` | Benchmark mode |
| `--model` | (backend default) | Override the model |
| `--reasoning-effort` | (backend behavior) | Pass a backend/model-specific reasoning effort |
| `--max-output-tokens` | (backend behavior) | Positive per-request output limit; currently supported by `copilot_oneshot` |
| `--filter` | (all benchmarks) | Substring match on path, comma-separated |
| `--task-list` | (all benchmarks) | Registered cohort name or file of exact mode-relative task IDs; mutually exclusive with `--filter` |
| `--jobs` | `1` | Number of parallel backend runs |
| `--timeout` | `28800` | Per-benchmark backend timeout in seconds |
| `--check-timeout` | `600` | Base verification seconds; PFS module budgets scale with selected original targets, up to 3x |
| `--check-cpus` | `8` | PFS CPU cap per module, including nested workers; integer from 1 to 8 |
| `--output-dir` | auto-generated | Output directory |
| `--resume` | off | Skip benchmarks already marked `SKIP` or genuine `PASS` (first-attempt or continuation) |
| `--infra-retries` | `3` | Extra attempts after a transient startup/infra failure that the backend approves as safe to replay |
| `--max-continuations` | `0` | Run up to N same-workspace continuation attempts after the first attempt completes without PASS; strict one-shot backends require `0` (see [Continuation runs](#continuation-runs)) |
| `--force-build` | off | Rebuild the Docker image |
| `--no-container` | off | Run without Docker (requires native setup) |
| `--keep-container` | off | Retain each agent container after it exits (drop `--rm`) for debugging (see [Debugging a run](#debugging-a-run-keep-container)) |
| `--session-dir` | off (default `~/.tlaps-bench/sessions` under `--keep-container`) | Persist each run's agent session state to this persistent host path (survives container removal and reboot; restore with `scripts/restore-session.sh`) |
| `--allow-unpriced-model` | off | Continue with blank equivalent cost when public pricing is unavailable |

Run `uv run tlaps-bench run --help` for the full flag list.

For Proof From Scratch, the runner freezes the selected original `proof_unit_ids` before execution and computes `T = ceil(x * min(1 + 0.25 * (N - 1), 3))`, where `x` is the positive `--check-timeout` and `N` is the number of selected original targets in that module. One, two, three, five, and nine or more targets receive 1x, 1.25x, 1.5x, 2x, and 3x respectively. Added helper lemmas do not affect this budget. Other evaluation modes retain their existing timeout semantics. `--timeout 0` still gives the agent unlimited total running time.

The runner passes the already computed T to both self-checking and grading. Each independent examination receives its own full T: self-checking does not spend the final grader's allowance, and the same candidate may be examined again. Within one examination, parsing and proving share a wall-clock budget; batching and interruption recovery retain elapsed time. Grader examinations persist under the attempt's grading directory and resume only with matching candidate bytes, canonical inputs, toolchain, and policy. New policy settings cannot silently resume an older run.

Standalone `tlaps-bench check --timeout T` takes an effective budget and never scales it again. Omit `--check-session` for a fresh examination, or use the same `--check-session DIR` to persist and resume one examination. Completed unit receipts and SANY parses are reused only within that input-bound session; final grading has a separate, grader-owned state directory. With `--container`, the session directory must be inside the mounted workspace. A crash may conservatively charge at most one extra 0.25-second checkpoint interval. Time between invocations is excluded. These budgets impose no new per-backend or per-obligation time limits.

Each module is capped at eight CPU cores by default, independently of `--jobs`. Docker limits the module container, including direct TLAPM calls; native Linux execution constrains the agent and checker process trees to at most eight CPUs with inherited affinity. Native PFS execution requires Linux and `taskset`; use Docker on other platforms. CPU affinity is a cooperative resource bound, not a sandbox against deliberately changing affinity. Module results record wall time and process CPU time (including reaped children); CPU accounting is marked incomplete after an abrupt interruption or when killed descendants could not be accounted for.

The structured module report distinguishes `BUDGET_EXHAUSTED` (a unit was running when the module deadline expired), `NOT_STARTED` (the budget ran out before the unit started), proof `FAIL`, and tool `ERROR`. `TIMEOUT` remains supported for historical reports. Verified targets and dependencies remain in partial reports; only dependency-closed coverage of every original target yields complete success. Run manifests record the base, original IDs/count, effective budget, CPU cap, absence of local limits, and policy version.

The default remains the complete suite. To run the committed 190-task Proof Completion Core:

```bash
uv run tlaps-bench run --mode proof-completion --task-list core
```

The current Core selects 190 tasks across 56 specifications. Full remains the default when `--task-list` is omitted.

`core` is a registered name for the current mode's committed `core.txt`; Proof Completion provides it today. Explicit file paths remain supported. Task lists use exact manifest IDs rather than substring matching. Unavailable cohorts, missing files, unknown IDs, duplicates, and empty lists fail before authentication, image setup, or model preflight. A task-list run records its resolved cohort in `task-list.json` inside the output directory.

### `tlaps-bench check`

Check a single proof file for correctness and cheating.

```bash
uv run tlaps-bench check path/to/file.tla --mode proof-completion --benchmark-dir path/to/canonical-context
uv run tlaps-bench check path/to/file.tla --mode proof-from-scratch --benchmark-dir path/to/canonical-context
uv run tlaps-bench check path/to/file.tla --sany-only
```

Full proof-from-scratch and marked proof-completion checks automatically require canonical replay. Pass an independent directory containing the original target and its declared context with `--benchmark-dir`; the canonical target must not alias the submitted file. Inside the evaluator runner this directory is supplied automatically. Full checks fail closed when no independent canonical context is available. `--sany-only` checks only the submitted file and its workspace dependencies, so it does not require canonical context. Legacy unmarked proof-completion checks keep their previous behavior.

Proof Completion checks reuse `<target-dir>/.tlacache` by default; use `--no-cache` for a cold check, or `--timeout 0` for no checker deadline. PFS module checks require a positive deadline and keep fingerprints within their examination directory. `--no-cache` disables TLAPM fingerprint reuse; completed SANY stages and unit receipts are retained as examination progress during recovery.

Cheating is checked before proving: a detected cheat fails fast and skips the tlapm run (`--keep-verifying` verifies anyway). Each run also snapshots the workspace to a hidden git ref — browse it with `git log refs/tlaps-check/history`; `--no-git-track` disables.

Huge proofs are verified in parallel shards (`tlapm --toolbox` line ranges split at theorem boundaries, one cache dir per shard). Sharding is automatic above `TLAPS_SHARD_MIN_LINES` (5000) lines at nproc/2 shards capped by available memory (`TLAPS_SHARD_MEM_MB` per shard); `--shards N` forces a count, `--shards 1` forces a single run.

Exit codes: `0` = PASS, `1` = FAIL, `3` = ERROR.

### `tlaps-bench score`

Compute scores from one or more result files.

```bash
uv run tlaps-bench score results/proof-from-scratch/pi/20260626_220712/results.json
uv run tlaps-bench score results/proof-completion/*/results.json
```

Strict comparisons require every run to contain the same applicable task IDs.

Each manifest entry maps its mode-relative task ID to the originating `.tla` path under `source/` (`spec_id`). Tasks from the same source module form one scoring group. Proof Completion entries also include `reference_proof_steps`.

The default primary score is the specification pass rate: a represented specification passes only when all of its selected tasks pass.

```text
spec_pass = 1 if all applicable selected tasks pass, otherwise 0
overall_score = completed specifications / represented specifications
```

Reports show three scores:

- **Specification pass rate** (primary, all leaves complete): specifications whose selected tasks all passed.
- **Task-level pass rate** (secondary): passed applicable tasks divided by all applicable tasks.
- **Specification-macro** (secondary): the average per-specification task pass rate, preserving partial credit.

`SKIP`, infrastructure-cut, and removed tasks are excluded and reported separately. Pass `--scoring equal` for the legacy task-level-only output.

### `tlaps-bench validate`

Verify that source proofs (before `PROOF OBVIOUS` replacement) pass tlapm.

```bash
uv run tlaps-bench validate --jobs 10
uv run tlaps-bench validate --filter Paxos --jobs 10
```

### `tlaps-bench generate`

Regenerate benchmark files from annotated source specs.

```bash
uv run tlaps-bench generate
uv run tlaps-bench generate --mode proof-from-scratch
uv run tlaps-bench generate --mode proof-from-scratch --verify
```

Proof-from-scratch generation emits the module suite under `benchmark/proof-from-scratch-module/`: one task per source `spec_id`, with the existing 276 theorem IDs as proof units. It reads `benchmark/proof-from-scratch/` and will not write into that tree. `--verify` regenerates into a scratch directory and compares the shipped suite. To rebuild the frozen 276-task selection corpus itself, invoke `uv run python -m dataset.proof_from_scratch.generate --layered` directly.

Proof-completion generation emits the layered suite described in [Layered-task trust boundary](#layered-task-trust-boundary): one read-only `<base>Model.tla` per source, one read-only `<task>Scaffold.tla` per target, an editable `<task>.tla` holding the fixed theorem statement and the marked proof region, and a `manifest.json` naming every task's source specification and exact context. Use `--legacy` only for the old generators.

```bash
uv run tlaps-bench generate --mode proof-completion
uv run tlaps-bench generate --mode proof-completion --filter EWD840   # one source group
uv run tlaps-bench generate --mode proof-completion --legacy         # archival single-file layout
uv run tlaps-bench generate --mode proof-completion --legacy --shared-model  # archival shared-model layout
```

`--output-dir` works with the default layered generator and with `--legacy --shared-model`. The flat `--legacy` generator writes only to `benchmark/proof-completion/`. Legacy generator outputs are archival and are not accepted by the manifest-only evaluator.

Every task is parsed back through the evaluator's own contract, then gated: each one must parse under standalone SANY with only its manifest context, and any task whose `PROOF OBVIOUS` placeholder already verifies is dropped as degenerate. `--skip-gates` bypasses both for fast iteration; a shipped dataset is generated with them. A `--filter` or positional-file run regenerates only the tasks belonging to the sources it processed and needs the existing manifest to preserve the rest. `benchmark/<mode>/audit.log` records every drop, every leak check, and every task that the previous dataset had but the run did not regenerate.

---

## Output Structure

Each run writes results to a timestamped directory:

```
results/<mode>/<backend>/<timestamp>/
├── results.json              # All verdicts, time, equivalent cost, and tokens
├── summary.md                # Scores, total task time, and equivalent cost
└── <Module>/<Theorem>/
    ├── result.json           # Per-benchmark verdict and metadata
    ├── input/
    │   ├── benchmark.tla     # Original benchmark file (copied in)
    │   ├── *.tla             # Dependency modules it EXTENDS (copied in)
    │   ├── prompt.txt        # Prompt sent to the agent
    │   └── skills/           # Exact project-skill snapshot available to the backend
    ├── agent/
    │   ├── solution.tla      # The agent's final output
    │   ├── output.jsonl      # Raw agent stdout capture
    │   ├── copilot-otel.jsonl # Copilot CLI only: official usage telemetry
    │   ├── attempts/          # Infra attempts, each with separate accounting.json
    │   ├── quota-attempts/    # Quota attempts, each with separate accounting.json
    │   ├── stderr.txt        # Agent stderr, if any — start here to debug a 0-token run
    │   └── transcript.txt    # Parsed transcript with token summary
    └── grading/
        ├── check.result        # Checker verdict and details
        └── agent_check.result  # Agent's own in-workspace check, if it ran one
```

With `--max-continuations`, each continuation round also writes a `continuations/round-N/` directory with that round's prompt, output, solution, and checker result.

### Usage and cost telemetry

For `codex`, `codex_single_turn`, `claude_code`, `copilot`, `copilot_oneshot`, `cursor`, `litellm`, `litellm_oneshot`, and `pi`, each formal benchmark result records:

- `time_secs`: agent wall time, excluding the checker
- `equivalent_cost_usd`: the same usage valued at public API prices, not the actual subscription spend

Infra and quota attempts are saved separately and excluded from formal results and totals.

Agent-reported USD is preferred; otherwise complete token usage is priced with `genai-prices`. Missing or partial data leaves the cost blank. If pricing is unavailable before a non-interactive run, use `--allow-unpriced-model` to continue with blank cost.

---

## Resuming a Run

If a run is interrupted or you want to retry only the failures:

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --output-dir results/proof-completion/codex/20260626_120000 --resume
```

The runner skips benchmarks already recorded as `SKIP` or as a genuine `PASS` in that directory (first-attempt or via a continuation round), and reruns the rest.

When resuming a task-list run, pass the same `--task-list` again. The runner rejects a different list, a different mode, or an output directory whose prior results were not recorded with a task list. Proof-from-scratch runs also record `run-manifest.json` and reject resume when the canonical corpus, execution sources, pinned official proof-library digest, content-locked verification toolchain, execution limits, or persistent-session policy changed. If the original run used `--session-dir` or the implicit session directory from `--keep-container`, resume with the same resolved session path.

Inline infra retries are intentionally short: the default `--infra-retries 3` gives the original attempt plus three retries with brief backoff. If a longer provider or network outage leaves `INFRA_ERROR` / `QUOTA_EXHAUSTED` results, rerun later with the same `--output-dir --resume`; those non-genuine results are not skipped.

---

## Continuation Runs

Use `--max-continuations N` to give the agent extra chances to finish a proof it already started:

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --max-continuations 3
```

Each benchmark still starts with the normal first attempt. If that attempt completes without PASS, the runner starts up to `N` more attempts in the same workspace. Each continuation sees the partial proof from the previous attempt. The chain stops once a continuation passes or the limit is reached.

The first-attempt verdict stays in `check_verdict`. Continuation rounds are saved under `continuations` in `results.json`, and reports show them separately as `Task-micro pass rate with continuations (≤N)`.

---

## Docker Details

Each run spins up an isolated container that installs the agent CLI, applies a network firewall (only LLM API hosts are reachable), and mounts benchmarks read-only to prevent tampering.

Cursor uses a DNS-backed IP set so newly discovered or rotated Cursor endpoints
become reachable without adding one firewall rule per resolved address. Other
DNS names, non-HTTPS traffic, and IPv6 remain blocked. Default Cursor entries
act as DNS suffixes and last for the container lifetime; a custom
`CURSOR_API_ENDPOINT` keeps the existing exact-host firewall behavior.

The runner fingerprints the Docker inputs and automatically rebuilds when the
embedded source or checker changes. Use `--force-build` only when you need to
rebuild the current fingerprint explicitly:

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --force-build
```

To skip Docker entirely (for debugging, requires native setup):

```bash
uv run tlaps-bench run --backend codex --model gpt-5.5 --no-container
```

### Debugging a run (`--keep-container`)

By default each agent container is started with `--rm`, so it (and its writable layer, where the agent's session state such as `.copilot` / `.codex` lives) is deleted the moment the run finishes or is interrupted. That makes it impossible to resume the agent or ask it follow-up questions afterwards.

Pass `--keep-container` to retain the container instead:

```bash
uv run tlaps-bench run --backend copilot --keep-container --filter my_benchmark
```

Each run prints the retained container's name, e.g.:

```text
[keep-container] retaining container 'tlaps-bench-my_benchmark-1a2b3c4d'. After it exits: `docker exec -it tlaps-bench-my_benchmark-1a2b3c4d bash` to inspect (start it first if stopped: `docker start ...`), `docker commit ... <img>` to snapshot, `docker rm -f ...` to remove.
```

The name is unique per attempt, so parallel jobs, infra retries and continuation rounds never collide.

`--keep-container` also **persists the session state to the host by default** (see below), so a single flag is enough for debugging and the state survives even a host reboot. Clean up when done — retained containers are **not** auto-removed:

```bash
docker ps -a --filter name=tlaps-bench- --format '{{.Names}}' | xargs -r docker rm -f
```

`--keep-container` only applies in container mode (it is ignored with `--no-container`).

### Persisting session state to the host (`--session-dir`)

Session state lives inside the container, and for backends that authenticate from a mounted credential file (`codex` / `codex_single_turn` / `claude_code` / `pi`) it is written into a `/tmp` tempdir — so a reboot (e.g. after an OOM) clears it even if the container is kept. To avoid that, the agent's session state is bind-mounted straight to a **persistent host directory**.

With `--keep-container` this happens automatically under `~/.tlaps-bench/sessions/`. Pass `--session-dir` to choose the location explicitly (and to persist without keeping the container):

```bash
uv run tlaps-bench run --backend copilot --session-dir ./sessions --filter my_benchmark
```

Each physical module writes its state to `<session-dir>/<backend>/<module-key>/`. The key includes the complete mode-relative module path, so modules with the same filename never share state. Retries, continuation rounds, `--keep-container`, and `--resume` all reuse that module's directory. For `codex`/`codex_single_turn`/`claude_code`/`pi` the credential files are stored there too, so a single mount holds both auth and session. Because it is a real host path — not `/tmp` and not tied to the container's lifetime — the state survives container removal and reboot. A `.gitignore` (`*`) is written at the session root so this credential-bearing data can't be accidentally committed. `--session-dir` is ignored with `--no-container`.

### Restoring a session into a container

To resume or inspect a persisted session, mount it back into a fresh container:

```bash
scripts/restore-session.sh --backend copilot ~/.tlaps-bench/sessions/copilot/<module-key>
```

This starts an interactive `tlaps-bench-base` shell with the session mounted at the backend's session path (e.g. `/root/.copilot`), so you can read the transcript or run the agent CLI's own resume command (e.g. `copilot --resume`). The container is removed on exit; the host session directory is not. (Network egress is not firewalled in this debug shell, and no benchmark files are mounted — it is for inspecting/continuing the agent session, not for grading.)

---

## Native Setup (Optional)

Only needed if you run with `--no-container` or develop the tooling itself.

**Additional requirements:** GNU Make, `curl`, `tar`, Python 3.12+, JDK 21+, and Linux x86-64 with glibc ≥ 2.38 (Ubuntu 24.04+, Debian 13+) or macOS arm64. On older Linux, use Docker instead.

```bash
make setup
```

This installs the Python environment, downloads the TLAPM and SANY artifacts locked by content in `config/verification-toolchain.json`, installs the exact official proof-library commits pinned in `config/proof-library-sources.json`, compiles the checker binary, and runs a SANY smoke test. Safe to rerun. Uses about 3 GB of disk. Setup warns when either official repository has moved but never updates the pins automatically; maintainers can inspect the pinned trees with `python3 scripts/install_proof_libraries.py inspect` before editing the source lock.

---

## Backend Architecture

All entries in the backend registry share the neutral `Backend` lifecycle. Tool-using workspace editors inherit `AgenticBackend`; strict single-response implementations inherit the sibling `OneShotBackend`. `codex_single_turn` instead reuses Codex CLI execution and telemetry while overriding its prompt, sandbox, materialization, and continuation capabilities. Prompt construction, command/deadline propagation, option validation, result metadata, request-audit validation, and submission preparation are polymorphic backend hooks, so the common runner and termination classifier do not special-case strict one-shot names or provider names. Runtime one-shot providers implement the `OneShotProvider` protocol and are selected through a registry; each strict one-shot backend cross-checks the common request contract against its provider's raw audit evidence. A provider may report one `usage_details` entry per model request; each entry must explicitly include both `input_tokens` and `output_tokens` to be complete. Providers without per-request details can return exact aggregate token counts instead. Unavailable counts must be `None`, which becomes `null` and makes the record a lower bound; explicit zeroes remain exact zeroes.

## Adding a New Agentic Backend

To add support for a new coding agent, create a Python file in `src/evaluator/backends/` that subclasses `AgenticBackend`.

### 1. Create the backend file

`src/evaluator/backends/my_agent.py`:

```python
"""My agent backend."""

from __future__ import annotations

import json
import os

from .agentic import AgenticBackend
from .base import detect_firewall_hosts


class MyAgentBackend(AgenticBackend):
    name = "my_agent"
    install_script = "install-my-agent.sh"
    project_skills_dir = ".agents/skills"
    env_keys = ["MY_AGENT_API_KEY"]

    def __init__(self, model: str | None = None):
        self.model = model or "default-model"

    def build_command(self, workspace: str, result_dir: str) -> list[str]:
        return ["my-agent", "--model", self.model, "--workspace", workspace]

    def parse_output(self, jsonl_path: str) -> tuple[str, int, int]:
        transcript, in_tok, out_tok = "", 0, 0
        try:
            with open(jsonl_path) as f:
                for line in f:
                    event = json.loads(line)
                    transcript += event.get("text", "")
                    in_tok += event.get("input_tokens", 0)
                    out_tok += event.get("output_tokens", 0)
        except FileNotFoundError:
            pass
        return transcript, in_tok, out_tok

    def check_auth(self) -> str | None:
        if not os.environ.get("MY_AGENT_API_KEY"):
            return "my_agent: MY_AGENT_API_KEY not set"
        return None

    def firewall_hosts(self) -> list[str]:
        return detect_firewall_hosts(self.model)
```

### 2. Register it

In `src/evaluator/backends/__init__.py`, add:

```python
from .my_agent import MyAgentBackend

_REGISTRY = {
    # ... existing backends ...
    MyAgentBackend.name: MyAgentBackend,
}
```

### 3. Add an install script (if needed)

Create `docker/install-scripts/install-my-agent.sh`:

```bash
#!/bin/bash
set -e
npm install -g my-agent-cli --cache /tmp/.npm && rm -rf /tmp/.npm
```

This script runs inside the container with full network access before the firewall is applied. Use it to install your agent's CLI.

### Interface reference

| Method | What it does |
|--------|-------------|
| `name` | String used as the `--backend` CLI value |
| `install_script` | Filename in `docker/install-scripts/` to run at container start. Set `None` if pre-installed. |
| `project_skills_dir` | Repository-relative project directory where the backend exposes Agent Skills. Leave `None` for unsupported backends. |
| `env_keys` | List of host environment variables forwarded into the container |
| `credential_mounts` | List of credential directory names to mount (see below) |
| `get_credential_mounts()` | Override this for dynamic credential logic |
| `build_command(workspace, result_dir)` | Returns the agent command as a list. The prompt is piped to stdin. The agent works in `workspace/` where the `.tla` file lives. |
| `parse_output(jsonl_path)` | Reads the captured stdout file. Returns `(transcript, input_tokens, output_tokens)`. |
| `parse_usage(jsonl_path, *, input_tokens, output_tokens)` | Returns a structured `UsageSummary`. The default implementation adapts the legacy token pair, so existing backends remain compatible. |
| `retry_may_duplicate_model_work(jsonl_path)` | Returns whether native activity—or missing native events—makes automatically replacing a failed/truncated launch unsafe. The default is `False`. |
| `execution_environment(result_dir)` | Returns per-execution environment additions, such as an isolated telemetry output path. |
| `attempt_output_files()` | Lists backend-owned artifacts that must be preserved and cleared across infra retries. |
| `check_auth()` | Fast host-side check before launching a container. Return `None` if OK, or an error string. |
| `firewall_hosts()` | List of API hostnames the container must allow. Use `detect_firewall_hosts(model)` to allow all known LLM API endpoints. |

### Credential mount names

| Name | Mounts from host | Into container |
|------|------------------|----------------|
| `"aws"` | `~/.aws/` | `~/.aws/` |
| `"codex"` | `~/.codex/` | `~/.codex/` |
| `"pi"` | `~/.pi/` | `~/.pi/` |
| `"claude"` | `~/.claude/` | `~/.claude/` |

---

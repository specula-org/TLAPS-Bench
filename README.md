# TLAPS Proof Benchmark

[![CI](https://github.com/specula-org/tlaps-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/specula-org/tlaps-bench/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A benchmark for evaluating AI's ability to write [TLAPS](https://proofs.tlaplus.net/doc/) (TLA+ Proof System) proofs.

Benchmark results are available on the [TLAPS-Bench website](https://specula-org.github.io/tlaps-bench-website/).

## Overview

TLAPS proofs are checked mechanically by `tlapm`: a proof is either accepted or
rejected, with no partial credit and no room for a plausible-but-wrong argument.
That makes proof construction a sharp test of an AI's formal reasoning.

Each task presents a TLA+ theorem whose proof body is replaced by `PROOF OBVIOUS`;
the AI must replace it with a real proof that `tlapm` accepts. Tasks come in two
types:

- **Proof completion** (`--mode proof-completion`) — the model and proof scaffold
  (inductive invariants, lemma decomposition, and preceding lemmas marked
  `PROOF OMITTED`) are given as read-only context, and the AI fills in one
  marked target proof.
- **Proof from scratch** (`--mode proof-from-scratch`) — only the model and
  the target theorem statement remain; the AI must invent the entire proof
  structure, including any helper lemmas.

## Benchmark problems

The benchmark draws on two kinds of source. A base of classic TLA+ **example
libraries**, a small set of **systems specifications** — real
protocols, several with no published proof. Both sets are expected to keep
growing as more specifications are added.
A `–` marks a source with no human proofs, from which no proof-completion task
can be derived.

**Example libraries**

| Source | Examples | Proof completion | Proof from scratch | Total |
|---|--:|--:|--:|--:|
| [tlaplus/Examples](https://github.com/tlaplus/Examples) | 50 | 357 | 179 | 536 |
| [TLAPS distribution examples](https://github.com/tlaplus/tlapm) | 14 | 91 | 51 | 142 |
| **Subtotal** | **64** | **448** | **230** | **678** |

**Systems specifications**

| Source | Examples | Proof completion | Proof from scratch | Total |
|---|--:|--:|--:|--:|
| [apalache-examples (Konnov)](https://github.com/konnov/apalache-examples) | 2 | 257 | – | 257 |
| [ZooKeeper (Remix)](https://arxiv.org/abs/2409.14301) | 2 | – | 18 | 18 |
| [Ivy liveness](https://github.com/kenmcmil/ivy) | 6 | – | 12 | 12 |
| [etcd (Specula)](https://github.com/specula-org) | 1 | – | 8 | 8 |
| [OpenAddressing](https://github.com/lemmy/Examples) | 1 | 1 | 5 | 6 |
| [Cahill serializable snapshot isolation](https://github.com/pron/amazon-snapshot-spec) | 1 | – | 1 | 1 |
| [MongoDB distributed transactions](https://github.com/mongodb-labs/vldb25-dist-txns) | 1 | – | 1 | 1 |
| [two_thread_mutex (Anvil)](https://github.com/anvil-verifier/anvil/blob/main/src/tla_demo.rs) | 1 | – | 1 | 1 |
| **Subtotal** | **15** | **258** | **46** | **304** |

**79 examples, 982 tasks in total.** A per-example breakdown is in
[`docs/DATASET.md`](docs/DATASET.md).

## Running

Requirements: [uv](https://docs.astral.sh/uv/) and
[Docker](https://docs.docker.com/get-docker/).
Windows users should run the benchmark through WSL2; native Windows is not supported.

### Recommended hardware

Proof checking can use substantial memory, especially for Isabelle-heavy tasks.
A few of these tasks can use significantly more than 64 GB of RAM, even when
only one job is running.

Use the following as a rough capacity-planning reference per parallel job:

| Profile | vCPUs per job | RAM per job | Guidance |
|---|---:|---:|---|
| Recommended | 8–12 | 96 GB | Provides better memory headroom. |
| Lower-headroom | 8–12 | 64 GB | A starting point; some Isabelle-heavy tasks may require more. |

On a small machine, start with `--jobs 1`. Increase the value after you
monitor peak memory use.

### Run the benchmark

```bash
git clone https://github.com/specula-org/tlaps-bench.git
cd tlaps-bench
export OPENAI_API_KEY=sk-...        # This step is optional: Codex is the default backend if no OpenAI key is provided.
uv run tlaps-bench run --filter GCD_GCD3
```

The first run builds a sandbox Docker image (tlapm, SANY, and the proof checker
bundled in) and runs the task inside it — a firewall allows only the LLM API
hosts, and the benchmarks are mounted read-only. Later runs reuse the image.
Results land in `results/<mode>/<backend>/<timestamp>/`.

Scale up, or switch task type:

```bash
# Proof-completion Core: 190 selected tasks, 4 in parallel
uv run tlaps-bench run --task-list core --jobs 4 --timeout 7200

# Full proof-completion suite: 4 in parallel, 2h timeout each
uv run tlaps-bench run --jobs 4 --timeout 7200

# Proof from scratch
uv run tlaps-bench run --mode proof-from-scratch --jobs 4
```

Each run writes `results.json` and `summary.md` (with specification pass rate as
the primary score and task-level pass rate as a secondary metric); `uv run
tlaps-bench score` (re)computes and compares scores. See the [scoring documentation](docs/USAGE.md#tlaps-bench-score)
for the grouping rule and formulas. Use `--resume` with a fixed `--output-dir` to
skip tasks already recorded as PASS, and `--force-build` to rebuild the image
after changing source.

Choosing an agent (`--backend` / `--model`) and its credentials, the full CLI
reference, and native (`--no-container`) setup are covered in the
[usage guide](docs/USAGE.md).

## Acknowledgement

We are grateful to the generous support from
* TLA+ Foundation
* OpenAI
* Anthropic (AI for Science Program)
* Qingrong Chen

## License

MIT — see [`LICENSE`](LICENSE). Third-party benchmark sources are attributed in
[`NOTICE`](NOTICE).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="pics/logo.jpg">
    <img alt="tlaps-bench" src="pics/logo.jpg" width=50%>
  </picture>
</p>

<h2 align="center">
A Benchmark of Formally Proving the Correctness of Complex Protocols and Systems using TLA+ Proof System (TLAPS)
</h2>

[![CI](https://github.com/specula-org/tlaps-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/specula-org/tlaps-bench/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Check out [TLAPS-Bench Leaderboard](https://specula-org.github.io/tlaps-bench-website/#/leaderboard).

**Our vision.** To prove the correctness of any given critical protocols and systems using [TLA+ Proof System (TLAPS)](https://proofs.tlaplus.net/doc/)

TLAPS-Bench evaluates whether AI agents can formally prove (or disprove) the correctness of complex protocols and systems using TLAPS. 

Each problem in TLAPS-Bench is a TLA+ specification (including the formal model and the invariants that specify correctness properties). AI agents are asked to prove that the formal model satisfies the invariants. We consider each task in TLAPS-Bench to formally prove one invariant of a given specification.

TLAS-Bench includes a sandboxed runtime for AI agents to faithfully prove the given specification without cheating. The runtime is equipped with extensive checks to prevent reward hacking. We have used the runtime to prove many specifications, such as [2PC](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_TwoPhase/TwoPhase.tla), [Paxos](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/Paxos/Paxos.tla), [TCP state machine](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_tcp/tcp_proof.tla), and many BFT and blockchain protocols ([Byzantine Paxos](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_byzpaxos/BPConProof.tla), [Byzantine broadcast](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_bcastByz/bcastByz.tla), etc.

**Note.** Historically, we had two types of problems: `Proof-Completion` and `Proof-from-Scratch`. We have retired `Proof-Completion` as completing a well-structured proof is no longer a challenge for frontier AI. However, `Proof-from-Scratch` tasks – which AI has to invent the entire proof structure – are still nontrivial and the proof problems take long-horizon efforts.

## Benchmark Problems

We are currently focusing on the following hard problems. 

| Problems | Type | # Spec | # Invariants |
| :---- | :---- | :---- | :---- |
| Ivy protocols ([alternating bit](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ivy_examples_alternating_bit_protocol/ivy_examples_alternating_bit_protocol.tla), [reliable broadcast](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ivy_examples_hybrid_reliable_broadcast_cisa/ivy_examples_hybrid_reliable_broadcast_cisa.tla), [split queue](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ivy_examples_split_queue_2_new/ivy_examples_split_queue_2_new.tla), [ticket](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ivy_examples_ticket/ivy_examples_ticket.tla), [nested ticket](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ivy_examples_ticket_nested/ivy_examples_ticket_nested.tla)) | Protocol | 5  | 10 |
| Cache coherence ([German](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_GermanProtocol/GermanControlBenchmarks.tla), [German Data](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_GermanProtocol/GermanData.tla), [FLASH](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_FlashProtocol/FlashWithMutex.tla)) | Protocol | 3 | 22 |
| [ZooKeeper protocol](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ZooKeeper/Zab.tla) | Protocol | 1 | 9 |
| [Cahill’s serializable snapshot isolation](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/CahillSSI/CahillSerializability.tla) | Protocol | 1  | 1 |
| [Ivy TLB](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ivy_examples_tlb/ivy_examples_tlb.tla) | System | 1  | 2 |
| [OpenAddressing](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/OpenAddressing/OpenAddressing.tla) | System | 1 | 5 |
| [B-tree](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/tlaplus_examples_btree/btree.tla) | System | 1 | 5 |
| [etcd Raft](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/etcd_raft/etcd_raft.tla) | System | 1 | 8 |
| [ZooKeeper implementation](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/ZooKeeper_LowLevel/ZkV3_7_0.tla) | System | 1 | 9 |
| [MongoDB distributed transactions](https://github.com/specula-org/TLAPS-Bench/blob/main/benchmark/proof-from-scratch-module/MongoDB/MultiShardTxnSnapshot.tla) | System | 1 | 1 |
| **Total** |  | 16 | 72 |

For more problems, check out [the full problem set](https://github.com/specula-org/TLAPS-Bench/tree/main/benchmark/proof-from-scratch-module).

## Running TLAPS-Bench

### Requirements 

* [uv](https://docs.astral.sh/uv/)  
* [Docker](https://docs.docker.com/get-docker/).   
* Windows users can run the benchmark using WSL2.

### Recommended hardware

Proof checking can use substantial memory, especially for Isabelle-heavy tasks. A few of these tasks can use significantly more than 64 GB of RAM for one job.

We recommend the following hardware configurations

| Profile | vCPUs per job | RAM per job | Guidance |
| :---- | :---- | :---- | :---- |
| Recommended | 8–12 | 96 GB | Provides better memory headroom. |
| Lower-headroom | 8–12 | 64 GB | A starting point; some Isabelle-heavy tasks may require more. |

On a wimpy machine, start with `--jobs 1`. Increase the value after you monitor peak memory use.

### Run the benchmark

```
git clone https://github.com/specula-org/tlaps-bench.git  
cd tlaps-bench  
export OPENAI_API_KEY=sk-...        # This step is optional: Codex is the default backend if no OpenAI key is provided.  
uv run tlaps-bench run --filter GCD_GCD3 # This is an example task that can be finished in seconds.  
```

The above command builds a sandbox Docker image, with `tlapm`, `SANY`, and the proof checker bundled in and runs the task inside it —- a firewall allows only the LLM API hosts, and the benchmarks are mounted read-only. Later runs reuse this image. Results are stored in `results/<mode>/<backend>/<timestamp>/`.

```  
uv run tlaps-bench run --mode proof-from-scratch --jobs 4  
```

How to set up an agent (`--backend` and `--model`) and its credentials, the full CLI reference, and native (`--no-container`) setup are described in our [usage guide](https://github.com/specula-org/tlaps-bench/blob/main/docs/USAGE.md).

## Acknowledgement

We are grateful to the generous support from

* TLA+ Foundation  
* OpenAI  
* Anthropic (AI for Science Program)  
* Qingrong Chen

## License

* [MIT LICENSE](https://github.com/specula-org/tlaps-bench/blob/main/LICENSE)  
* Third-party benchmark sources are attributed in [NOTICE](https://github.com/specula-org/tlaps-bench/blob/main/NOTICE)


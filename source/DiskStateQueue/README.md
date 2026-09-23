# TLC disk state queue

Source: [tlaplus/tlaplus](https://github.com/tlaplus/tlaplus/tree/f959b37fb8dcd62a236abb6d0ca4c1cff7c96b55/tlatools/org.lamport.tlatools/spec/queue)
at commit `f959b37fb8dcd62a236abb6d0ca4c1cff7c96b55` on
`mku-StateQueueTLA`. `DiskStateQueue.tla` and `DiskStateQueueWorkload.tla`
are copied unchanged. `upstream.json` records the source paths and SHA-256
hashes, including the upstream TLC exploration module and configuration.
The MIT license is preserved in `LICENSES/tlaplus-MIT.txt`; see `NOTICE`.

`DiskStateQueueProof.tla` adds exactly one proof-from-scratch target:

```tla
THEOREM DeadlockFreedom == Spec => []DeadlockFree
```

There is no reference TLAPS proof and no proof-completion task. Both benchmark
layouts represent the same single target; the module suite is the runner's
proof-from-scratch input.

The workload enqueues `Capacity + 1` initial entries, starts the workers, and
suspends, checkpoints, and resumes them. Each worker dequeues once, may enqueue
an arbitrary number of entries, and calls `finishAll` when its batch returns.
Recovery, repeated checkpoints, peeking, and cleaner requests are outside this
workload. The underlying model abstracts values and physical arrays to queue
occupancies while retaining pool file indices, monitor ownership, wait sets,
and per-thread control state.

`DeadlockFree` means that the workload has terminated or at least one active
thread is outside `Blocked`. It is a state predicate about notification and
monitor blocking, not an eventual-termination or starvation-freedom claim.
The target uses the upstream predicate unchanged and adds no fairness premise.

All upstream assumptions are retained: a finite thread set, a nonempty worker
set, distinct background-thread identities, positive natural `Capacity`, and
the original restore-queue and workload assumptions. `SpuriousWakeups` remains
an arbitrary Boolean, so the theorem covers both settings. No queue-occupancy,
thread-count, capacity upper bound, or execution-length bound is added to the
theorem. The `MCDiskStateQueueWorkload` module and validation configurations
are exploration aids and are not included in the benchmark task's context.

## Validation

The pinned benchmark toolchain's TLC completed the upstream bounded model:
one worker, `Capacity = 1`, `MaxQueueLoad = 3`, and
`SpuriousWakeups = FALSE`. It generated 44,886 states, found 14,805 distinct
states, and exhausted the constrained state graph at depth 66 without an error.

A second configuration uses two workers, `Capacity = 1`, and
`SpuriousWakeups = TRUE`, with no queue-occupancy constraint. Random simulation
completed 2,000 traces at depth limit 150 with seed `20260923`, checking 364,252
states without an error. Both configurations check `TypeOK`, `WorkloadTypeOK`,
`Conservation`, `DiskSafety`, `DeadlockFree`, and `Locality`.

These are bounded checks, not a proof of the parameterized theorem. The checks
use one TLC worker, a 768 MiB heap, and at most two JVM-visible processors.
Reproduce from the repository root after installing the pinned toolchain:

```sh
timeout 60s java -XX:ActiveProcessorCount=2 -Xmx768m -XX:+UseParallelGC \
  -DTLA-Library=source/DiskStateQueue -cp lib/tla2tools.jar tlc2.TLC \
  -workers 1 -metadir /tmp/disk-state-queue-bfs \
  -config source/DiskStateQueue/validation/MCDiskStateQueueWorkload.cfg \
  source/DiskStateQueue/MCDiskStateQueueWorkload.tla

timeout 60s java -XX:ActiveProcessorCount=2 -Xmx768m -XX:+UseParallelGC \
  -DTLA-Library=source/DiskStateQueue -cp lib/tla2tools.jar tlc2.TLC \
  -workers 1 -simulate num=2000 -depth 150 -seed 20260923 \
  -metadir /tmp/disk-state-queue-simulation \
  -config source/DiskStateQueue/validation/TwoWorkersSpurious.cfg \
  source/DiskStateQueue/DiskStateQueueWorkload.tla
```

Regenerate the single target and module suite with:

```sh
uv run python -m dataset.proof_from_scratch.generate --filter /DiskStateQueue/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
uv run python -m dataset.proof_from_scratch.module_tasks --verify
```

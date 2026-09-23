# LLVM libomp barrier and tasking

This group adds one proof-from-scratch module with four safety targets:

| Target | Requirement |
|---|---|
| ActiveTasksImplyActiveTeam | Executing tasks retain an active parallel task team or a live owning serial region. |
| NoQueuedTasksAfterDeactivation | A retired parallel task team has no queued work or unfinished proxy bottom halves. |
| ParityConsistency | Threads working in the same barrier agree on the parallel task-team slot. |
| ParityRestoredAfterCancel | After cancellation has returned every thread, their task-team slots agree. |

Each goal is `Spec => []Property`. These are safety properties; the module does
not claim starvation freedom or eventual barrier completion.

## Origin and scope

The source is adapted from Specula's libomp case study. `upstream.json` pins the
original model and the LLVM implementation used by that study. It retains
per-thread program counters, task identities and parents, task stealing,
detachable tasks, external completion, cancellation, two task-team slots,
serialized nested parallel regions, and team/thread teardown.

This is a **repaired model**, including a correction to the recorded proxy-task
termination race. It is not a proof of the unmodified LLVM revision. The
implementation and historical bug report justify the modeled mechanisms; the
operational repairs below are explicit benchmark changes.

The model assumes finitely many natural-number thread IDs containing the primary
thread 0, a finite task set, a distinct sentinel, and an arbitrary natural-number
barrier-round limit. The proof task does not fix the thread/task counts or the
number of rounds to a model-checking instance. Task identities form a finite pool
within one execution and are not recycled after completion, as in the source
case study. CPU memory-order effects, barrier-tree topology, and task-dependency
hash tables are outside this abstraction.

## Repairs

- **Completion accounting.** A task records its implicit-task root. That root
  retains a completion obligation for every descendant until it finishes or is
  cancelled. Proxy obligations remain outstanding through bottom-half completion.
  A thread may mark itself finished after a failed local search only when its
  root has no outstanding obligations. This represents corrected termination
  bookkeeping and closes the enqueue/completion gap; it does not add the target
  invariants as transition guards.
- **Serial contexts.** A nested serial team's slot 0 is distinct from the parent
  team's slot 0. Its queued work is local to that serial region, and leaving the
  region waits for its live tasks. The active-team target checks both contexts.
- **Cancellation.** Unstarted tasks can be cancelled; executing/detached work
  drains before its root leaves the cancelled barrier. Normal task-team waiting
  is skipped after cancellation. Per-invocation thread completion flags are reset
  before the next barrier.
- **Retirement versus initial inactivity.** The original queue predicate fails
  after a single legal pre-barrier enqueue because the task team is initially
  inactive. The repaired property checks actual retirement, recorded until the
  slot opens for a later barrier, and includes pending proxy cleanup.
- **Adversarial read.** The explicit `StealFromReapedThread` bug-injection action
  is excluded from the normal transition relation; regular stealing and teardown
  remain modeled.

The source implementation checks incomplete children before decrementing the
unfinished-thread counter (`kmp_tasking.cpp:3317–3331`), reactivates a finished
stealer before publishing the deque removal (`3109–3132`), and splits proxy
completion into enqueue/top-half/bottom-half stages (`4210–4364`). The repaired
root accounting keeps those completion obligations live across that split.

## Validation

A complete TLAPS reference proof is in `tests/fixtures/libomp/reference/`.
It establishes initialization, preservation by all 29 actions and stuttering,
and the four temporal goals. The reference uses the same parameter domains as
the benchmark, with no fixed thread/task counts or model-checking state bounds.
Its dependency manifest requires checking every proof module with `--strict
--nofp`; imported lemmas are independently checked, rather than assumed valid.

The proof files are outside the generated task context. The benchmark exposes
the model, the four goal statements, and empty proof regions.

`tests/dataset/test_libomp.py` also checks three complete finite instances,
a 31-state normal/proxy/serial/cancellation lifecycle, pre-activation enqueue,
invalid domains, and five negative controls. Removing pending-work accounting,
releasing proxy credit early, deactivating prematurely, restoring the wrong
serial slot, or toggling on cancellation must reproduce an invariant violation.

Run all model controls and the complete reference proof with:

```sh
uv run pytest -q tests/dataset/test_libomp.py
```

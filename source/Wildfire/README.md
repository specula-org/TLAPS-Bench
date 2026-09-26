# Wildfire verification challenge

This adds one hard proof-from-scratch task for a **repaired** Wildfire
cache-coherence protocol:

```tla
THEOREM Refinement == TraceSpec => AlphaModel!Spec
```

`WildfireProof.tla` instantiates both the repaired concrete protocol and the
original Alpha memory specification with the same request/response recorder.
The goal retains Alpha's existential initial memory,
temporal hiding of `reqSeq` and `beforeOrder`, and liveness requirement. There is
no fixed refinement mapping, reference proof, or proof-completion task. The
theorem is an open proof obligation, not an established correctness result.

## Source and scope

The source is the [Wildfire challenge](https://lamport.azurewebsites.net/pubs/wildfire-challenge.pdf)
by Leslie Lamport, Madhu Sharma, Mark Tuttle, and Yuan Yu. The five specification
modules are pinned to `pron/wildfire-challenge` commit
`bf02363fa9bc3e9e81124d372ffd86bbd14ecbf8`. `upstream.json` records original and
imported SHA-256 hashes; `UPSTREAM-README` preserves the original attribution.
The obsolete bundled standard modules are replaced by the benchmark toolchain's
standard library. No upstream license declaration is present at this revision;
see the repository's `NOTICE`.

The benchmark keeps the two-level switch network, non-FIFO control queues,
separate data fills, memory barriers, LL/SC, evictions, shadow mode, and original
fairness conditions. Processor count is finite but unbounded; address count and
queue lengths have no benchmark bound. `DataLen` remains any positive natural.
The published models retain their request/response parameters. The theorem
wrapper supplies the explicit observation interface described below.

## Repairs

`repairs.patch` records all changes to the five upstream modules.

1. **LL/SC request ordering.** Preserve program order among both LL and SC
   operations, including different addresses. Otherwise `LL a; LL b; SC a`
   can return a successful SC without an Alpha-valid matching LL.
2. **Shadow entry.** Include outgoing invalidations as well as forwarded gets
   when a local request creates remote probe traffic. Otherwise local traffic
   can bypass an outstanding remote invalidation.
3. **Probe ordering.** In `GSToLS`, a Q0 directory request must follow an older
   invalidation or forwarded get. Without this additional ordering, the
   message-passing litmus can return a stale value after its memory barrier.
   This clause concerns requests, not Q1 replies, which already have an
   ordering rule.
4. **Victim shadow clearing.** Preserve shadowing while a remote victim ack
   travels through the global switch, as the upstream comment requires.
   Keep the original global-switch route for a local victim ack in shadow
   mode as well: sending it directly can discard a cache version before an
   older forwarded get arrives. This repair reconciles routing with the
   documented intent; it is not claimed as a fourth independently demonstrated
   violation of observable Alpha behavior.

Additionally, `ProcessorHomes` and `AddressHomes` state the intended topology:
each processor and address maps to a member of `LS`. Existing assumptions are
named without changing their formulas. Tuple binders in `Wildfire` are rewritten
using one bound location and tuple projections, and the single tab is expanded,
so imported modules load in the pinned TLAPM. The invalidation branch uses an
explicit empty-version `IF` before accessing the newest cache version. Trailing
whitespace is removed. These compatibility edits do not introduce state bounds.

The two unproved upstream type/message-invariance theorems are removed from
dependencies. Their predicate definitions remain available, but the task does
not silently assume those theorems.

## Interface contract and scope

The official archive was downloaded from [Lamport's challenge page](https://lamport.azurewebsites.net/tla/wildfire-challenge.html)
on 2026-09-26. All five specification modules are byte-identical to the pinned
mirror; the archive hash is recorded in `upstream.json`.

The published `AlphaInterface.tla` leaves the representation of `aInt` and the
request/response actions unspecified. Its comments treat them as the observable
issue/delivery events. `InnerAlpha.Liveness` requires every non-MB request to
receive a response. `Wildfire.Liveness` expresses the same intended progress
using weak fairness. The concrete `Next` has no arbitrary message-loss action.
Delayed and out-of-order delivery are modeled; packet-loss tolerance is not.

To state a definite benchmark, the wrapper uses an **unbounded, lossless event
history** as the interface representation:

```tla
RecordRequest(old, new, p, r) ==
    new = Append(old, [kind |-> "request", proc |-> p, value |-> r])
RecordResponse(old, new, p, r) ==
    new = Append(old, [kind |-> "response", proc |-> p, value |-> r])
```

Both named instances explicitly substitute these operators. `TraceSpec` starts
with an empty history and otherwise uses the repaired protocol's full `Spec`.
A response can always be recorded, but its actual delivery still requires a
protocol step and the original fairness. The history records observable event
order; it does not fix Alpha's hidden `beforeOrder` or impose sequential
consistency on memory execution. Client programs, processor counts, address
sets, request counts, and history/queue lengths are not fixed to a TLC instance.

This is a benchmark-defined instance of the official interface parameters,
**not an upstream-endorsed correction or a proof for every possible callback
implementation**. The wrapper extends `Wildfire` to retain its declarations and
assumptions; the inherited abstract callback parameters are explicitly replaced
in both scored instances. Tests set those unused parameters to `FALSE` and
still exercise real request/response histories.

The earlier unrestricted goal fails when `ResponseToEnv` permanently refuses
responses: a fair concrete execution can queue a response and stutter forever,
whereas Alpha requires its delivery. The interim repair at `0de5aac0` added
`[]ResponseReceptive`. The current goal removes that premise and supplies a
concrete recording interface instead. This makes the observable contract
explicit rather than silently quantifying over hostile callback definitions.
It does not claim equivalence to that interim theorem for arbitrary interfaces.
A generalization to interfaces with backpressure would need a separate
interface-abstraction/progress argument; no such result is assumed here.

## Validation and limits

The regression suite checks the source and both generated layouts with the
pinned TLC toolchain:

| Check | Distinct states | Scope |
|---|---:|---|
| LL/SC ordering | 305 | One processor, two addresses, fixed three-request program |
| Shadow entry | 4,432 | Three processors, two addresses, staged and pruned litmus |
| Probe ordering | 20,405 | Two processors, two addresses, staged and pruned litmus |
| Victim ack routing | 2 per case | Local transition checks for local/remote and shadowed/unshadowed cases |
| Permanently blocked abstract interface | 9 | Reproduces the old unrestricted goal's liveness failure |
| Recorded local read | 13 | Records both the issued request and its delivered response |

The recorded-interface controls run on the source and both generated layouts,
with local/remote memory and read-only/LL-SC-MB client programs. They check legal
history entries, request completion, and that the restricted test behaviors
satisfy the actual `TraceSpec`. A separate reachability control witnesses a
recorded response. Removing response-send fairness makes completion fail even
though recording remains enabled. These controls do not add a progress premise.

All three litmus checks use one-bit data. Sentinel overrides are confined to
the TLC fixtures. Restoring old ordering reproduces each forbidden history.
The shadow-entry negative control restores both the shadow-entry and probe
ordering rules because either repair can block this particular witness; it
does not establish independent necessity of both repairs.

The shadow/probe checks restrict the environment and transition relation. Their
clean results cover those restricted state graphs, not all executions of the
programs. An additional unpruned two-processor exploration was stopped at its
60-second budget without a reported violation; it did not exhaust the graph.
None of these checks proves the full parameterized refinement, temporal hiding,
or liveness. No proof-generation experiment is required for inclusion.

The first run at `ff2da4d7` stopped with the interface counterexample and 0/1
target proofs. The interim run at `0de5aac0` checked eight helper lemmas but
remained 0/1, with temporal hiding unresolved. Those results belong to different
statements and are not results for the recorded-interface task.

Both SANY and TLAPM load the task and its exact context. The per-theorem
`PROOF OBVIOUS` placeholder fails its obligation; the module task retains its
unresolved proof region. TLAPM reports that the parameterized Alpha instance's
axioms are hidden, so a future proof must derive any needed instantiated facts
from the concrete assumptions.

**The full target is currently tool-blocked on the pinned TLAPM:** independent
minimal probes could not establish even `\EE x : TRUE`; Zenon, SMT, and Isabelle
reported unsupported expressions, and PTL did not discharge it. The interface
instantiation does not remove this operator from Alpha. Loading and finite
regressions are not a complete proof or evidence of supported temporal hiding.
See [PROOF_PLAN.md](PROOF_PLAN.md) for the feasibility gate and proof milestones.

```sh
uv run pytest -q tests/dataset/test_wildfire.py
uv run python -m dataset.proof_from_scratch.generate --filter /Wildfire/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
uv run python -m dataset.proof_from_scratch.module_tasks --verify
```

The model-checking fixtures stay under `tests/fixtures/wildfire/` and are absent
from the benchmark context. Run the task with `--mode proof-from-scratch
--filter Wildfire/WildfireProof.tla`.

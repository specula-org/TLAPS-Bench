# Wildfire verification challenge

This adds one hard proof-from-scratch task for a **repaired** Wildfire
cache-coherence protocol:

```tla
THEOREM Refinement ==
    (Spec /\ []ResponseReceptive) => AlphaModel!Spec
```

`WildfireProof.tla` extends the concrete protocol and instantiates the original
Alpha memory specification. The goal retains Alpha's existential initial memory,
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
The environment's request/response operators remain parameters of both models.
The theorem requires an environment that remains able to accept every legal
response, as specified below.

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

## Response environment premise

The original benchmark goal `Spec => AlphaModel!Spec` is false when the
unspecified `ResponseToEnv` operator permanently refuses responses. A
one-processor, one-address instance can accept a read, finish it internally,
queue its response, and stutter forever. `ProcSendResponse` is disabled, so
its weak fairness requirement is satisfied. Alpha must record the accepted
request, but cannot set its `responded` field to `TRUE` because its own
`SendResponse` also requires `ResponseToEnv`. This contradicts Alpha's
unconditional per-request liveness requirement.

The theorem wrapper now states an explicit interface premise:

```tla
ResponseReceptive ==
    \A p \in Proc, r \in Response :
        ENABLED ResponseToEnv(aInt, aInt', p, r)
```

`[]ResponseReceptive` means that at every state the environment permits some
interface successor for each legal response. It says nothing about protocol
queues, completed requests, or whether an enabled response is actually sent.
Protocol progress must still follow from the concrete actions and fairness.
Neither `Wildfire!Spec` nor `Alpha!Spec` is changed by this repair, and Alpha's
safety, temporal hiding, and liveness requirements remain the conclusion.

This corrects the original interface comment's claim that arbitrary environment
operators need no extra assumptions: that claim is insufficient for the full
liveness refinement. The new premise is part of the task statement and fixed
context, not an assumption a submitted proof may add.

## Validation and limits

The regression suite checks the source and both generated layouts with the
pinned TLC toolchain:

| Check | Distinct states | Scope |
|---|---:|---|
| LL/SC ordering | 305 | One processor, two addresses, fixed three-request program |
| Shadow entry | 4,432 | Three processors, two addresses, staged and pruned litmus |
| Probe ordering | 20,405 | Two processors, two addresses, staged and pruned litmus |
| Victim ack routing | 2 per case | Local transition checks for local/remote and shadowed/unshadowed cases |
| Permanently blocked response environment | 9 | Reproduces the old goal's liveness failure and violates the new premise |
| Receptive response environment | 13 | Completes the read under the original fairness; the premise holds throughout |

The response-environment checks run on the source and both generated layouts.
Removing response-send fairness makes the receptive control violate liveness
again. This verifies that the new premise alone does not guarantee progress.

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

The first run at `ff2da4d77875389563c4b920df036a0b381594c4` stopped with this
environment counterexample and 0/1 target proofs. Its inputs and results remain
separate from reruns of the repaired statement; it is evidence of an invalid
old goal, not evidence of the corrected goal's proof difficulty.

Both SANY and TLAPM load the task and its exact context. The per-theorem
`PROOF OBVIOUS` placeholder fails its obligation; the module task retains its
unresolved proof region. TLAPM reports that the parameterized Alpha instance's
axioms are hidden, so a future proof must derive any needed instantiated facts
from the concrete assumptions. Loading is not evidence that all eventual
temporal proof steps are supported by the current backends.

```sh
uv run pytest -q tests/dataset/test_wildfire.py
uv run python -m dataset.proof_from_scratch.generate --filter /Wildfire/ --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
uv run python -m dataset.proof_from_scratch.module_tasks --verify
```

The model-checking fixtures stay under `tests/fixtures/wildfire/` and are absent
from the benchmark context. Run the task with `--mode proof-from-scratch
--filter Wildfire/WildfireProof.tla`.

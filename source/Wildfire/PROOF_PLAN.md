# Wildfire proof plan

## Goal and interpretation

Prove the single benchmark goal:

```tla
THEOREM Refinement == TraceSpec => AlphaModel!Spec
```

`TraceSpec` uses the repaired protocol and an initially empty, unbounded history
of request/response events. The Alpha instance uses the identical observation
interface. Its initial-memory existential, temporal hiding of `reqSeq` and
`beforeOrder`, value/order/LL-SC constraints, and per-request liveness all remain.
There is no supplied invariant, fixed refinement mapping, bounded queue, fixed
client program, or assumed response-completion property.

The published interface explicitly leaves its representation open. The recorder
is our concrete choice within that interface, not a claim that the authors have
endorsed these repairs. The official model contains delayed/reordered messages
and fairness, but no arbitrary packet-loss action. Adding loss/retry/backpressure
would be a separately specified extension, not a prerequisite for this goal.

One interpretation question remains for the original authors: is
`ResponseToEnv` intended only to record a memory-output event, or may it disable
that output? If the latter, what environment/fairness contract was intended for
full Alpha refinement? No upstream answer is currently claimed. The recorder
is an explicit, reviewable benchmark choice while that question remains open.

## Current evidence

- The official archive's five specification files match the pinned mirror byte
  for byte; hashes are in `upstream.json`.
- Protocol fixes have positive/negative finite litmus checks. The victim-routing
  adjustment has local transition tests, not a fourth independent Alpha witness.
- The recorded interface is exercised through the actual named instance, in
  source and both generated layouts. Receptiveness is checked as a consequence
  of the recorder, not supplied as a theorem premise. Fairness-removal controls
  still violate progress.
- The `ff2da4d7` experiment found the unrestricted-interface counterexample.
  The `0de5aac0` experiment checked eight helper lemmas but proved 0/1 targets.
  Neither result is a proof or measurement of this revised goal. Some helper
  statements may be reusable after substituting the recorded instance, but
  every reused proof must be checked again.
- The pinned TLAPM reports version `4600b24`. Independent probes of
  `\EE x : TRUE` failed in all four tested routes: Zenon, SMT, Isabelle, and
  PTL. This is a checker-feasibility issue, not evidence that the theorem is
  false or that an agent lacks reasoning ability.

## Milestones and acceptance criteria

| Stage | Work | Required result before proceeding |
|---|---|---|
| 1. Checker feasibility | Establish a sound path for temporal-existential introduction and the required history-variable/refinement rules. Inspect supported releases/rules or build a narrowly scoped prototype. | At least one trusted route proves true hiding/witness examples and rejects false controls; any added rule has a justified soundness argument. A parser-only pass or a hard-coded successful receipt is insufficient. |
| 2. Concrete invariants | Develop typing, cache-version ownership, message/queue ordering, shadow-loop, memory-value, and LL/SC pairing invariants. | Initialization and preservation by every concrete action and stuttering are independently checked. TLC helps find defects but is not the proof. |
| 3. Abstract witness | Construct `reqSeq` and `beforeOrder` witnesses consistent with the complete observed history. Establish Alpha initialization, value/ordering axioms, and step simulation. | A single globally coherent abstract behavior, not independently chosen witnesses for each bounded prefix. Any auxiliary history/prophecy construction must preserve the concrete behaviors and be checked. |
| 4. Progress | Prove requests advance through queues, fills, shadow handling, barriers, retirement, and response delivery under the original weak fairness. | Every non-MB request eventually receives its matching response. Derive recorder availability; do not assume this conclusion or strengthen scheduler fairness silently. |
| 5. Full refinement | Combine the witnesses and progress argument; discharge initial-memory choice and temporal hiding. | The unchanged full target checks with no omitted obligations, additional axioms, altered context, or finite-instance restriction. |
| 6. Independent replay | Freeze source, proof, toolchain, and all dependency hashes; run a cold authoritative check. | All target dependencies are trusted, canonical inputs match, and a reproducible complete result is saved. |

## Tooling gate and budgets

Stage 1 is currently blocked. Start with one bounded feasibility investigation,
not another full eight-hour proof-generation attempt against unchanged tools.
Record the exact failing obligations and the proposed trusted rule or backend.
If a sound route is not available, retain this as a Draft, tool-blocked challenge;
do not turn repeated unsupported-operator failures into model-failure scores.

A temporal prover outside TLAPS could supply a formally checked bridge, but
that would be a mixed-prover result until the benchmark checker verifies that
bridge and its input correspondence. It must not be reported as a pure TLAPS
PASS. The current helper contract also disallows new top-level variables and
non-catalog imports: settle the admissible witness construction in stage 1,
before producing a large proof that cannot be submitted.

Once stage 1 passes, start one `gpt-6-astra` / `max` attempt on the exact revised
head, one module at a time, with an eight-hour agent budget and one-hour checker
budget. Preserve the session and partial artifacts. Review the first checked
vertical slice before allocating further rounds; report proof, tooling, model
defect, and budget outcomes separately. Changed statements/toolchains get new
run identities rather than resuming either historical result directory.

Stages 2–4 can be organized as incremental checked lemmas, but those milestones
remain partial progress. Only stages 5–6 establish the benchmark result. No cost
or completion-time prediction follows from the two early experiments.

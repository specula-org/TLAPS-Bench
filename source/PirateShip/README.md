# PirateShip consensus

This proof-from-scratch module contains eleven safety targets derived from
[PirateshipOrg/pirateship-tla](https://github.com/PirateshipOrg/pirateship-tla/tree/19096c1de2f87c68a21311c9100a5bab423caa0e).
The original `pirateship.tla` is preserved byte-for-byte under `upstream/`.
`upstream.json` pins its commit and SHA-256 and records the adapted model hash.
`prepare.py` applies six exact, reviewable replacements from
`tlaps-compatibility.json` to produce `PirateShip.tla`.

**Draft merge prerequisite:** the pinned TLA+ repository contains no license
file or source-level license grant. Permission to redistribute this material
must be clarified before merge. The separate Rust implementation's MIT license
is not used as evidence of a license for these TLA+ files. See `NOTICE`.

## Model and theorem scope

The source models ordered, reliable pairwise message channels, normal proposal
and voting, view changes, quorum certificates, and two Byzantine action families:
entry omission and leader equivocation. These actions share a natural-number
`MaxByzActions` budget. That parameter remains symbolic; its value of two in
some validation configurations is not a theorem assumption.

The theorem retains the original `Init`, `Next`, and `Fairness`. No loss,
reordering, retransmission, crash/recovery implementation detail, or additional
Byzantine action is introduced. The model supports crash-fault reasoning through
its scheduling abstraction; it does not contain an explicit crash/restart state
machine. No implementation refinement or unrestricted Byzantine-fault-tolerance
claim is made.

The primary protocol obligations are:

| Target | Meaning |
|---|---|
| `BranchInvCorrect` | Committed branches are comparable prefixes while no Byzantine action has occurred. Empty view-stabilization batches receive the upstream treatment. |
| `CommittedBranchAppendOnlyPropCorrect` | Each replica preserves its committed nonempty batches under the upstream before-fault condition. |
| `AuditBranchInvCorrect` | Correct replicas have comparable audited prefixes. |
| `AuditedBranchAppendOnlyPropCorrect` | Correct replicas preserve their audited prefixes over transitions. |

The other seven goals preserve upstream's type, index-bound, leader-uniqueness,
branch-shape, view-monotonicity, view-stabilization, and audit-index-monotonicity
checks. They are explicit proof obligations, not supplied facts. All eleven
proofs are omitted, with no supplied inductive strengthening or reference proof.
The three `Prop` goals are temporal safety properties, not liveness goals.

`CR` is the entire replica set before the first Byzantine action and the honest
replicas afterward. The conditional committed-branch goals do not promise
committed agreement after an attack; audited-prefix goals cover that modeled
case. Audit-index monotonicity is retained as a supporting obligation, not
claimed to add an independent end-to-end guarantee beyond audited-prefix
preservation and appropriate index/typing facts. The module is the evaluation
unit; eleven goals should not be read as eleven unrelated hard problems.

## Explicit parameter contract

All upstream assumptions are retained. Three premises are added and named:

- `ReplicaSetFinite`: `IsFiniteSet(R)`, for replica enumeration and cardinality.
- `DistinguishedTransaction`: `1 \in Txs`, because the upstream equivocation
  action replaces a transaction by `1`.
- `ByzantineBudgetNatural`: `MaxByzActions \in Nat`.

These premises restrict the source's parameter contract and are not represented
as equivalent rewrites. In particular, the original model permits `Txs = {2}`:
a Byzantine initial leader can send transaction `2` and then equivocate to `1`,
violating `TypeOK` in two transitions. The regression suite reproduces this on
the unchanged upstream source. The adapted source and both generated layouts
reject that parameter domain before state exploration, while positive
configurations with `Txs = {1,2}` execute the Byzantine actions.

No bound on replica count, transaction count, view numbers, branch lengths, or
execution length is added to the proof tasks. `Txs` is not required to be finite.

## Recursive-function adaptation

`RUnanimity(i,S)` becomes a curried recursive function: its first domain is
`0..Len(b)` and each value is a function on `SUBSET R`. The result at `i=0` maps
every accumulated voter set to `{0}`. The recursive branch decreases `i` by one
and indexes the preceding function with the union of accumulated and current
votes. `UnanimityScan` exposes this function; `HighestUnanimity` selects its
original result at `Len(b)` and `{}`.

`RMaxQuorum(i)` becomes a recursive function on `default..Len(b)`, with the same
base value and quorum predicate. `QuorumScan` exposes it and `MaxQuorum` selects
its original result. Its intended call domain requires
`default \in 0..Len(b)`; the conversion does not establish that all protocol
calls satisfy this condition. That remains part of the protocol proof.

The two recursions are well founded because their natural index decreases to
the lower bound. The vote-set argument stays in `SUBSET R` when the branch
votes and replica identity satisfy their declared domains. The curried form
avoids recursive operators and tuple binders in the proof context.

`tests/fixtures/pirateship/RecursionProof.tla` uses the pinned
`NaturalsInduction!FiniteNatInductiveDef` theorem to establish both actual scan
unfolding equations, their boundary values, and voter-set closure. The fixture
is a compatibility regression, is outside the source/benchmark context, and
supplies no protocol proof to a task. Finite comparisons against the original
recursive operators check lengths zero through three, all voter-set sequences
for three replicas, and quorum/default/acknowledgment boundary cases. These
comparisons supplement the unfolding proofs; they are not a universal
machine-checked equivalence certificate between the two TLA+ encodings.

## Validation

The regression suite checks:

- The original two-transition transaction-domain counterexample, rejection by
  the adapted source and both generated layouts, and invalid action budgets.
- Recursive-operator/function agreement on the finite input family above.
- TLAPS recursion obligations in both source and generated module contexts.
- A 28-transition scenario reaching audited prefixes and preserving them over
  a view change, with audit progress checked before and after the change.
- A 31-transition scenario exercising equivocation, a view change, and entry
  omission, then reaching nonempty audited prefixes at every honest replica. Both scenarios check every selected property and `Init /\ [][Next]_vars`
  against the actual source and generated models. Fixture fairness ensures the
  prescribed schedule completes; it is not a protocol liveness proof.
- Complete constrained exploration of a three-replica crash-fault instance
  (813 distinct states) and a four-replica Byzantine instance (12,926 distinct
  states). The former allows one view change and one batch; the latter allows
  two Byzantine actions and two batches in view zero. Both bound each channel
  to one queued message and use `Txs = {1,2}`. Longer audit and view-change paths
  are covered by the separate scenarios, not these small state spaces.

These checks do not certify the eleven unbounded theorems or establish a model
solve rate. The upstream green CI is also bounded: its exact-head crash check
stopped at ten minutes with 407,244 queued states remaining; the Byzantine job
used random simulation. Its result is not described as exhaustive verification.

After installing the repository's pinned toolchain, run:

```sh
python3 source/PirateShip/prepare.py --check
uv run pytest -q tests/dataset/test_pirateship.py
uv run python -m dataset.proof_from_scratch.generate --filter /PirateShip/PirateShipProof.tla --allow-no-proof --layered
uv run python -m dataset.proof_from_scratch.module_tasks
uv run python -m dataset.proof_from_scratch.module_tasks --verify
```

`validation/SmallPirateShip.tla` and the two `.cfg` files reproduce the small
model checks with `lib/tla2tools.jar`, `lib/community` on `TLA-Library`, and
`source/PirateShip` on the module search path. None of their state constraints,
configuration assignments, or test fixtures is bundled into a proof task.

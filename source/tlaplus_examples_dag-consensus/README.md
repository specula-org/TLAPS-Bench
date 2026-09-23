# Sailfish proof-task validity

The task retains three goals: `Spec => []TypeOK`, `Spec => []Agreement`, and
`Spec => []Liveness`. No goal was weakened, removed, or supplied with a proof.

## Confirmed defects

The inputs used by the September 23 experiment admit two reachable violations.

- Agreement: with four nodes, one Byzantine node, and ordinary three-node
  quorums, a 16-transition trace commits `<<a, 1>>` and later replaces one
  correct node's log with a history starting at `<<d, 1>>`. The Byzantine
  round-2 leader omitted its predecessor without obtaining a no-vote certificate.
  The model checked this rule for correct leaders but admitted the Byzantine
  vertex into the shared DAG without the same certificate validation.
- Liveness: the abstract quorum assumptions permit non-monotone quorum sets.
  With five nodes and quorum bases `{a,b,c}`, `{b,c,d,e}`, and all five nodes,
  a valid 11-transition trace reaches round 3 without committing the correct
  round-1 leader: adding a Byzantine vote makes the voters cease to be a quorum.
  Ordinary cardinality/weight threshold quorums do not have this behavior.

The original complete dependency bundle was model-checked independently. Both
violations recur without modifying its state machine, invariants, or assumptions.
These are faults of the proof task, not evidence that the targets are too hard.

The follow-up proof attempt exposed a third defect: `LeadersAreNodes` was stated
only in `BlockDag`, whose assumptions do not become assumptions of `Sailfish`
through `INSTANCE`. A single correct node can reach round 3 with an empty log
when every leader is outside `N`, violating Liveness for round 1. The source and
both generated layouts now state `RoundLeadersAreNodes` in the model itself.
This makes explicit the leader domain already required by `BlockDag`; it does
not exclude Byzantine leaders or change any target theorem.

## Repair and protocol evidence

1. State quorum upward closure explicitly. This narrows admissible quorum
   systems to ones where a superset of a quorum remains a quorum.
2. Validate a Byzantine leader before admitting its vertex: it must reference
   its predecessor or have a quorum of no-votes. This excludes the invalid
   leader behavior while retaining both valid admission paths. The PlusCal
   source and its generated translation carry the same guard.
3. Express `Linearize` as a recursive function over vertices of the fixed DAG.
   Each recursive call chooses a smaller-round ancestor; Genesis returns the
   empty sequence. The previous function domain included arbitrary pairs of
   vertex/edge subsets, including disconnected structures without Genesis.
   Keeping the DAG fixed preserves the causal histories of valid DAGs and avoids
   requiring a recursive value on those invalid subgraphs. It also removes the
   multiple-argument function binder from this definition.

The protocol requires a leader that omits its predecessor to carry a no-vote
certificate. See the [authors' protocol explanation](https://decentralizedthoughts.github.io/2024-05-23-sailfish/)
and the implementation's [header validation](https://github.com/nibeshrestha/sailfish/blob/1af06a98bc07c49c99e23971b5e2b2b95adbf87f/primary/src/core.rs#L243).
The latter checks predecessor references and verifies the leader's certificate
before storing the header and voting for it. Its
[certificate checks](https://github.com/nibeshrestha/sailfish/blob/1af06a98bc07c49c99e23971b5e2b2b95adbf87f/primary/src/messages.rs#L358)
use weight thresholds, which are upward closed. The repair follows the existing
abstract model's representation of no-votes by same-round vertices without a
predecessor reference; it does not add a new message-level protocol model.

## Validation

`tests/dataset/test_sailfish_validity.py` runs nineteen regression checks. They replay
both original violations, verify rejection of the bad quorum parameters, reach
normal commits on corrected traces, distinguish sufficient and insufficient
no-vote certificates, compare old/new causal histories on a branching DAG, and
check that all three task statements remain unchanged. Removing either semantic
fix independently reproduces its corresponding invariant violation.

For the leader-domain repair, all three layouts (source, layered theorem task,
and module task) reject an outside leader before initialization, reproduce the
Liveness violation when only the new assumption is removed, and reach a normal
commit with a valid leader. These controls explore all four reachable states
of the one-node, three-round configuration.

Additional exhaustive TLC configurations completed without an invariant violation:

| Configuration | Distinct states |
|---|---:|
| Original Agreement scenario with repaired admission | 238 |
| Agreement scenario with a valid Byzantine leader | 6,838 |
| Liveness scenario with upward-closed quorums | 230,432 |
| Three nodes, four rounds, before GST | 34,332 |
| Three nodes, four rounds, after GST | 5,138 |
| Four nodes, three rounds, after GST | 4,178 |

The first three configurations retain the counterexample-search constraints;
the last three explore all transitions of their finite configurations. These
checks validate the repair in finite instances; the unrestricted proofs remain
the benchmark's task.

Regenerate the layered Sailfish corpus using the repository generator, then emit
its module task with `dataset.proof_from_scratch.module_tasks`. Both generated
forms must retain the same three proof-unit IDs and empty proof regions.

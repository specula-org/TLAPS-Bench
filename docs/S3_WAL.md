# WALs on S3 proof tasks

Three modules import Jack Vanlightly's simplified protocol models at
[`06d5cc60990cf8e5995dc56f28e5d56128eca227`](https://github.com/Vanlightly/s3-wal-collection/tree/06d5cc60990cf8e5995dc56f28e5d56128eca227).
Each selected target is `Spec => []Property`, with no supplied reference proof.
The module tasks allow shared helper definitions and proofs across their goals.

| Group | Source wrapper | Safety targets |
|---|---|---:|
| SlateDBWAL | `source/SlateDBWAL/SlateDBWALProof.tla` | 4 |
| OSWALD | `source/OSWALD/OswaldProof.tla` | 3 |
| Walgit | `source/Walgit/WalgitProof.tla` | 7 |

These are fourteen proof targets, including three type invariants; they are not
fourteen independent protocol mechanisms. The predicates and their overlaps
are retained from the upstream default safety configurations.
SlateDB's additional `UniqueEpochs` predicate is not selected because it is not
enabled upstream. Liveness properties are outside this addition.

## Theorem domains and scope

The proof wrappers make the upstream model-value conventions explicit:
process and value sets are finite, the writer/replica set is nonempty, control
labels are distinct, and absence sentinels cannot collide with the values or
object types against which the protocol compares them. No fixed number of
writers, replicas, garbage collectors, or values is a theorem assumption.
The default configurations are retained under each source group's
`validation/` directory.

The upstream workload permits each payload value to be proposed at most once.
The finite value set is arbitrary in a proof task, but an individual configured
execution can propose only finitely many values. The benchmark preserves this workload and
the upstream S3 conditional-write abstraction. It does not model the storage
service's implementation or certify the complete products bearing these names.
SlateDB replaces an LSM flush with a state-machine snapshot. Walgit omits
ambiguous CAS failures, explicit crashes, and collection of old committed log
segments. The upstream notes are retained beside each source model.

## Walgit manifest correction

The upstream `ValidManifest` requires a remaining log segment ending at
`headSeq`. This is false in the initial empty manifest, and after a checkpoint
covers the complete committed history and removes its segment references.

The corrected conjunct defines `cpSeq` as zero without a checkpoint and the
checkpoint sequence otherwise. It requires `cpSeq <= headSeq`; a segment must
end at `headSeq` when `cpSeq < headSeq`. Segment non-overlap, the existing
segment-bound condition, and equality of the head with the maximum committed
sequence remain unchanged. `ManifestRepresentsCommittedState` still requires
reconstruction of all committed entries from the checkpoint and log segments.
This predicate correction does not change protocol actions.

This corrects an overstrong false predicate; it is not a logically equivalent
rewrite of that predicate. The change admits the legitimate empty and fully
checkpointed states while retaining the intended head-coverage requirement.

OSWALD also has a stray `|` after its module terminator. Removing that trailing
character makes the source compatible with the benchmark's module-boundary
integrity check and changes no TLA+ definition.

## Explicit action priority

SlateDBWAL and Walgit use overlapping `CASE` guards in the upstream models.
TLC chooses the first matching arm, but TLA+ does not give matching arms that
priority. The proof contexts make the intended order explicit with mutually
exclusive guards. Walgit restores a checkpoint before replaying later segments
and catches up before retrying a log slot. SlateDB loads a manifest before
checking its boundary, finishes refreshing before judging its validity or
epoch, and finishes replay before inspecting another WAL entry.

Without these guards, a fresh Walgit replica can omit checkpointed entries and
SlateDB can fence its only writer before finishing a refresh. Choosing those
overlapping arms violates the selected safety properties. The repair preserves
the original first-match TLC behavior on well-typed reachable states; it narrows
the under-specified TLA+ actions. The safety predicates and parameter assumptions
are unchanged by this repair.

## Validation

`tests/dataset/test_s3_wal.py` checks small complete instances in both source
and generated module contexts. It reproduces the original Walgit failure at
initialization and demonstrates that adding only an empty-log exception still
fails after a full checkpoint. A negative control drops a committed segment
reference and must still violate the corrected predicate. Parameter controls
reject an empty process set, colliding state labels, and an OSWALD sentinel
that aliases a payload.

Four additional regressions extract the actual `CASE` guards from source and
generated module contexts and check that at most one explicit arm is enabled
in reachable states. They reject the models before the priority repair, even
when the default TLC branch order passes the selected safety invariants.

Larger upstream-configured checks are recorded in
`tests/fixtures/s3_wal/validation.json`. Finite-state exploration is screening
evidence, not a general proof of these parameterized statements. A budget-ended
run is reported as incomplete exploration. No new model experiment accompanies
this addition.

Before the action-priority repair, the default configurations with three
writers/replicas and three values produced:

| Model | Result | Distinct states |
|---|---|---:|
| SlateDBWAL | No violation in 30 minutes; exploration incomplete | 118,332,535 |
| OSWALD | Complete finite exploration, no violation | 3,606,090 |
| Walgit | No violation in 30 minutes; exploration incomplete | 63,298,973 |

For budget-ended runs, counts are the last progress snapshot before timeout.
The original nineteen focused regression checks and fourteen `PROOF OBVIOUS`
controls are recorded with those historical runs. The repaired contexts have
twenty-three focused regression checks; the eleven affected flat tasks are
regenerated with SANY and triviality gates under the repository-locked TLAPM
`7824dab`. The locked TLAPM is installed separately for these checks.

The recorded large TLC runs used revision `4260e47` and retain that build's
hashes and state counts. Upstream replaced the `v1.8.0` download on September 25;
the CI lock now uses revision `8f4bc8b`, whose SHA-256 matches release asset
`588774920`. Compatibility checks against the updated build are separate from
the original large-run evidence.

Regenerate the selected flat tasks with:

```sh
uv run python -m dataset.proof_from_scratch.generate --layered --allow-no-proof \
  source/SlateDBWAL/SlateDBWALProof.tla \
  source/OSWALD/OswaldProof.tla source/Walgit/WalgitProof.tla
uv run python -m dataset.proof_from_scratch.module_tasks
uv run pytest -q tests/dataset/test_s3_wal.py
```

Each `upstream.json` records original hashes, the local model hash, and the
adaptations. The MIT license and copyright notice are retained in
`LICENSES/s3-wal-collection-MIT.txt` and `NOTICE`.

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
No protocol action is changed.

This corrects an overstrong false predicate; it is not a logically equivalent
rewrite of that predicate. The change admits the legitimate empty and fully
checkpointed states while retaining the intended head-coverage requirement.

OSWALD also has a stray `|` after its module terminator. Removing that trailing
character makes the source compatible with the benchmark's module-boundary
integrity check and changes no TLA+ definition.

## Validation

`tests/dataset/test_s3_wal.py` checks small complete instances in both source
and generated module contexts. It reproduces the original Walgit failure at
initialization and demonstrates that adding only an empty-log exception still
fails after a full checkpoint. A negative control drops a committed segment
reference and must still violate the corrected predicate. Parameter controls
reject an empty process set, colliding state labels, and an OSWALD sentinel
that aliases a payload.

Larger upstream-configured checks are recorded in
`tests/fixtures/s3_wal/validation.json`. Finite-state exploration is screening
evidence, not a general proof of these parameterized statements. A budget-ended
run is reported as incomplete exploration. No new model experiment accompanies
this addition.

The default configurations with three writers/replicas and three values produced:

| Model | Result | Distinct states |
|---|---|---:|
| SlateDBWAL | No violation in 30 minutes; exploration incomplete | 118,332,535 |
| OSWALD | Complete finite exploration, no violation | 3,606,090 |
| Walgit | No violation in 30 minutes; exploration incomplete | 63,298,973 |

For budget-ended runs, counts are the last progress snapshot before timeout.
The nineteen focused regression checks pass, and all fourteen `PROOF OBVIOUS`
controls fail under the repository-locked TLAPM `7824dab`, with valid SANY
inputs and no accepted target. The locked TLAPM was installed separately for
these checks; the existing shared installation was not replaced.

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

# Remaining SI proof work

## Open target

`StorageCallerHistory!CallerEpochSITarget` is an operator stating the target, not a proved theorem:

```tla
(CallerHistoryEpochSpec /\ []SingleWritePerKey) => []FullSI
```

`FullSI` is defined in [IdentitySnapshotIsolation.tla](IdentitySnapshotIsolation.tla). It retains transaction ids, ordered operations and snapshot-state positions. `NoConf` detects intervening writes even when their visible payload equals an earlier value.

The proved `CallerHistoryEpochSpec => []TimestampSICertificate` theorem supplies commit identities, a strict total order, read cuts, payload fidelity, all positional external/local reads, and no intervening write conflicts. Turning these facts into the execution required by `FullSI` remains a substantive proof obligation.

## Required bridge

1. Enumerate the finite committed transaction identities in timestamp/log-position order. Show that this record sequence belongs to `IdentityCC!Orders`, without a fixed cardinality bound.
2. Prove that `IdentityCC!OperationStates` and `Effects` reconstruct the retained payloads, including ordered writes/removes and reads of the latest own write.
3. Relate `IdentityCC!ExecutionStates` at each positional cut to the certificate's latest-visible-version semantics. Equal state values must retain separate occurrences.
4. Discharge `IdentityCC!Complete` and `NoConf` for each transaction in that execution.
5. To claim a conservative extension of every unlabelled Storage behavior, separately prove the observer's converse lifting direction.

The caller contract, no-rollback epoch boundary and `SingleWritePerKey` premise remain part of the target. The SI predicate permits repeated writes, but no stronger unrestricted theorem is claimed.

## Other scope issues

- Without `FreshPrepareCall`, the raw epoch model permits backdated prepares and crossed snapshots that violate `FullSI`.
- Histories that retain commits removed by `RollbackToStable` still violate the all-history SI target. Recovery-inclusive survivor/withdrawal semantics require a separate definition and proof.
- Raw rollback can leave committed flags together with an empty log, causing a `Max({})` TLC evaluation error on a later start. The executable-model control preserves this diagnostic.

The executable controls document the behavior of the pinned abstract model and the history definitions. They do not by themselves establish whether a corresponding production execution is possible.

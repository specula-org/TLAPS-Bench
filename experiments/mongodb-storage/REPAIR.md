# Identity and occurrence repair

The initial history adapter formed a set of bare operation sequences. Two distinct transactions that both only delete the same key therefore became one element. A legal serial five-transaction execution was represented by four histories and incorrectly rejected by that adapter.

[StorageCallerCollapseSI.tla](StorageCallerCollapseSI.tla) preserves the 21-state execution. [StorageCallerCollapseAudit.tla](StorageCallerCollapseAudit.tla) checks that it has five identity-preserving histories and four legacy histories, satisfies `FullSI`, and violates `LegacyFullSI`.

The active `CommittedHistories` contains `[id |-> tid, ops |-> history]` records. [IdentitySnapshotIsolation.tla](IdentitySnapshotIsolation.tla) defines finite orders of distinct transaction ids, ordered operation effects, and positional snapshot/parent states. Reads following a local write must see the latest preceding local write. `NoConf` checks intervening write footprints, including deletes that restore an earlier visible payload. The definition permits SI write skew.

This is an explicit revised property, not a claimed general equivalence to `ClientCentric!SnapshotIsolation`. The state-based formulation in [Crooks et al., Seeing is Believing](https://www.cs.cornell.edu/lorenzo/papers/Crooks17Seeing.pdf), section 3, assumes uniquely identifiable values; repeated raw `NoValue` tombstones require additional care. The old adapter remains available as `LegacyCommittedHistories`, `LegacyFullSI`, and the `Legacy*Target` operators. Storage actions and the operation observer are unchanged.

[IdentitySIControls.tla](IdentitySIControls.tla) provides nineteen semantic controls for duplicate histories, repeated operations, own reads, dirty/fuzzy/fractured reads, lost updates, permitted write skew, ordered effects, restored-payload conflicts, and duplicate ids. These checks and the bounded Storage explorations validate examples within their stated coverage. The certificate-to-SI proof remains open; see [SI_GAP.md](SI_GAP.md).

----------------------- MODULE MultiShardTxnSnapshot -----------------------
EXTENDS MultiShardTxn

ASSUME SnapshotConfiguration ==
    /\ RC = "snapshot"
    /\ IgnorePrepareBlocking = "false"
    /\ IgnoreWriteConflicts = "false"

THEOREM SnapshotIsolationCorrect == Spec => []SnapshotIsolation
PROOF OMITTED

=============================================================================

----------------------- MODULE MultiShardTxnSnapshot_SnapshotIsolationCorrectDefs -----------------------
EXTENDS MultiShardTxn

ASSUME SnapshotConfiguration ==
    /\ RC = "snapshot"
    /\ IgnorePrepareBlocking = "false"
    /\ IgnoreWriteConflicts = "false"

=============================================================================

----------------------- MODULE MultiShardTxnSnapshotDefs -----------------------
EXTENDS MultiShardTxn

ASSUME SnapshotConfiguration ==
    /\ RC = "snapshot"
    /\ IgnorePrepareBlocking = "false"
    /\ IgnoreWriteConflicts = "false"

=============================================================================

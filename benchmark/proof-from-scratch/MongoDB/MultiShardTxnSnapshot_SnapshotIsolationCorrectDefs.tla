----------------------- MODULE MultiShardTxnSnapshot_SnapshotIsolationCorrectDefs -----------------------
EXTENDS MultiShardTxn

ASSUME SnapshotConfiguration ==
    /\ RC = "snapshot"
    /\ IgnorePrepareBlocking = "false"
    /\ IgnoreWriteConflicts = "false"
    /\ Timestamps \subseteq Nat

WritesEachKeyAtMostOnce(transaction) ==
    \A i, j \in DOMAIN transaction :
        (/\ transaction[i].op = "write"
         /\ transaction[j].op = "write"
         /\ transaction[i].key = transaction[j].key) => i = j

SingleWritePerKey ==
    \A transaction \in Range(ops) : WritesEachKeyAtMostOnce(transaction)

=============================================================================

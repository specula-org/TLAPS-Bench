----------------------- MODULE MultiShardTxnSnapshot -----------------------
EXTENDS MultiShardTxn

ASSUME SnapshotConfiguration ==
    /\ RC = "snapshot"
    /\ IgnorePrepareBlocking = "false"
    /\ IgnoreWriteConflicts = "false"
    /\ Timestamps \subseteq Nat

\* A transaction's write identifier must differ from the initial-value sentinel.
ASSUME NoValueIsNotTransaction == NoValue \notin TxId

WritesEachKeyAtMostOnce(transaction) ==
    \A i, j \in DOMAIN transaction :
        (/\ transaction[i].op = "write"
         /\ transaction[j].op = "write"
         /\ transaction[i].key = transaction[j].key) => i = j

SingleWritePerKey ==
    \A transaction \in Range(ops) : WritesEachKeyAtMostOnce(transaction)

THEOREM SnapshotIsolationCorrect ==
    (Spec /\ []SingleWritePerKey) => []SnapshotIsolation
PROOF OMITTED

=============================================================================

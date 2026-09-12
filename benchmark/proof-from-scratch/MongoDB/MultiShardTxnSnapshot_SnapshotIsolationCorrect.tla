---- MODULE MultiShardTxnSnapshot_SnapshotIsolationCorrect ----
EXTENDS MultiShardTxnSnapshot_SnapshotIsolationCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM SnapshotIsolationCorrect == Spec => []SnapshotIsolation
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

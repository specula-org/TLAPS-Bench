---- MODULE MultiShardTxnSnapshot ----
EXTENDS MultiShardTxnSnapshotDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM SnapshotIsolationCorrect == Spec => []SnapshotIsolation
\* BEGIN AGENT PROOF MongoDB/MultiShardTxnSnapshot_SnapshotIsolationCorrect.tla
PROOF OMITTED
\* END AGENT PROOF MongoDB/MultiShardTxnSnapshot_SnapshotIsolationCorrect.tla
====

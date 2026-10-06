---- MODULE OswaldProof_ConsistentWriterSnapshotsInvariant ----
EXTENDS OswaldProof_ConsistentWriterSnapshotsInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ConsistentWriterSnapshotsInvariant == Spec => []ConsistentWriterSnapshots
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

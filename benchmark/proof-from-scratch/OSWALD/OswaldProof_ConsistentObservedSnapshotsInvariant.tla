---- MODULE OswaldProof_ConsistentObservedSnapshotsInvariant ----
EXTENDS OswaldProof_ConsistentObservedSnapshotsInvariantDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ConsistentObservedSnapshotsInvariant == Spec => []ConsistentObservedSnapshots
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

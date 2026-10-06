---- MODULE OswaldProof ----
EXTENDS OswaldProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOKInvariant == Spec => []TypeOK
\* BEGIN AGENT PROOF OSWALD/OswaldProof_TypeOKInvariant.tla
PROOF OMITTED
\* END AGENT PROOF OSWALD/OswaldProof_TypeOKInvariant.tla

THEOREM ConsistentWriterSnapshotsInvariant == Spec => []ConsistentWriterSnapshots
\* BEGIN AGENT PROOF OSWALD/OswaldProof_ConsistentWriterSnapshotsInvariant.tla
PROOF OMITTED
\* END AGENT PROOF OSWALD/OswaldProof_ConsistentWriterSnapshotsInvariant.tla

THEOREM ConsistentObservedSnapshotsInvariant == Spec => []ConsistentObservedSnapshots
\* BEGIN AGENT PROOF OSWALD/OswaldProof_ConsistentObservedSnapshotsInvariant.tla
PROOF OMITTED
\* END AGENT PROOF OSWALD/OswaldProof_ConsistentObservedSnapshotsInvariant.tla
====

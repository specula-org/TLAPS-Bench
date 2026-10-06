---- MODULE WalgitProof ----
EXTENDS WalgitProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOKInvariant == Spec => []TypeOK
\* BEGIN AGENT PROOF Walgit/WalgitProof_TypeOKInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_TypeOKInvariant.tla

THEOREM ValidReplicasInvariant == Spec => []ValidReplicas
\* BEGIN AGENT PROOF Walgit/WalgitProof_ValidReplicasInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_ValidReplicasInvariant.tla

THEOREM ValidManifestInvariant == Spec => []ValidManifest
\* BEGIN AGENT PROOF Walgit/WalgitProof_ValidManifestInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_ValidManifestInvariant.tla

THEOREM ValidLogSegmentsInvariant == Spec => []ValidLogSegments
\* BEGIN AGENT PROOF Walgit/WalgitProof_ValidLogSegmentsInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_ValidLogSegmentsInvariant.tla

THEOREM ReplicaStateIsCommittedPrefixInvariant == Spec => []ReplicaStateIsCommittedPrefix
\* BEGIN AGENT PROOF Walgit/WalgitProof_ReplicaStateIsCommittedPrefixInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_ReplicaStateIsCommittedPrefixInvariant.tla

THEOREM ManifestRepresentsCommittedStateInvariant == Spec => []ManifestRepresentsCommittedState
\* BEGIN AGENT PROOF Walgit/WalgitProof_ManifestRepresentsCommittedStateInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_ManifestRepresentsCommittedStateInvariant.tla

THEOREM ConsistentReadsInvariant == Spec => []ConsistentReads
\* BEGIN AGENT PROOF Walgit/WalgitProof_ConsistentReadsInvariant.tla
PROOF OMITTED
\* END AGENT PROOF Walgit/WalgitProof_ConsistentReadsInvariant.tla
====

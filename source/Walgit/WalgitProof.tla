---- MODULE WalgitProof ----
EXTENDS Walgit

\* Explicit domains for the symbolic parameters used by the upstream TLC model.
ASSUME FiniteDomains ==
    /\ IsFiniteSet(Replicas)
    /\ IsFiniteSet(Values)
    /\ Replicas # {}

ASSUME DistinctLabels ==
    Cardinality({IDLE, GET_MANIFEST, REPLAY_WAL, CLAIM_SLOT, CAS_MANIFEST, CHECK_SLOT, DELETE_OWN_SEGMENT, DELETE_BURNED_SEGMENTS, READY, COMMIT_CHECKPOINT, ILLEGAL_STATE, REPLICATE, WRITE, CHECKPOINT}) = 14

ASSUME SentinelDomain == None \notin CheckpointRefType

THEOREM TypeOKInvariant == Spec => []TypeOK
PROOF OMITTED

THEOREM ValidReplicasInvariant == Spec => []ValidReplicas
PROOF OMITTED

THEOREM ValidManifestInvariant == Spec => []ValidManifest
PROOF OMITTED

THEOREM ValidLogSegmentsInvariant == Spec => []ValidLogSegments
PROOF OMITTED

THEOREM ReplicaStateIsCommittedPrefixInvariant == Spec => []ReplicaStateIsCommittedPrefix
PROOF OMITTED

THEOREM ManifestRepresentsCommittedStateInvariant == Spec => []ManifestRepresentsCommittedState
PROOF OMITTED

THEOREM ConsistentReadsInvariant == Spec => []ConsistentReads
PROOF OMITTED

====

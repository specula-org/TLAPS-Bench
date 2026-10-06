---- MODULE WalgitProofDefs ----
EXTENDS Walgit

ASSUME FiniteDomains ==
    /\ IsFiniteSet(Replicas)
    /\ IsFiniteSet(Values)
    /\ Replicas # {}

ASSUME DistinctLabels ==
    Cardinality({IDLE, GET_MANIFEST, REPLAY_WAL, CLAIM_SLOT, CAS_MANIFEST, CHECK_SLOT, DELETE_OWN_SEGMENT, DELETE_BURNED_SEGMENTS, READY, COMMIT_CHECKPOINT, ILLEGAL_STATE, REPLICATE, WRITE, CHECKPOINT}) = 14

ASSUME SentinelDomain == None \notin CheckpointRefType

====

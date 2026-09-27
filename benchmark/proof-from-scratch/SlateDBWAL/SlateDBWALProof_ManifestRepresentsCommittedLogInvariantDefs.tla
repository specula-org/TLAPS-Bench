---- MODULE SlateDBWALProof_ManifestRepresentsCommittedLogInvariantDefs ----
EXTENDS SlateDBWAL

ASSUME FiniteDomains ==
    /\ IsFiniteSet(Writers)
    /\ IsFiniteSet(GarbageCollectors)
    /\ IsFiniteSet(Values)
    /\ Writers # {}

ASSUME DistinctLabels ==
    Cardinality({IDLE, FIND_NEXT_WAL_ID, CLAIM_EPOCH, CHECK_BOUNDARY, WRITE_FENCE, VALIDATE_BEFORE_RETRY, VALIDATE_BEFORE_REPLAY, VALIDATE_BEFORE_NOT_FOUND, LOAD_SNAPSHOT, REPLAY_WAL, READY, COMMIT_SNAPSHOT, FENCED, NOT_FOUND, MANIFEST_GC, WAL_GC, LOAD_BOUNDARY, COMPUTE_BOUNDARY, ADVANCE_BOUNDARY, FIND_LAST_WAL_ID, DELETE, DONE, DATA, FENCE, ILLEGAL_STATE}) = 25

ASSUME SentinelDomain == NIL \notin (WALObjectType \cup ManifestType \cup BoundaryType \cup Seq(Values))

====

---- MODULE OswaldProof_TypeOKInvariantDefs ----
EXTENDS Oswald

ASSUME FiniteDomains ==
    /\ IsFiniteSet(Writers)
    /\ IsFiniteSet(GarbageCollectors)
    /\ IsFiniteSet(Values)
    /\ Writers # {}

ASSUME DistinctLabels ==
    Cardinality({SNAPSHOT_RECOVERY, CATCHUP_RECOVERY, VALIDATE, UPDATE_MANIFEST, READY, DELETE}) = 6

ASSUME SentinelDomain == NIL \notin Values

====

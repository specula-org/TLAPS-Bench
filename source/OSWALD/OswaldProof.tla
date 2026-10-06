---- MODULE OswaldProof ----
EXTENDS Oswald

\* Explicit domains for the symbolic parameters used by the upstream TLC model.
ASSUME FiniteDomains ==
    /\ IsFiniteSet(Writers)
    /\ IsFiniteSet(GarbageCollectors)
    /\ IsFiniteSet(Values)
    /\ Writers # {}

ASSUME DistinctLabels ==
    Cardinality({SNAPSHOT_RECOVERY, CATCHUP_RECOVERY, VALIDATE, UPDATE_MANIFEST, READY, DELETE}) = 6

ASSUME SentinelDomain == NIL \notin Values

THEOREM TypeOKInvariant == Spec => []TypeOK
PROOF OMITTED

THEOREM ConsistentWriterSnapshotsInvariant == Spec => []ConsistentWriterSnapshots
PROOF OMITTED

THEOREM ConsistentObservedSnapshotsInvariant == Spec => []ConsistentObservedSnapshots
PROOF OMITTED

====

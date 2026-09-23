---- MODULE LibompCounting ----
EXTENDS LibompInitialization
Counting == ~cancelled /\ pc[Primary] \in {"barrier_gather", "barrier_tasks"}
LEMMA PreserveCount ==
 ASSUME CountInv, Counting' => Counting,
        UNCHANGED <<RoundSlot, unfinished, UnfinishedSet>>
 PROVE CountInv'
 BY SMTT("r10") DEF Counting, CountInv

LEMMA EmptyCount ==
 ASSUME TypeOK, CountInv, Counting, unfinished[RoundSlot] = 0
 PROVE \A t \in Thread : threadFinished[t]
<1>1. IsFiniteSet(UnfinishedSet)
 BY ThreadDomain, FS_Subset, SMTT("r10") DEF UnfinishedSet
<1>2. Cardinality(UnfinishedSet) = 0
 BY SMTT("r10") DEF CountInv, Counting
<1>3. UnfinishedSet = {}
 BY <1>1, <1>2, FS_EmptySet, SMTT("r10")
<1> QED BY <1>3, SMTT("r10") DEF UnfinishedSet
====

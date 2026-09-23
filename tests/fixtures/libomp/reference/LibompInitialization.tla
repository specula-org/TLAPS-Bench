---- MODULE LibompInitialization ----
EXTENDS LibompInvariant, TLAPS, FiniteSetTheorems

LEMMA PrimaryMember == Primary \in Thread
  BY ThreadDomain, SMT DEF Primary

LEMMA InitialInvariant == Init => Inductive
<1>1. Init => TypeOK
  BY ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMT
  DEF Init, TypeOK, PcStates, TaskPhases
<1>2. Init => SerialInv
  BY PrimaryMember, SentinelDistinct, SMT
  DEF Init, SerialInv, Effective, Toggled, RoundSlot, Slots
<1>3. Init => PhaseInv
  BY PrimaryMember, FS_EmptySet, SMT
  DEF Init, PhaseInv, Effective, Toggled, RoundSlot, Drained, Before, After, AllGathered, UnfinishedSet
<1>4. Init => WorkInv
  BY PrimaryMember, SentinelDistinct, SMT
  DEF Init, WorkInv, LiveTask, Effective, Toggled, RoundSlot, Drained, Before, After
<1>5. Init => CountInv
  BY PrimaryMember, SMT DEF Init, CountInv
<1> QED BY <1>1, <1>2, <1>3, <1>4, <1>5 DEF Inductive

LEMMA InvariantImpliesGoals ==
  Inductive => /\ ActiveTasksImplyActiveTeam
               /\ NoQueuedTasksAfterDeactivation
               /\ ParityConsistency
               /\ ParityRestoredAfterCancel
<1>1. Inductive => ActiveTasksImplyActiveTeam
  BY PrimaryMember, SMT
  DEF Inductive, TypeOK, WorkInv, PhaseInv, SerialInv, LiveTask, ActiveTasksImplyActiveTeam,
      Effective, Toggled, RoundSlot, Drained, After, Before, Slots, AllGathered
<1>2. Inductive => NoQueuedTasksAfterDeactivation
  BY PrimaryMember, SMT
  DEF Inductive, TypeOK, WorkInv, PhaseInv, LiveTask, NoQueuedTasksAfterDeactivation,
      QueuedTasks, PendingProxyTasks, Drained, After
<1>3. Inductive => ParityConsistency
  BY SMT
  DEF Inductive, SerialInv, Effective, Toggled, ParityConsistency, ActiveInBarrier
<1>4. Inductive => ParityRestoredAfterCancel
  BY SMT
  DEF Inductive, TypeOK, SerialInv, Effective, Toggled, ParityRestoredAfterCancel
<1> QED BY <1>1, <1>2, <1>3, <1>4
====

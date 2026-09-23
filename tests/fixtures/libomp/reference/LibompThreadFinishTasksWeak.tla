---- MODULE LibompThreadFinishTasksWeak ----
EXTENDS LibompCounting

LEMMA Step_ThreadFinishTasksWeak ==
  ASSUME NEW t \in Thread, Inductive, ThreadFinishTasksWeak(t)
  PROVE Inductive'

<1>T. TypeOK BY DEF Inductive
<1>S. SerialInv BY DEF Inductive
<1>P. PhaseInv BY DEF Inductive
<1>W. WorkInv BY DEF Inductive
<1>C. CountInv BY DEF Inductive
<1>1. TypeOK'
  BY <1>T, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK
<1>2. SerialInv'
  BY <1>T, <1>S, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv
<1>3. PhaseInv'
  BY <1>T, <1>S, <1>P, <1>W, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, FS_Subset, FS_AddElement, FS_RemoveElement, FS_EmptySet, SMTT("r10")
  DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv, WorkInv
<1>4. WorkInv'
  BY <1>T, <1>S, <1>P, <1>W, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv, WorkInv
<1>N. IsFiniteSet(UnfinishedSet)
  BY ThreadDomain, FS_Subset, SMTT("r10") DEF UnfinishedSet
<1>O. t \in UnfinishedSet
  BY SMTT("r10") DEF ThreadFinishTasksWeak, UnfinishedSet
<1>U. UnfinishedSet' = UnfinishedSet \ {t}
  BY <1>T, SMTT("r10") DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, TypeOK, UnfinishedSet
<1>K. Cardinality(UnfinishedSet') = Cardinality(UnfinishedSet) - 1
  BY <1>N, <1>O, <1>U, FS_RemoveElement, SMTT("r10")
<1>R. UNCHANGED RoundSlot
  BY SMTT("r10") DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, Effective, Toggled, RoundSlot
<1>L. CurrentSlot(t) = RoundSlot
  BY <1>T, <1>S, SMTT("r10") DEF ThreadFinishTasksWeak, TypeOK, SerialInv, CurrentSlot, Effective, Toggled
<1>A. Counting' => Counting
  BY SMTT("r10") DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, Counting
<1>B. unfinished'[RoundSlot'] = unfinished[RoundSlot] - 1
  BY <1>T, <1>L, <1>R, SMTT("r10") DEF ThreadFinishTasksWeak, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, TypeOK, CurrentSlot
<1>5. CountInv'
  BY <1>C, <1>A, <1>B, <1>K, SMTT("r10") DEF CountInv, Counting
<1> QED BY <1>1, <1>2, <1>3, <1>4, <1>5 DEF Inductive
====

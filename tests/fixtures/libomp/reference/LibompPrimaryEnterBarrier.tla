---- MODULE LibompPrimaryEnterBarrier ----
EXTENDS LibompCounting

LEMMA Step_PrimaryEnterBarrier ==
  ASSUME Inductive, PrimaryEnterBarrier
  PROVE Inductive'

<1>T. TypeOK BY DEF Inductive
<1>S. SerialInv BY DEF Inductive
<1>P. PhaseInv BY DEF Inductive
<1>W. WorkInv BY DEF Inductive
<1>C. CountInv BY DEF Inductive
<1>1. TypeOK'
  BY <1>T, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, FS_CardinalityType, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK
<1>2. SerialInv'
  BY <1>T, <1>S, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv
<1>3. PhaseInv'
  BY <1>T, <1>S, <1>P, <1>W, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv, WorkInv
<1>4. WorkInv'
  BY <1>T, <1>S, <1>P, <1>W, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv, WorkInv
<1>U. UnfinishedSet' = Thread
  BY <1>T, <1>P, <1>W, PrimaryMember, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, TypeOK, PhaseInv, WorkInv, Before, After, UnfinishedSet
<1>R. RoundSlot' = CurrentSlot(Primary)
  BY <1>T, <1>S, PrimaryMember, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, TypeOK, SerialInv, Effective, Toggled, RoundSlot, Slots, CurrentSlot
<1>5. CountInv'
  BY <1>U, <1>R, <1>T, PrimaryMember, SMTT("r10")
  DEF PrimaryEnterBarrier, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, CountInv, TypeOK, NumThreads, CurrentSlot
<1> QED BY <1>1, <1>2, <1>3, <1>4, <1>5 DEF Inductive
====

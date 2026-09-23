---- MODULE LibompSerializedParallelExit ----
EXTENDS LibompCounting

LEMMA Step_SerializedParallelExit ==
  ASSUME NEW t \in Thread, Inductive, SerializedParallelExit(t)
  PROVE Inductive'

<1>T. TypeOK BY DEF Inductive
<1>S. SerialInv BY DEF Inductive
<1>P. PhaseInv BY DEF Inductive
<1>W. WorkInv BY DEF Inductive
<1>C. CountInv BY DEF Inductive
<1>1. TypeOK'
  BY <1>T, <1>S, <1>P, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv
<1>2. SerialInv'
  BY <1>T, <1>S, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv
<1>3. PhaseInv'
  BY <1>T, <1>S, <1>P, <1>W, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv, WorkInv
<1>4. WorkInv'
  BY <1>T, <1>S, <1>P, <1>W, PrimaryMember, ThreadDomain, TaskDomain, SentinelDistinct, RoundDomain, SMTT("r10")
  DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, PcStates, TaskPhases, CurrentSlot, QueuedTasks, SerialQueuedTasks, PendingProxyTasks, LiveTask, FreeTasks, AllGathered, Workers, Primary, NumThreads, InBarrier, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, TypeOK, SerialInv, PhaseInv, WorkInv
<1>U. UNCHANGED UnfinishedSet
  BY <1>T, <1>W, SMTT("r10") DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, UnfinishedSet, WorkInv, TypeOK, Before, After
<1>R. UNCHANGED RoundSlot
  BY <1>T, <1>S, PrimaryMember, SMTT("r10") DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, TypeOK, SerialInv, Effective, Toggled, RoundSlot, Slots, Primary, Workers
<1>A. Counting' => Counting
  BY <1>T, PrimaryMember, SMTT("r10") DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars, TypeOK, Counting, Primary, Workers
<1>F. UNCHANGED unfinished
  BY SMTT("r10") DEF SerializedParallelExit, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, allVars
<1>5. CountInv'
  BY <1>C, <1>U, <1>R, <1>A, <1>F, PreserveCount
<1> QED BY <1>1, <1>2, <1>3, <1>4, <1>5 DEF Inductive
====

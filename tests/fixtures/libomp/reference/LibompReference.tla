---- MODULE LibompReference ----
EXTENDS LibompStuttering, LibompBarrierDone, LibompCancelBarrier, LibompCancelQueuedTask, LibompCompleteTask, LibompDetachTask, LibompEarlyFulfillEvent, LibompExecuteTask, LibompFulfillEvent, LibompPrimaryCancelledBarrier, LibompPrimaryEnterBarrier, LibompPrimaryRelease, LibompPrimaryStartTaskWait, LibompPrimaryTaskTeamWait, LibompProxyTaskComplete, LibompReapTeam, LibompReapThread, LibompScheduleDetachTask, LibompScheduleTask, LibompSerializedParallelEntry, LibompSerializedParallelExit, LibompStartNextRound, LibompStealTask, LibompTaskTeamSync, LibompThreadFinishTasks, LibompThreadFinishTasksWeak, LibompWorkerCancelledBarrier, LibompWorkerEnterBarrier, LibompWorkerReceiveRelease, LibompWorkerStartTasks

LEMMA InvariantNext == Inductive /\ [Next]_allVars => Inductive'
<1> SUFFICES ASSUME Inductive, [Next]_allVars PROVE Inductive'
  OBVIOUS
<1>1. CASE UNCHANGED allVars
  BY <1>1, StutterPreserves
<1>2. CASE Next
  BY <1>2, Step_BarrierDone, Step_CancelBarrier, Step_CancelQueuedTask, Step_CompleteTask, Step_DetachTask, Step_EarlyFulfillEvent, Step_ExecuteTask, Step_FulfillEvent, Step_PrimaryCancelledBarrier, Step_PrimaryEnterBarrier, Step_PrimaryRelease, Step_PrimaryStartTaskWait, Step_PrimaryTaskTeamWait, Step_ProxyTaskComplete, Step_ReapTeam, Step_ReapThread, Step_ScheduleDetachTask, Step_ScheduleTask, Step_SerializedParallelEntry, Step_SerializedParallelExit, Step_StartNextRound, Step_StealTask, Step_TaskTeamSync, Step_ThreadFinishTasks, Step_ThreadFinishTasksWeak, Step_WorkerCancelledBarrier, Step_WorkerEnterBarrier, Step_WorkerReceiveRelease, Step_WorkerStartTasks, SMTT("r10")
  DEF Next, Workers, Primary
<1> QED BY <1>1, <1>2

THEOREM InvariantAlways == Spec => []Inductive
  BY InitialInvariant, InvariantNext, PTL DEF Spec

THEOREM AllFourTargets == Spec => [](
  /\ ActiveTasksImplyActiveTeam
  /\ NoQueuedTasksAfterDeactivation
  /\ ParityConsistency
  /\ ParityRestoredAfterCancel)
  BY InvariantAlways, InvariantImpliesGoals, PTL

THEOREM ActiveTasksImplyActiveTeamCorrect == Spec => []ActiveTasksImplyActiveTeam
  BY AllFourTargets, PTL

THEOREM NoQueuedTasksAfterDeactivationCorrect == Spec => []NoQueuedTasksAfterDeactivation
  BY AllFourTargets, PTL

THEOREM ParityConsistencyCorrect == Spec => []ParityConsistency
  BY AllFourTargets, PTL

THEOREM ParityRestoredAfterCancelCorrect == Spec => []ParityRestoredAfterCancel
  BY AllFourTargets, PTL

====

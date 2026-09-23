---- MODULE LibompLifecycle ----
EXTENDS libompDefs
CONSTANTS A, B
VARIABLE step
TraceVars == <<allVars, step>>
TraceInit == Init /\ step = 0
TraceAction ==
  CASE step = 0 -> ScheduleDetachTask(0) /\ taskPhase'[A] = "queued"
    [] step = 1 -> PrimaryEnterBarrier
    [] step = 2 -> WorkerEnterBarrier(1)
    [] step = 3 -> PrimaryStartTaskWait
    [] step = 4 -> WorkerStartTasks(1)
    [] step = 5 -> ExecuteTask(1) /\ taskOwner'[A] = 1
    [] step = 6 -> DetachTask(1, A)
    [] step = 7 -> FulfillEvent(A)
    [] step = 8 -> ProxyTaskComplete(A)
    [] step = 9 -> ThreadFinishTasks(0)
    [] step = 10 -> ThreadFinishTasks(1)
    [] step = 11 -> PrimaryTaskTeamWait
    [] step = 12 -> PrimaryRelease
    [] step = 13 -> WorkerReceiveRelease(1)
    [] step = 14 -> TaskTeamSync(0)
    [] step = 15 -> TaskTeamSync(1)
    [] step = 16 -> BarrierDone(0)
    [] step = 17 -> BarrierDone(1)
    [] step = 18 -> StartNextRound
    [] step = 19 -> SerializedParallelEntry(0)
    [] step = 20 -> ScheduleTask(0) /\ taskPhase'[B] = "queued"
    [] step = 21 -> ExecuteTask(0) /\ taskOwner'[B] = 0
    [] step = 22 -> CompleteTask(0, B)
    [] step = 23 -> SerializedParallelExit(0)
    [] step = 24 -> PrimaryEnterBarrier
    [] step = 25 -> WorkerEnterBarrier(1)
    [] step = 26 -> CancelBarrier
    [] step = 27 -> PrimaryCancelledBarrier
    [] step = 28 -> WorkerCancelledBarrier(1)
    [] step = 29 -> StartNextRound
    [] OTHER -> FALSE
TraceNext == /\ step < 30
             /\ TraceAction
             /\ step' = step + 1
TraceSpec == TraceInit /\ [][TraceNext]_TraceVars
CompletedLifecycle == step = 30 =>
  /\ barrierRound = 2
  /\ taskPhase[A] = "completed" /\ taskPhase[B] = "completed"
  /\ taskTeamSlot[0] = 1 /\ taskTeamSlot[1] = 1
  /\ pendingTasks[0] = {} /\ pendingTasks[1] = {}
====

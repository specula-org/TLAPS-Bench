---- MODULE LibompInvariant ----
EXTENDS libompRuntime
Slots == {0, 1}
Before == {"idle", "barrier_gather", "barrier_tasks"}
After == {"barrier_task_wait", "barrier_release", "barrier_sync", "done"}
Effective(t) == IF inSerial[t] THEN savedSlot[t] ELSE taskTeamSlot[t]
Toggled(t) == ~cancelled /\ pc[t] \in {"barrier_sync", "done"}
RoundSlot == IF Toggled(Primary) THEN 1 - Effective(Primary) ELSE Effective(Primary)
Drained == ~cancelled /\ pc[Primary] \in After
UnfinishedSet == {t \in Thread : ~threadFinished[t]}

SerialInv ==
 /\ \A t \in Thread :
      IF inSerial[t]
      THEN /\ savedSlot[t] \in Slots /\ taskTeamSlot[t] = 0
           /\ pc[t] \in {"idle", "barrier_tasks"}
           /\ ~threadFinished[t]
      ELSE savedSlot[t] = Nil
 /\ \A t \in Thread : Effective(t) = IF Toggled(t) THEN 1 - RoundSlot ELSE RoundSlot

PhaseInv ==
 /\ (\E t \in Thread : pc[t] # "idle") => barrierRound < MaxBarriers
 /\ cancelled => /\ pc[Primary] \in {"barrier_gather", "barrier_tasks", "done"}
                  /\ \A t \in Thread : pc[t] \in Before \cup {"done"}
 /\ ~cancelled =>
      /\ (pc[Primary] = "idle" => \A t \in Thread : pc[t] \in {"idle", "barrier_gather"})
      /\ (pc[Primary] \in {"barrier_gather", "barrier_tasks"} => \A t \in Thread : pc[t] \in Before)
      /\ (\E t \in Thread : pc[t] \in {"barrier_tasks"} \cup After) => AllGathered
 /\ Drained => \A t \in Thread :
       /\ pc[t] \in {"barrier_tasks", "barrier_task_wait", "barrier_release", "barrier_sync", "done"}
       /\ (pc[t] = "barrier_tasks" => threadFinished[t])
 /\ (pc[Primary] # "idle" /\ ~Drained) => taskTeamActive[RoundSlot]
 /\ taskTeamRetired[RoundSlot] = Drained

WorkInv ==
 /\ \A t \in Thread : pendingTasks[t] = {task \in Task : taskRoot[task] = t /\ LiveTask(task)}
 /\ \A task \in Task : LiveTask(task) =>
      /\ taskRoot[task] \in Thread /\ taskSlot[task] \in Slots
      /\ pc[taskRoot[task]] \in Before /\ ~threadFinished[taskRoot[task]]
      /\ IF serialOwner[task] = Nil THEN taskSlot[task] = RoundSlot
         ELSE /\ serialOwner[task] \in Thread /\ inSerial[serialOwner[task]]
      /\ taskPhase[task] = "executing" =>
           /\ taskOwner[task] \in Thread /\ ~threadFinished[taskOwner[task]]
           /\ IF serialOwner[task] = Nil THEN pc[taskOwner[task]] = "barrier_tasks"
              ELSE /\ taskOwner[task] = serialOwner[task]
                   /\ pc[taskOwner[task]] \in {"idle", "barrier_tasks"}
 /\ Drained => \A task \in Task : ~LiveTask(task)
 /\ \A t \in Thread :
      /\ (threadState[t] = "active" => ~threadFinished[t])
      /\ threadFinished[t] =>
           /\ pendingTasks[t] = {} /\ ~inSerial[t]
           /\ pc[t] \in {"barrier_tasks"} \cup After
           /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
 /\ \A task \in Task :
      taskPhase[task] \in {"free", "queued", "detached", "fulfilled", "completed", "cancelled"} => taskOwner[task] = Nil

CountInv ==
 (~cancelled /\ pc[Primary] \in {"barrier_gather", "barrier_tasks"}) =>
       unfinished[RoundSlot] = Cardinality(UnfinishedSet)

Inductive == TypeOK /\ SerialInv /\ PhaseInv /\ WorkInv /\ CountInv
====

---- MODULE libompRuntime ----

EXTENDS Integers, FiniteSets, Sequences, TLC

CONSTANTS
    Thread,         
    Task,           
    MaxBarriers,    
    Nil             

ASSUME ThreadDomain == /\ IsFiniteSet(Thread) /\ 0 \in Thread /\ Thread \subseteq Nat
ASSUME TaskDomain == IsFiniteSet(Task)
ASSUME SentinelDistinct == Nil \notin Thread \cup Task
ASSUME RoundDomain == MaxBarriers \in Nat

Primary == 0
Workers == Thread \ {Primary}
NumThreads == Cardinality(Thread)

VARIABLES
    pc,                 
    barrierRound,       
    cancelled           

barrierVars == <<pc, barrierRound, cancelled>>

VARIABLES
    taskTeamSlot,       
    taskTeamActive,     
    unfinished          

parityVars == <<taskTeamSlot, taskTeamActive, unfinished>>

VARIABLES
    threadState,        
    teamValid,          
    threadFinished      

lifecycleVars == <<threadState, teamValid, threadFinished>>

VARIABLES
    taskPhase,          
    taskOwner,          
    taskParent,         
    childCount,         
    taskDetachable,     
    eventFulfilled,     
    taskSlot            

taskVars == <<taskPhase, taskOwner, taskParent, childCount, taskDetachable, eventFulfilled, taskSlot>>

VARIABLES
    taskCount           

taskCountVars == <<taskCount>>

VARIABLES
    inSerial,           
    savedSlot           

serialVars == <<inSerial, savedSlot>>

VARIABLES taskRoot, pendingTasks, serialOwner, taskTeamRetired
workVars == <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>
allVars == <<barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars>>

CurrentSlot(t) == taskTeamSlot[t]

FreeTasks == {task \in Task : taskPhase[task] = "free"}

QueuedTasks(slot) == {task \in Task : taskSlot[task] = slot /\ serialOwner[task] = Nil /\ taskPhase[task] = "queued"}

SerialQueuedTasks(t) == {task \in Task : serialOwner[task] = t /\ taskPhase[task] = "queued"}
PendingProxyTasks(slot) == {task \in Task : serialOwner[task] = Nil /\ taskSlot[task] = slot /\ taskPhase[task] = "fulfilled"}
LiveTask(task) == taskPhase[task] \in {"queued", "executing", "detached", "fulfilled"}

InBarrier(t) == pc[t] \in {"barrier_gather", "barrier_tasks", "barrier_task_wait",
                           "barrier_release", "barrier_sync"}

Init ==
    
    /\ pc = [t \in Thread |-> "idle"]
    /\ barrierRound = 0
    /\ cancelled = FALSE

    /\ taskTeamSlot = [t \in Thread |-> 0]
    /\ taskTeamActive = [slot \in {0, 1} |-> FALSE]
    /\ unfinished = [slot \in {0, 1} |-> 0]
    
    /\ threadState = [t \in Thread |-> "active"]
    /\ teamValid = TRUE
    /\ threadFinished = [t \in Thread |-> FALSE]
    
    /\ taskPhase = [task \in Task |-> "free"]
    /\ taskOwner = [task \in Task |-> Nil]
    /\ taskParent = [task \in Task |-> Nil]
    /\ childCount = [task \in Task |-> 0]
    /\ taskDetachable = [task \in Task |-> FALSE]
    /\ eventFulfilled = [task \in Task |-> FALSE]
    /\ taskSlot = [task \in Task |-> Nil]
    
    /\ taskCount = [slot \in {0, 1} |-> 0]
    
    /\ inSerial = [t \in Thread |-> FALSE]
    /\ savedSlot = [t \in Thread |-> Nil]
    /\ taskRoot = [task \in Task |-> Nil]
    /\ pendingTasks = [t \in Thread |-> {}]
    /\ serialOwner = [task \in Task |-> Nil]
    /\ taskTeamRetired = [slot \in {0, 1} |-> FALSE]

PrimaryEnterBarrier ==
    /\ pc[Primary] = "idle"
    /\ taskTeamRetired' = [taskTeamRetired EXCEPT ![CurrentSlot(Primary)] = FALSE]
    /\ barrierRound < MaxBarriers
    /\ ~inSerial[Primary]  

    /\ LET slot == CurrentSlot(Primary)
       IN /\ taskTeamActive' = [taskTeamActive EXCEPT ![slot] = TRUE]
          
          /\ unfinished' = [unfinished EXCEPT ![slot] = NumThreads]
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_gather"]
    /\ UNCHANGED <<barrierRound, cancelled, taskTeamSlot,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner>>

WorkerEnterBarrier(t) ==
    /\ t \in Workers
    /\ pc[t] = "idle"
    /\ barrierRound < MaxBarriers
    /\ ~inSerial[t]  
    /\ pc' = [pc EXCEPT ![t] = "barrier_gather"]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

AllGathered == \A t \in Thread : pc[t] \in {"barrier_gather", "barrier_tasks",
                                             "barrier_task_wait", "barrier_release",
                                             "barrier_sync", "done"}

WorkerStartTasks(t) ==
    /\ t \in Workers
    /\ pc[t] = "barrier_gather"
    /\ AllGathered
    /\ pc' = [pc EXCEPT ![t] = "barrier_tasks"]
    /\ threadState' = [threadState EXCEPT ![t] = "active"]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = FALSE]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars, teamValid,
                   taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

PrimaryStartTaskWait ==
    /\ pc[Primary] = "barrier_gather"
    /\ AllGathered
    /\ ~cancelled
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_tasks"]
    /\ threadState' = [threadState EXCEPT ![Primary] = "active"]
    /\ threadFinished' = [threadFinished EXCEPT ![Primary] = FALSE]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars, teamValid,
                   taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

ScheduleTask(t) ==
    /\ pc[t] \in {"idle", "barrier_tasks"}
    /\ threadState[t] = "active"
    /\ ~cancelled
    /\ ~threadFinished[t]
    /\ \E task \in FreeTasks :
        /\ LET slot == CurrentSlot(t)
               
               hasParent == \E pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
               theParent == IF \E pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
                            THEN CHOOSE pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
                            ELSE Nil
           IN
           
           /\ taskRoot' = [taskRoot EXCEPT ![task] = IF theParent = Nil THEN t ELSE taskRoot[theParent]]
           /\ LET root == IF theParent = Nil THEN t ELSE taskRoot[theParent]
              IN pendingTasks' = [pendingTasks EXCEPT ![root] = @ \cup {task}]
           /\ serialOwner' = [serialOwner EXCEPT ![task] = IF inSerial[t] THEN t ELSE Nil]
           /\ taskPhase' = [taskPhase EXCEPT ![task] = "queued"]
           /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]
           /\ taskParent' = [taskParent EXCEPT ![task] = theParent]
           /\ childCount' = IF theParent /= Nil
                            THEN [childCount EXCEPT ![theParent] = childCount[theParent] + 1]
                            ELSE childCount
           /\ taskDetachable' = [taskDetachable EXCEPT ![task] = FALSE]
           /\ eventFulfilled' = [eventFulfilled EXCEPT ![task] = FALSE]
           /\ taskSlot' = [taskSlot EXCEPT ![task] = slot]
           /\ taskCount' = IF inSerial[t] THEN taskCount ELSE [taskCount EXCEPT ![slot] = taskCount[slot] + 1]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars, serialVars>>
    /\ UNCHANGED <<taskTeamRetired>>

ScheduleDetachTask(t) ==
    /\ pc[t] \in {"idle", "barrier_tasks"}
    /\ threadState[t] = "active"
    /\ ~cancelled
    /\ ~threadFinished[t]
    /\ \E task \in FreeTasks :
        /\ LET slot == CurrentSlot(t)
               
               theParent == IF \E pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
                            THEN CHOOSE pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
                            ELSE Nil
           IN
           /\ taskRoot' = [taskRoot EXCEPT ![task] = IF theParent = Nil THEN t ELSE taskRoot[theParent]]
           /\ LET root == IF theParent = Nil THEN t ELSE taskRoot[theParent]
              IN pendingTasks' = [pendingTasks EXCEPT ![root] = @ \cup {task}]
           /\ serialOwner' = [serialOwner EXCEPT ![task] = IF inSerial[t] THEN t ELSE Nil]
           /\ taskPhase' = [taskPhase EXCEPT ![task] = "queued"]
           /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]
           /\ taskParent' = [taskParent EXCEPT ![task] = theParent]
           /\ childCount' = IF theParent /= Nil
                            THEN [childCount EXCEPT ![theParent] = childCount[theParent] + 1]
                            ELSE childCount
           /\ taskDetachable' = [taskDetachable EXCEPT ![task] = TRUE]
           /\ eventFulfilled' = [eventFulfilled EXCEPT ![task] = FALSE]
           /\ taskSlot' = [taskSlot EXCEPT ![task] = slot]
           /\ taskCount' = IF inSerial[t] THEN taskCount ELSE [taskCount EXCEPT ![slot] = taskCount[slot] + 1]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars, serialVars>>
    /\ UNCHANGED <<taskTeamRetired>>

ExecuteTask(t) ==
    /\ (pc[t] = "barrier_tasks" \/ (inSerial[t] /\ pc[t] = "idle"))
    /\ threadState[t] = "active"
    /\ LET slot == CurrentSlot(t)
       IN \E task \in (IF inSerial[t] THEN SerialQueuedTasks(t) ELSE QueuedTasks(slot)) :
           /\ taskPhase' = [taskPhase EXCEPT ![task] = "executing"]
           /\ taskOwner' = [taskOwner EXCEPT ![task] = t]
           /\ taskCount' = IF inSerial[t] THEN taskCount ELSE [taskCount EXCEPT ![slot] = taskCount[slot] - 1]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, childCount, taskDetachable, eventFulfilled, taskSlot, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

StealTask(thief, victim) ==
    /\ thief /= victim
    /\ ~inSerial[thief]
    /\ pc[thief] = "barrier_tasks"

    /\ threadState[thief] \in {"active", "stealing", "finished"}
    
    /\ teamValid
    /\ threadState[victim] /= "reaped"
    /\ LET slot == CurrentSlot(thief)
       IN \E task \in QueuedTasks(slot) :
           
           /\ IF threadFinished[thief]
              THEN 
                   /\ unfinished' = [unfinished EXCEPT ![slot] = unfinished[slot] + 1]
                   /\ threadFinished' = [threadFinished EXCEPT ![thief] = FALSE]
              ELSE /\ UNCHANGED <<unfinished, threadFinished>>
           /\ taskPhase' = [taskPhase EXCEPT ![task] = "executing"]
           /\ taskOwner' = [taskOwner EXCEPT ![task] = thief]
           /\ taskCount' = [taskCount EXCEPT ![slot] = taskCount[slot] - 1]
           /\ threadState' = [threadState EXCEPT ![thief] = "active"]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamSlot, taskTeamActive,
                   teamValid, taskParent, childCount, taskDetachable, eventFulfilled, taskSlot, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

CompleteTask(t, task) ==
    /\ pc[t] \in {"barrier_tasks", "idle"}
    /\ taskPhase[task] = "executing"
    /\ taskOwner[task] = t
    /\ ~taskDetachable[task] \/ eventFulfilled[task]  

    /\ pendingTasks' = [pendingTasks EXCEPT ![taskRoot[task]] = @ \ {task}]
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "completed"]
    /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]
    /\ childCount' = IF taskParent[task] /= Nil
                     THEN [childCount EXCEPT ![taskParent[task]] = childCount[taskParent[task]] - 1]
                     ELSE childCount
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, taskDetachable, eventFulfilled, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, serialOwner, taskTeamRetired>>

DetachTask(t, task) ==
    /\ pc[t] \in {"barrier_tasks", "idle"}
    /\ taskPhase[task] = "executing"
    /\ taskOwner[task] = t
    /\ taskDetachable[task]
    /\ ~eventFulfilled[task]  

    /\ taskPhase' = [taskPhase EXCEPT ![task] = "detached"]
    /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]  
    
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, childCount, taskDetachable, eventFulfilled, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

FulfillEvent(task) ==
    /\ taskDetachable[task]
    /\ taskPhase[task] = "detached"
    /\ ~eventFulfilled[task]

    /\ eventFulfilled' = [eventFulfilled EXCEPT ![task] = TRUE]

    /\ taskPhase' = [taskPhase EXCEPT ![task] = "fulfilled"]
    /\ childCount' = IF taskParent[task] /= Nil
                     THEN [childCount EXCEPT ![taskParent[task]] = childCount[taskParent[task]] - 1]
                     ELSE childCount
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskOwner, taskParent, taskDetachable, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

EarlyFulfillEvent(task) ==
    /\ taskDetachable[task]
    /\ taskPhase[task] = "executing"  
    /\ ~eventFulfilled[task]

    /\ eventFulfilled' = [eventFulfilled EXCEPT ![task] = TRUE]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskPhase, taskOwner, taskParent, childCount, taskDetachable, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

ProxyTaskComplete(task) ==
    /\ taskPhase[task] = "fulfilled"
    /\ eventFulfilled[task]
    
    /\ pendingTasks' = [pendingTasks EXCEPT ![taskRoot[task]] = @ \ {task}]
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "completed"]
    /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, childCount, taskDetachable, eventFulfilled, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, serialOwner, taskTeamRetired>>

ThreadFinishTasks(t) ==
    /\ pc[t] = "barrier_tasks"
    /\ threadState[t] = "active"
    /\ ~threadFinished[t]
    /\ pendingTasks[t] = {}
    /\ ~inSerial[t]  
    
    /\ LET slot == CurrentSlot(t)
       IN /\ QueuedTasks(slot) = {}  
          
          /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
          
          /\ unfinished' = [unfinished EXCEPT ![slot] = unfinished[slot] - 1]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = TRUE]
    /\ threadState' = [threadState EXCEPT ![t] = "finished"]

    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamSlot, taskTeamActive,
                   teamValid, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

ThreadFinishTasksWeak(t) ==
    /\ pc[t] = "barrier_tasks"
    /\ threadState[t] \in {"active"}
    /\ ~threadFinished[t]
    /\ pendingTasks[t] = {}
    /\ ~inSerial[t]  
    
    /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"

    /\ LET slot == CurrentSlot(t)
       IN unfinished' = [unfinished EXCEPT ![slot] = unfinished[slot] - 1]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = TRUE]
    /\ threadState' = [threadState EXCEPT ![t] = "finished"]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamSlot, taskTeamActive,
                   teamValid, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

PrimaryTaskTeamWait ==
    /\ pc[Primary] = "barrier_tasks"
    /\ ~cancelled
    /\ taskTeamRetired' = [taskTeamRetired EXCEPT ![CurrentSlot(Primary)] = TRUE]
    /\ threadFinished[Primary]
    /\ ~inSerial[Primary]  
    /\ LET slot == CurrentSlot(Primary)
       IN 
          /\ unfinished[slot] = 0
          
          /\ taskTeamActive' = [taskTeamActive EXCEPT ![slot] = FALSE]
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_task_wait"]
    /\ UNCHANGED <<barrierRound, cancelled, taskTeamSlot, unfinished,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner>>

PrimaryRelease ==
    /\ pc[Primary] = "barrier_task_wait"
    /\ ~cancelled
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_release"]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

WorkerReceiveRelease(t) ==
    /\ t \in Workers
    /\ pc[t] = "barrier_tasks"
    /\ threadFinished[t]
    /\ ~inSerial[t]  
    /\ ~cancelled  
    /\ pc[Primary] \in {"barrier_release", "barrier_sync", "done"}
    /\ pc' = [pc EXCEPT ![t] = "barrier_release"]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

TaskTeamSync(t) ==
    /\ pc[t] = "barrier_release"
    /\ ~inSerial[t]  
    
    /\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = 1 - taskTeamSlot[t]]
    
    /\ pc' = [pc EXCEPT ![t] = "barrier_sync"]
    /\ UNCHANGED <<barrierRound, cancelled, taskTeamActive, unfinished,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

BarrierDone(t) ==
    /\ pc[t] = "barrier_sync"
    /\ pc' = [pc EXCEPT ![t] = "done"]
    /\ threadState' = [threadState EXCEPT ![t] = "active"]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = FALSE]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   teamValid, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

StartNextRound ==
    /\ \A t \in Thread : pc[t] = "done"
    /\ barrierRound' = barrierRound + 1
    /\ pc' = [t \in Thread |-> "idle"]
    /\ cancelled' = FALSE
    /\ threadFinished' = [t \in Thread |-> FALSE]
    /\ threadState' = [t \in Thread |-> "active"]
    /\ taskTeamRetired' = [taskTeamRetired EXCEPT ![taskTeamSlot[Primary]] = FALSE]
    /\ teamValid' = TRUE
    /\ UNCHANGED <<parityVars,
                   taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner>>

CancelBarrier ==
    /\ ~cancelled
    /\ pc[Primary] \in {"barrier_gather", "barrier_tasks"}
    
    /\ \E t \in Workers : InBarrier(t)
    /\ cancelled' = TRUE
    /\ UNCHANGED <<pc, barrierRound, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

PrimaryCancelledBarrier ==
    /\ pc[Primary] \in {"barrier_gather", "barrier_tasks", "barrier_task_wait"}
    /\ cancelled
    /\ pendingTasks[Primary] = {}
    /\ ~\E task \in Task : taskOwner[task] = Primary /\ taskPhase[task] = "executing"
    /\ ~inSerial[Primary]  

    /\ pc' = [pc EXCEPT ![Primary] = "done"]

    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

WorkerCancelledBarrier(t) ==
    /\ t \in Workers
    /\ pc[t] \in {"barrier_gather", "barrier_tasks"}
    /\ cancelled
    /\ pendingTasks[t] = {}
    /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
    /\ ~inSerial[t]  
    
    /\ pc' = [pc EXCEPT ![t] = "done"]
    
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

ReapTeam ==
    /\ pc[Primary] = "done"
    /\ teamValid
    /\ teamValid' = FALSE
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars,
                   threadState, threadFinished, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

ReapThread(t) ==
    /\ t \in Workers
    /\ ~teamValid
    /\ threadState[t] \in {"finished", "active"}
    /\ threadState' = [threadState EXCEPT ![t] = "reaped"]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars,
                   teamValid, threadFinished, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

SerializedParallelEntry(t) ==
    /\ pc[t] \in {"idle", "barrier_tasks"}
    /\ ~inSerial[t]
    /\ threadState[t] = "active"
    
    /\ savedSlot' = [savedSlot EXCEPT ![t] = taskTeamSlot[t]]
    
    /\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = 0]
    /\ inSerial' = [inSerial EXCEPT ![t] = TRUE]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamActive, unfinished,
                   lifecycleVars, taskVars, taskCountVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

SerializedParallelExit(t) ==
    /\ inSerial[t]
    /\ ~\E task \in Task : serialOwner[task] = t /\ LiveTask(task)
    
    /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
    
    /\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = savedSlot[t]]
    /\ savedSlot' = [savedSlot EXCEPT ![t] = Nil]
    /\ inSerial' = [inSerial EXCEPT ![t] = FALSE]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamActive, unfinished,
                   lifecycleVars, taskVars, taskCountVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

CancelQueuedTask(task) ==
    /\ cancelled
    /\ taskPhase[task] = "queued"
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "cancelled"]
    /\ pendingTasks' = [pendingTasks EXCEPT ![taskRoot[task]] = @ \ {task}]
    /\ childCount' = IF taskParent[task] = Nil THEN childCount
                     ELSE [childCount EXCEPT ![taskParent[task]] = @ - 1]
    /\ taskCount' = IF serialOwner[task] # Nil THEN taskCount
                    ELSE [taskCount EXCEPT ![taskSlot[task]] = @ - 1]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskOwner, taskParent, taskDetachable, eventFulfilled, taskSlot,
                   serialVars, taskRoot, serialOwner, taskTeamRetired>>

Next ==
    
    \/ PrimaryEnterBarrier
    \/ \E t \in Workers : WorkerEnterBarrier(t)
    
    \/ \E t \in Workers : WorkerStartTasks(t)
    \/ PrimaryStartTaskWait
    
    \/ \E t \in Thread : ScheduleTask(t)
    \/ \E t \in Thread : ScheduleDetachTask(t)
    
    \/ \E t \in Thread : ExecuteTask(t)
    
    \/ \E thief, victim \in Thread : StealTask(thief, victim)
    
    \/ \E t \in Thread, task \in Task : CompleteTask(t, task)
    
    \/ \E t \in Thread, task \in Task : DetachTask(t, task)
    \/ \E task \in Task : FulfillEvent(task)
    \/ \E task \in Task : EarlyFulfillEvent(task)
    \/ \E task \in Task : ProxyTaskComplete(task)
    
    \/ \E t \in Thread : ThreadFinishTasks(t)
    \/ \E t \in Thread : ThreadFinishTasksWeak(t)
    \/ PrimaryTaskTeamWait
    \/ PrimaryRelease
    \/ \E t \in Workers : WorkerReceiveRelease(t)
    \/ \E t \in Thread : TaskTeamSync(t)
    \/ \E t \in Thread : BarrierDone(t)
    
    \/ StartNextRound
    
    \/ \E task \in Task : CancelQueuedTask(task)
    \/ CancelBarrier
    \/ PrimaryCancelledBarrier
    \/ \E t \in Workers : WorkerCancelledBarrier(t)
    
    \/ ReapTeam
    \/ \E t \in Workers : ReapThread(t)
    
    \/ \E t \in Thread : SerializedParallelEntry(t)
    \/ \E t \in Thread : SerializedParallelExit(t)

Spec == Init /\ [][Next]_allVars

ActiveInBarrier(t) == pc[t] \in {"barrier_gather", "barrier_tasks", "barrier_task_wait"}

ParityConsistency ==
    \A t1, t2 \in Thread :
        (ActiveInBarrier(t1) /\ ActiveInBarrier(t2) /\ ~inSerial[t1] /\ ~inSerial[t2]) =>
        taskTeamSlot[t1] = taskTeamSlot[t2]

ParityRestoredAfterCancel ==

    (\A t \in Thread : pc[t] = "done") /\ cancelled =>
    \A t1, t2 \in Thread : taskTeamSlot[t1] = taskTeamSlot[t2]

ActiveTasksImplyActiveTeam ==
    \A task \in Task :
        (taskPhase[task] = "executing" /\ taskSlot[task] /= Nil) =>
        IF serialOwner[task] = Nil THEN taskTeamActive[taskSlot[task]]
         ELSE inSerial[serialOwner[task]]

NoQueuedTasksAfterDeactivation ==
    \A slot \in {0, 1} :
        taskTeamRetired[slot] =>
        QueuedTasks(slot) \cup PendingProxyTasks(slot) = {}

====

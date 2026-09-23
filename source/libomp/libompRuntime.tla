---- MODULE libompRuntime ----
\* Repaired Specula abstraction of LLVM libomp barrier + tasking interaction
\* Models: task team parity (Family 1), task stealing during transitions (Family 2),
\*         detachable task completion (Family 3), barrier cancellation + parity (Family 5),
\*         nested serial parallel + parity corruption (Family 6)
\*
\* Source: openmp/runtime/src/kmp_barrier.cpp, kmp_tasking.cpp, kmp.h

EXTENDS Integers, FiniteSets, Sequences, TLC

CONSTANTS
    Thread,         \* Set of thread IDs (e.g., {0, 1, 2, 3})
    Task,           \* Set of task IDs (model values)
    MaxBarriers,    \* Maximum barrier rounds
    Nil             \* Sentinel value

ASSUME ThreadDomain == /\ IsFiniteSet(Thread) /\ 0 \in Thread /\ Thread \subseteq Nat
ASSUME TaskDomain == IsFiniteSet(Task)
ASSUME SentinelDistinct == Nil \notin Thread \cup Task
ASSUME RoundDomain == MaxBarriers \in Nat

\* Thread 0 is always the primary thread
Primary == 0
Workers == Thread \ {Primary}
NumThreads == Cardinality(Thread)

\* Task phases (Family 3: detachable task lifecycle)
\* kmp_tasking.cpp: td_flags.started/executing/complete/freed (kmp.h:2747-2750)
TaskPhases == {"free", "queued", "executing", "detached", "fulfilled", "completed", "cancelled"}

\* --------------------------------------------------------------------------
\* Variables
\* --------------------------------------------------------------------------

\* --- Core barrier variables ---
\* Models: kmp_barrier.cpp barrier_template gather/release phases
VARIABLES
    pc,                 \* Thread program counter
    barrierRound,       \* Current barrier round number (bounds exploration)
    cancelled           \* Whether current barrier is cancelled (kmp_team_t::t_cancel_request, kmp.h:3219)

barrierVars == <<pc, barrierRound, cancelled>>

\* --- Task team parity variables (Family 1) ---
\* Models: kmp.h:3157 t_task_team[2], kmp.h:3037 th_task_state
VARIABLES
    taskTeamSlot,       \* taskTeamSlot[t] \in {0, 1}: which slot thread t uses (th_task_state, kmp.h:3037)
    taskTeamActive,     \* taskTeamActive[slot] \in BOOLEAN: is this slot active? (tt_active, kmp.h:2884)
    unfinished          \* unfinished[slot] \in Nat: tt_unfinished_threads per slot (kmp.h:2881)

parityVars == <<taskTeamSlot, taskTeamActive, unfinished>>

\* --- Thread lifecycle variables (Family 2) ---
\* Models: kmp.h:3038-3039 th_reap_state, kmp.h:3045 th_used_in_team
VARIABLES
    threadState,        \* threadState[t] \in {"active", "stealing", "finished", "reaped"}
    teamValid,          \* BOOLEAN: is the team structure still valid?
    threadFinished      \* threadFinished[t] \in BOOLEAN: has thread decremented unfinished? (kmp_tasking.cpp:3331)

lifecycleVars == <<threadState, teamValid, threadFinished>>

\* --- Task variables (Family 3: detachable tasks) ---
\* Models: kmp_taskdata_t (kmp.h:2767-2815)
VARIABLES
    taskPhase,          \* taskPhase[task] \in TaskPhases
    taskOwner,          \* taskOwner[task] \in Thread \cup {Nil}: which thread is working on it
    taskParent,         \* taskParent[task] \in Task \cup {Nil}: parent task
    childCount,         \* childCount[task] \in Nat: td_incomplete_child_tasks (kmp.h:2786)
    taskDetachable,     \* taskDetachable[task] \in BOOLEAN: td_flags.detachable (kmp.h:2732)
    eventFulfilled,     \* eventFulfilled[task] \in BOOLEAN: event.type != KMP_EVENT_ALLOW_COMPLETION
    taskSlot            \* taskSlot[task] \in {0, 1, Nil}: which task team slot this task belongs to

taskVars == <<taskPhase, taskOwner, taskParent, childCount, taskDetachable, eventFulfilled, taskSlot>>

\* --- Task count variables ---
\* Models: tt_found_tasks (kmp.h:2868), task deque state
VARIABLES
    taskCount           \* taskCount[slot] \in Nat: number of queued/executing tasks per slot

taskCountVars == <<taskCount>>

\* --- Serial parallel variables (Family 6: nested serial parallel) ---
\* Models: kmp_runtime.cpp:1290-1349 (__kmp_serialized_parallel)
\* and kmp_csupport.cpp:740-752 (__kmpc_end_serialized_parallel)
VARIABLES
    inSerial,           \* inSerial[t] \in BOOLEAN: is thread in serialized parallel?
    savedSlot           \* savedSlot[t] \in {0, 1, Nil}: saved th_task_state before serial entry

serialVars == <<inSerial, savedSlot>>

\* Task completion obligations remain attached to their implicit-task root
\* until ordinary completion, proxy bottom-half completion, or cancellation.
\* pendingTasks abstracts that accounting as identities instead of a counter.
\* serialOwner separates a nested serial team's slot 0 from the parent team.
\* Retired is set by actual deactivation and cleared when that slot is reopened;
\* it distinguishes a retired team from one that has not been activated yet.
VARIABLES taskRoot, pendingTasks, serialOwner, taskTeamRetired
workVars == <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>
allVars == <<barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars>>

\* --------------------------------------------------------------------------
\* Program counter states
\* --------------------------------------------------------------------------
\* Models the phases of __kmp_barrier_template (kmp_barrier.cpp:1792-2126)
\* and __kmp_fork_barrier/__kmp_join_barrier
PcStates == {
    "idle",                     \* Before barrier entry
    "barrier_gather",           \* In gather phase (kmp_barrier.cpp:1915-1945)
    "barrier_tasks",            \* Executing tasks during barrier wait (kmp_tasking.cpp:3152)
    "barrier_task_wait",        \* Primary waiting for tt_unfinished_threads==0 (kmp_tasking.cpp:4062)
    "barrier_release",          \* In release phase (kmp_barrier.cpp:2028-2066)
    "barrier_sync",             \* Calling __kmp_task_team_sync (kmp_tasking.cpp:4020)
    "done"                      \* Barrier complete, back to idle for next round
}

\* --------------------------------------------------------------------------
\* Helpers
\* --------------------------------------------------------------------------

\* Current task team slot for a thread
CurrentSlot(t) == taskTeamSlot[t]

\* Other task team slot (the one being prepared for next barrier)
OtherSlot(t) == 1 - taskTeamSlot[t]

\* All threads agree on which slot is current
AllSlotsAgree == \A t1, t2 \in Thread :
    (pc[t1] \notin {"done"} /\ pc[t2] \notin {"done"}) =>
    taskTeamSlot[t1] = taskTeamSlot[t2]

\* Count of threads that haven't finished task work in a slot
\* Models: tt_unfinished_threads (kmp.h:2881)
UnfinishedInSlot(slot) == unfinished[slot]

\* Tasks in a given slot
TasksInSlot(slot) == {task \in Task : taskSlot[task] = slot /\ taskPhase[task] \notin {"free", "completed"}}

\* Free tasks available for allocation
FreeTasks == {task \in Task : taskPhase[task] = "free"}

\* Queued tasks in current slot that can be stolen/executed
QueuedTasks(slot) == {task \in Task : taskSlot[task] = slot /\ serialOwner[task] = Nil /\ taskPhase[task] = "queued"}

SerialQueuedTasks(t) == {task \in Task : serialOwner[task] = t /\ taskPhase[task] = "queued"}
PendingProxyTasks(slot) == {task \in Task : serialOwner[task] = Nil /\ taskSlot[task] = slot /\ taskPhase[task] = "fulfilled"}
LiveTask(task) == taskPhase[task] \in {"queued", "executing", "detached", "fulfilled"}

\* Is a thread in the barrier (between gather and done)?
InBarrier(t) == pc[t] \in {"barrier_gather", "barrier_tasks", "barrier_task_wait",
                           "barrier_release", "barrier_sync"}

\* --------------------------------------------------------------------------
\* Init
\* --------------------------------------------------------------------------
Init ==
    \* Barrier state
    /\ pc = [t \in Thread |-> "idle"]
    /\ barrierRound = 0
    /\ cancelled = FALSE
    \* Task team parity (Family 1): all threads start on slot 0
    \* kmp_tasking.cpp:4027 - th_task_state initialized to 0
    /\ taskTeamSlot = [t \in Thread |-> 0]
    /\ taskTeamActive = [slot \in {0, 1} |-> FALSE]
    /\ unfinished = [slot \in {0, 1} |-> 0]
    \* Thread lifecycle (Family 2)
    /\ threadState = [t \in Thread |-> "active"]
    /\ teamValid = TRUE
    /\ threadFinished = [t \in Thread |-> FALSE]
    \* Task state (Family 3)
    /\ taskPhase = [task \in Task |-> "free"]
    /\ taskOwner = [task \in Task |-> Nil]
    /\ taskParent = [task \in Task |-> Nil]
    /\ childCount = [task \in Task |-> 0]
    /\ taskDetachable = [task \in Task |-> FALSE]
    /\ eventFulfilled = [task \in Task |-> FALSE]
    /\ taskSlot = [task \in Task |-> Nil]
    \* Task counts
    /\ taskCount = [slot \in {0, 1} |-> 0]
    \* Serial parallel (Family 6)
    /\ inSerial = [t \in Thread |-> FALSE]
    /\ savedSlot = [t \in Thread |-> Nil]
    /\ taskRoot = [task \in Task |-> Nil]
    /\ pendingTasks = [t \in Thread |-> {}]
    /\ serialOwner = [task \in Task |-> Nil]
    /\ taskTeamRetired = [slot \in {0, 1} |-> FALSE]

\* --------------------------------------------------------------------------
\* Actions
\* --------------------------------------------------------------------------

\* ===== BARRIER ENTRY =====

\* __kmp_barrier_template: primary thread enters barrier
\* kmp_barrier.cpp:1873-1913 (pre-gather setup)
\* Primary calls __kmp_task_team_setup before gather (line 1912-1913)

PrimaryEnterBarrier ==
    /\ pc[Primary] = "idle"
    /\ taskTeamRetired' = [taskTeamRetired EXCEPT ![CurrentSlot(Primary)] = FALSE]
    /\ barrierRound < MaxBarriers
    /\ ~inSerial[Primary]  \* can't enter barrier from serial region
    \* __kmp_task_team_setup (kmp_tasking.cpp:3935-4015)
    \* Initialize the CURRENT slot (th_task_state) for this barrier round
    \* kmp_tasking.cpp:3960: task_team = team->t.t_task_team[this_thr->th.th_task_state]
    /\ LET slot == CurrentSlot(Primary)
       IN /\ taskTeamActive' = [taskTeamActive EXCEPT ![slot] = TRUE]
          \* kmp_tasking.cpp:3728 __kmp_task_team_init: tt_unfinished_threads = team_nth
          /\ unfinished' = [unfinished EXCEPT ![slot] = NumThreads]
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_gather"]
    /\ UNCHANGED <<barrierRound, cancelled, taskTeamSlot,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner>>

\* __kmp_barrier_template: worker thread enters barrier
\* kmp_barrier.cpp:1915-1945 (gather phase - worker side)
WorkerEnterBarrier(t) ==
    /\ t \in Workers
    /\ pc[t] = "idle"
    /\ barrierRound < MaxBarriers
    /\ ~inSerial[t]  \* can't enter barrier from serial region
    /\ pc' = [pc EXCEPT ![t] = "barrier_gather"]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== GATHER COMPLETION =====

\* All threads have entered the barrier gather phase
\* Models: primary detects all workers arrived via b_arrived flags
\* kmp_barrier.cpp:298-306 (gather wait loop)
AllGathered == \A t \in Thread : pc[t] \in {"barrier_gather", "barrier_tasks",
                                             "barrier_task_wait", "barrier_release",
                                             "barrier_sync", "done"}

\* Workers transition from gather to task execution
\* kmp_barrier.cpp:298-306 - while waiting in gather, threads execute tasks
\* kmp_tasking.cpp:3152 - __kmp_execute_tasks_template
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

\* Primary enters task_wait phase after all gathered
\* kmp_barrier.cpp:1949-1953 - primary calls __kmp_task_team_wait
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

\* ===== TASK SCHEDULING =====

\* __kmpc_omp_task: allocate and enqueue a new task
\* kmp_tasking.cpp:1563 - __kmpc_omp_task
\* kmp_tasking.cpp:1501 - __kmp_push_task (push to deque)
ScheduleTask(t) ==
    /\ pc[t] \in {"idle", "barrier_tasks"}
    /\ threadState[t] = "active"
    /\ ~cancelled
    /\ ~threadFinished[t]
    /\ \E task \in FreeTasks :
        /\ LET slot == CurrentSlot(t)
               \* Find parent: the task currently being executed by thread t (if any)
               hasParent == \E pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
               theParent == IF \E pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
                            THEN CHOOSE pt \in Task : taskOwner[pt] = t /\ taskPhase[pt] = "executing"
                            ELSE Nil
           IN
           \* kmp_tasking.cpp:1390-1395 - increment parent's td_incomplete_child_tasks
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

\* Schedule a detachable task (Family 3)
\* kmp_tasking.cpp:1563 with td_flags.detachable = TASK_DETACHABLE
ScheduleDetachTask(t) ==
    /\ pc[t] \in {"idle", "barrier_tasks"}
    /\ threadState[t] = "active"
    /\ ~cancelled
    /\ ~threadFinished[t]
    /\ \E task \in FreeTasks :
        /\ LET slot == CurrentSlot(t)
               \* Find parent: the task currently being executed by thread t (if any)
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

\* ===== TASK EXECUTION =====

\* __kmp_execute_tasks_template: thread picks up a task from its own deque
\* kmp_tasking.cpp:3158-3175 - get task from own deque first
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

\* ===== TASK STEALING (Family 2) =====

\* __kmp_steal_task: thread steals a task from another thread's deque
\* kmp_tasking.cpp:3011-3130
\* Key: lines 3113-3126 - if thread already decremented unfinished, must re-increment
StealTask(thief, victim) ==
    /\ thief /= victim
    /\ ~inSerial[thief]
    /\ pc[thief] = "barrier_tasks"
    \* kmp_tasking.cpp:3296-3417: thread continues stealing loop AFTER thread_finished=TRUE
    \* The loop only exits when tt_unfinished_threads==0 AND thread_finished, not before
    /\ threadState[thief] \in {"active", "stealing", "finished"}
    \* Family 2: check victim is still valid
    /\ teamValid
    /\ threadState[victim] /= "reaped"
    /\ LET slot == CurrentSlot(thief)
       IN \E task \in QueuedTasks(slot) :
           \* kmp_tasking.cpp:3113-3126 - re-increment if thread_finished
           /\ IF threadFinished[thief]
              THEN \* kmp_tasking.cpp:3120 - KMP_ATOMIC_INC(unfinished_threads)
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

\* Family 2: Steal from a reaped thread (BUG PATH)
\* kmp_tasking.cpp:3334-3338 - "unsafe to reference thread->th.th_team"
\* This models the bug where a stealer accesses data from a reaped victim
StealFromReapedThread(thief, victim) ==
    /\ thief /= victim
    /\ pc[thief] = "barrier_tasks"
    /\ threadState[thief] \in {"active", "stealing"}
    \* BUG: victim has been reaped but thief doesn't know
    /\ threadState[victim] = "reaped"
    /\ threadState' = [threadState EXCEPT ![thief] = "stealing"]
    \* This action represents the dangerous read - invariant should catch it
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars,
                   teamValid, threadFinished, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== TASK COMPLETION =====

\* __kmp_task_finish: normal (non-detach) completion path
\* kmp_tasking.cpp:924-970
CompleteTask(t, task) ==
    /\ pc[t] \in {"barrier_tasks", "idle"}
    /\ taskPhase[task] = "executing"
    /\ taskOwner[task] = t
    /\ ~taskDetachable[task] \/ eventFulfilled[task]  \* detachable tasks that got early-fulfilled
    \* kmp_tasking.cpp:925 - td_flags.complete = 1
    \* kmp_tasking.cpp:943 - KMP_ATOMIC_DEC(&td_parent->td_incomplete_child_tasks)
    /\ pendingTasks' = [pendingTasks EXCEPT ![taskRoot[task]] = @ \ {task}]
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "completed"]
    /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]
    /\ childCount' = IF taskParent[task] /= Nil
                     THEN [childCount EXCEPT ![taskParent[task]] = childCount[taskParent[task]] - 1]
                     ELSE childCount
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, taskDetachable, eventFulfilled, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, serialOwner, taskTeamRetired>>

\* ===== DETACHABLE TASK PROTOCOL (Family 3) =====

\* __kmp_task_finish: detach path - task body finishes but event not fulfilled
\* kmp_tasking.cpp:878-906
\* The executing thread sets proxy = TASK_PROXY and gives up ownership
DetachTask(t, task) ==
    /\ pc[t] \in {"barrier_tasks", "idle"}
    /\ taskPhase[task] = "executing"
    /\ taskOwner[task] = t
    /\ taskDetachable[task]
    /\ ~eventFulfilled[task]  \* event not yet fulfilled
    \* kmp_tasking.cpp:888 - td_flags.executing = 0
    \* kmp_tasking.cpp:901 - td_flags.proxy = TASK_PROXY (ownership transfer)
    \* WARNING: kmp_tasking.cpp:898-899 "no access to taskdata after this point"
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "detached"]
    /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]  \* ownership released
    \* NOTE: td_incomplete_child_tasks NOT decremented (deferred to fulfill)
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, childCount, taskDetachable, eventFulfilled, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* __kmp_fulfill_event: external thread fulfills the detach event
\* kmp_tasking.cpp:4378-4423
\* Two sub-cases: task already detached (proxy=TASK_PROXY) or early fulfill
FulfillEvent(task) ==
    /\ taskDetachable[task]
    /\ taskPhase[task] = "detached"
    /\ ~eventFulfilled[task]
    \* kmp_tasking.cpp:4385-4400 - acquire event->lock, check proxy
    \* Since task is "detached", proxy == TASK_PROXY, so detached = true
    \* kmp_tasking.cpp:4399 - event->type = KMP_EVENT_UNINITIALIZED
    /\ eventFulfilled' = [eventFulfilled EXCEPT ![task] = TRUE]
    \* kmp_tasking.cpp:4402-4421 - drive proxy completion
    \* __kmp_first_top_half_finish_proxy (kmp_tasking.cpp:4222-4239)
    \*   - td_flags.complete = 1
    \*   - set PROXY_TASK_FLAG
    \* __kmp_second_top_half_finish_proxy (kmp_tasking.cpp:4241-4252)
    \*   - KMP_ATOMIC_DEC(&td_parent->td_incomplete_child_tasks) (line 4247)
    \*   - clear PROXY_TASK_FLAG
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "fulfilled"]
    /\ childCount' = IF taskParent[task] /= Nil
                     THEN [childCount EXCEPT ![taskParent[task]] = childCount[taskParent[task]] - 1]
                     ELSE childCount
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskOwner, taskParent, taskDetachable, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Early fulfill: event fulfilled while task body is still running
\* kmp_tasking.cpp:4385-4400 - proxy != TASK_PROXY case
EarlyFulfillEvent(task) ==
    /\ taskDetachable[task]
    /\ taskPhase[task] = "executing"  \* task body still running
    /\ ~eventFulfilled[task]
    \* kmp_tasking.cpp:4399 - event->type = KMP_EVENT_UNINITIALIZED
    \* Task finish will later see type != ALLOW_COMPLETION and take normal path
    /\ eventFulfilled' = [eventFulfilled EXCEPT ![task] = TRUE]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskPhase, taskOwner, taskParent, childCount, taskDetachable, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Bottom-half completion of fulfilled proxy task
\* kmp_tasking.cpp:4254-4270 - __kmp_bottom_half_finish_proxy
\* Frees the task after proxy flag is cleared
ProxyTaskComplete(task) ==
    /\ taskPhase[task] = "fulfilled"
    /\ eventFulfilled[task]
    \* kmp_tasking.cpp:4268-4269 - release deps, free task
    /\ pendingTasks' = [pendingTasks EXCEPT ![taskRoot[task]] = @ \ {task}]
    /\ taskPhase' = [taskPhase EXCEPT ![task] = "completed"]
    /\ taskOwner' = [taskOwner EXCEPT ![task] = Nil]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars, lifecycleVars,
                   taskParent, childCount, taskDetachable, eventFulfilled, taskSlot, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, serialOwner, taskTeamRetired>>

\* ===== THREAD FINISH TASK WORK =====

\* __kmp_execute_tasks_template: thread finishes all tasks, decrements unfinished
\* kmp_tasking.cpp:3318-3332
\* Precondition: final_spin AND td_incomplete_child_tasks == 0 AND !thread_finished
ThreadFinishTasks(t) ==
    /\ pc[t] = "barrier_tasks"
    /\ threadState[t] = "active"
    /\ ~threadFinished[t]
    /\ pendingTasks[t] = {}
    /\ ~inSerial[t]  \* can't finish tasks while in serialized parallel
    \* kmp_tasking.cpp:3323 - no incomplete child tasks on implicit task
    /\ LET slot == CurrentSlot(t)
       IN /\ QueuedTasks(slot) = {}  \* no more tasks to execute
          \* No executing tasks owned by this thread
          /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
          \* kmp_tasking.cpp:3327 - KMP_ATOMIC_DEC(unfinished_threads)
          /\ unfinished' = [unfinished EXCEPT ![slot] = unfinished[slot] - 1]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = TRUE]
    /\ threadState' = [threadState EXCEPT ![t] = "finished"]
    \* WARNING: kmp_tasking.cpp:3334-3338
    \* "It is now unsafe to reference thread->th.th_team!!!"
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamSlot, taskTeamActive,
                   teamValid, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Weak variant: thread marks finished when IT couldn't find a task (own deque empty
\* + steal failed), even though tasks may exist in other threads' deques.
\* kmp_tasking.cpp:3376-3394: condition is per-thread "no task found", not global.
\* Both variants check the repaired implicit-task completion accounting.
\* The weak variant still permits a failed local search with other work queued.
ThreadFinishTasksWeak(t) ==
    /\ pc[t] = "barrier_tasks"
    /\ threadState[t] \in {"active"}
    /\ ~threadFinished[t]
    /\ pendingTasks[t] = {}
    /\ ~inSerial[t]  \* can't finish tasks while in serialized parallel
    \* No executing tasks owned by this thread (implicit task children check)
    /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
    \* NOTE: unlike ThreadFinishTasks, does NOT require QueuedTasks(slot) = {}
    \* The thread simply failed to find a task this iteration (CAS failed, victim empty, etc.)
    /\ LET slot == CurrentSlot(t)
       IN unfinished' = [unfinished EXCEPT ![slot] = unfinished[slot] - 1]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = TRUE]
    /\ threadState' = [threadState EXCEPT ![t] = "finished"]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamSlot, taskTeamActive,
                   teamValid, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== PRIMARY TASK TEAM WAIT =====

\* __kmp_task_team_wait: primary waits for tt_unfinished_threads == 0
\* kmp_tasking.cpp:4046-4083
PrimaryTaskTeamWait ==
    /\ pc[Primary] = "barrier_tasks"
    /\ ~cancelled
    /\ taskTeamRetired' = [taskTeamRetired EXCEPT ![CurrentSlot(Primary)] = TRUE]
    /\ threadFinished[Primary]
    /\ ~inSerial[Primary]  \* can't progress barrier while in serialized parallel
    /\ LET slot == CurrentSlot(Primary)
       IN \* kmp_tasking.cpp:4062-4066 - wait for unfinished == 0
          /\ unfinished[slot] = 0
          \* kmp_tasking.cpp:4075-4081 - deactivate old task team
          /\ taskTeamActive' = [taskTeamActive EXCEPT ![slot] = FALSE]
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_task_wait"]
    /\ UNCHANGED <<barrierRound, cancelled, taskTeamSlot, unfinished,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner>>

\* ===== BARRIER RELEASE =====

\* __kmp_barrier_template: release phase
\* kmp_barrier.cpp:2028-2066
\* Primary releases all workers; workers wait on b_go
PrimaryRelease ==
    /\ pc[Primary] = "barrier_task_wait"
    /\ ~cancelled
    /\ pc' = [pc EXCEPT ![Primary] = "barrier_release"]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Workers receive the release signal
\* kmp_barrier.cpp:2033-2061 (worker side of release)
WorkerReceiveRelease(t) ==
    /\ t \in Workers
    /\ pc[t] = "barrier_tasks"
    /\ threadFinished[t]
    /\ ~inSerial[t]  \* can't progress barrier while in serialized parallel
    /\ ~cancelled  \* Workers detect cancellation in release wait spin loop
    /\ pc[Primary] \in {"barrier_release", "barrier_sync", "done"}
    /\ pc' = [pc EXCEPT ![t] = "barrier_release"]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== TASK TEAM SYNC =====

\* __kmp_task_team_sync: toggle th_task_state and pick up new task team
\* kmp_tasking.cpp:4020-4038
\* Called by ALL threads after release phase
\* ASSERT: team != serial_team (line 4084) - NEVER called for serial teams
TaskTeamSync(t) ==
    /\ pc[t] = "barrier_release"
    /\ ~inSerial[t]  \* ASSERT: team != serial_team (kmp_tasking.cpp:4084)
    \* kmp_tasking.cpp:4027 - th_task_state = 1 - th_task_state
    /\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = 1 - taskTeamSlot[t]]
    \* kmp_tasking.cpp:4031-4032 - pick up new task team
    /\ pc' = [pc EXCEPT ![t] = "barrier_sync"]
    /\ UNCHANGED <<barrierRound, cancelled, taskTeamActive, unfinished,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== BARRIER COMPLETION =====

\* Thread completes barrier and returns to idle for next round
BarrierDone(t) ==
    /\ pc[t] = "barrier_sync"
    /\ pc' = [pc EXCEPT ![t] = "done"]
    /\ threadState' = [threadState EXCEPT ![t] = "active"]
    /\ threadFinished' = [threadFinished EXCEPT ![t] = FALSE]
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   teamValid, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== ROUND TRANSITION =====

\* All threads done, advance to next barrier round
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

\* ===== CANCELLATION (Family 5) =====

\* __kmp_barrier_gomp_cancel / cancel parallel
\* kmp_barrier.cpp:2138-2157
\* Cancellation during barrier gather phase
CancelBarrier ==
    /\ ~cancelled
    /\ pc[Primary] \in {"barrier_gather", "barrier_tasks"}
    \* At least one worker must have entered the barrier
    /\ \E t \in Workers : InBarrier(t)
    /\ cancelled' = TRUE
    /\ UNCHANGED <<pc, barrierRound, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Primary detects cancellation and skips task_team_wait and release
\* kmp_barrier.cpp:1951 (!cancelled guard), 2028 (!cancelled guard), 2063 (!cancelled guard)
\* Family 5: parity is NOT toggled after cancelled barrier!
PrimaryCancelledBarrier ==
    /\ pc[Primary] \in {"barrier_gather", "barrier_tasks", "barrier_task_wait"}
    /\ cancelled
    /\ pendingTasks[Primary] = {}
    /\ ~\E task \in Task : taskOwner[task] = Primary /\ taskPhase[task] = "executing"
    /\ ~inSerial[Primary]  \* cancellation detected in barrier template, not inside serial
    \* kmp_barrier.cpp:1951 - skips __kmp_task_team_wait
    \* kmp_barrier.cpp:2028 - skips release
    \* kmp_barrier.cpp:2063 - skips __kmp_task_team_sync
    /\ pc' = [pc EXCEPT ![Primary] = "done"]
    \* Family 5 bug path: task_team_sync is SKIPPED
    \* This means th_task_state is NOT toggled for primary
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Worker detects cancellation and skips sync
\* kmp_barrier.cpp:2149-2150 - revert b_arrived
WorkerCancelledBarrier(t) ==
    /\ t \in Workers
    /\ pc[t] \in {"barrier_gather", "barrier_tasks"}
    /\ cancelled
    /\ pendingTasks[t] = {}
    /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
    /\ ~inSerial[t]  \* cancellation detected in barrier template, not inside serial
    \* Worker also skips task_team_sync
    /\ pc' = [pc EXCEPT ![t] = "done"]
    \* Family 5: worker's th_task_state also NOT toggled
    /\ UNCHANGED <<barrierRound, cancelled, parityVars,
                   lifecycleVars, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== TEAM TEARDOWN (Family 2) =====

\* __kmp_join_barrier: primary frees team while workers may still be active
\* kmp_barrier.cpp:2349-2352: "team data structure may be deallocated"
\* This can only happen after primary has passed the barrier
ReapTeam ==
    /\ pc[Primary] = "done"
    /\ teamValid
    /\ teamValid' = FALSE
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars,
                   threadState, threadFinished, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* Thread gets reaped during team teardown
\* kmp_barrier.cpp:2577-2591 - early exit if g_done
ReapThread(t) ==
    /\ t \in Workers
    /\ ~teamValid
    /\ threadState[t] \in {"finished", "active"}
    /\ threadState' = [threadState EXCEPT ![t] = "reaped"]
    /\ UNCHANGED <<pc, barrierRound, cancelled, parityVars,
                   teamValid, threadFinished, taskVars, taskCountVars, serialVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* ===== SERIALIZED PARALLEL (Family 6) =====

\* __kmp_serialized_parallel: thread enters nested serial parallel region
\* kmp_runtime.cpp:1301 - serial_team->t.t_primary_task_state = th_task_state (SAVE)
\* kmp_runtime.cpp:1343 - th_task_team = NULL
\* kmp_runtime.cpp:1344 - th_task_state = 0 (RESET)
\*
\* Serial teams use ONLY t_task_team[0] (kmp_tasking.cpp:4003-4015)
\* Serial teams NEVER call __kmp_task_team_sync (assert at line 4084)
\*
\* BUG SCENARIO: Thread in parallel with slot=1 enters serial, resets to slot=0.
\* Tasks created in serial go to slot 0. On exit, thread restores to slot=1.
\* The slot 0 tasks are now orphaned in the parallel team's "other" slot.
\* If slot 0 becomes active in next barrier, stale serial tasks appear.
SerializedParallelEntry(t) ==
    /\ pc[t] \in {"idle", "barrier_tasks"}
    /\ ~inSerial[t]
    /\ threadState[t] = "active"
    \* kmp_runtime.cpp:1301 - save th_task_state
    /\ savedSlot' = [savedSlot EXCEPT ![t] = taskTeamSlot[t]]
    \* kmp_runtime.cpp:1344 - th_task_state = 0
    /\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = 0]
    /\ inSerial' = [inSerial EXCEPT ![t] = TRUE]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamActive, unfinished,
                   lifecycleVars, taskVars, taskCountVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* __kmpc_end_serialized_parallel: thread exits serial parallel region
\* kmp_csupport.cpp:748-749 - th_task_state = serial_team->t.t_primary_task_state (RESTORE)
\* kmp_csupport.cpp:751-752 - th_task_team = team->t.t_task_team[th_task_state] (RELOAD)
\*
\* Key: the restored th_task_state points back into the PARENT team's task_team array.
\* If the parent team's slot has changed state (active/inactive/freed) during the serial
\* region, the thread gets a stale/wrong task team reference.
SerializedParallelExit(t) ==
    /\ inSerial[t]
    /\ ~\E task \in Task : serialOwner[task] = t /\ LiveTask(task)
    \* Implicit taskwait at end of parallel region: no executing tasks
    /\ ~\E task \in Task : taskOwner[task] = t /\ taskPhase[task] = "executing"
    \* kmp_csupport.cpp:748 - restore th_task_state
    /\ taskTeamSlot' = [taskTeamSlot EXCEPT ![t] = savedSlot[t]]
    /\ savedSlot' = [savedSlot EXCEPT ![t] = Nil]
    /\ inSerial' = [inSerial EXCEPT ![t] = FALSE]
    /\ UNCHANGED <<pc, barrierRound, cancelled, taskTeamActive, unfinished,
                   lifecycleVars, taskVars, taskCountVars>>
    /\ UNCHANGED <<taskRoot, pendingTasks, serialOwner, taskTeamRetired>>

\* --------------------------------------------------------------------------
\* Next
\* --------------------------------------------------------------------------
\* A cancelled parallel region discards tasks that have not begun execution.
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
    \* Barrier entry
    \/ PrimaryEnterBarrier
    \/ \E t \in Workers : WorkerEnterBarrier(t)
    \* Gather completion
    \/ \E t \in Workers : WorkerStartTasks(t)
    \/ PrimaryStartTaskWait
    \* Task scheduling
    \/ \E t \in Thread : ScheduleTask(t)
    \/ \E t \in Thread : ScheduleDetachTask(t)
    \* Task execution
    \/ \E t \in Thread : ExecuteTask(t)
    \* Task stealing (Family 2)
    \/ \E thief, victim \in Thread : StealTask(thief, victim)
    \* Task completion
    \/ \E t \in Thread, task \in Task : CompleteTask(t, task)
    \* Detachable tasks (Family 3)
    \/ \E t \in Thread, task \in Task : DetachTask(t, task)
    \/ \E task \in Task : FulfillEvent(task)
    \/ \E task \in Task : EarlyFulfillEvent(task)
    \/ \E task \in Task : ProxyTaskComplete(task)
    \* Thread finish & barrier sync
    \/ \E t \in Thread : ThreadFinishTasks(t)
    \/ \E t \in Thread : ThreadFinishTasksWeak(t)
    \/ PrimaryTaskTeamWait
    \/ PrimaryRelease
    \/ \E t \in Workers : WorkerReceiveRelease(t)
    \/ \E t \in Thread : TaskTeamSync(t)
    \/ \E t \in Thread : BarrierDone(t)
    \* Round transition
    \/ StartNextRound
    \* Cancellation (Family 5)
    \/ \E task \in Task : CancelQueuedTask(task)
    \/ CancelBarrier
    \/ PrimaryCancelledBarrier
    \/ \E t \in Workers : WorkerCancelledBarrier(t)
    \* Team teardown (Family 2)
    \/ ReapTeam
    \/ \E t \in Workers : ReapThread(t)
    \* Serialized parallel (Family 6)
    \/ \E t \in Thread : SerializedParallelEntry(t)
    \/ \E t \in Thread : SerializedParallelExit(t)

Spec == Init /\ [][Next]_allVars

\* --------------------------------------------------------------------------
\* Invariants
\* --------------------------------------------------------------------------

\* === Standard Safety ===

\* Type invariant
TypeOK ==
    /\ pc \in [Thread -> PcStates]
    /\ barrierRound \in 0..MaxBarriers
    /\ cancelled \in BOOLEAN
    /\ taskTeamSlot \in [Thread -> {0, 1}]
    /\ taskTeamActive \in [{0, 1} -> BOOLEAN]
    /\ unfinished \in [{0, 1} -> Int]
    /\ threadState \in [Thread -> {"active", "stealing", "finished", "reaped"}]
    /\ teamValid \in BOOLEAN
    /\ threadFinished \in [Thread -> BOOLEAN]
    /\ taskPhase \in [Task -> TaskPhases]
    /\ taskOwner \in [Task -> Thread \cup {Nil}]
    /\ taskParent \in [Task -> Task \cup {Nil}]
    /\ childCount \in [Task -> Int]
    /\ taskDetachable \in [Task -> BOOLEAN]
    /\ eventFulfilled \in [Task -> BOOLEAN]
    /\ taskSlot \in [Task -> {0, 1, Nil}]
    /\ taskCount \in [{0, 1} -> Int]
    /\ inSerial \in [Thread -> BOOLEAN]
    /\ savedSlot \in [Thread -> {0, 1, Nil}]
    /\ taskRoot \in [Task -> Thread \cup {Nil}]
    /\ pendingTasks \in [Thread -> SUBSET Task]
    /\ serialOwner \in [Task -> Thread \cup {Nil}]
    /\ taskTeamRetired \in [{0, 1} -> BOOLEAN]

\* === Extension Invariants (Bug Family targets) ===

\* Family 1: All threads actively working in the barrier must agree on which slot is current
\* kmp_tasking.cpp:4152-4155 - debug assert th_task_team == t_task_team[th_task_state]
\* Excludes release/sync phases where threads toggle one-by-one (transient disagreement is expected)
\* Excludes threads in serial parallel (they have reset slot to 0)
ActiveInBarrier(t) == pc[t] \in {"barrier_gather", "barrier_tasks", "barrier_task_wait"}

ParityConsistency ==
    \A t1, t2 \in Thread :
        (ActiveInBarrier(t1) /\ ActiveInBarrier(t2) /\ ~inSerial[t1] /\ ~inSerial[t2]) =>
        taskTeamSlot[t1] = taskTeamSlot[t2]

\* Family 1: tt_unfinished_threads never goes negative
\* kmp_tasking.cpp:3327 - KMP_ATOMIC_DEC
UnfinishedNonNegative ==
    /\ unfinished[0] >= 0
    /\ unfinished[1] >= 0

\* Family 2: No thread decrements tt_unfinished_threads more than once
\* kmp_tasking.cpp:3331 - thread_finished = TRUE prevents double decrement
UnfinishedExactlyOnce ==
    \A t \in Thread :
        (threadFinished[t] /\ threadState[t] = "finished") =>
        ~(\E t2 \in Thread : t2 /= t /\ threadFinished[t2] /\ threadState[t2] = "finished"
           /\ unfinished[CurrentSlot(t)] < 0)

\* Family 2: No thread accesses victim data after victim's team is freed
\* kmp_tasking.cpp:3334-3338 - "unsafe to reference thread->th.th_team"
NoAccessAfterReap ==
    \A t \in Thread :
        threadState[t] = "stealing" =>
        \A victim \in Thread :
            victim /= t => threadState[victim] /= "reaped"

\* Family 3: Ownership exclusivity - after detach, only fulfiller accesses taskdata
\* kmp_tasking.cpp:898-899 - "no access to taskdata after this point"
OwnershipExclusive ==
    \A task \in Task :
        taskPhase[task] = "detached" =>
        taskOwner[task] = Nil

\* Family 3: Child count consistency - never negative
ChildCountNonNegative ==
    \A task \in Task : childCount[task] >= 0

\* Family 3: Task count consistency
TaskCountNonNegative ==
    /\ taskCount[0] >= 0
    /\ taskCount[1] >= 0

\* Family 5: After a cancelled barrier where sync was skipped,
\* parity must still be consistent for the next barrier
\* kmp_barrier.cpp:2063 - sync skipped when cancelled
ParityRestoredAfterCancel ==
    \* If we're in "done" state and barrier was cancelled, all threads
    \* should still have consistent slots (since none toggled)
    (\A t \in Thread : pc[t] = "done") /\ cancelled =>
    \A t1, t2 \in Thread : taskTeamSlot[t1] = taskTeamSlot[t2]

\* === Shutdown Race Invariants (Direction 2: fork/join steal race) ===

\* Executing tasks retain a live parallel team or their owning serial region.
\* Violation means: primary deactivated the task team while a worker was still executing.
\* This is the D28377 pattern: steal-after-finish races with task_team_wait.
ActiveTasksImplyActiveTeam ==
    \A task \in Task :
        (taskPhase[task] = "executing" /\ taskSlot[task] /= Nil) =>
        IF serialOwner[task] = Nil THEN taskTeamActive[taskSlot[task]]
         ELSE inSerial[serialOwner[task]]

\* A retired parallel task team contains neither queued work nor a pending
\* proxy bottom half. Inactive slots that are open for the next round may
\* receive work before setup activates them.
NoQueuedTasksAfterDeactivation ==
    \A slot \in {0, 1} :
        taskTeamRetired[slot] =>
        QueuedTasks(slot) \cup PendingProxyTasks(slot) = {}

\* === Family 6: Serial Parallel Invariants ===

\* After exiting serial parallel, the thread's restored slot must match
\* what the parallel team expects. If other threads are active in the barrier
\* at a different slot, the restoring thread is out of sync.
\* This catches parity corruption from save/reset/restore across serial regions.
SerialExitParityConsistent ==
    \A t1, t2 \in Thread :
        \* Thread t1 just exited serial (or is in serial with saved slot)
        \* Thread t2 is active in barrier with known-good slot
        (ActiveInBarrier(t1) /\ ActiveInBarrier(t2) /\ ~inSerial[t1] /\ ~inSerial[t2]) =>
        taskTeamSlot[t1] = taskTeamSlot[t2]

\* Tasks created during serial parallel (using slot 0) should not remain
\* active/queued when the thread returns to a different slot.
\* This catches task orphaning when serial tasks leak into the parallel team's slot.
SerialTasksNotOrphaned ==
    \A t \in Thread :
        \A task \in Task :
            \* Thread t created a task in slot 0 during serial, then restored to slot 1
            \* The task is still active but in the wrong slot for the thread
            (taskOwner[task] = t /\ taskPhase[task] = "executing" /\
             taskSlot[task] /= Nil /\ ~inSerial[t] /\ taskTeamSlot[t] /= taskSlot[task]) =>
            FALSE  \* This should never happen

\* === Structural Invariants ===

\* Barrier round is bounded
RoundBound == barrierRound <= MaxBarriers

\* Task phase consistency: completed tasks have no owner
CompletedTasksNoOwner ==
    \A task \in Task : taskPhase[task] = "completed" => taskOwner[task] = Nil

\* Free tasks have no owner
FreeTasksNoOwner ==
    \A task \in Task : taskPhase[task] = "free" => taskOwner[task] = Nil
====

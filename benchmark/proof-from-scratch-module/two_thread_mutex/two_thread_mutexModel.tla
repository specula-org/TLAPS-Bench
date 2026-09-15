-------------------------- MODULE two_thread_mutexModel -------------------------
EXTENDS TLAPS

VARIABLES lock, threads

vars == << lock, threads >>

Tid == {"A", "B"}

Init ==
  /\ lock = FALSE
  /\ threads = [tid \in Tid |-> "Waiting"]

Acquire(tid) ==
  /\ tid \in Tid
  /\ lock = FALSE
  /\ threads[tid] = "Waiting"
  /\ lock' = TRUE
  /\ threads' = [threads EXCEPT ![tid] = "Holding"]

Release(tid) ==
  /\ tid \in Tid
  /\ threads[tid] = "Holding"
  /\ lock' = FALSE
  /\ threads' = [threads EXCEPT ![tid] = "Terminated"]

Next ==
  \/ \E tid \in Tid : Acquire(tid)
  \/ \E tid \in Tid : Release(tid)

Spec ==
  /\ Init
  /\ [][Next]_vars
  /\ \A tid \in Tid :
       /\ WF_vars(Acquire(tid))
       /\ WF_vars(Release(tid))

=============================================================================

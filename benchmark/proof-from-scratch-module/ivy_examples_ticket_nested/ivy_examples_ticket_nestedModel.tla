---------------------- MODULE ivy_examples_ticket_nestedModel ----------------------
EXTENDS Naturals, TLAPS

CONSTANT Thread

ASSUME ThreadAssumption == Thread # {}

VARIABLES pc, service, next_ticket, m, c

vars == << pc, service, next_ticket, m, c >>

Init ==
  /\ pc = [t \in Thread |-> "Idle"]
  /\ service = 0
  /\ next_ticket = 0
  /\ m = [t \in Thread |-> 0]
  /\ c = [t \in Thread |-> 0]

TakeTicket(t) ==
  /\ t \in Thread
  /\ pc[t] = "Idle"
  /\ pc' = [pc EXCEPT ![t] = "Waiting"]
  /\ next_ticket' = next_ticket + 1
  /\ m' = [m EXCEPT ![t] = next_ticket]
  /\ UNCHANGED << service, c >>

EnterCritical(t, k) ==
  /\ t \in Thread
  /\ k \in Nat
  /\ pc[t] = "Waiting"
  /\ m[t] = k
  /\ k <= service
  /\ pc' = [pc EXCEPT ![t] = "Critical"]
  /\ c' = [c EXCEPT ![t] = next_ticket]
  /\ UNCHANGED << service, next_ticket, m >>

RunNestedTask(t, k) ==
  /\ t \in Thread
  /\ k \in Nat
  /\ pc[t] = "Critical"
  /\ c[t] = k + 1
  /\ c' = [c EXCEPT ![t] = k]
  /\ UNCHANGED << pc, service, next_ticket, m >>

LeaveCritical(t) ==
  /\ t \in Thread
  /\ pc[t] = "Critical"
  /\ c[t] = 0
  /\ pc' = [pc EXCEPT ![t] = "Idle"]
  /\ service' = service + 1
  /\ UNCHANGED << next_ticket, m, c >>

Step(t) ==
  \/ TakeTicket(t)
  \/ \E k \in Nat : EnterCritical(t, k)
  \/ \E k \in Nat : RunNestedTask(t, k)
  \/ LeaveCritical(t)

Next ==
  \E t \in Thread : Step(t)

SafetySpec ==
  /\ Init
  /\ [][Next]_vars

=============================================================================

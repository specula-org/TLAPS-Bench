------------------------- MODULE ivy_examples_ticketModel -------------------------
EXTENDS Naturals, TLAPS

CONSTANT Thread

ASSUME ThreadAssumption == Thread # {}

VARIABLES pc, service, next_ticket, m

vars == << pc, service, next_ticket, m >>

Init ==
  /\ pc = [t \in Thread |-> "Idle"]
  /\ service = 0
  /\ next_ticket = 0
  /\ m = [t \in Thread |-> 0]

TakeTicket(t) ==
  /\ t \in Thread
  /\ pc[t] = "Idle"
  /\ pc' = [pc EXCEPT ![t] = "Waiting"]
  /\ service' = service
  /\ next_ticket' = next_ticket + 1
  /\ m' = [m EXCEPT ![t] = next_ticket]

EnterCritical(t, k) ==
  /\ t \in Thread
  /\ k \in Nat
  /\ pc[t] = "Waiting"
  /\ m[t] = k
  /\ k <= service
  /\ pc' = [pc EXCEPT ![t] = "Critical"]
  /\ UNCHANGED << service, next_ticket, m >>

LeaveCritical(t) ==
  /\ t \in Thread
  /\ pc[t] = "Critical"
  /\ pc' = [pc EXCEPT ![t] = "Idle"]
  /\ service' = service + 1
  /\ next_ticket' = next_ticket
  /\ m' = m

Step(t) ==
  \/ TakeTicket(t)
  \/ \E k \in Nat : EnterCritical(t, k)
  \/ LeaveCritical(t)

Next ==
  \E t \in Thread : Step(t)

SafetySpec ==
  /\ Init
  /\ [][Next]_vars

=============================================================================

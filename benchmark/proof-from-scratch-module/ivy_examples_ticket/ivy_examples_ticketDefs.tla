------------------------- MODULE ivy_examples_ticketDefs -------------------------
EXTENDS ivy_examples_ticketModel

Spec ==
  /\ SafetySpec
  /\ \A t \in Thread : WF_vars(Step(t))

MutualExclusion ==
  \A t1, t2 \in Thread :
    (pc[t1] = "Critical" /\ pc[t2] = "Critical") => t1 = t2

NonStarvation ==
  \A t \in Thread : (pc[t] = "Waiting") ~> (pc[t] = "Critical")

=============================================================================

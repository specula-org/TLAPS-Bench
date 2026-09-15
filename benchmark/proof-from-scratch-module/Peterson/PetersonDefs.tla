--------------------------- MODULE PetersonDefs  ----------------------------

EXTENDS PetersonModel

MutualExclusion == ~(pc[0] = "cs"  /\ pc[1] = "cs")

Wait(i) == (pc[0] = "a3a") \/ (pc[0] = "a3b")
CS(i) == pc[i] = "cs"
Fairness == WF_vars(proc(0)) /\ WF_vars(proc(1))
FairSpec == Spec /\ Fairness
Liveness == (Wait(0) ~> CS(0)) /\ (Wait(1) ~> CS(1))

=============================================================================

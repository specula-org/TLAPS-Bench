--------------------------------- MODULE Lock ---------------------------------

EXTENDS Integers, TLAPS

VARIABLES pc, lock

vars == << pc, lock >>

ProcSet == (1..2)

Init == 
        /\ lock = 1
        /\ pc = [self \in ProcSet |-> "l0"]

l0(self) == /\ pc[self] = "l0"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "l1"]
            /\ lock' = lock

l1(self) == /\ pc[self] = "l1"
            /\ lock = 1
            /\ lock' = 0
            /\ pc' = [pc EXCEPT ![self] = "cs"]

cs(self) == /\ pc[self] = "cs"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "l2"]
            /\ lock' = lock

l2(self) == /\ pc[self] = "l2"
            /\ lock' = 1
            /\ pc' = [pc EXCEPT ![self] = "l0"]

-------------------------------------------------------------------------------

===============================================================================

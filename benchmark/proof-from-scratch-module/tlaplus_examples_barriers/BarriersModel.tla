------------------------------- MODULE BarriersModel -------------------------------

EXTENDS TLAPS, Integers, FiniteSets, FiniteSetTheorems

CONSTANTS
  N

VARIABLES pc, lock, gate_1, gate_2, rdv

vars == << pc, lock, gate_1, gate_2, rdv >>

ProcSet == (1..N)

Init == 
        /\ lock = 1
        /\ gate_1 = 0
        /\ gate_2 = 0
        /\ rdv = 0
        /\ pc = [self \in ProcSet |-> "a0"]

a0(self) == /\ pc[self] = "a0"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "a1"]
            /\ UNCHANGED << lock, gate_1, gate_2, rdv >>

a1(self) == /\ pc[self] = "a1"
            /\ lock = 1
            /\ lock' = 0
            /\ pc' = [pc EXCEPT ![self] = "a2"]
            /\ UNCHANGED << gate_1, gate_2, rdv >>

a2(self) == /\ pc[self] = "a2"
            /\ rdv' = rdv + 1
            /\ pc' = [pc EXCEPT ![self] = "a3"]
            /\ UNCHANGED << lock, gate_1, gate_2 >>

a3(self) == /\ pc[self] = "a3"
            /\ IF rdv = N
                  THEN /\ pc' = [pc EXCEPT ![self] = "a4"]
                  ELSE /\ pc' = [pc EXCEPT ![self] = "a5"]
            /\ UNCHANGED << lock, gate_1, gate_2, rdv >>

a4(self) == /\ pc[self] = "a4"
            /\ gate_1' = gate_1 + N
            /\ pc' = [pc EXCEPT ![self] = "a5"]
            /\ UNCHANGED << lock, gate_2, rdv >>

a5(self) == /\ pc[self] = "a5"
            /\ lock' = 1
            /\ pc' = [pc EXCEPT ![self] = "a6"]
            /\ UNCHANGED << gate_1, gate_2, rdv >>

a6(self) == /\ pc[self] = "a6"
            /\ gate_1 > 0
            /\ gate_1' = gate_1 - 1
            /\ pc' = [pc EXCEPT ![self] = "a7"]
            /\ UNCHANGED << lock, gate_2, rdv >>

a7(self) == /\ pc[self] = "a7"
            /\ lock = 1
            /\ lock' = 0
            /\ pc' = [pc EXCEPT ![self] = "a8"]
            /\ UNCHANGED << gate_1, gate_2, rdv >>

a8(self) == /\ pc[self] = "a8"
            /\ rdv' = rdv - 1
            /\ pc' = [pc EXCEPT ![self] = "a9"]
            /\ UNCHANGED << lock, gate_1, gate_2 >>

a9(self) == /\ pc[self] = "a9"
            /\ IF rdv = 0
                  THEN /\ pc' = [pc EXCEPT ![self] = "a10"]
                  ELSE /\ pc' = [pc EXCEPT ![self] = "a11"]
            /\ UNCHANGED << lock, gate_1, gate_2, rdv >>

a10(self) == /\ pc[self] = "a10"
             /\ gate_2' = gate_2 + N
             /\ pc' = [pc EXCEPT ![self] = "a11"]
             /\ UNCHANGED << lock, gate_1, rdv >>

a11(self) == /\ pc[self] = "a11"
             /\ lock' = 1
             /\ pc' = [pc EXCEPT ![self] = "a12"]
             /\ UNCHANGED << gate_1, gate_2, rdv >>

a12(self) == /\ pc[self] = "a12"
             /\ gate_2 > 0
             /\ gate_2' = gate_2 - 1
             /\ pc' = [pc EXCEPT ![self] = "a0"]
             /\ UNCHANGED << lock, gate_1, rdv >>

proc(self) == a0(self) \/ a1(self) \/ a2(self) \/ a3(self) \/ a4(self)
                 \/ a5(self) \/ a6(self) \/ a7(self) \/ a8(self)
                 \/ a9(self) \/ a10(self) \/ a11(self) \/ a12(self)

Next == (\E self \in 1..N: proc(self))

Spec == Init /\ [][Next]_vars

ASSUME N_Assumption == N \in Nat \ {0} 

===============================================================================

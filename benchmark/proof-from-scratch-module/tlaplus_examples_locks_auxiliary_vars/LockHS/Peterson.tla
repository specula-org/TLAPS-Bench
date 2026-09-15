------------------------------- MODULE Peterson -------------------------------

EXTENDS Integers, TLAPS

Other(p) == IF p = 1 THEN 2 ELSE 1 

VARIABLES pc, c, turn

vars == << pc, c, turn >>

ProcSet == (1..2)

Init == 
        /\ c = [self \in ProcSet |-> FALSE]
        /\ turn = 1
        /\ pc = [self \in ProcSet |-> "a0"]

a0(self) == /\ pc[self] = "a0"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "a1"]
            /\ UNCHANGED << c, turn >>

a1(self) == /\ pc[self] = "a1"
            /\ c' = [c EXCEPT ![self] = TRUE]
            /\ pc' = [pc EXCEPT ![self] = "a2"]
            /\ turn' = turn

a2(self) == /\ pc[self] = "a2"
            /\ turn' = Other(self)
            /\ pc' = [pc EXCEPT ![self] = "a3"]
            /\ c' = c

a3(self) == /\ pc[self] = "a3"
            /\ ~c[Other(self)] \/ turn = self
            /\ pc' = [pc EXCEPT ![self] = "cs"]
            /\ UNCHANGED << c, turn >>

cs(self) == /\ pc[self] = "cs"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "a4"]
            /\ UNCHANGED << c, turn >>

a4(self) == /\ pc[self] = "a4"
            /\ c' = [c EXCEPT ![self] = FALSE]
            /\ pc' = [pc EXCEPT ![self] = "a0"]
            /\ turn' = turn

proc(self) == a0(self) \/ a1(self) \/ a2(self) \/ a3(self) \/ cs(self)
                 \/ a4(self)

Next == (\E self \in 1..2: proc(self))

Spec == Init /\ [][Next]_vars

pc_translation(label) ==
  CASE (label = "a0") -> "l0"
    [] (label \in {"a1", "a2", "a3"}) -> "l1"
    [] (label \in {"cs"}) -> "cs"
    [] (label \in {"a4"}) -> "l2"

lock_translation == IF \E p \in ProcSet : pc[p] \in {"cs", "a4"} THEN 0 ELSE 1

L == INSTANCE Lock
     WITH pc <- [p \in ProcSet |-> pc_translation(pc[p])], 
     lock <- lock_translation

-------------------------------------------------------------------------------

===============================================================================

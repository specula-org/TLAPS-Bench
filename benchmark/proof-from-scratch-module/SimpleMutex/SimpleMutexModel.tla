----------------------------- MODULE SimpleMutexModel -----------------------------
EXTENDS Integers, TLAPS

VARIABLES trying, pc

vars == << trying, pc >>

ProcSet == ({0,1})

Init == 
        /\ trying = [i \in {0,1} |-> FALSE]
        /\ pc = [self \in ProcSet |-> CASE self \in {0,1} -> "a"]

a(self) == /\ pc[self] = "a"
           /\ trying' = [trying EXCEPT ![self] = TRUE]
           /\ pc' = [pc EXCEPT ![self] = "b"]

b(self) == /\ pc[self] = "b"
           /\ ~trying[1 - self]
           /\ pc' = [pc EXCEPT ![self] = "cs"]
           /\ UNCHANGED trying

cs(self) == /\ pc[self] = "cs"
            /\ TRUE
            /\ pc' = [pc EXCEPT ![self] = "Done"]
            /\ UNCHANGED trying

p(self) == a(self) \/ b(self) \/ cs(self)

Next == (\E self \in {0,1}: p(self))
           \/ 
              ((\A self \in ProcSet: pc[self] = "Done") /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

=============================================================================

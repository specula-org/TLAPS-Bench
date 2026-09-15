---------------------------- MODULE FindHighestModel -----------------------------

EXTENDS Sequences, Naturals, Integers, TLAPS

VARIABLES f, h, i, pc

max(a, b) == IF a >= b THEN a ELSE b

vars == << f, h, i, pc >>

Init == 
        /\ f \in Seq(Nat)
        /\ h = -1
        /\ i = 1
        /\ pc = "lb"

lb == /\ pc = "lb"
      /\ IF i <= Len(f)
            THEN /\ h' = max(h, f[i])
                 /\ i' = i + 1
                 /\ pc' = "lb"
            ELSE /\ pc' = "Done"
                 /\ UNCHANGED << h, i >>
      /\ f' = f

Terminating == pc = "Done" /\ UNCHANGED vars

Next == lb
           \/ Terminating

Spec == Init /\ [][Next]_vars

=============================================================================


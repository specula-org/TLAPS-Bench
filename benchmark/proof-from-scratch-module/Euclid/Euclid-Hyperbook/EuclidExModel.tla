------------------------------ MODULE EuclidExModel ------------------------------
EXTENDS GCD, TLAPS
CONSTANTS M, N
ASSUME MNPosInt == 
    /\ M \in Nat \ {0}
    /\ N \in Nat \ {0}

VARIABLES x, y, pc

vars == << x, y, pc >>

Init == 
        /\ x = M
        /\ y = N
        /\ pc = "Lbl_1"

Lbl_1 == /\ pc = "Lbl_1"
         /\ IF x # y
               THEN /\ IF x < y
                          THEN /\ y' = y - x
                               /\ x' = x
                          ELSE /\ x' = x - y
                               /\ y' = y
                    /\ pc' = "Lbl_1"
               ELSE /\ pc' = "Done"
                    /\ UNCHANGED << x, y >>

Next == Lbl_1 
           \/ (pc = "Done" /\ UNCHANGED vars)

Spec == Init /\ [][Next]_vars

=============================================================================


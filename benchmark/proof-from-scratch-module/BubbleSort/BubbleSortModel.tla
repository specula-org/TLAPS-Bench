----------------------------- MODULE BubbleSortModel -----------------------------

EXTENDS Integers, TLAPS, TLC

CONSTANT N
ASSUME NAssumption == N \in Nat /\ N >= 1

VARIABLES A, A0, i, j, pc

vars == << A, A0, i, j, pc >>

Init == 
        /\ A \in [1..N -> Int]
        /\ A0 = A
        /\ i = 1
        /\ j = 1
        /\ pc = "Lbl_1"

Lbl_1 == /\ pc = "Lbl_1"
         /\ IF i < N
               THEN /\ j' = i+1
                    /\ pc' = "Lbl_2"
               ELSE /\ pc' = "Done"
                    /\ j' = j
         /\ UNCHANGED << A, A0, i >>

Lbl_2 == /\ pc = "Lbl_2"
         /\ IF j > 1  /\  A[j-1] > A[j]
               THEN /\ A' = [A EXCEPT ![j-1] = A[j],
                                      ![j] = A[j-1]]
                    /\ j' = j-1
                    /\ pc' = "Lbl_2"
                    /\ i' = i
               ELSE /\ i' = i+1
                    /\ pc' = "Lbl_1"
                    /\ UNCHANGED << A, j >>
         /\ A0' = A0

Next == Lbl_1 \/ Lbl_2
           \/ 
              (pc = "Done" /\ UNCHANGED vars)

Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(Next)

=============================================================================


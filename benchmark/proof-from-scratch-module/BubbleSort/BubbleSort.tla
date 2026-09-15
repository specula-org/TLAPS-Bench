---- MODULE BubbleSort ----
EXTENDS BubbleSortDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM IsPermOfExchange == 
           \A A1 \in [1..N -> Int],  i1, j1 \in 1..N :
             /\ [A1 EXCEPT ![i1] = A1[j1], ![j1] = A1[i1]] \in [1..N -> Int]
             /\ IsPermOf([A1 EXCEPT ![i1] = A1[j1], ![j1] = A1[i1]], A1)
\* BEGIN AGENT PROOF BubbleSort/BubbleSort_IsPermOfExchange.tla
PROOF OMITTED
\* END AGENT PROOF BubbleSort/BubbleSort_IsPermOfExchange.tla

THEOREM IsPermOfTransitive == 
          \A A1, B, C \in [1..N -> Int] : 
             IsPermOf(A1, B) /\ IsPermOf(B, C) => IsPermOf(A1, C)
\* BEGIN AGENT PROOF BubbleSort/BubbleSort_IsPermOfTransitive.tla
PROOF OMITTED
\* END AGENT PROOF BubbleSort/BubbleSort_IsPermOfTransitive.tla

THEOREM Spec => [](pc = "Done" => IsSorted(A) /\ IsPermOf(A, A0))
\* BEGIN AGENT PROOF BubbleSort/BubbleSort_line202.tla
PROOF OMITTED
\* END AGENT PROOF BubbleSort/BubbleSort_line202.tla
====

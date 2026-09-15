----------------------------- MODULE Sailfish_LivenessCorrectDefs -----------------------------

EXTENDS SailfishModel

INSTANCE BlockDag 

Liveness == \A r \in R : r >= GST /\ Leader(r) \notin F =>
    \A n \in N \ F : round[n] >= r+2 =>
        \E i \in DOMAIN log[n] : log[n][i] = LeaderVertex(r)

===========================================================================

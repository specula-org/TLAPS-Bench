----------------------------- MODULE ConsensusModel ------------------------------
EXTENDS Sets, TLAPS
CONSTANT Value  
VARIABLE chosen 
Init == chosen = {}

Next == 
    /\ chosen = {}
    /\ \E v \in Value : chosen' = {v}

Spec == Init /\ [][Next]_chosen
=============================================================================

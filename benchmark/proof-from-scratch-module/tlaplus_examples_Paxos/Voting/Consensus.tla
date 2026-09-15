----------------------------- MODULE Consensus ------------------------------ 
EXTENDS Naturals, FiniteSets, TLAPS, FiniteSetTheorems

CONSTANT Value 

VARIABLE chosen

Init == chosen = {}

Next == /\ chosen = {}
        /\ \E v \in Value : chosen' = {v}

Spec == Init /\ [][Next]_chosen 
-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

ASSUME ValuesNonempty == Value # {}

=============================================================================

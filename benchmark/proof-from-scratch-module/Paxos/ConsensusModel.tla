----------------------------- MODULE ConsensusModel -----------------------------

EXTENDS Naturals, FiniteSets, TLAPS
CONSTANTS Values 

VARIABLES chosen 

Init == chosen = {}

Next == /\ chosen = {}
        /\ \E v \in Values : chosen' = {v}
        
Spec == Init /\ [][Next]_chosen

=============================================================================


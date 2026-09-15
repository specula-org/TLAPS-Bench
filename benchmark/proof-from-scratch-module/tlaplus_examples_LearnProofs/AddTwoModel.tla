------------------------------ MODULE AddTwoModel --------------------------------

EXTENDS Naturals, TLAPS

VARIABLE x

vars == << x >>

Init == 
        /\ x = 0

Next == x' = x + 2

Spec == Init /\ [][Next]_vars

=============================================================================


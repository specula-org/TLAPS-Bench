--------------------- MODULE MissionariesAndCannibals_proofModel ------------------

EXTENDS MissionariesAndCannibals, TLAPS

vars == <<bank_of_boat, who_is_on_bank>>
Spec == Init /\ [][Next]_vars

============================================================================

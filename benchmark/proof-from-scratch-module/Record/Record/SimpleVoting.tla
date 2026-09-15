---------------------------- MODULE SimpleVoting ----------------------------
EXTENDS Naturals
-----------------------------------------------------------------------------
CONSTANT Participant

VARIABLE maxBal

-----------------------------------------------------------------------------
Init == maxBal = [p \in Participant |-> 0]

IncreaseMaxBal(p, b) ==
  /\ maxBal[p] < b
  /\ maxBal' = [maxBal EXCEPT ![p] = b]
-----------------------------------------------------------------------------
Next == \E p \in Participant, b \in Nat : IncreaseMaxBal(p, b)

Spec == Init /\ [][Next]_maxBal
=============================================================================


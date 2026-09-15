------------------------------- MODULE VotingDefs -------------------------------

EXTENDS VotingModel

ChosenAt(b, v) == \E Q \in Quorum : 
                     \A a \in Q : VotedFor(a, b, v)

chosen == {v \in Value : \E b \in Ballot : ChosenAt(b, v)}

C == INSTANCE Consensus

=============================================================================


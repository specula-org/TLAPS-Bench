------------------------------ MODULE VotingDefs -------------------------------

EXTENDS VotingModel

TypeOK == 
   /\ votes  \in [Acceptor -> SUBSET (Ballot \X Value)]
   /\ maxBal \in [Acceptor -> Ballot \cup {-1}]

ChosenAt(b, v) == 
   \E Q \in Quorum : \A a \in Q : VotedFor(a, b, v)

chosen == {v \in Value : \E b \in Ballot : ChosenAt(b, v)}

CannotVoteAt(a, b) == /\ maxBal[a] > b
                      /\ DidNotVoteAt(a, b)

NoneOtherChoosableAt(b, v) == 
   \E Q \in Quorum : 
      \A a \in Q : VotedFor(a, b, v) \/ CannotVoteAt(a, b)

SafeAt(b, v) == \A c \in 0..(b-1) : NoneOtherChoosableAt(c, v)

OneValuePerBallot ==  
    \A a1, a2 \in Acceptor, b \in Ballot, v1, v2 \in Value : 
       VotedFor(a1, b, v1) /\ VotedFor(a2, b, v2) => (v1 = v2)

VotesSafe == \A a \in Acceptor, b \in Ballot, v \in Value :
                 VotedFor(a, b, v) => SafeAt(b, v)

Inv == TypeOK /\ VotesSafe /\ OneValuePerBallot

C == INSTANCE Consensus 
        WITH  Value <- Value,  chosen <- chosen 

=============================================================================

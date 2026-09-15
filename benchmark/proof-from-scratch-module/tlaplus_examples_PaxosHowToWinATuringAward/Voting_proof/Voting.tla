------------------------------ MODULE Voting ------------------------------- 

EXTENDS Integers, TLAPS

CONSTANTS Value, Acceptor, Quorum

ASSUME QuorumAssumption ==
       /\ \A Q \in Quorum : Q \subseteq Acceptor
       /\ \A Q1, Q2 \in Quorum : Q1 \cap Q2 /= {} 

Ballot == Nat
-----------------------------------------------------------------------------

VARIABLES votes, maxBal

TypeOK == 
   /\ votes  \in [Acceptor -> SUBSET (Ballot \X Value)]
   /\ maxBal \in [Acceptor -> Ballot \cup {-1}]

VotedFor(a, b, v) == <<b, v>> \in votes[a]

ChosenAt(b, v) == 
   \E Q \in Quorum : \A a \in Q : VotedFor(a, b, v)

chosen == {v \in Value : \E b \in Ballot : ChosenAt(b, v)}

DidNotVoteAt(a, b) == \A v \in Value : ~ VotedFor(a, b, v) 

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

ShowsSafeAt(Q, b, v) == 
  /\ \A a \in Q : maxBal[a] >= b
  /\ \E c \in -1..(b-1) : 
      /\ (c /= -1) => \E a \in Q : VotedFor(a, c, v)
      /\ \A d \in (c+1)..(b-1), a \in Q : DidNotVoteAt(a, d)

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

C == INSTANCE Consensus 
        WITH  Value <- Value,  chosen <- chosen 

=============================================================================

------------------------------- MODULE PaxosHistVarDefs --------------------------

EXTENDS PaxosHistVarModel

VotedForIn(a, v, b) == \E m \in sent : /\ m.type = "2b"
                                       /\ m.val  = v
                                       /\ m.bal  = b
                                       /\ m.acc  = a

ChosenIn(v, b) == \E Q \in Quorums :
                     \A a \in Q : VotedForIn(a, v, b)

Chosen(v) == \E b \in Ballots : ChosenIn(v, b)

Consistency == \A v1, v2 \in Values : Chosen(v1) /\ Chosen(v2) => (v1 = v2)

Messages ==      [type : {"1a"}, bal : Ballots]
            \cup [type : {"1b"}, bal : Ballots, maxVBal : Ballots \cup {-1},
                    maxVal : Values \cup {None}, acc : Acceptors]
            \cup [type : {"2a"}, bal : Ballots, val : Values]
            \cup [type : {"2b"}, bal : Ballots, val : Values, acc : Acceptors]

TypeOK == sent \in SUBSET Messages

WontVoteIn(a, b) == /\ \A v \in Values : ~ VotedForIn(a, v, b)
                    /\ \E m \in sent: m.type \in {"1b", "2b"} /\ m.acc = a /\ m.bal > b

SafeAt(v, b) == 
  \A b2 \in 0..(b-1) :
    \E Q \in Quorums :
      \A a \in Q : VotedForIn(a, v, b2) \/ WontVoteIn(a, b2)

MsgInv ==
  \A m \in sent : 
    /\ m.type = "1b" => /\ VotedForIn(m.acc, m.maxVal, m.maxVBal) \/ m.maxVBal = -1
                        /\ \A b \in m.maxVBal+1..m.bal-1: ~\E v \in Values: VotedForIn(m.acc, v, b)
    /\ m.type = "2a" => /\ SafeAt(m.val, m.bal)
                        /\ \A m2 \in sent : (m2.type = "2a" /\ m2.bal = m.bal) => m2 = m
    /\ m.type = "2b" => \E m2 \in sent : /\ m2.type = "2a"
                                         /\ m2.bal  = m.bal
                                         /\ m2.val  = m.val

Inv == TypeOK /\ MsgInv

=============================================================================


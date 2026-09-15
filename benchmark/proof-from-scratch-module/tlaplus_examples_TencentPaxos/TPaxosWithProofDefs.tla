------------------------------ MODULE TPaxosWithProofDefs --------------------------------

EXTENDS TPaxosWithProofModel

State == [maxBal: Ballot \cup {-1},
         maxVBal: Ballot \cup {-1}, maxVVal: Value \cup {None}]

Message == [from: Participant,
            to : SUBSET Participant,
            state: [Participant -> [maxBal: Ballot \cup {-1},
                                    maxVBal: Ballot \cup {-1},
                                    maxVVal: Value \cup {None}]]]

TypeOK ==
    /\ state \in [Participant -> [Participant -> State]]

    /\ msgs \subseteq Message

VotedForIn(a, b, v) == \E m \in msgs:
                            /\ m.from = a
                            /\ m.state[a].maxBal = b
                            /\ m.state[a].maxVBal = b
                            /\ m.state[a].maxVVal = v

ChosenIn(b, v) == \E Q \in Quorum:
                    \A a \in Q: VotedForIn(a, b, v)

Chosen(v) == \E b \in Ballot: ChosenIn(b, v)

Consistency == 
   \A v1, v2 \in Value: Chosen(v1) /\ Chosen(v2) => (v1 = v2)

WontVoteIn(a, b) == /\ \A v \in Value: ~ VotedForIn(a, b, v)
                    /\ state[a][a].maxBal > b

SafeAt(b, v) ==
        \A c \in 0..(b-1):
            \E Q \in Quorum:
                \A a \in Q: VotedForIn(a, c, v) \/ WontVoteIn(a, c)

MsgInv ==
    \A m \in msgs:
        LET p == m.from
            curState == m.state[p]
         IN /\ curState.maxBal >= curState.maxVBal
            /\ curState.maxBal # curState.maxVBal
                => /\ curState.maxBal =< state[p][p].maxBal
                   /\ \A c \in (curState.maxVBal + 1)..(curState.maxBal - 1):
                        ~ \E v \in Value: VotedForIn(p, c, v)
            /\ curState.maxBal = curState.maxVBal 
                => /\ SafeAt(curState.maxVBal, curState.maxVVal)
                   /\ \A ma \in msgs: (ma.state[ma.from].maxBal = curState.maxBal
                                       /\ ma.state[ma.from].maxBal = ma.state[ma.from].maxVBal)
                                    => ma.state[ma.from].maxVVal = curState.maxVVal
            /\\/ /\ curState.maxVVal \in Value
                 /\ curState.maxVBal \in Ballot
                 /\ VotedForIn(m.from, curState.maxVBal, curState.maxVVal)
              \/ /\ curState.maxVVal = None
                 /\ curState.maxVBal = -1
            /\ curState.maxBal \in Ballot
            /\ m.from \notin m.to
            /\ \A q \in Participant: /\ m.state[q].maxVBal <= state[q][q].maxVBal
                                     /\ m.state[q].maxBal <= state[q][q].maxBal
AccInv ==
    \A a \in Participant:
        /\ (state[a][a].maxVBal = -1) <=> (state[a][a].maxVVal = None)
        /\ \A q \in Participant: state[a][q].maxVBal <= state[a][q].maxBal
        /\ (state[a][a].maxVBal >= 0) => VotedForIn(a, state[a][a].maxVBal, state[a][a].maxVVal)
        /\ \A c \in Ballot: c > state[a][a].maxVBal
            => ~ \E v \in Value: VotedForIn(a, c, v)
        /\ \A q \in Participant:
            /\ state[a][a].maxBal >= state[q][a].maxBal
            /\ state[a][a].maxVBal >= state[q][a].maxVBal
        /\ \A q \in Participant:
                state[a][q].maxBal \in Ballot
                        => \E m \in msgs:
                              /\ m.from = q
                              /\ m.state[q].maxBal = state[a][q].maxBal
                              /\ m.state[q].maxVBal = state[a][q].maxVBal
                              /\ m.state[q].maxVVal = state[a][q].maxVVal

Inv == MsgInv /\ AccInv /\ TypeOK

=============================================================================


------------------------------ MODULE TPaxosWithProofModel --------------------------------

EXTENDS Integers, FiniteSets, TLAPS
Max(m, n) == IF m > n THEN m ELSE n
Injective(f) == \A a, b \in DOMAIN f: (a # b) => (f[a] # f[b])
CONSTANTS
    Participant,  
    Value         

None == CHOOSE b : b \notin Value

NP == Cardinality(Participant) 

Quorum == {Q \in SUBSET Participant : Cardinality(Q) * 2 >= NP + 1}
ASSUME QuorumAssumption ==
    /\ \A Q \in Quorum : Q \subseteq Participant
    /\ \A Q1, Q2 \in Quorum : Q1 \cap Q2 # {}

Ballot == Nat

PIndex == CHOOSE f \in [Participant -> 1 .. NP] : Injective(f)
Bals(p) == {b \in Ballot : b % NP = PIndex[p] - 1} 

InitState == [maxBal |-> -1, maxVBal |-> -1, maxVVal |-> None]

VARIABLES
    state,  
    msgs    

vars == <<state, msgs>>

Send(m) == msgs' = msgs \cup {m}
Init ==
    /\ state = [p \in Participant |-> [q \in Participant |-> InitState]]
    /\ msgs = {}

Prepare(p, b) ==
    /\ b \in Bals(p)
    /\ state[p][p].maxBal < b
    /\ state' = [state EXCEPT ![p][p].maxBal = b]
    /\ Send([from |-> p, to |-> Participant \ {p}, state |-> state'[p]])

UpdateState(q, p, pp) ==
    LET maxB == Max(state[q][q].maxBal, pp.maxBal)
        maxBV == IF (maxB <= pp.maxVBal)
                    THEN pp.maxVBal
                    ELSE state[q][q].maxVBal
        maxVV == IF (maxB <= pp.maxVBal)
                    THEN pp.maxVVal
                    ELSE state[q][q].maxVVal
       new_state_qq == [maxBal |-> maxB,
                        maxVBal |-> maxBV,
                        maxVVal |-> maxVV]
       new_state_qp == [maxBal |->  Max(state[q][p].maxBal, pp.maxBal),
                        maxVBal |-> Max(state[q][p].maxVBal, pp.maxVBal),
                        maxVVal |-> (IF (state[q][p].maxVBal =< pp.maxVBal)
                                        THEN pp.maxVVal
                                        ELSE state[q][p].maxVVal)]
    IN  state' =
          [state EXCEPT
              ![q] = [ state[q] EXCEPT
                          ![q] = new_state_qq,
                          ![p] = new_state_qp
                      ]
           ]

OnMessage(q) ==
    \E m \in msgs :
        /\ q \in m.to
        /\ LET p == m.from
           IN  UpdateState(q, p, m.state[p])
        /\ LET qm == [from |-> m.from, to |-> m.to \ {q}, state |-> m.state] 
               nm == [from |-> q, to |-> {m.from}, state |-> state'[q]] 
           IN  IF \/ m.state[q].maxBal < state'[q][q].maxBal
                  \/ m.state[q].maxVBal < state'[q][q].maxVBal
                 THEN msgs' = msgs \cup {nm}
                 ELSE UNCHANGED msgs

Accept(p, b, v) ==
    /\ b \in Bals(p)
    /\ ~ \E m \in msgs: m.state[m.from].maxBal = b /\ m.state[m.from].maxVBal = b
    /\ state[p][p].maxBal = b 
    /\ state[p][p].maxVBal # b 
    /\ \E Q \in Quorum :
       /\ \A q \in Q : state[p][q].maxBal = b
       
       /\ \/ \A q \in Q : state[p][q].maxVBal = -1 

          \/ \E c \in 0..(b-1):
              /\ \A r \in Q: state[p][r].maxVBal =< c
              /\ \E r \in Q: /\ state[p][r].maxVBal = c
                             /\ state[p][r].maxVVal = v

    /\ state' = [state EXCEPT ![p] = [state[p] EXCEPT
                                        ![p] = [state[p][p] EXCEPT !.maxVBal = b,
                                                                   !.maxVVal = v]]]
    /\ Send([from |-> p, to |-> Participant \ {p}, state |-> state'[p]])
Next == \E p \in Participant : \/ OnMessage(p)
                               \/ \E b \in Ballot : \/ Prepare(p, b)
                                                    \/ \E v \in Value : Accept(p, b, v)
Spec == Init /\ [][Next]_vars

=============================================================================


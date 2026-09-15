----------------------------- MODULE SailfishModel -----------------------------

EXTENDS Integers, FiniteSets, Sequences

CONSTANTS
    N 
,   F 
,   R 
,   IsQuorum(_) 
,   IsBlocking(_) 
,   Leader(_) 
,   GST 

ASSUME NodesAreFinite == IsFiniteSet(N)

ASSUME ByzantineNodesAreNodes == F \subseteq N

ASSUME RoundsStartAtOne == \E n \in R : R = 1..n

ASSUME GSTIsARoundNumber == GST \in Nat

ASSUME CorrectNodesFormQuorum == IsQuorum(N \ F)

ASSUME QuorumMinusByzantineIsBlocking ==
    \A Q \in SUBSET N : IsQuorum(Q) => IsBlocking(Q \ F)

ASSUME BlockingSetsIntersectQuorums ==
    \A B,Q \in SUBSET N : IsBlocking(B) /\ IsQuorum(Q) => B \cap Q # {}

INSTANCE BlockDag 

VARIABLES vs, es

dag == <<vs, es>>
NoLeaderVoteQuorum(r, vertices, add) ==
    LET NoLeaderVote == {v \in vertices : LeaderVertex(r-1) \notin Children(dag, v)}
    IN  IsQuorum({Node(v) : v \in NoLeaderVote} \cup add)

VARIABLES round, log

vars == << vs, es, round, log >>

Init == 
        /\ vs = {Genesis}
        /\ es = {}
        
        /\ round = [self \in N \ F |-> 0]
        /\ log = [self \in N \ F |-> <<>>]

correctNode(self) == IF round[self] = 0
                        THEN /\ round' = [round EXCEPT ![self] = 1]
                             /\ vs' = (vs \cup {<<self, 1>>})
                             /\ es' = (es \cup {<<<<self, 1>>, Genesis>>})
                             /\ log' = log
                        ELSE /\ \E r \in {r \in R : r > round[self]}:
                                  \E deliveredVertices \in SUBSET {v \in vs : Round(v) = r-1}:
                                    /\ IsQuorum({Node(v) : v \in deliveredVertices})
                                    /\ r >= GST => (N \ F) \subseteq {Node(v) : v \in deliveredVertices}
                                    /\ round' = [round EXCEPT ![self] = r]
                                    /\ LeaderVertex(r-1) \in deliveredVertices =>
                                         \/ LeaderVertex(r-2) \in Children(dag, LeaderVertex(r-1))
                                         \/ NoLeaderVoteQuorum(r-1, deliveredVertices, {})
                                    /\ IF Leader(r) = self
                                          THEN /\ \/ LeaderVertex(r-1) \in deliveredVertices
                                                  \/ NoLeaderVoteQuorum(r, {v \in vs : Round(v) = r}, {self})
                                          ELSE /\ TRUE
                                    /\ LET newV == <<self, r>> IN
                                         /\ vs' = (vs \cup {newV})
                                         /\ es' = (es \cup {<<newV, pv>> : pv \in deliveredVertices})
                                    /\ IF r > 2
                                          THEN /\ LET votesForLeader == {pv \in deliveredVertices : <<pv, LeaderVertex(r-2)>> \in es'} IN
                                                    IF IsQuorum({Node(pv) : pv \in votesForLeader})
                                                       THEN /\ log' = [log EXCEPT ![self] = Linearize(dag, LeaderVertex(r-2))]
                                                       ELSE /\ TRUE
                                                            /\ log' = log
                                          ELSE /\ TRUE
                                               /\ log' = log

byzantineNode(self) == /\ \E r \in R:
                            LET newV == <<self, r>> IN
                              /\ newV \notin vs
                              /\ IF r = 1
                                    THEN /\ vs' = (vs \cup {newV})
                                         /\ es' = (es \cup {<<newV, Genesis>>})
                                    ELSE /\ \E delivered \in SUBSET {v \in vs : Round(v) = r-1}:
                                              /\ IsQuorum({Node(v) : v \in delivered})
                                              /\ vs' = (vs \cup {newV})
                                              /\ es' = (es \cup {<<newV, pv>> : pv \in delivered})
                       /\ UNCHANGED << round, log >>

Next == (\E self \in N \ F: correctNode(self))
           \/ (\E self \in F: byzantineNode(self))

Spec == Init /\ [][Next]_vars

===========================================================================

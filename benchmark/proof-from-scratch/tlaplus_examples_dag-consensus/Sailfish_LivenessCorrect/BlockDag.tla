----------------------------- MODULE BlockDag -----------------------------

EXTENDS FiniteSets, Sequences, Integers, Utils, Digraph, TLC

CONSTANTS
    N 
,   R 
,   Leader(_) 

ASSUME RoundsArePositiveIntegers == R \subseteq Nat \ {0}

ASSUME LeadersAreNodes == \A r \in R : Leader(r) \in N

Node(v) == v[1]
Round(v) == IF v = <<>> THEN 0 ELSE v[2] 

LeaderVertex(r) == IF r > 0 THEN <<Leader(r), r>> ELSE <<>>
IsLeader(v) == LeaderVertex(Round(v)) = v
Genesis == <<>>

OrderSet(S) ==
    LET orderSet[s \in SUBSET S] == IF s = {} THEN <<>> ELSE
          LET e == CHOOSE e \in s : TRUE
          IN  Append(orderSet[s \ {e}], e)
    IN  orderSet[S]

PreviousLeader(dag, r) == CHOOSE l \in Vertices(dag) : 
    /\  IsLeader(l)
    /\  Round(l) = Max({Round(l2) : l2 \in 
            {l2 \in Vertices(dag) : IsLeader(l2) /\ Round(l2) < r}})

Linearize(dag, l) ==
    LET linearize[d \in (SUBSET Vertices(dag)) \X (SUBSET Edges(dag)),
                  v \in Vertices(dag)] ==
          IF Vertices(d) = {<<>>} THEN <<>> ELSE
          LET dagOfL == SubDag(d, {v})
              prevL == PreviousLeader(dagOfL, Round(v))
              dagOfPrev == SubDag(d, {prevL})
              remaining == Vertices(dagOfL) \ Vertices(dagOfPrev)
          IN  linearize[dagOfPrev, prevL] \o OrderSet(remaining \ {v}) \o <<v>>
    IN  linearize[dag, l]

=========================================================================

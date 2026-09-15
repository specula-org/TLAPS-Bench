----------------------------- MODULE SailfishDefs -----------------------------

EXTENDS SailfishModel

INSTANCE BlockDag 

TypeOK ==
    /\  \A v \in vs \ {<<>>} : 
        /\  Node(v) \in N /\ Round(v) \in Nat \ {0}
        /\  \A c \in Children(dag, v) : Round(c) = Round(v) - 1
    /\  \A e \in es :
            /\  e = <<e[1],e[2]>>
            /\  {e[1], e[2]} \subseteq vs
    /\  \A n \in N \ F : round[n] \in Nat

Agreement == \A n1,n2 \in N \ F : Compatible(log[n1], log[n2])

Liveness == \A r \in R : r >= GST /\ Leader(r) \notin F =>
    \A n \in N \ F : round[n] >= r+2 =>
        \E i \in DOMAIN log[n] : log[n][i] = LeaderVertex(r)

===========================================================================

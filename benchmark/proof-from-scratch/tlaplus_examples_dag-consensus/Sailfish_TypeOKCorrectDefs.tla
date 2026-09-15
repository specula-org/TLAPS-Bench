----------------------------- MODULE Sailfish_TypeOKCorrectDefs -----------------------------

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

===========================================================================

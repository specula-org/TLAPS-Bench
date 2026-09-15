----------------------------- MODULE Digraph -----------------------------

Vertices(digraph) == digraph[1]
Edges(digraph) == digraph[2]

Children(digraph, v) ==
    {c \in Vertices(digraph) : <<v, c>> \in Edges(digraph)}

Descendants(dag, vs) ==
    LET descendants[s \in SUBSET (Vertices(dag) \cup vs)] ==
          IF s = {} THEN {} ELSE
          LET children == {c \in Vertices(dag) : \E v \in s : <<v,c>> \in Edges(dag)} IN
              children \cup descendants[children]
    IN  descendants[vs]

SubDag(dag, vs) ==
    LET vs2 == Descendants(dag, vs) \cup vs
        es2 == {e \in Edges(dag) : e[1] \in vs2} 
    IN  <<vs2, es2>>
    
==========================================================================

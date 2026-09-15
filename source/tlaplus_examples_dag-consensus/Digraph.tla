----------------------------- MODULE Digraph -----------------------------

(**************************************************************************************)
(* A digraph is a pair consisting of a set of vertices and a set of edges             *)
(**************************************************************************************)
 
Vertices(digraph) == digraph[1]
Edges(digraph) == digraph[2]

IsDigraph(digraph) ==
    /\  digraph = <<Vertices(digraph), Edges(digraph)>>
    /\  \A e \in Edges(digraph) :
        /\  e = <<e[1],e[2]>>
        /\  {e[1],e[2]} \subseteq Vertices(digraph)

Children(digraph, v) ==
    {c \in Vertices(digraph) : <<v, c>> \in Edges(digraph)}

(**************************************************************************************)
(* Descendants(dag, vs) is the set of vertices reachable from any vertex in vs       *)
(**************************************************************************************)
\* Every recursive call passes a set of vertices of dag, so a function over the
\* subsets of dag's vertices (together with the initial vs) covers the recursion.
Descendants(dag, vs) ==
    LET descendants[s \in SUBSET (Vertices(dag) \cup vs)] ==
          IF s = {} THEN {} ELSE
          LET children == {c \in Vertices(dag) : \E v \in s : <<v,c>> \in Edges(dag)} IN
              children \cup descendants[children]
    IN  descendants[vs]

(**************************************************************************************)
(* The sub-dag reachable from the set of vertices vs:                                 *)
(**************************************************************************************)
SubDag(dag, vs) ==
    LET vs2 == Descendants(dag, vs) \cup vs
        es2 == {e \in Edges(dag) : e[1] \in vs2} \* implies e[2] \in vs2
    IN  <<vs2, es2>>
    
==========================================================================

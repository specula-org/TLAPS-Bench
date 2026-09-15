---------------------------- MODULE GraphTheoremDefs ----------------------------
EXTENDS Sets, TLAPS

Edges(Nodes) == { {m[1], m[2]} : m \in Nodes \X Nodes }

NonLoopEdges(Nodes) == {e \in Edges(Nodes) : Cardinality(e) = 2}
SimpleGraphs(Nodes) == SUBSET NonLoopEdges(Nodes)
Degree(n, G) == Cardinality ({e \in G : n \in e})

=============================================================================

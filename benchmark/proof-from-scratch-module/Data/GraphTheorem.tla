---- MODULE GraphTheorem ----
EXTENDS GraphTheoremDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM
  ASSUME NEW Nodes, IsFiniteSet(Nodes), Cardinality(Nodes) > 1,
         NEW G \in SimpleGraphs(Nodes)
  PROVE  \E m, n \in Nodes : /\ m # n
                             /\ Degree(m, G) = Degree(n, G)
\* BEGIN AGENT PROOF Data/GraphTheorem_line62.tla
PROOF OMITTED
\* END AGENT PROOF Data/GraphTheorem_line62.tla
====

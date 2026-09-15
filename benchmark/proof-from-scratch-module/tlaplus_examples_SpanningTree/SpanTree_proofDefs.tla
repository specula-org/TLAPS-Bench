--------------------------- MODULE SpanTree_proofDefs -----------------------------

EXTENDS SpanTree, TLAPS

ASSUME ConstantsAssumption ==
  /\ Root \in Nodes
  /\ \A e \in Edges : (e \subseteq Nodes) /\ (Cardinality(e) = 2)
  /\ MaxCardinality \in Nat
  /\ MaxCardinality >= Cardinality(Nodes)

============================================================================

------------------------------- MODULE CRDT_proofModel ---------------------------------
EXTENDS CRDT, Functions, NaturalsInduction, FunctionTheorems, TLAPS

OGSpec ==
  /\ [](TypeOK /\ Safety)
  /\ [][\E n, o \in Node : Gossip(n,o)]_vars
  /\ [](\A n, o \in Node : WF_vars(Gossip(n,o)))

=============================================================================

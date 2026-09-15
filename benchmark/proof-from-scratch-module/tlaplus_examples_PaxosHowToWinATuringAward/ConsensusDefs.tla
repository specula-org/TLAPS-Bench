----------------------------- MODULE ConsensusDefs ------------------------------

EXTENDS ConsensusModel

TypeOK == /\ chosen \subseteq Value
          /\ IsFiniteSet(chosen) 

Inv == /\ TypeOK
       /\ Cardinality(chosen) \leq 1

=============================================================================

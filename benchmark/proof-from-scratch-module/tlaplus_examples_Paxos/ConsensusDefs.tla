----------------------------- MODULE ConsensusDefs ------------------------------
EXTENDS ConsensusModel

TypeOK == /\ chosen \subseteq Value
          /\ IsFiniteSet(chosen) 

Inv == /\ TypeOK
       /\ Cardinality(chosen) \leq 1

Success == <>(chosen # {})
LiveSpec == Spec /\ WF_chosen(Next)  

=============================================================================

------------------------------- MODULE bosco_TypeOKCorrectDefs -------------------------------

EXTENDS boscoModel

TypeOK == 
  /\ sent \subseteq P \times M
  /\ pc \in [ Corr -> {"V0", "V1", "S0", "S1", "D0", "D1", "U0", "U1"} ]
  /\ rcvd \in [ Corr -> SUBSET (P \times M) ]

=============================================================================


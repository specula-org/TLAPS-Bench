------------------------------- MODULE boscoDefs -------------------------------

EXTENDS boscoModel

TypeOK == 
  /\ sent \subseteq P \times M
  /\ pc \in [ Corr -> {"V0", "V1", "S0", "S1", "D0", "D1", "U0", "U1"} ]
  /\ rcvd \in [ Corr -> SUBSET (P \times M) ]
          
Lemma3_0 == (\E self \in Corr: (pc[self] = "D0")) => (\A self \in Corr: (pc[self] /= "D1"))  
Lemma3_1 == (\E self \in Corr: (pc[self] = "D1")) => (\A self \in Corr: (pc[self] /= "D0"))  

Lemma4_0 == (\E self \in Corr: (pc[self] = "D0")) => (\A self \in Corr: (pc[self] /= "U1"))  
Lemma4_1 == (\E self \in Corr: (pc[self] = "D1")) => (\A self \in Corr: (pc[self] /= "U0"))  

=============================================================================


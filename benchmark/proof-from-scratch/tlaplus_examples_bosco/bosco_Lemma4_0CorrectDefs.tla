------------------------------- MODULE bosco_Lemma4_0CorrectDefs -------------------------------

EXTENDS boscoModel

Lemma4_0 == (\E self \in Corr: (pc[self] = "D0")) => (\A self \in Corr: (pc[self] /= "U1"))  

=============================================================================


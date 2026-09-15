------------------------------- MODULE bosco_Lemma3_0CorrectDefs -------------------------------

EXTENDS boscoModel

Lemma3_0 == (\E self \in Corr: (pc[self] = "D0")) => (\A self \in Corr: (pc[self] /= "D1"))  

=============================================================================


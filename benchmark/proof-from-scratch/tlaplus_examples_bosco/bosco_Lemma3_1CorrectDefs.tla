------------------------------- MODULE bosco_Lemma3_1CorrectDefs -------------------------------

EXTENDS boscoModel

Lemma3_1 == (\E self \in Corr: (pc[self] = "D1")) => (\A self \in Corr: (pc[self] /= "D0"))  

=============================================================================


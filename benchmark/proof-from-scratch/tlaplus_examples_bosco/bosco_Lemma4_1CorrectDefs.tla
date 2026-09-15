------------------------------- MODULE bosco_Lemma4_1CorrectDefs -------------------------------

EXTENDS boscoModel

Lemma4_1 == (\E self \in Corr: (pc[self] = "D1")) => (\A self \in Corr: (pc[self] /= "U0"))  

=============================================================================


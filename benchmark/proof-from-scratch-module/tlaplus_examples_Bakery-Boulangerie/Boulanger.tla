---- MODULE Boulanger ----
EXTENDS BoulangerDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_Bakery-Boulangerie/Boulanger_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Bakery-Boulangerie/Boulanger_TypeCorrect.tla

THEOREM Spec => []MutualExclusion
\* BEGIN AGENT PROOF tlaplus_examples_Bakery-Boulangerie/Boulanger_MutualExclusion.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Bakery-Boulangerie/Boulanger_MutualExclusion.tla
====

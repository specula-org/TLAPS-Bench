---- MODULE EWD998PCal_proof ----
EXTENDS EWD998PCal_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM InitRefinement == Init => EWD998!Init
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/EWD998PCal_proof_InitRefinement.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/EWD998PCal_proof_InitRefinement.tla

THEOREM TypeCorrect == Spec => []PCalTypeOK
\* BEGIN AGENT PROOF tlaplus_examples_ewd998/EWD998PCal_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd998/EWD998PCal_proof_TypeCorrect.tla
====

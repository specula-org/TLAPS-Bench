---- MODULE EWD687a_proof ----
EXTENDS EWD687a_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_ewd687a/EWD687a_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd687a/EWD687a_proof_TypeCorrect.tla

THEOREM Thm_CountersConsistent == Spec => CountersConsistent
\* BEGIN AGENT PROOF tlaplus_examples_ewd687a/EWD687a_proof_Thm_CountersConsistent.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd687a/EWD687a_proof_Thm_CountersConsistent.tla

THEOREM Safety == Spec => []DT1Inv
\* BEGIN AGENT PROOF tlaplus_examples_ewd687a/EWD687a_proof_Safety.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ewd687a/EWD687a_proof_Safety.tla
====

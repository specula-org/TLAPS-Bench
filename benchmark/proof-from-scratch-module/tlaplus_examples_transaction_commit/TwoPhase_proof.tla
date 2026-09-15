---- MODULE TwoPhase_proof ----
EXTENDS TwoPhase_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == TPSpec => []TPTypeOK
\* BEGIN AGENT PROOF tlaplus_examples_transaction_commit/TwoPhase_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_transaction_commit/TwoPhase_proof_TypeCorrect.tla

THEOREM Consistency == TPSpec => []TC!TCConsistent
\* BEGIN AGENT PROOF tlaplus_examples_transaction_commit/TwoPhase_proof_Consistency.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_transaction_commit/TwoPhase_proof_Consistency.tla
====

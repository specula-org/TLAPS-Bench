---- MODULE TCommit_proof ----
EXTENDS TCommit_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TCorrect == TCSpec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_transaction_commit/TCommit_proof_TCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_transaction_commit/TCommit_proof_TCorrect.tla
====

---- MODULE PaxosCommit_proof ----
EXTENDS PaxosCommit_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOK_Init == PCSpec => PCTypeOK
\* BEGIN AGENT PROOF tlaplus_examples_transaction_commit/PaxosCommit_proof_TypeOK_Init.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_transaction_commit/PaxosCommit_proof_TypeOK_Init.tla
====

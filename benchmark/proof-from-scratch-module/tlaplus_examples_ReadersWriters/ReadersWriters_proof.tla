---- MODULE ReadersWriters_proof ----
EXTENDS ReadersWriters_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_ReadersWriters/ReadersWriters_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ReadersWriters/ReadersWriters_proof_TypeCorrect.tla

THEOREM SafetyCorrect == Spec => []Safety
\* BEGIN AGENT PROOF tlaplus_examples_ReadersWriters/ReadersWriters_proof_SafetyCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_ReadersWriters/ReadersWriters_proof_SafetyCorrect.tla
====

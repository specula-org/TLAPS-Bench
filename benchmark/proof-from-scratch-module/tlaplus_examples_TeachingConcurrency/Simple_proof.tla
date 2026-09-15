---- MODULE Simple_proof ----
EXTENDS Simple_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_proof_TypeCorrect.tla

THEOREM InvInvariant == Spec => []Inv
\* BEGIN AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_proof_InvInvariant.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_TeachingConcurrency/Simple_proof_InvInvariant.tla
====

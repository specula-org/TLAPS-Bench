---- MODULE Channel_proof ----
EXTENDS Channel_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeInvariant
\* BEGIN AGENT PROOF tlaplus_examples_SpecifyingSystems_AsynchronousInterface/Channel_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_SpecifyingSystems_AsynchronousInterface/Channel_proof_TypeCorrect.tla
====

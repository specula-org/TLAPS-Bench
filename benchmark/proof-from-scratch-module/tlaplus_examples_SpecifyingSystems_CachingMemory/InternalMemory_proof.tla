---- MODULE InternalMemory_proof ----
EXTENDS InternalMemory_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == ISpec => []TypeInvariant
\* BEGIN AGENT PROOF tlaplus_examples_SpecifyingSystems_CachingMemory/InternalMemory_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_SpecifyingSystems_CachingMemory/InternalMemory_proof_TypeCorrect.tla
====

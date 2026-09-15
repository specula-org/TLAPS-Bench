---- MODULE AllocatorImplementation_proof ----
EXTENDS AllocatorImplementation_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Specification => []TypeInvariant
\* BEGIN AGENT PROOF tlaplus_examples_allocator/AllocatorImplementation_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_allocator/AllocatorImplementation_proof_TypeCorrect.tla
====

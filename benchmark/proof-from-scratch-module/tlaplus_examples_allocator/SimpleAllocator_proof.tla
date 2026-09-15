---- MODULE SimpleAllocator_proof ----
EXTENDS SimpleAllocator_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == SimpleAllocator => []TypeInvariant
\* BEGIN AGENT PROOF tlaplus_examples_allocator/SimpleAllocator_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_allocator/SimpleAllocator_proof_TypeCorrect.tla

THEOREM Mutex == SimpleAllocator => []ResourceMutex
\* BEGIN AGENT PROOF tlaplus_examples_allocator/SimpleAllocator_proof_Mutex.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_allocator/SimpleAllocator_proof_Mutex.tla
====

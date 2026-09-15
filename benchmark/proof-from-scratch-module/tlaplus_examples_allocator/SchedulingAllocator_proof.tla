---- MODULE SchedulingAllocator_proof ----
EXTENDS SchedulingAllocator_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Allocator => []TypeInvariant
\* BEGIN AGENT PROOF tlaplus_examples_allocator/SchedulingAllocator_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_allocator/SchedulingAllocator_proof_TypeCorrect.tla

THEOREM Mutex == Allocator => []ResourceMutex
\* BEGIN AGENT PROOF tlaplus_examples_allocator/SchedulingAllocator_proof_Mutex.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_allocator/SchedulingAllocator_proof_Mutex.tla
====

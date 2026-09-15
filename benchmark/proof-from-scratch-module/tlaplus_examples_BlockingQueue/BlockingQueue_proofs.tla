---- MODULE BlockingQueue_proofs ----
EXTENDS BlockingQueue_proofsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM DeadlockFreedom == Spec => []Invariant
\* BEGIN AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueue_proofs_DeadlockFreedom.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueue_proofs_DeadlockFreedom.tla
====

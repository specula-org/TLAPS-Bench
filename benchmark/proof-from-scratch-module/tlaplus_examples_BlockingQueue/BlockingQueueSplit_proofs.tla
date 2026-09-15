---- MODULE BlockingQueueSplit_proofs ----
EXTENDS BlockingQueueSplit_proofsDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Implements == Spec => A!Spec
\* BEGIN AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueueSplit_proofs_Implements.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueueSplit_proofs_Implements.tla

THEOREM DeadlockFreedom == Spec => []A!Invariant
\* BEGIN AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueueSplit_proofs_DeadlockFreedom.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueueSplit_proofs_DeadlockFreedom.tla

THEOREM IInvRefines == ASSUME IInv PROVE A!IInv
\* BEGIN AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueueSplit_proofs_IInvRefines.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_BlockingQueue/BlockingQueueSplit_proofs_IInvRefines.tla
====

---- MODULE DiskStateQueueProof ----
EXTENDS DiskStateQueueProofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM DeadlockFreedom == Spec => []DeadlockFree
\* BEGIN AGENT PROOF DiskStateQueue/DiskStateQueueProof_DeadlockFreedom.tla
PROOF OMITTED
\* END AGENT PROOF DiskStateQueue/DiskStateQueueProof_DeadlockFreedom.tla
====

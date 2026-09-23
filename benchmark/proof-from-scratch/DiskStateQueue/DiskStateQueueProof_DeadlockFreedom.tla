---- MODULE DiskStateQueueProof_DeadlockFreedom ----
EXTENDS DiskStateQueueProof_DeadlockFreedomDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM DeadlockFreedom == Spec => []DeadlockFree
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

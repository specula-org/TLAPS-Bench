---- MODULE libomp_NoQueuedTasksAfterDeactivationCorrect ----
EXTENDS libomp_NoQueuedTasksAfterDeactivationCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM NoQueuedTasksAfterDeactivationCorrect == Spec => []NoQueuedTasksAfterDeactivation
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

---- MODULE libomp ----
EXTENDS libompDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM ActiveTasksImplyActiveTeamCorrect == Spec => []ActiveTasksImplyActiveTeam
\* BEGIN AGENT PROOF libomp/libomp_ActiveTasksImplyActiveTeamCorrect.tla
PROOF OMITTED
\* END AGENT PROOF libomp/libomp_ActiveTasksImplyActiveTeamCorrect.tla

THEOREM NoQueuedTasksAfterDeactivationCorrect == Spec => []NoQueuedTasksAfterDeactivation
\* BEGIN AGENT PROOF libomp/libomp_NoQueuedTasksAfterDeactivationCorrect.tla
PROOF OMITTED
\* END AGENT PROOF libomp/libomp_NoQueuedTasksAfterDeactivationCorrect.tla

THEOREM ParityConsistencyCorrect == Spec => []ParityConsistency
\* BEGIN AGENT PROOF libomp/libomp_ParityConsistencyCorrect.tla
PROOF OMITTED
\* END AGENT PROOF libomp/libomp_ParityConsistencyCorrect.tla

THEOREM ParityRestoredAfterCancelCorrect == Spec => []ParityRestoredAfterCancel
\* BEGIN AGENT PROOF libomp/libomp_ParityRestoredAfterCancelCorrect.tla
PROOF OMITTED
\* END AGENT PROOF libomp/libomp_ParityRestoredAfterCancelCorrect.tla
====

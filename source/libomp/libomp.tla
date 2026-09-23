---- MODULE libomp ----
EXTENDS libompRuntime

THEOREM ActiveTasksImplyActiveTeamCorrect == Spec => []ActiveTasksImplyActiveTeam
PROOF OMITTED

THEOREM NoQueuedTasksAfterDeactivationCorrect == Spec => []NoQueuedTasksAfterDeactivation
PROOF OMITTED

THEOREM ParityConsistencyCorrect == Spec => []ParityConsistency
PROOF OMITTED

THEOREM ParityRestoredAfterCancelCorrect == Spec => []ParityRestoredAfterCancel
PROOF OMITTED

====

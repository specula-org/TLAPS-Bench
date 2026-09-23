---- MODULE libomp_ActiveTasksImplyActiveTeamCorrect ----
EXTENDS libomp_ActiveTasksImplyActiveTeamCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ActiveTasksImplyActiveTeamCorrect == Spec => []ActiveTasksImplyActiveTeam
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

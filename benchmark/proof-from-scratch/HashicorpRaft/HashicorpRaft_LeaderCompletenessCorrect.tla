---- MODULE HashicorpRaft_LeaderCompletenessCorrect ----
EXTENDS HashicorpRaft_LeaderCompletenessCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM LeaderCompletenessCorrect == Spec => []LeaderCompleteness
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

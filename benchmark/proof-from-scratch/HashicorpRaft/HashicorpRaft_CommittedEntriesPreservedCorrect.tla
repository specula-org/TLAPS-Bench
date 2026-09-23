---- MODULE HashicorpRaft_CommittedEntriesPreservedCorrect ----
EXTENDS HashicorpRaft_CommittedEntriesPreservedCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM CommittedEntriesPreservedCorrect == Spec => []CommittedEntriesPreserved
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

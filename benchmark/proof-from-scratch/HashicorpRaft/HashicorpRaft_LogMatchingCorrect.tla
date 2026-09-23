---- MODULE HashicorpRaft_LogMatchingCorrect ----
EXTENDS HashicorpRaft_LogMatchingCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM LogMatchingCorrect == Spec => []LogMatching
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

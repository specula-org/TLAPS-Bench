---- MODULE HashicorpRaft_ElectionSafetyCorrect ----
EXTENDS HashicorpRaft_ElectionSafetyCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ElectionSafetyCorrect == Spec => []ElectionSafety
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

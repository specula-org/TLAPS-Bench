---- MODULE HashicorpRaft_StateMachineSafetyCorrect ----
EXTENDS HashicorpRaft_StateMachineSafetyCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM StateMachineSafetyCorrect == Spec => []StateMachineSafety
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

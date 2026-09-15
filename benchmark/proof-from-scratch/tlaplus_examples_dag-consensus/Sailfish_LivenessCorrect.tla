---- MODULE Sailfish_LivenessCorrect ----
EXTENDS Sailfish_LivenessCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM LivenessCorrect == Spec => []Liveness
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

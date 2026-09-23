---- MODULE HashicorpRaft_ConfigurationSafetyCorrect ----
EXTENDS HashicorpRaft_ConfigurationSafetyCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ConfigurationSafetyCorrect == Spec => []ConfigurationSafety
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

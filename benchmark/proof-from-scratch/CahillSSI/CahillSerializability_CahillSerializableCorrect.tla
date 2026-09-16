---- MODULE CahillSerializability_CahillSerializableCorrect ----
EXTENDS CahillSerializability_CahillSerializableCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM CahillSerializableCorrect == Spec => []CahillSerializable(history)
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

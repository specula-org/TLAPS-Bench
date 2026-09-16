---- MODULE CahillSerializability ----
EXTENDS CahillSerializabilityDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM CahillSerializableCorrect == Spec => []CahillSerializable(history)
\* BEGIN AGENT PROOF CahillSSI/CahillSerializability_CahillSerializableCorrect.tla
PROOF OMITTED
\* END AGENT PROOF CahillSSI/CahillSerializability_CahillSerializableCorrect.tla
====

---- MODULE PirateShipProof_MonotonicAuditedIndexPropCorrect ----
EXTENDS PirateShipProof_MonotonicAuditedIndexPropCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM MonotonicAuditedIndexPropCorrect == Spec => MonotonicAuditedIndexProp
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

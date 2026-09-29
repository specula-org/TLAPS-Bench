---- MODULE PirateShipProof_AuditedBranchAppendOnlyPropCorrect ----
EXTENDS PirateShipProof_AuditedBranchAppendOnlyPropCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM AuditedBranchAppendOnlyPropCorrect == Spec => AuditedBranchAppendOnlyProp
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

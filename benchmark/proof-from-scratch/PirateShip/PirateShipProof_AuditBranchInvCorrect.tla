---- MODULE PirateShipProof_AuditBranchInvCorrect ----
EXTENDS PirateShipProof_AuditBranchInvCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM AuditBranchInvCorrect == Spec => []AuditBranchInv
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

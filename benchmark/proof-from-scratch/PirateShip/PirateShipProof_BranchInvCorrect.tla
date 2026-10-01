---- MODULE PirateShipProof_BranchInvCorrect ----
EXTENDS PirateShipProof_BranchInvCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM BranchInvCorrect == Spec => []BranchInv
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

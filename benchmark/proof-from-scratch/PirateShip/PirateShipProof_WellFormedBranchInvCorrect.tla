---- MODULE PirateShipProof_WellFormedBranchInvCorrect ----
EXTENDS PirateShipProof_WellFormedBranchInvCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM WellFormedBranchInvCorrect == Spec => []WellFormedBranchInv
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

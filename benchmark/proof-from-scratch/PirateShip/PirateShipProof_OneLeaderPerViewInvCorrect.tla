---- MODULE PirateShipProof_OneLeaderPerViewInvCorrect ----
EXTENDS PirateShipProof_OneLeaderPerViewInvCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM OneLeaderPerViewInvCorrect == Spec => []OneLeaderPerViewInv
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

---- MODULE PirateShipProof_ViewMonotonicInvCorrect ----
EXTENDS PirateShipProof_ViewMonotonicInvCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ViewMonotonicInvCorrect == Spec => []ViewMonotonicInv
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

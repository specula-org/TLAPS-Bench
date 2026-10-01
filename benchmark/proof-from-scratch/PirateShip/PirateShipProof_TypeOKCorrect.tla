---- MODULE PirateShipProof_TypeOKCorrect ----
EXTENDS PirateShipProof_TypeOKCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM TypeOKCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

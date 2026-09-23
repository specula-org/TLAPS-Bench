---- MODULE libomp_ParityRestoredAfterCancelCorrect ----
EXTENDS libomp_ParityRestoredAfterCancelCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM ParityRestoredAfterCancelCorrect == Spec => []ParityRestoredAfterCancel
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

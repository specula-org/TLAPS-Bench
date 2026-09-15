---- MODULE Disruptor_SPMC_TypeOkCorrect ----
EXTENDS Disruptor_SPMC_TypeOkCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM TypeOkCorrect == Spec => []TypeOk
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

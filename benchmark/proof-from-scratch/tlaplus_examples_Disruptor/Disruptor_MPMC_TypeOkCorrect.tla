---- MODULE Disruptor_MPMC_TypeOkCorrect ----
EXTENDS Disruptor_MPMC_TypeOkCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM TypeOkCorrect == Spec => []TypeOk
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

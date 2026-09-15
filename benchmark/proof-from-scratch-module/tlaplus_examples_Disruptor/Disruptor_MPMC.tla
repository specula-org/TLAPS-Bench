---- MODULE Disruptor_MPMC ----
EXTENDS Disruptor_MPMCDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOkCorrect == Spec => []TypeOk
\* BEGIN AGENT PROOF tlaplus_examples_Disruptor/Disruptor_MPMC_TypeOkCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Disruptor/Disruptor_MPMC_TypeOkCorrect.tla

THEOREM NoDataRacesCorrect == Spec => []NoDataRaces
\* BEGIN AGENT PROOF tlaplus_examples_Disruptor/Disruptor_MPMC_NoDataRacesCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Disruptor/Disruptor_MPMC_NoDataRacesCorrect.tla
====

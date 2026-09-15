---- MODULE Disruptor_SPMC ----
EXTENDS Disruptor_SPMCDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOkCorrect == Spec => []TypeOk
\* BEGIN AGENT PROOF tlaplus_examples_Disruptor/Disruptor_SPMC_TypeOkCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Disruptor/Disruptor_SPMC_TypeOkCorrect.tla

THEOREM NoDataRacesCorrect == Spec => []NoDataRaces
\* BEGIN AGENT PROOF tlaplus_examples_Disruptor/Disruptor_SPMC_NoDataRacesCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_Disruptor/Disruptor_SPMC_NoDataRacesCorrect.tla
====

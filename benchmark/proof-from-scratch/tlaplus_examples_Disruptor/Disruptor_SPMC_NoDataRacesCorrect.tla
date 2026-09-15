---- MODULE Disruptor_SPMC_NoDataRacesCorrect ----
EXTENDS Disruptor_SPMC_NoDataRacesCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM NoDataRacesCorrect == Spec => []NoDataRaces
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

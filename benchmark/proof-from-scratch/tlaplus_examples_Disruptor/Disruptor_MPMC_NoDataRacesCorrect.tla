---- MODULE Disruptor_MPMC_NoDataRacesCorrect ----
EXTENDS Disruptor_MPMC_NoDataRacesCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM NoDataRacesCorrect == Spec => []NoDataRaces
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

---- MODULE SimpleMutex ----
EXTENDS SimpleMutexDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM
  ASSUME TypeOK, Inv, Next
  PROVE  TypeOK' /\ Inv'
\* BEGIN AGENT PROOF SimpleMutex/SimpleMutex_line140.tla
PROOF OMITTED
\* END AGENT PROOF SimpleMutex/SimpleMutex_line140.tla

THEOREM Safety == Spec => []MutualExclusion
\* BEGIN AGENT PROOF SimpleMutex/SimpleMutex_Safety.tla
PROOF OMITTED
\* END AGENT PROOF SimpleMutex/SimpleMutex_Safety.tla
====

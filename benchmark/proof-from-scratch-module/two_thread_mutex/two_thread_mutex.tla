---- MODULE two_thread_mutex ----
EXTENDS two_thread_mutexDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Liveness == Spec => Termination
\* BEGIN AGENT PROOF two_thread_mutex/two_thread_mutex_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF two_thread_mutex/two_thread_mutex_Liveness.tla
====

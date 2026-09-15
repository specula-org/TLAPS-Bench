-------------------------- MODULE two_thread_mutexDefs -------------------------
EXTENDS two_thread_mutexModel

BothThreadsTerminated ==
  \A tid \in Tid : threads[tid] = "Terminated"

Termination ==
  <>BothThreadsTerminated

=============================================================================

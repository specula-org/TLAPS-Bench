------------------------- MODULE StorageRollbackSI -------------------------
EXTENDS StorageHistory
CONSTANT N, T0, T1, T2, K
VARIABLE pc

ScenarioInit == HistoryInit /\ pc = 0

ScheduledAction ==
  \/ /\ pc = 0 /\ StartTransaction(N,T0,0,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 1 /\ CommitTransaction(N,T0,1) /\ UNCHANGED history
  \/ /\ pc = 2 /\ StartTransaction(N,T1,1,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 3 /\ ObserveRead(N,T1,K,NoValue)
  \/ /\ pc = 4 /\ ObserveWrite(N,T1,K,T1)
  \/ /\ pc = 5 /\ CommitTransaction(N,T1,2) /\ UNCHANGED history
  \/ /\ pc = 6 /\ SetStableTimestamp(N,1) /\ UNCHANGED history
  \/ /\ pc = 7 /\ RollbackToStable(N) /\ UNCHANGED history
  \/ /\ pc = 8 /\ StartTransaction(N,T2,1,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 9 /\ ObserveRead(N,T2,K,NoValue)
  \/ /\ pc = 10 /\ ObserveWrite(N,T2,K,T2)
  \/ /\ pc = 11 /\ CommitTransaction(N,T2,2) /\ UNCHANGED history

\* Every scheduled step must also satisfy the unrestricted observer Next.
ScenarioNext == HistoryNext /\ ScheduledAction /\ pc' = pc + 1
=============================================================================

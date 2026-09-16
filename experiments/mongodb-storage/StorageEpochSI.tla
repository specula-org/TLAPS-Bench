--------------------------- MODULE StorageEpochSI ---------------------------
EXTENDS StorageHistory
CONSTANT N, A, R, B, S, X, Y
VARIABLE pc

ScenarioInit == HistoryInit /\ pc = 0
ScheduledAction ==
  \/ /\ pc = 0 /\ StartTransaction(N,A,0,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 1 /\ ObserveWrite(N,A,Y,A)
  \/ /\ pc = 2 /\ CommitTransaction(N,A,5) /\ UNCHANGED history
  \/ /\ pc = 3 /\ StartTransaction(N,R,5,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 4 /\ ObserveRead(N,R,X,NoValue)
  \/ /\ pc = 5 /\ ObserveRead(N,R,Y,A)
  \/ /\ pc = 6 /\ CommitTransaction(N,R,6) /\ UNCHANGED history
  \/ /\ pc = 7 /\ StartTransaction(N,B,0,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 8 /\ ObserveWrite(N,B,X,B)
  \/ /\ pc = 9 /\ PrepareTransaction(N,B,1) /\ UNCHANGED history
  \/ /\ pc = 10 /\ CommitPreparedTransaction(N,B,1,1) /\ UNCHANGED history
  \/ /\ pc = 11 /\ StartTransaction(N,S,1,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 12 /\ ObserveRead(N,S,X,B)
  \/ /\ pc = 13 /\ ObserveRead(N,S,Y,NoValue)
  \/ /\ pc = 14 /\ CommitTransaction(N,S,7) /\ UNCHANGED history

\* This is an actual recovery-free Storage history, not a synthetic init.
ScenarioNext == HistoryEpochNext /\ ScheduledAction /\ pc' = pc + 1
=============================================================================

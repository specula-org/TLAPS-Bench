----------------------- MODULE StorageCallerCollapseSI -----------------------
EXTENDS StorageSICertificate
CONSTANT N, A, B, D1, D2, R, X, Y, Z
VARIABLE pc

ScenarioInit == HistoryInit /\ pc = 0
ScheduledAction ==
  \/ /\ pc = 0 /\ StartTransaction(N,A,0,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 1 /\ ObserveWrite(N,A,X,A)
  \/ /\ pc = 2 /\ ObserveWrite(N,A,Y,A)
  \/ /\ pc = 3 /\ CommitTransaction(N,A,1) /\ UNCHANGED history
  \/ /\ pc = 4 /\ StartTransaction(N,D1,1,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 5 /\ ObserveRemove(N,D1,X)
  \/ /\ pc = 6 /\ CommitTransaction(N,D1,2) /\ UNCHANGED history
  \/ /\ pc = 7 /\ StartTransaction(N,B,2,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 8 /\ ObserveRead(N,B,Y,A)
  \/ /\ pc = 9 /\ ObserveRead(N,B,X,NoValue)
  \/ /\ pc = 10 /\ ObserveWrite(N,B,X,B)
  \/ /\ pc = 11 /\ ObserveWrite(N,B,Z,B)
  \/ /\ pc = 12 /\ CommitTransaction(N,B,3) /\ UNCHANGED history
  \/ /\ pc = 13 /\ StartTransaction(N,D2,3,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 14 /\ ObserveRemove(N,D2,X)
  \/ /\ pc = 15 /\ CommitTransaction(N,D2,4) /\ UNCHANGED history
  \/ /\ pc = 16 /\ StartTransaction(N,R,4,RC,"false") /\ UNCHANGED history
  \/ /\ pc = 17 /\ ObserveRead(N,R,Z,B)
  \/ /\ pc = 18 /\ ObserveRead(N,R,X,NoValue)
  \/ /\ pc = 19 /\ CommitTransaction(N,R,5) /\ UNCHANGED history

\* Every step is an actual step of the exact intended caller/epoch observer.
ScenarioNext == CallerHistoryEpochNext /\ ScheduledAction /\ pc' = pc + 1
=============================================================================

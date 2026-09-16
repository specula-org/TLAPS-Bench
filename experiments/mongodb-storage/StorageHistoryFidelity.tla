----------------------- MODULE StorageHistoryFidelity -----------------------
EXTENDS StorageHistoryAlgebra, StorageHistoryProjection, StorageEpoch

HistoryShape ==
  /\ DOMAIN history = Node
  /\ \A n \in Node :
       /\ DOMAIN history[n] = MTxId
       /\ \A t \in MTxId : IsSeq(history[n][t])

UsedSnapshotShape ==
  \A n \in Node, t \in MTxId :
    (mtxnSnapshots[n][t].active \/ mtxnSnapshots[n][t].committed) =>
      /\ {"writeSet","data"} \subseteq DOMAIN mtxnSnapshots[n][t]
      /\ DOMAIN mtxnSnapshots[n][t].data = Keys
      /\ mtxnSnapshots[n][t].writeSet \subseteq Keys

HistoryFidelity ==
  \A n \in Node, t \in MTxId :
    /\ ((mtxnSnapshots[n][t].active \/ mtxnSnapshots[n][t].committed) =>
          HistoryState(history[n][t],mtxnSnapshots[n][t].writeSet,mtxnSnapshots[n][t].data))
    /\ ((~mtxnSnapshots[n][t].active /\ ~mtxnSnapshots[n][t].committed /\
          ~mtxnSnapshots[n][t].aborted) => history[n][t] = <<>>)

THEOREM UsedShapeInitial == Init => UsedSnapshotShape
BY SMT DEF Init, UsedSnapshotShape

THEOREM UsedShapeStep ==
  Inv /\ Lifecycle /\ UsedSnapshotShape /\ [Next]_vars => UsedSnapshotShape'
BY SMTT(20) DEF Inv, SnapshotShape, Lifecycle, UsedSnapshotShape, Next, vars,
  ActiveTransactions, SnapshotKV, StartTransaction, TransactionWrite, TransactionRead,
  TransactionRemove, PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
  AbortTransaction, SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM FullNextUsedShape == Spec => []UsedSnapshotShape
BY FullNextShape, FullNextLifecycle, UsedShapeInitial, UsedShapeStep, PTL DEF Spec

THEOREM HistoryShapeInitial == HistoryInit => HistoryShape
BY SMT, EmptyIsSeq DEF HistoryInit, HistoryShape

THEOREM HistoryShapeStep == HistoryShape /\ [HistoryNext]_historyVars => HistoryShape'
BY SMT, AppendIsSeq DEF HistoryShape, HistoryNext, HistoryEpochNext, historyVars,
   ObservedOperations, ObserveRead, ObserveWrite, ObserveRemove

THEOREM FullHistoryShape == HistorySpec => []HistoryShape
BY HistoryShapeInitial, HistoryShapeStep, PTL DEF HistorySpec

THEOREM HistoryFidelityInitial == HistoryInit => HistoryFidelity
BY SMT DEF HistoryInit, Init, HistoryFidelity

THEOREM ObserveReadFidelity ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, Lifecycle, UsedSnapshotShape, HistoryShape, HistoryFidelity, ObserveRead(n,t,k,v)
  PROVE HistoryFidelity'
BY SMTT(20), ReadHistoryState
   DEF Inv, SnapshotShape, Lifecycle, UsedSnapshotShape, HistoryShape, HistoryFidelity,
       ObserveRead, TransactionRead, ActiveTransactions

THEOREM ObserveWriteFidelity ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, Lifecycle, StatusShape, UsedSnapshotShape, HistoryShape, HistoryFidelity,
         ObserveWrite(n,t,k,v)
  PROVE HistoryFidelity'
BY SMTT(25), WriteHistoryState
   DEF Inv, SnapshotShape, Lifecycle, StatusShape, UsedSnapshotShape, HistoryShape,
       HistoryFidelity, ObserveWrite, TransactionWrite, ActiveTransactions,
       STATUS_OK, STATUS_ROLLBACK

THEOREM ObserveRemoveFidelity ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys,
         Inv, Lifecycle, StatusShape, UsedSnapshotShape, HistoryShape, HistoryFidelity,
         ObserveRemove(n,t,k)
  PROVE HistoryFidelity'
BY SMTT(25), WriteHistoryState
   DEF Inv, SnapshotShape, Lifecycle, StatusShape, UsedSnapshotShape, HistoryShape,
       HistoryFidelity, ObserveRemove, TransactionRemove, ActiveTransactions,
       STATUS_OK, STATUS_ROLLBACK, STATUS_NOTFOUND

THEOREM QuietFidelity ==
  Inv /\ Lifecycle /\ UsedSnapshotShape /\ HistoryFidelity /\ UNCHANGED history /\
  (QuietEpochNext \/ (\E n \in Node : RollbackToStable(n)) \/ UNCHANGED vars)
    => HistoryFidelity'
BY SMTT(25), EmptyHistoryState
   DEF Inv, SnapshotShape, Lifecycle, UsedSnapshotShape, HistoryFidelity,
       QuietEpochNext, vars, StartTransaction, SnapshotKV, ActiveTransactions,
       PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
       AbortTransaction, SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM HistoryFidelityStep ==
  Inv /\ Lifecycle /\ StatusShape /\ UsedSnapshotShape /\ HistoryShape /\
  HistoryFidelity /\ [HistoryNext]_historyVars => HistoryFidelity'
BY SMT, ObserveReadFidelity, ObserveWriteFidelity, ObserveRemoveFidelity, QuietFidelity
   DEF HistoryNext, HistoryEpochNext, ObservedOperations, historyVars

THEOREM FullHistoryFidelity == HistorySpec => []HistoryFidelity
BY HistoryBehaviorProjection, FullNextShape, FullNextLifecycle, FullNextStatusShape,
   FullNextUsedShape, FullHistoryShape, HistoryFidelityInitial, HistoryFidelityStep,
   PTL DEF HistorySpec, Spec
=============================================================================

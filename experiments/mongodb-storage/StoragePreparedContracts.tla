--------------------- MODULE StoragePreparedContracts ---------------------
EXTENDS StorageContracts

PreparedFrozen ==
  \A n \in Node : \A t \in PreparedTransactions(n) :
    t \in {u \in MTxId : mtxnSnapshots'[n][u].active} =>
      /\ mtxnSnapshots'[n][t].writeSet = mtxnSnapshots[n][t].writeSet
      /\ mtxnSnapshots'[n][t].data = mtxnSnapshots[n][t].data
      /\ mtxnSnapshots'[n][t].ts = mtxnSnapshots[n][t].ts
      /\ mtxnSnapshots'[n][t].prepareTs = mtxnSnapshots[n][t].prepareTs
      /\ mtxnSnapshots'[n][t].prepared

THEOREM PreparedFrozenStep == Inv /\ [Next]_vars => PreparedFrozen
BY SMTT(30) DEF Inv, SnapshotShape, WriterExclusion, PreparedFrozen,
  PreparedTransactions, ActiveTransactions, Next, vars, StartTransaction,
  TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
  CommitTransaction, CommitPreparedTransaction, AbortTransaction,
  SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM FullNextShape == Spec => []Inv
BY WriterExclusionInit, WriterExclusionStep, PTL DEF Spec

THEOREM FullNextPreparedFrozen == Spec => [][PreparedFrozen]_vars
BY FullNextShape, PreparedFrozenStep, PTL DEF Spec
=============================================================================

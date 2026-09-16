-------------------------- MODULE StorageLifecycle --------------------------
EXTENDS StoragePreparedContracts

Lifecycle ==
  \A n \in Node, t \in MTxId :
    /\ {"active", "committed", "aborted"} \subseteq DOMAIN mtxnSnapshots[n][t]
    /\ mtxnSnapshots[n][t].committed \in BOOLEAN
    /\ mtxnSnapshots[n][t].aborted \in BOOLEAN
    /\ ~(mtxnSnapshots[n][t].active /\ mtxnSnapshots[n][t].committed)
    /\ ~(mtxnSnapshots[n][t].committed /\ mtxnSnapshots[n][t].aborted)

TerminalFlagsMonotone ==
  \A n \in Node, t \in MTxId :
    /\ (mtxnSnapshots[n][t].committed => mtxnSnapshots'[n][t].committed)
    /\ (mtxnSnapshots[n][t].aborted => mtxnSnapshots'[n][t].aborted)

THEOREM LifecycleInit == Init => Lifecycle
BY SMT DEF Init, Lifecycle

THEOREM LifecycleStep == Inv /\ Lifecycle /\ [Next]_vars => Lifecycle'
BY SMTT(25) DEF Inv, SnapshotShape, WriterExclusion, Lifecycle, Next, vars,
  SnapshotKV, ActiveTransactions, PreparedTransactions, StartTransaction,
  TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
  CommitTransaction, CommitPreparedTransaction, AbortTransaction,
  SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM TerminalFlagsStep == Inv /\ Lifecycle /\ [Next]_vars => TerminalFlagsMonotone
BY SMTT(25) DEF Inv, SnapshotShape, WriterExclusion, Lifecycle, TerminalFlagsMonotone,
  Next, vars, SnapshotKV, ActiveTransactions, PreparedTransactions, StartTransaction,
  TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
  CommitTransaction, CommitPreparedTransaction, AbortTransaction,
  SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM FullNextLifecycle == Spec => []Lifecycle
BY FullNextShape, LifecycleInit, LifecycleStep, PTL DEF Spec

THEOREM FullNextTerminalFlags == Spec => [][TerminalFlagsMonotone]_vars
BY FullNextShape, FullNextLifecycle, TerminalFlagsStep, PTL DEF Spec
=============================================================================

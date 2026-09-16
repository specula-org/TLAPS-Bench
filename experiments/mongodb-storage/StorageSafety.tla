--------------------------- MODULE StorageSafety ---------------------------
EXTENDS StorageReadContracts, StoragePreparedContracts, StorageAdmissionContracts, StorageLifecycle

PrepareModeInvariant ==
  \A n \in Node : \A t \in ActiveTransactions(n) :
    /\ "ignorePrepare" \in DOMAIN mtxnSnapshots[n][t]
    /\ mtxnSnapshots[n][t].ignorePrepare = "false"

THEOREM PrepareModeInit == Init => PrepareModeInvariant
BY SMT DEF Init, PrepareModeInvariant, ActiveTransactions

THEOREM PrepareModeStep ==
  Inv /\ PrepareModeInvariant /\ [Next]_vars => PrepareModeInvariant'
BY SMTT(25) DEF Inv, SnapshotShape, WriterExclusion, PrepareModeInvariant,
  ActiveTransactions, Next, vars, IgnorePrepareOptions, SnapshotKV,
  StartTransaction, TransactionWrite, TransactionRead, TransactionRemove,
  PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
  AbortTransaction, SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM FullNextPrepareMode == Spec => []PrepareModeInvariant
BY FullNextShape, PrepareModeInit, PrepareModeStep, PTL DEF Spec

ReadResponses ==
  \A n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} :
    AcceptedRead(n,t,k,v) =>
      /\ ~PrepareConflict(n,t,k)
      /\ (txnStatus'[n][t] = STATUS_NOTFOUND <=> v = NoValue)
      /\ (k \in mtxnSnapshots[n][t].writeSet => v = mtxnSnapshots[n][t].data[k])

THEOREM UnconditionalReadStep ==
  StatusShape /\ PrepareModeInvariant => ReadResponses
BY SMT, AcceptedReadHasNoPrepareConflict, AcceptedReadSeesOwnWrite
   DEF ReadResponses, PrepareModeInvariant, AcceptedRead, TransactionRead,
       ActiveTransactions

THEOREM FullNextUnconditionalReads == Spec => [][ReadResponses]_vars
BY FullNextStatusShape, FullNextPrepareMode, UnconditionalReadStep, PTL

THEOREM StorageSafety ==
  (Init /\ [][Next]_vars) =>
    /\ []WriterExclusion
    /\ [][PreparedFrozen]_vars
    /\ [][ReadResponses]_vars
    /\ [][AdmissionContract]_vars
    /\ []Lifecycle
    /\ [][TerminalFlagsMonotone]_vars
BY FullNextWriterExclusion, FullNextPreparedFrozen, FullNextUnconditionalReads,
   FullNextAdmission, FullNextLifecycle, FullNextTerminalFlags,
   PTL DEF Spec
=============================================================================

---------------------- MODULE StorageCommitProvenance ----------------------
EXTENDS StorageProvenance, StorageLogAlgebra

CommitProvenance ==
  \A n \in Node : \A i \in DOMAIN mlog[n] :
    "data" \in DOMAIN mlog[n][i] =>
      /\ "tid" \in DOMAIN mlog[n][i]
      /\ mlog[n][i].tid \in MTxId
      /\ mtxnSnapshots[n][mlog[n][i].tid].committed

THEOREM CommitProvenanceInitial == Init => CommitProvenance
BY SMT DEF Init, CommitProvenance

THEOREM SameLogCommitProvenance ==
  CommitProvenance /\ TerminalFlagsMonotone /\ mlog' = mlog => CommitProvenance'
BY SMT DEF CommitProvenance, TerminalFlagsMonotone

THEOREM AppendCommitProvenance ==
  ASSUME NEW n \in Node, NEW e, LogShape, CommitProvenance, TerminalFlagsMonotone,
         mlog' = [mlog EXCEPT ![n] = Append(@,e)],
         "data" \in DOMAIN e =>
           /\ "tid" \in DOMAIN e /\ e.tid \in MTxId
           /\ mtxnSnapshots'[n][e.tid].committed
  PROVE CommitProvenance'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF LogShape, CommitProvenance, TerminalFlagsMonotone

THEOREM CommitProvenanceStep ==
  Inv /\ Lifecycle /\ LogShape /\ CommitProvenance /\ [EpochNext]_vars
    => CommitProvenance'
<1>1. ASSUME Inv, Lifecycle, LogShape, CommitProvenance, [EpochNext]_vars
      PROVE CommitProvenance'
  <2>1. TerminalFlagsMonotone
    BY SMT, <1>1, EpochActionProjection, TerminalFlagsStep
  <2> QED BY SMTT(25), <1>1, <2>1, AppendCommitProvenance, SameLogCommitProvenance,
              DurableAppendForm
    DEF EpochNext, vars, Inv, SnapshotShape, Lifecycle,
        StartTransaction, TransactionWrite, TransactionRead, TransactionRemove,
        PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
        AbortTransaction, SetStableTimestamp, SetOldestTimestamp,
        PrepareTxnToLog, CommitTxnToLog, CommitLogEntry, DurableEntry
<1> QED BY SMT, <1>1

THEOREM EpochCommitProvenance == EpochSpec => []CommitProvenance
BY EpochBehaviorProjection, FullNextShape, FullNextLifecycle, EpochLogShape,
   CommitProvenanceInitial, CommitProvenanceStep, PTL DEF EpochSpec
=============================================================================

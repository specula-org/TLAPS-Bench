------------------------- MODULE StorageProvenance -------------------------
EXTENDS StorageEpoch, StorageSeqLemmas

LogShape ==
  /\ DOMAIN mlog = Node
  /\ \A n \in Node : IsSeq(mlog[n])

PrepareShape ==
  \A n \in Node : \A t \in ActiveTransactions(n) :
    /\ {"prepared", "prepareTs"} \subseteq DOMAIN mtxnSnapshots[n][t]
    /\ mtxnSnapshots[n][t].prepared \in BOOLEAN

PreparedProvenance ==
  \A n \in Node : \A t \in PreparedTransactions(n) :
    \E i \in DOMAIN mlog[n] :
      /\ "prepare" \in DOMAIN mlog[n][i]
      /\ mlog[n][i].tid = t
      /\ mlog[n][i].ts = mtxnSnapshots[n][t].prepareTs

LogsExtend ==
  \A n \in Node : \A i \in DOMAIN mlog[n] :
    /\ i \in DOMAIN mlog'[n]
    /\ mlog'[n][i] = mlog[n][i]

THEOREM LogAppendFacts ==
  ASSUME NEW n \in Node, NEW e, LogShape,
         mlog' = [mlog EXCEPT ![n] = Append(@,e)]
  PROVE /\ LogShape'
        /\ LogsExtend
        /\ Len(mlog[n])+1 \in DOMAIN mlog'[n]
        /\ mlog'[n][Len(mlog[n])+1] = e
BY SMT, AppendIsSeq, AppendEntries, SequenceDomain DEF LogShape, LogsExtend

THEOREM ProvenanceInit == Init => (LogShape /\ PrepareShape /\ PreparedProvenance)
BY SMT, EmptyIsSeq DEF Init, LogShape, PrepareShape, PreparedProvenance,
                      ActiveTransactions, PreparedTransactions

THEOREM PrepareShapeStep == Inv /\ PrepareShape /\ [EpochNext]_vars => PrepareShape'
BY SMTT(25) DEF Inv, SnapshotShape, PrepareShape, EpochNext, vars,
  SnapshotKV, ActiveTransactions, PreparedTransactions, StartTransaction,
  TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
  CommitTransaction, CommitPreparedTransaction, AbortTransaction,
  SetStableTimestamp, SetOldestTimestamp

THEOREM PreparedCommitAppends ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         CommitPreparedTransaction(n,t,ts,dts)
  PROVE \E e : mlog' = [mlog EXCEPT ![n] = Append(@,e)]
BY Isa DEF CommitPreparedTransaction, CommitTxnToLogWithDurable

THEOREM LogShapeStep == LogShape /\ [EpochNext]_vars => LogShape'
BY SMT, LogAppendFacts, PreparedCommitAppends DEF LogShape, EpochNext, vars,
  StartTransaction, TransactionWrite, TransactionRead, TransactionRemove,
  PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
  AbortTransaction, SetStableTimestamp, SetOldestTimestamp,
  PrepareTxnToLog, CommitTxnToLog

THEOREM StartTransactionPreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW rc, NEW ip,
         Inv, PrepareShape, PreparedProvenance, StartTransaction(n,t,ts,rc,ip)
  PROVE PreparedProvenance'
BY SMT DEF Inv, SnapshotShape, PrepareShape, PreparedProvenance,
  ActiveTransactions, PreparedTransactions, StartTransaction, SnapshotKV

THEOREM TransactionWritePreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, PrepareShape, PreparedProvenance, TransactionWrite(n,t,k,v,"false")
  PROVE PreparedProvenance'
BY SMT DEF Inv, SnapshotShape, PrepareShape, PreparedProvenance,
  ActiveTransactions, PreparedTransactions, TransactionWrite

THEOREM TransactionReadPreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, PrepareShape, PreparedProvenance, TransactionRead(n,t,k,v)
  PROVE PreparedProvenance'
BY SMT DEF Inv, SnapshotShape, PrepareShape, PreparedProvenance,
  ActiveTransactions, PreparedTransactions, TransactionRead

THEOREM TransactionRemovePreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys,
         Inv, PrepareShape, PreparedProvenance, TransactionRemove(n,t,k)
  PROVE PreparedProvenance'
BY SMT DEF Inv, SnapshotShape, PrepareShape, PreparedProvenance,
  ActiveTransactions, PreparedTransactions, TransactionRemove

THEOREM AbortTransactionPreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, 
         Inv, PrepareShape, PreparedProvenance, AbortTransaction(n,t)
  PROVE PreparedProvenance'
BY SMT DEF Inv, SnapshotShape, PrepareShape, PreparedProvenance,
  ActiveTransactions, PreparedTransactions, AbortTransaction

THEOREM CommitTransactionPreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, 
         Inv, LogShape, PrepareShape, PreparedProvenance, CommitTransaction(n,t,ts)
  PROVE PreparedProvenance'
<1>1. LogsExtend
  BY SMT, LogAppendFacts DEF CommitTransaction, CommitTxnToLog
<1> QED BY SMT, <1>1 DEF Inv, SnapshotShape, PrepareShape,
  PreparedProvenance, LogsExtend, CommitTransaction, PreparedTransactions, ActiveTransactions

THEOREM CommitPreparedTransactionPreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         Inv, LogShape, PrepareShape, PreparedProvenance, CommitPreparedTransaction(n,t,ts,dts)
  PROVE PreparedProvenance'
<1>1. LogsExtend
  BY SMT, LogAppendFacts, PreparedCommitAppends
<1> QED BY SMT, <1>1 DEF Inv, SnapshotShape, PrepareShape,
  PreparedProvenance, LogsExtend, CommitPreparedTransaction, PreparedTransactions, ActiveTransactions

THEOREM PrepareTransactionPreservesProvenance ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, 
         Inv, LogShape, PrepareShape, PreparedProvenance, PrepareTransaction(n,t,ts)
  PROVE PreparedProvenance'
<1>1. LogsExtend
  BY SMT, LogAppendFacts DEF PrepareTransaction, PrepareTxnToLog
<1>2. /\ Len(mlog[n])+1 \in DOMAIN mlog'[n]
        /\ mlog'[n][Len(mlog[n])+1] = [prepare |-> TRUE, ts |-> ts, tid |-> t]
  BY SMT, LogAppendFacts DEF PrepareTransaction, PrepareTxnToLog
<1> QED BY SMT, <1>1, <1>2 DEF Inv, SnapshotShape, PrepareShape,
  PreparedProvenance, LogsExtend, PrepareTransaction, PreparedTransactions,
  ActiveTransactions

THEOREM PreparedProvenanceStep ==
  Inv /\ LogShape /\ PrepareShape /\ PreparedProvenance /\ [EpochNext]_vars
    => PreparedProvenance'
BY SMT, StartTransactionPreservesProvenance, TransactionWritePreservesProvenance,
  TransactionReadPreservesProvenance, TransactionRemovePreservesProvenance,
  AbortTransactionPreservesProvenance, PrepareTransactionPreservesProvenance,
  CommitTransactionPreservesProvenance, CommitPreparedTransactionPreservesProvenance
  DEF EpochNext, vars, SetStableTimestamp, SetOldestTimestamp, PreparedProvenance,
      ActiveTransactions, PreparedTransactions

THEOREM EpochLogShape == EpochSpec => []LogShape
BY ProvenanceInit, LogShapeStep, PTL DEF EpochSpec

THEOREM EpochPrepareShape == EpochSpec => []PrepareShape
BY EpochBehaviorProjection, FullNextShape, ProvenanceInit, PrepareShapeStep,
   PTL DEF EpochSpec

THEOREM EpochPreparedProvenance == EpochSpec => []PreparedProvenance
BY EpochBehaviorProjection, FullNextShape, EpochLogShape, EpochPrepareShape,
   ProvenanceInit, PreparedProvenanceStep, PTL DEF EpochSpec
=============================================================================

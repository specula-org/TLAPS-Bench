-------------------------- MODULE StorageCoherence --------------------------
EXTENDS StorageTimestamps, StorageReadAlgebra

DataShape ==
  \A n \in Node : \A t \in ActiveTransactions(n) :
    /\ "data" \in DOMAIN mtxnSnapshots[n][t]
    /\ DOMAIN mtxnSnapshots[n][t].data = Keys

CoherenceCore ==
  \A n \in Node : \A t \in ActiveTransactions(n) : \A k \in Keys :
    k \notin mtxnSnapshots[n][t].writeSet =>
      \/ LatePrepared(mlog[n],t,k,mtxnSnapshots[n][t].ts)
      \/ mtxnSnapshots[n][t].data[k] = LogRead(mlog[n],k,mtxnSnapshots[n][t].ts)

ActiveSnapshotCoherence ==
  \A n \in Node : \A t \in ActiveTransactions(n) : \A k \in Keys :
    k \notin mtxnSnapshots[n][t].writeSet =>
      TxnRead(n,t,k) = SnapshotRead(n,k,mtxnSnapshots[n][t].ts).value

SnapshotReadFrame ==
  \A n \in Node, t \in MTxId : mtxnSnapshots'[n][t].active =>
    /\ mtxnSnapshots[n][t].active
    /\ mtxnSnapshots'[n][t].ts = mtxnSnapshots[n][t].ts
    /\ \A k \in Keys : k \notin mtxnSnapshots'[n][t].writeSet =>
         /\ k \notin mtxnSnapshots[n][t].writeSet
         /\ mtxnSnapshots'[n][t].data[k] = mtxnSnapshots[n][t].data[k]

ReaderLogFrame ==
  \A n \in Node, t \in MTxId, k \in Keys :
    (mtxnSnapshots'[n][t].active /\ k \notin mtxnSnapshots'[n][t].writeSet) =>
      /\ (LatePrepared(mlog[n],t,k,mtxnSnapshots[n][t].ts) =>
           LatePrepared(mlog'[n],t,k,mtxnSnapshots'[n][t].ts))
      /\ (LogRead(mlog'[n],k,mtxnSnapshots'[n][t].ts) =
             LogRead(mlog[n],k,mtxnSnapshots[n][t].ts)
          \/ LatePrepared(mlog'[n],t,k,mtxnSnapshots'[n][t].ts))

THEOREM CoherenceFromFrames ==
  CoherenceCore /\ SnapshotReadFrame /\ ReaderLogFrame => CoherenceCore'
BY SMT DEF CoherenceCore, SnapshotReadFrame, ReaderLogFrame, ActiveTransactions

THEOREM DataShapeInitial == Init => DataShape
BY SMT DEF Init, DataShape, ActiveTransactions

THEOREM DataShapeStep == Inv /\ DataShape /\ [EpochNext]_vars => DataShape'
BY SMTT(20) DEF Inv, SnapshotShape, DataShape, EpochNext, vars,
  SnapshotKV, ActiveTransactions, StartTransaction,
  TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
  CommitTransaction, CommitPreparedTransaction, AbortTransaction,
  SetStableTimestamp, SetOldestTimestamp

THEOREM CoherenceInitial == Init => CoherenceCore
BY SMT DEF Init, CoherenceCore, ActiveTransactions

NoLogStep ==
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values : TransactionWrite(n,t,k,v,"false")
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : TransactionRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys : TransactionRemove(n,t,k)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)
    \/ UNCHANGED vars

THEOREM NoLogCoherenceFrames ==
  Inv /\ DataShape /\ TimestampShape /\ NoLogStep =>
    (SnapshotReadFrame /\ ReaderLogFrame)
<1>1. Inv /\ DataShape /\ TimestampShape /\ NoLogStep =>
        (SnapshotReadFrame /\ mlog' = mlog)
  BY SMTT(20) DEF Inv, SnapshotShape, DataShape, TimestampShape, NoLogStep,
       SnapshotReadFrame, ActiveTransactions, vars, TransactionWrite,
       TransactionRead, TransactionRemove, AbortTransaction, SetStableTimestamp,
       SetOldestTimestamp
<1> QED BY SMT, <1>1 DEF SnapshotReadFrame, ReaderLogFrame

THEOREM StartCoherence ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW ip,
         Inv, DataShape, TimestampShape, CoherenceCore,
         StartTransaction(n,t,ts,"snapshot",ip)
  PROVE CoherenceCore'
BY SMTT(20), SnapshotReadValue
   DEF Inv, SnapshotShape, DataShape, TimestampShape, CoherenceCore,
       ActiveTransactions, StartTransaction, SnapshotKV

THEOREM PrepareTransactionCoherenceFrames ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts,
         Inv, DataShape, TimestampShape, LogShape, TimestampBound,
         PreparedProvenance, PrepareTransaction(n,t,ts)
  PROVE SnapshotReadFrame /\ ReaderLogFrame
<1>1. SnapshotReadFrame
  BY SMT DEF Inv, SnapshotShape, DataShape, TimestampShape, SnapshotReadFrame,
       ActiveTransactions, PrepareTransaction
<1>2. ReaderLogFrame
  BY SMTT(20), <1>1, InvisibleAppendRead, LatePreparedAppendMonotone
     DEF ReaderLogFrame, SnapshotReadFrame, LogShape,
         PrepareTransaction, PrepareTxnToLog
<1> QED BY SMT, <1>1, <1>2

THEOREM ReaderAppendFrameLemma ==
  ASSUME NEW n \in Node, NEW e, LogShape, SnapshotReadFrame,
         mlog' = [mlog EXCEPT ![n] = Append(@,e)],
         \A r \in MTxId, k \in Keys :
           (mtxnSnapshots'[n][r].active /\ k \notin mtxnSnapshots'[n][r].writeSet) =>
             /\ (LatePrepared(mlog[n],r,k,mtxnSnapshots[n][r].ts) =>
                  LatePrepared(Append(mlog[n],e),r,k,mtxnSnapshots[n][r].ts))
             /\ (LogRead(Append(mlog[n],e),k,mtxnSnapshots[n][r].ts) =
                    LogRead(mlog[n],k,mtxnSnapshots[n][r].ts)
                 \/ LatePrepared(Append(mlog[n],e),r,k,mtxnSnapshots[n][r].ts))
  PROVE ReaderLogFrame
BY SMT DEF LogShape, SnapshotReadFrame, ReaderLogFrame

THEOREM ReaderTimestampsNatural ==
  Inv /\ TimestampBound =>
    \A n \in Node : \A r \in ActiveTransactions(n) : mtxnSnapshots[n][r].ts \in Nat
BY SMT DEF Inv, SnapshotShape, TimestampBound, ActiveReadTimestamps, ActiveTransactions

THEOREM CommitTransactionCoherenceFrames ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, DataShape, TimestampShape, LogShape, TimestampBound,
         PreparedProvenance, CommitTransaction(n,t,ts)
  PROVE SnapshotReadFrame /\ ReaderLogFrame
<1>1. SnapshotReadFrame
  BY SMT DEF Inv, SnapshotShape, DataShape, TimestampShape, SnapshotReadFrame,
       ActiveTransactions, CommitTransaction
<1>2. \A r \in ActiveTransactions(n) : ts > mtxnSnapshots[n][r].ts
  BY SMT, OrdinaryCommitAfterReaders
<1>3. \A r \in ActiveTransactions(n), k \in Keys :
        /\ (LatePrepared(mlog[n],r,k,mtxnSnapshots[n][r].ts) =>
             LatePrepared(Append(mlog[n],CommitLogEntry(n,t,ts)),r,k,mtxnSnapshots[n][r].ts))
        /\ LogRead(Append(mlog[n],CommitLogEntry(n,t,ts)),k,mtxnSnapshots[n][r].ts) =
             LogRead(mlog[n],k,mtxnSnapshots[n][r].ts)
  BY SMTT(15), <1>2, ReaderTimestampsNatural, InvisibleAppendRead, LatePreparedAppendMonotone
     DEF LogShape, CommitLogEntry
<1>4. ReaderLogFrame
  BY SMT, <1>1, <1>3, ReaderAppendFrameLemma
     DEF CommitTransaction, CommitTxnToLog, SnapshotReadFrame, ActiveTransactions
<1> QED BY SMT, <1>1, <1>4

THEOREM CommitPreparedTransactionCoherenceFrames ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         Inv, DataShape, TimestampShape, LogShape, TimestampBound,
         PreparedProvenance, CommitPreparedTransaction(n,t,ts,dts)
  PROVE SnapshotReadFrame /\ ReaderLogFrame
<1>1. SnapshotReadFrame
  BY SMT DEF Inv, SnapshotShape, DataShape, TimestampShape, SnapshotReadFrame,
       ActiveTransactions, CommitPreparedTransaction
<1>2. \E p \in DOMAIN mlog[n] :
        "prepare" \in DOMAIN mlog[n][p] /\ mlog[n][p].tid = t
  BY SMT DEF PreparedProvenance, PreparedTransactions, CommitPreparedTransaction
<1>3. \A r \in MTxId \ {t}, k \in Keys :
        /\ (LatePrepared(mlog[n],r,k,mtxnSnapshots[n][r].ts) =>
             LatePrepared(Append(mlog[n],DurableEntry(n,t,ts,dts)),r,k,mtxnSnapshots[n][r].ts))
        /\ (LogRead(Append(mlog[n],DurableEntry(n,t,ts,dts)),k,mtxnSnapshots[n][r].ts) =
             LogRead(mlog[n],k,mtxnSnapshots[n][r].ts)
            \/ LatePrepared(Append(mlog[n],DurableEntry(n,t,ts,dts)),r,k,mtxnSnapshots[n][r].ts))
  BY SMTT(15), <1>2, LatePreparedAppendMonotone, PreparedAppendRead
     DEF LogShape, DurableEntry
<1>4. ~mtxnSnapshots'[n][t].active
  BY SMT DEF Inv, SnapshotShape, CommitPreparedTransaction
<1>5. ReaderLogFrame
  BY SMT, <1>1, <1>3, <1>4, ReaderAppendFrameLemma, DurableAppendForm
     DEF CommitPreparedTransaction
<1> QED BY SMT, <1>1, <1>5

THEOREM CoherenceStep ==
  Inv /\ DataShape /\ TimestampShape /\ LogShape /\ TimestampBound /\
  PreparedProvenance /\ CoherenceCore /\ [EpochNext]_vars => CoherenceCore'
BY SMT, CoherenceFromFrames, NoLogCoherenceFrames, StartCoherence,
   PrepareTransactionCoherenceFrames, CommitTransactionCoherenceFrames,
   CommitPreparedTransactionCoherenceFrames, SnapshotConcern, NaturalTimestampDomain
   DEF EpochNext, NoLogStep

THEOREM EpochDataShape == EpochSpec => []DataShape
BY EpochBehaviorProjection, FullNextShape, DataShapeInitial, DataShapeStep,
   PTL DEF EpochSpec

THEOREM EpochCoherenceCore == EpochSpec => []CoherenceCore
BY EpochBehaviorProjection, FullNextShape, EpochDataShape, EpochTimestampShape,
   EpochLogShape, EpochTimestampBound, EpochPreparedProvenance,
   CoherenceInitial, CoherenceStep, PTL DEF EpochSpec

THEOREM CoreImpliesCoherence == CoherenceCore => ActiveSnapshotCoherence
BY SMT, TxnReadChoice, SnapshotReadValue
   DEF CoherenceCore, ActiveSnapshotCoherence

THEOREM EpochActiveSnapshotCoherence == EpochSpec => []ActiveSnapshotCoherence
BY EpochCoherenceCore, CoreImpliesCoherence, PTL
=============================================================================

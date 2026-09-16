-------------------------- MODULE StorageTimestamps --------------------------
EXTENDS StorageProvenance, StorageLogAlgebra, StorageArithmetic

ASSUME SnapshotConcern == RC = "snapshot"
ASSUME NaturalTimestampDomain == Timestamps \subseteq Nat

TimestampShape ==
  /\ \A n \in Node : \A t \in ActiveTransactions(n) :
       "ts" \in DOMAIN mtxnSnapshots[n][t]
  /\ \A n \in Node : \A i \in DOMAIN mlog[n] : "ts" \in DOMAIN mlog[n][i]

TimestampBound ==
  \A n \in Node : \E b \in Nat :
    (ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \subseteq 0..b

TimestampGrowth(ts) ==
  \A n \in Node :
    (ActiveReadTimestamps(n)' \cup CommitTimestamps(n)') \subseteq
      (ActiveReadTimestamps(n) \cup CommitTimestamps(n) \cup {0,ts})

THEOREM GrowBound ==
  ASSUME NEW S, NEW S2, NEW ts \in Nat,
         \E b \in Nat : S \subseteq 0..b,
         S2 \subseteq S \cup {0,ts}
  PROVE \E b \in Nat : S2 \subseteq 0..b
<1>1. PICK b \in Nat : S \subseteq 0..b BY SMT
<1>2. S2 \subseteq 0..(b+ts) BY SMT, <1>1
<1> QED BY SMT, <1>2

THEOREM TimestampGrowthPreservesBound ==
  ASSUME NEW ts \in Nat, TimestampBound, TimestampGrowth(ts)
  PROVE TimestampBound'
BY SMT, GrowBound DEF TimestampBound, TimestampGrowth

THEOREM TimestampInitial == Init => (TimestampShape /\ TimestampBound)
BY SMT DEF Init, TimestampShape, TimestampBound, ActiveTransactions,
           ActiveReadTimestamps, CommitTimestamps

THEOREM TimestampShapeStep ==
  Inv /\ LogShape /\ TimestampShape /\ [EpochNext]_vars => TimestampShape'
BY SMTT(20), AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, EpochNext, vars,
       SnapshotKV, ActiveTransactions, StartTransaction,
       TransactionWrite, TransactionRead, TransactionRemove, PrepareTransaction,
       CommitTransaction, CommitPreparedTransaction, AbortTransaction,
       SetStableTimestamp, SetOldestTimestamp, PrepareTxnToLog, CommitTxnToLog,
       CommitLogEntry, DurableEntry

THEOREM StartTransactionTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, LogShape, TimestampShape, StartTransaction(n,t,ts,"snapshot","false")
  PROVE TimestampGrowth(ts)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, StartTransaction, SnapshotKV

THEOREM TransactionWriteTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, LogShape, TimestampShape, TransactionWrite(n,t,k,v,"false")
  PROVE TimestampGrowth(0)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, TransactionWrite

THEOREM TransactionReadTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, LogShape, TimestampShape, TransactionRead(n,t,k,v)
  PROVE TimestampGrowth(0)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, TransactionRead

THEOREM TransactionRemoveTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys,
         Inv, LogShape, TimestampShape, TransactionRemove(n,t,k)
  PROVE TimestampGrowth(0)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, TransactionRemove

THEOREM AbortTransactionTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, 
         Inv, LogShape, TimestampShape, AbortTransaction(n,t)
  PROVE TimestampGrowth(0)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, AbortTransaction

THEOREM PrepareTransactionTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, LogShape, TimestampShape, PrepareTransaction(n,t,ts)
  PROVE TimestampGrowth(ts)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, PrepareTransaction, PrepareTxnToLog

THEOREM CommitTransactionTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, LogShape, TimestampShape, CommitTransaction(n,t,ts)
  PROVE TimestampGrowth(ts)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, CommitTransaction, CommitTxnToLog, CommitLogEntry

THEOREM CommitPreparedTransactionTimestampGrowth ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat, NEW dts,
         Inv, LogShape, TimestampShape, CommitPreparedTransaction(n,t,ts,dts)
  PROVE TimestampGrowth(ts)
BY SMTT(15), AppendImage, AppendEntries, SequenceDomain, DurableAppendForm
   DEF Inv, SnapshotShape, LogShape, TimestampShape, TimestampGrowth,
       ActiveTransactions, ActiveReadTimestamps, CommitTimestamps, CommitPreparedTransaction, DurableEntry

THEOREM TimestampBoundStep ==
  Inv /\ LogShape /\ TimestampShape /\ TimestampBound /\ [EpochNext]_vars => TimestampBound'
BY SMT, TimestampGrowthPreservesBound, StartTransactionTimestampGrowth,
   TransactionWriteTimestampGrowth, TransactionReadTimestampGrowth,
   TransactionRemoveTimestampGrowth, AbortTransactionTimestampGrowth,
   PrepareTransactionTimestampGrowth, CommitTransactionTimestampGrowth,
   CommitPreparedTransactionTimestampGrowth, SnapshotConcern, NaturalTimestampDomain
   DEF EpochNext, vars, IgnorePrepareOptions, SetStableTimestamp, SetOldestTimestamp,
       TimestampBound, ActiveReadTimestamps, CommitTimestamps

THEOREM EpochTimestampShape == EpochSpec => []TimestampShape
BY EpochBehaviorProjection, FullNextShape, EpochLogShape, TimestampInitial,
   TimestampShapeStep, PTL DEF EpochSpec

THEOREM EpochTimestampBound == EpochSpec => []TimestampBound
BY EpochBehaviorProjection, FullNextShape, EpochLogShape, EpochTimestampShape,
   TimestampInitial, TimestampBoundStep, PTL DEF EpochSpec

THEOREM OrdinaryCommitAfterReaders ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         NEW r \in ActiveTransactions(n), Inv, TimestampBound,
         CommitTransaction(n,t,ts)
  PROVE ts > mtxnSnapshots[n][r].ts
<1>1. PICK b \in Nat : (ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \subseteq 0..b
  BY SMT DEF TimestampBound
<1>2. mtxnSnapshots[n][r].ts \in (ActiveReadTimestamps(n) \cup CommitTimestamps(n))
  BY SMT DEF Inv, SnapshotShape, ActiveReadTimestamps, ActiveTransactions
<1>3. /\ Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \in 0..b
        /\ mtxnSnapshots[n][r].ts <= Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n))
  BY SMT, <1>1, <1>2, BoundedMaximum
<1> QED BY SMT, <1>1, <1>2, <1>3 DEF CommitTransaction

THEOREM PrepareAfterReaders ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         NEW r \in ActiveTransactions(n), Inv, TimestampBound,
         PrepareTransaction(n,t,ts)
  PROVE ts > mtxnSnapshots[n][r].ts
<1>1. PICK b \in Nat : ActiveReadTimestamps(n) \subseteq 0..b
  BY SMT DEF TimestampBound
<1>2. mtxnSnapshots[n][r].ts \in ActiveReadTimestamps(n)
  BY SMT DEF Inv, SnapshotShape, ActiveReadTimestamps, ActiveTransactions
<1>3. /\ Max(ActiveReadTimestamps(n)) \in 0..b
        /\ mtxnSnapshots[n][r].ts <= Max(ActiveReadTimestamps(n))
  BY SMT, <1>1, <1>2, BoundedMaximum
<1> QED BY SMT, <1>1, <1>2, <1>3 DEF PrepareTransaction
=============================================================================

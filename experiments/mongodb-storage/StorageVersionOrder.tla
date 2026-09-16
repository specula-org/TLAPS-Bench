------------------------ MODULE StorageVersionOrder ------------------------
EXTENDS StorageTimestamps, StorageCommitProvenance

PreparedOrder ==
  \A n \in Node : \A t \in PreparedTransactions(n) :
    /\ mtxnSnapshots[n][t].prepareTs \in Nat
    /\ mtxnSnapshots[n][t].ts < mtxnSnapshots[n][t].prepareTs

FreshWrites ==
  \A n \in Node : \A t \in ActiveTransactions(n) :
    \A i \in DOMAIN mlog[n] :
      ("data" \in DOMAIN mlog[n][i] /\
        mtxnSnapshots[n][t].writeSet \cap DOMAIN mlog[n][i].data # {})
        => mlog[n][i].ts <= mtxnSnapshots[n][t].ts

PerKeyStrictOrder ==
  \A n \in Node : \A i,j \in DOMAIN mlog[n] :
    (/\ i < j /\ "data" \in DOMAIN mlog[n][i] /\ "data" \in DOMAIN mlog[n][j]
     /\ DOMAIN mlog[n][i].data \cap DOMAIN mlog[n][j].data # {})
      => mlog[n][i].ts < mlog[n][j].ts

THEOREM ReachableTimesNatural ==
  Inv /\ TimestampBound =>
    /\ \A n \in Node : \A t \in ActiveTransactions(n) : mtxnSnapshots[n][t].ts \in Nat
    /\ \A n \in Node : \A i \in DOMAIN mlog[n] : mlog[n][i].ts \in Nat
BY SMT DEF Inv, SnapshotShape, TimestampBound, ActiveReadTimestamps,
           CommitTimestamps, ActiveTransactions

THEOREM PreparedOrderInitial == Init => PreparedOrder
BY SMT DEF Init, PreparedOrder, PreparedTransactions, ActiveTransactions

THEOREM PrepareEstablishesOrder ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, PrepareShape, TimestampShape, TimestampBound, PreparedOrder,
         PrepareTransaction(n,t,ts)
  PROVE PreparedOrder'
<1>1. ts > mtxnSnapshots[n][t].ts
  BY SMT, PrepareAfterReaders DEF PrepareTransaction
<1> QED BY SMT, <1>1 DEF Inv, SnapshotShape, PrepareShape, TimestampShape,
       PreparedOrder, PrepareTransaction, PreparedTransactions, ActiveTransactions

THEOREM PreparedOrderStep ==
  Inv /\ PrepareShape /\ TimestampShape /\ TimestampBound /\ PreparedOrder /\
  [EpochNext]_vars => PreparedOrder'
BY SMTT(20), PrepareEstablishesOrder, NaturalTimestampDomain, SnapshotConcern
   DEF Inv, SnapshotShape, PrepareShape, TimestampShape, PreparedOrder,
       EpochNext, vars, ActiveTransactions, PreparedTransactions, SnapshotKV,
       StartTransaction, TransactionWrite, TransactionRead, TransactionRemove,
       CommitTransaction, CommitPreparedTransaction, AbortTransaction,
       SetStableTimestamp, SetOldestTimestamp

THEOREM EpochPreparedOrder == EpochSpec => []PreparedOrder
BY EpochBehaviorProjection, FullNextShape, EpochPrepareShape, EpochTimestampShape,
   EpochTimestampBound, PreparedOrderInitial, PreparedOrderStep, PTL DEF EpochSpec

THEOREM FreshKeyAdmission ==
  ASSUME NEW n \in Node, NEW t \in ActiveTransactions(n), NEW k,
         Inv, Lifecycle, CommitProvenance, TimestampBound,
         ~WriteConflictExists(n,t,k)
  PROVE \A i \in DOMAIN mlog[n] :
    ("data" \in DOMAIN mlog[n][i] /\ k \in DOMAIN mlog[n][i].data)
       => mlog[n][i].ts <= mtxnSnapshots[n][t].ts
BY SMTT(15), ReachableTimesNatural
   DEF CommitProvenance, Lifecycle, ActiveTransactions, WriteConflictExists

THEOREM FreshWritesInitial == Init => FreshWrites
BY SMT DEF Init, FreshWrites, ActiveTransactions

WriteSetFrame ==
  \A n \in Node, t \in MTxId : mtxnSnapshots'[n][t].active =>
    /\ mtxnSnapshots[n][t].active
    /\ mtxnSnapshots'[n][t].ts = mtxnSnapshots[n][t].ts
    /\ mtxnSnapshots'[n][t].writeSet \subseteq mtxnSnapshots[n][t].writeSet

THEOREM FreshWritesNoLog ==
  FreshWrites /\ WriteSetFrame /\ mlog'=mlog => FreshWrites'
BY SMT DEF FreshWrites, WriteSetFrame, ActiveTransactions

THEOREM FreshWritesAppend ==
  ASSUME NEW n \in Node, NEW e, LogShape, FreshWrites, WriteSetFrame,
         mlog' = [mlog EXCEPT ![n] = Append(@,e)],
         \A t \in MTxId : mtxnSnapshots'[n][t].active =>
           ("data" \notin DOMAIN e \/
             mtxnSnapshots'[n][t].writeSet \cap DOMAIN e.data = {})
  PROVE FreshWrites'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF LogShape, FreshWrites, WriteSetFrame, ActiveTransactions

THEOREM StartFreshWrites ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW ip,
         Inv, TimestampShape, FreshWrites, StartTransaction(n,t,ts,"snapshot",ip)
  PROVE FreshWrites'
BY SMT DEF Inv, SnapshotShape, TimestampShape, FreshWrites,
           StartTransaction, SnapshotKV, ActiveTransactions

THEOREM MutationFreshWrites ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW k \in Keys, NEW v,
         Inv, TimestampShape, TimestampBound, Lifecycle, CommitProvenance,
         FreshWrites,
         TransactionWrite(n,t,k,v,"false") \/ TransactionRemove(n,t,k)
  PROVE FreshWrites'
<1>1. ~WriteConflictExists(n,t,k) =>
        \A i \in DOMAIN mlog[n] :
          ("data" \in DOMAIN mlog[n][i] /\ k \in DOMAIN mlog[n][i].data)
             => mlog[n][i].ts <= mtxnSnapshots[n][t].ts
  BY SMT, FreshKeyAdmission DEF TransactionWrite, TransactionRemove
<1>2. /\ mlog'=mlog
        /\ \A q \in Node, r \in MTxId :
          /\ mtxnSnapshots'[q][r].active = mtxnSnapshots[q][r].active
          /\ (mtxnSnapshots[q][r].active =>
               /\ mtxnSnapshots'[q][r].ts = mtxnSnapshots[q][r].ts
               /\ (mtxnSnapshots'[q][r].writeSet = mtxnSnapshots[q][r].writeSet
                  \/ /\ q=n /\ r=t /\ ~WriteConflictExists(n,t,k)
                     /\ mtxnSnapshots'[q][r].writeSet = mtxnSnapshots[q][r].writeSet \cup {k}))
  BY SMT DEF Inv, SnapshotShape, TimestampShape, ActiveTransactions,
             TransactionWrite, TransactionRemove
<1> QED BY SMTT(15), <1>1, <1>2 DEF FreshWrites, ActiveTransactions

THEOREM PrepareFreshWrites ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts,
         Inv, TimestampShape, LogShape, FreshWrites, PrepareTransaction(n,t,ts)
  PROVE FreshWrites'
<1>1. WriteSetFrame
  BY SMT DEF Inv, SnapshotShape, TimestampShape, WriteSetFrame,
             ActiveTransactions, PrepareTransaction
<1> QED BY SMT, <1>1, FreshWritesAppend DEF PrepareTransaction, PrepareTxnToLog

THEOREM CommitFreshWrites ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         Inv, TimestampShape, LogShape, FreshWrites,
         CommitTransaction(n,t,ts) \/ CommitPreparedTransaction(n,t,ts,dts)
  PROVE FreshWrites'
<1>1. WriteSetFrame
  BY SMT DEF Inv, SnapshotShape, TimestampShape, WriteSetFrame,
             ActiveTransactions, CommitTransaction, CommitPreparedTransaction
<1>2. \A r \in MTxId : mtxnSnapshots'[n][r].active =>
        mtxnSnapshots'[n][r].writeSet \cap SnapshotUpdatedKeys(n,t) = {}
  BY SMT DEF Inv, SnapshotShape, WriterExclusion, ActiveTransactions,
             SnapshotUpdatedKeys, CommitTransaction, CommitPreparedTransaction
<1> QED BY SMTT(20), <1>1, <1>2, FreshWritesAppend, DurableAppendForm
     DEF CommitTransaction, CommitPreparedTransaction, CommitTxnToLog,
         CommitLogEntry, DurableEntry

VersionNoLogStep ==
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : TransactionRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)
    \/ UNCHANGED vars

THEOREM VersionNoLogFrame ==
  Inv /\ TimestampShape /\ VersionNoLogStep => (WriteSetFrame /\ mlog'=mlog)
BY SMT DEF Inv, SnapshotShape, TimestampShape, VersionNoLogStep, WriteSetFrame,
           ActiveTransactions, TransactionRead, AbortTransaction, SetStableTimestamp,
           SetOldestTimestamp, vars

THEOREM FreshWritesStep ==
  Inv /\ TimestampShape /\ TimestampBound /\ Lifecycle /\ CommitProvenance /\
  LogShape /\ FreshWrites /\ [EpochNext]_vars => FreshWrites'
BY SMTT(20), StartFreshWrites, MutationFreshWrites, PrepareFreshWrites,
   CommitFreshWrites, FreshWritesNoLog, VersionNoLogFrame, SnapshotConcern
   DEF EpochNext, VersionNoLogStep

THEOREM EpochFreshWrites == EpochSpec => []FreshWrites
BY EpochBehaviorProjection, FullNextShape, FullNextLifecycle, EpochTimestampShape,
   EpochTimestampBound, EpochCommitProvenance, EpochLogShape,
   FreshWritesInitial, FreshWritesStep, PTL DEF EpochSpec

THEOREM PerKeyOrderInitial == Init => PerKeyStrictOrder
BY SMT DEF Init, PerKeyStrictOrder

THEOREM PerKeyOrderAppend ==
  ASSUME NEW n \in Node, NEW e, LogShape, PerKeyStrictOrder,
         mlog' = [mlog EXCEPT ![n] = Append(@,e)],
         \A i \in DOMAIN mlog[n] :
           ("data" \in DOMAIN mlog[n][i] /\ "data" \in DOMAIN e /\
             DOMAIN mlog[n][i].data \cap DOMAIN e.data # {}) => mlog[n][i].ts < e.ts
  PROVE PerKeyStrictOrder'
BY SMTT(20), AppendEntries, SequenceDomain DEF LogShape, PerKeyStrictOrder

THEOREM CommitsAfterOwnSnapshot ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat, NEW dts,
         Inv, TimestampBound, PreparedOrder,
         CommitTransaction(n,t,ts) \/ CommitPreparedTransaction(n,t,ts,dts)
  PROVE ts > mtxnSnapshots[n][t].ts
BY SMT, OrdinaryCommitAfterReaders, ReachableTimesNatural
   DEF PreparedOrder, CommitTransaction, CommitPreparedTransaction

THEOREM CommitPerKeyOrder ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat, NEW dts,
         Inv, TimestampBound, PreparedOrder, LogShape, FreshWrites, PerKeyStrictOrder,
         CommitTransaction(n,t,ts) \/ CommitPreparedTransaction(n,t,ts,dts)
  PROVE PerKeyStrictOrder'
<1>1. ts > mtxnSnapshots[n][t].ts BY SMT, CommitsAfterOwnSnapshot
<1>2. \A i \in DOMAIN mlog[n] :
        ("data" \in DOMAIN mlog[n][i] /\
         DOMAIN mlog[n][i].data \cap SnapshotUpdatedKeys(n,t) # {}) => mlog[n][i].ts < ts
  BY SMT, <1>1, ReachableTimesNatural
     DEF FreshWrites, SnapshotUpdatedKeys, CommitTransaction, CommitPreparedTransaction
<1> QED BY SMTT(20), <1>2, PerKeyOrderAppend, DurableAppendForm
     DEF CommitTransaction, CommitPreparedTransaction, CommitTxnToLog,
         CommitLogEntry, DurableEntry

THEOREM PerKeyOrderQuiet == PerKeyStrictOrder /\ mlog'=mlog => PerKeyStrictOrder'
BY SMT DEF PerKeyStrictOrder

THEOREM PreparePerKeyOrder ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, LogShape, PerKeyStrictOrder,
         PrepareTransaction(n,t,ts)
  PROVE PerKeyStrictOrder'
BY SMT, PerKeyOrderAppend DEF PrepareTransaction, PrepareTxnToLog

THEOREM PerKeyOrderStep ==
  Inv /\ TimestampBound /\ PreparedOrder /\ LogShape /\ FreshWrites /\
  PerKeyStrictOrder /\ [EpochNext]_vars => PerKeyStrictOrder'
BY SMTT(20), CommitPerKeyOrder, PreparePerKeyOrder, PerKeyOrderQuiet, NaturalTimestampDomain
   DEF EpochNext, vars, StartTransaction, TransactionRead,
       TransactionWrite, TransactionRemove, AbortTransaction,
       SetStableTimestamp, SetOldestTimestamp

THEOREM EpochPerKeyStrictOrder == EpochSpec => []PerKeyStrictOrder
BY EpochBehaviorProjection, FullNextShape, EpochTimestampBound, EpochPreparedOrder,
   EpochLogShape, EpochFreshWrites, PerKeyOrderInitial, PerKeyOrderStep, PTL DEF EpochSpec
=============================================================================

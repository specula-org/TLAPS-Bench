------------------------ MODULE StorageReadStability ------------------------
EXTENDS StorageCaller, StorageCommitIdentity

UsedTransactions(n) == ActiveTransactions(n) \cup CommittedTransactions(n,mtxnSnapshots)

THEOREM UsedReaderTypes ==
  Inv /\ TimestampShape /\ TimestampBound /\ CommitIdentity /\ CommitSnapshot =>
    \A n \in Node : \A t \in UsedTransactions(n) :
      /\ "ts" \in DOMAIN mtxnSnapshots[n][t]
      /\ mtxnSnapshots[n][t].ts \in Nat
BY SMT, ReachableTimesNatural
   DEF UsedTransactions, CommittedTransactions, ActiveTransactions,
       TimestampShape, CommitIdentity, CommitSnapshot

THEOREM OrdinaryCommitAfterLog ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         TimestampBound, CommitTransaction(n,t,ts)
  PROVE \A i \in DOMAIN mlog[n] : mlog[n][i].ts < ts
<1>1. PICK b \in Nat : (ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \subseteq 0..b
  BY SMT DEF TimestampBound
<1>2. ASSUME NEW i \in DOMAIN mlog[n] PROVE mlog[n][i].ts < ts
  <2>1. mlog[n][i].ts \in ActiveReadTimestamps(n) \cup CommitTimestamps(n)
    BY SMT, <1>2 DEF CommitTimestamps
  <2>2. /\ Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n)) \in 0..b
          /\ mlog[n][i].ts <= Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n))
    BY SMT, <1>1, <2>1, BoundedMaximum
  <2> QED BY SMT, <1>1, <2>1, <2>2 DEF CommitTransaction
<1> QED BY SMT, <1>2

THEOREM OrdinaryCommitAfterUsedReaders ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, TimestampBound, CommitIdentity, CommitSnapshot, CommitTransaction(n,t,ts)
  PROVE \A r \in UsedTransactions(n) : mtxnSnapshots[n][r].ts < ts
BY SMT, OrdinaryCommitAfterReaders, OrdinaryCommitAfterLog, ReachableTimesNatural
   DEF UsedTransactions, CommittedTransactions, CommitIdentity, CommitSnapshot

THEOREM CallerPrepareAfterUsedReaders ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Timestamps,
         Inv, TimestampBound, CommitIdentity, CommitSnapshot,
         FreshPrepareCall, PrepareTransaction(n,t,ts)
  PROVE \A r \in UsedTransactions(n) : mtxnSnapshots[n][r].ts < ts
BY SMT, PrepareAfterReaders, NaturalTimestampDomain, ReachableTimesNatural
   DEF UsedTransactions, CommittedTransactions, CommitIdentity, CommitSnapshot,
       FreshPrepareCall

UsedTimestampFrame ==
  \A n \in Node : \A t \in UsedTransactions(n) :
    mtxnSnapshots'[n][t].ts = mtxnSnapshots[n][t].ts

THEOREM UsedTimestampFrameStep ==
  Inv /\ Lifecycle /\ TimestampShape /\ TimestampBound /\ CommitIdentity /\
  CommitSnapshot /\ [EpochNext]_vars => UsedTimestampFrame
BY SMTT(20), UsedReaderTypes
   DEF UsedTimestampFrame, UsedTransactions, CommittedTransactions, Inv,
       SnapshotShape, Lifecycle, ActiveTransactions, EpochNext, vars,
       StartTransaction, TransactionWrite, TransactionRead, TransactionRemove,
       PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
       AbortTransaction, SetStableTimestamp, SetOldestTimestamp

THEOREM PreparedCommitInvisibleToSafeReader ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat, NEW dts,
         NEW r \in UsedTransactions(n), NEW k \in Keys,
         Inv, TimestampShape, TimestampBound, CommitIdentity, CommitSnapshot,
         PreparedOrder, ~PrepareConflict(n,r,k), CommitPreparedTransaction(n,t,ts,dts)
  PROVE ~("data" \in DOMAIN DurableEntry(n,t,ts,dts) /\
           k \in DOMAIN DurableEntry(n,t,ts,dts).data /\
           DurableEntry(n,t,ts,dts).ts <= mtxnSnapshots[n][r].ts)
<1>1. /\ mtxnSnapshots[n][r].ts \in Nat
        /\ mtxnSnapshots[n][t].prepareTs \in Nat
        /\ mtxnSnapshots[n][t].ts < ts
  BY SMT, UsedReaderTypes, CommitsAfterOwnSnapshot
     DEF PreparedOrder, CommitPreparedTransaction
<1> QED BY SMT, <1>1 DEF PrepareConflict, DurableEntry, CommitPreparedTransaction,
                        PreparedTransactions, SnapshotUpdatedKeys

SafeReadTransport ==
  \A n \in Node : \A r \in UsedTransactions(n) : \A k \in Keys :
    ~PrepareConflict(n,r,k) =>
      /\ ~PrepareConflict(n,r,k)'
      /\ LogRead(mlog'[n],k,mtxnSnapshots'[n][r].ts) =
           LogRead(mlog[n],k,mtxnSnapshots[n][r].ts)

THEOREM PreparePreservesReadSafety ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Timestamps,
         Inv, Lifecycle, PrepareShape, TimestampShape, TimestampBound, CommitIdentity,
         CommitSnapshot, FreshPrepareCall, PrepareTransaction(n,t,ts)
  PROVE \A q \in Node : \A r \in UsedTransactions(q) : \A k \in Keys :
    ~PrepareConflict(q,r,k) => ~PrepareConflict(q,r,k)'
<1>1. \A r \in UsedTransactions(n) : mtxnSnapshots[n][r].ts < ts
  BY SMT, CallerPrepareAfterUsedReaders
<1>2. UsedTimestampFrame
  BY SMT, UsedTimestampFrameStep DEF EpochNext
<1> QED BY SMTT(20), <1>1, <1>2, UsedReaderTypes, NaturalTimestampDomain
   DEF PrepareConflict, Inv, SnapshotShape, PrepareShape, TimestampShape,
       PrepareTransaction, UsedTimestampFrame, ActiveTransactions, SnapshotUpdatedKeys

PreparedSetFrame ==
  \A n \in Node : \A t \in PreparedTransactions(n)' :
    /\ t \in PreparedTransactions(n)
    /\ mtxnSnapshots'[n][t].writeSet = mtxnSnapshots[n][t].writeSet
    /\ mtxnSnapshots'[n][t].prepareTs = mtxnSnapshots[n][t].prepareTs

NoPrepareStep ==
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps, ip \in IgnorePrepareOptions : StartTransaction(n,t,ts,RC,ip)
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values : TransactionWrite(n,t,k,v,"false")
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : TransactionRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys : TransactionRemove(n,t,k)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : CommitTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts,dts \in Timestamps : CommitPreparedTransaction(n,t,ts,dts)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)
    \/ UNCHANGED vars

THEOREM PreparedSetFrameStep == Inv /\ PrepareShape /\ NoPrepareStep => PreparedSetFrame
BY SMTT(20) DEF Inv, SnapshotShape, PrepareShape, PreparedSetFrame, NoPrepareStep,
   PreparedTransactions, ActiveTransactions, SnapshotKV, vars,
   StartTransaction, TransactionWrite, TransactionRead, TransactionRemove,
   CommitTransaction, CommitPreparedTransaction, AbortTransaction,
   SetStableTimestamp, SetOldestTimestamp

THEOREM PreparedFrameReadSafety ==
  UsedTimestampFrame /\ PreparedSetFrame =>
    \A n \in Node : \A r \in UsedTransactions(n) : \A k \in Keys :
      ~PrepareConflict(n,r,k) => ~PrepareConflict(n,r,k)'
BY SMT DEF UsedTimestampFrame, PreparedSetFrame, PrepareConflict,
           PreparedTransactions, ActiveTransactions, SnapshotUpdatedKeys

THEOREM CallerReadSafetyStep ==
  Inv /\ Lifecycle /\ PrepareShape /\ TimestampShape /\ TimestampBound /\
  CommitIdentity /\ CommitSnapshot /\ [CallerEpochNext]_vars =>
    \A n \in Node : \A r \in UsedTransactions(n) : \A k \in Keys :
      ~PrepareConflict(n,r,k) => ~PrepareConflict(n,r,k)'
BY SMT, UsedTimestampFrameStep, PreparePreservesReadSafety,
   PreparedSetFrameStep, PreparedFrameReadSafety
   DEF CallerEpochNext, EpochNext, NoPrepareStep

SafeLogTransport ==
  \A n \in Node : \A r \in UsedTransactions(n) : \A k \in Keys :
    ~PrepareConflict(n,r,k) =>
      LogRead(mlog'[n],k,mtxnSnapshots'[n][r].ts) =
        LogRead(mlog[n],k,mtxnSnapshots[n][r].ts)

THEOREM SameLogTransport == UsedTimestampFrame /\ mlog'=mlog => SafeLogTransport
BY SMT DEF UsedTimestampFrame, SafeLogTransport

THEOREM AppendSafeLogTransport ==
  ASSUME NEW n \in Node, NEW e, LogShape, UsedTimestampFrame,
         mlog'=[mlog EXCEPT ![n]=Append(@,e)],
         \A r \in UsedTransactions(n), k \in Keys : ~PrepareConflict(n,r,k) =>
           ~("data" \in DOMAIN e /\ k \in DOMAIN e.data /\ e.ts <= mtxnSnapshots[n][r].ts)
  PROVE SafeLogTransport
BY SMT, InvisibleAppendRead DEF LogShape, UsedTimestampFrame, SafeLogTransport

THEOREM OrdinaryCommitSafeLogTransport ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat,
         Inv, LogShape, TimestampShape, TimestampBound, CommitIdentity, CommitSnapshot,
         UsedTimestampFrame, CommitTransaction(n,t,ts)
  PROVE SafeLogTransport
<1>1. \A r \in UsedTransactions(n) : mtxnSnapshots[n][r].ts < ts
  BY SMT, OrdinaryCommitAfterUsedReaders
<1> QED BY SMT, <1>1, AppendSafeLogTransport, UsedReaderTypes
   DEF CommitTransaction, CommitTxnToLog, CommitLogEntry

THEOREM PreparedCommitSafeLogTransport ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat, NEW dts,
         Inv, LogShape, TimestampShape, TimestampBound, CommitIdentity, CommitSnapshot,
         PreparedOrder, UsedTimestampFrame, CommitPreparedTransaction(n,t,ts,dts)
  PROVE SafeLogTransport
BY SMT, PreparedCommitInvisibleToSafeReader, AppendSafeLogTransport, DurableAppendForm
   DEF CommitPreparedTransaction

THEOREM PrepareSafeLogTransport ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts,
         LogShape, UsedTimestampFrame, PrepareTransaction(n,t,ts)
  PROVE SafeLogTransport
BY SMT, AppendSafeLogTransport DEF PrepareTransaction, PrepareTxnToLog

THEOREM SafeLogTransportStep ==
  Inv /\ Lifecycle /\ LogShape /\ TimestampShape /\ TimestampBound /\
  CommitIdentity /\ CommitSnapshot /\ PreparedOrder /\ [EpochNext]_vars => SafeLogTransport
<1>1. ASSUME Inv, Lifecycle, LogShape, TimestampShape, TimestampBound,
             CommitIdentity, CommitSnapshot, PreparedOrder, [EpochNext]_vars
      PROVE SafeLogTransport
  <2>1. UsedTimestampFrame BY SMT, <1>1, UsedTimestampFrameStep
  <2> QED BY SMT, <1>1, <2>1, OrdinaryCommitSafeLogTransport, PreparedCommitSafeLogTransport,
             PrepareSafeLogTransport, SameLogTransport, NaturalTimestampDomain
     DEF EpochNext, vars, StartTransaction, TransactionWrite, TransactionRead,
         TransactionRemove, AbortTransaction, SetStableTimestamp, SetOldestTimestamp
<1> QED BY SMT, <1>1

THEOREM SafeReadTransportStep ==
  Inv /\ Lifecycle /\ PrepareShape /\ LogShape /\ TimestampShape /\ TimestampBound /\
  CommitIdentity /\ CommitSnapshot /\ PreparedOrder /\ [CallerEpochNext]_vars => SafeReadTransport
BY SMT, CallerReadSafetyStep, SafeLogTransportStep
   DEF CallerEpochNext, SafeReadTransport, SafeLogTransport

THEOREM CallerSafeReadTransport == CallerEpochSpec => [][SafeReadTransport]_vars
BY CallerEpochProjection, EpochBehaviorProjection, FullNextShape, FullNextLifecycle,
   EpochPrepareShape, EpochLogShape, EpochTimestampShape, EpochTimestampBound,
   EpochCommitIdentity, EpochCommitSnapshot, EpochPreparedOrder, SafeReadTransportStep,
   PTL DEF CallerEpochSpec
=============================================================================

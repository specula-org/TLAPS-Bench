----------------------- MODULE StorageCommitIdentity -----------------------
EXTENDS StorageVersionOrder, StorageCoherence

CommittedFrozen ==
  \A n \in Node, t \in MTxId : mtxnSnapshots[n][t].committed =>
    mtxnSnapshots'[n][t] = mtxnSnapshots[n][t]

CommitIdentity ==
  /\ \A n \in Node, t \in MTxId : mtxnSnapshots[n][t].committed =>
       \E i \in DOMAIN mlog[n] : "data" \in DOMAIN mlog[n][i] /\ mlog[n][i].tid=t
  /\ \A n \in Node : \A i,j \in DOMAIN mlog[n] :
       ("data" \in DOMAIN mlog[n][i] /\ "data" \in DOMAIN mlog[n][j] /\
         mlog[n][i].tid=mlog[n][j].tid) => i=j

CommitSnapshot ==
  \A n \in Node : \A i \in DOMAIN mlog[n] : "data" \in DOMAIN mlog[n][i] =>
    LET t == mlog[n][i].tid IN
      /\ {"ts","writeSet","data"} \subseteq DOMAIN mtxnSnapshots[n][t]
      /\ mtxnSnapshots[n][t].ts \in Nat
      /\ mtxnSnapshots[n][t].ts < mlog[n][i].ts
      /\ DOMAIN mlog[n][i].data = Keys \cap mtxnSnapshots[n][t].writeSet
      /\ \A k \in DOMAIN mlog[n][i].data : mlog[n][i].data[k] = mtxnSnapshots[n][t].data[k]

THEOREM CommittedFrozenStep == Inv /\ Lifecycle /\ [Next]_vars => CommittedFrozen
BY SMTT(20) DEF Inv, SnapshotShape, Lifecycle, CommittedFrozen, Next, vars,
  ActiveTransactions, StartTransaction, TransactionWrite, TransactionRead,
  TransactionRemove, PrepareTransaction, CommitTransaction, CommitPreparedTransaction,
  AbortTransaction, SetStableTimestamp, SetOldestTimestamp, RollbackToStable

THEOREM CommitIdentityInitial == Init => (CommitIdentity /\ CommitSnapshot)
BY SMT DEF Init, CommitIdentity, CommitSnapshot

THEOREM QuietCommitIdentity ==
  CommitIdentity /\ mlog'=mlog /\
  (\A n \in Node, t \in MTxId : mtxnSnapshots'[n][t].committed = mtxnSnapshots[n][t].committed)
    => CommitIdentity'
BY SMT DEF CommitIdentity

THEOREM AppendCommitIdentity ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW e, Inv, Lifecycle,
         LogShape, CommitProvenance, CommitIdentity,
         mlog'=[mlog EXCEPT ![n]=Append(@,e)],
         mtxnSnapshots'=[mtxnSnapshots EXCEPT ![n][t].active=FALSE, ![n][t].committed=TRUE],
         mtxnSnapshots[n][t].active, "data" \in DOMAIN e, e.tid=t
  PROVE CommitIdentity'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF Inv, SnapshotShape, Lifecycle, LogShape, CommitProvenance, CommitIdentity

THEOREM PrepareCommitIdentity ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, Inv, Lifecycle,
         LogShape, CommitIdentity, PrepareTransaction(n,t,ts)
  PROVE CommitIdentity'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF Inv, SnapshotShape, Lifecycle, LogShape, CommitIdentity,
       PrepareTransaction, PrepareTxnToLog

THEOREM CommitAddsIdentity ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         Inv, Lifecycle, LogShape, CommitProvenance, CommitIdentity,
         CommitTransaction(n,t,ts) \/ CommitPreparedTransaction(n,t,ts,dts)
  PROVE CommitIdentity'
BY SMT, AppendCommitIdentity, DurableAppendForm
   DEF CommitTransaction, CommitPreparedTransaction, CommitTxnToLog,
       CommitLogEntry, DurableEntry, ActiveTransactions

IdentityQuietStep ==
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps, ip \in IgnorePrepareOptions : StartTransaction(n,t,ts,RC,ip)
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values : TransactionWrite(n,t,k,v,"false")
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : TransactionRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys : TransactionRemove(n,t,k)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)
    \/ UNCHANGED vars

THEOREM IdentityQuietFrame ==
  Inv /\ Lifecycle /\ IdentityQuietStep =>
    /\ mlog'=mlog
    /\ \A n \in Node, t \in MTxId : mtxnSnapshots'[n][t].committed = mtxnSnapshots[n][t].committed
BY SMTT(20) DEF Inv, SnapshotShape, Lifecycle, IdentityQuietStep, vars,
    StartTransaction, SnapshotKV, ActiveTransactions, TransactionWrite, TransactionRead,
    TransactionRemove, AbortTransaction, SetStableTimestamp, SetOldestTimestamp

THEOREM CommitIdentityStep ==
  Inv /\ Lifecycle /\ LogShape /\ CommitProvenance /\ CommitIdentity /\
  [EpochNext]_vars => CommitIdentity'
BY SMT, CommitAddsIdentity, QuietCommitIdentity, PrepareCommitIdentity, IdentityQuietFrame
   DEF EpochNext, IdentityQuietStep

THEOREM CommitSnapshotAppend ==
  ASSUME NEW n \in Node, NEW e, LogShape, CommitProvenance, CommitSnapshot,
         CommittedFrozen, mlog'=[mlog EXCEPT ![n]=Append(@,e)],
         "data" \in DOMAIN e =>
           LET t == e.tid IN
             /\ {"ts","writeSet","data"} \subseteq DOMAIN mtxnSnapshots'[n][t]
             /\ mtxnSnapshots'[n][t].ts \in Nat
             /\ mtxnSnapshots'[n][t].ts < e.ts
             /\ DOMAIN e.data = Keys \cap mtxnSnapshots'[n][t].writeSet
             /\ \A k \in DOMAIN e.data : e.data[k] = mtxnSnapshots'[n][t].data[k]
  PROVE CommitSnapshot'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF LogShape, CommitProvenance, CommitSnapshot, CommittedFrozen

THEOREM CommitEstablishesSnapshot ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts \in Nat, NEW dts,
         Inv, Lifecycle, LogShape, DataShape, TimestampShape, TimestampBound,
         PreparedOrder, CommitProvenance, CommitSnapshot, CommittedFrozen,
         CommitTransaction(n,t,ts) \/ CommitPreparedTransaction(n,t,ts,dts)
  PROVE CommitSnapshot'
<1>1. /\ mtxnSnapshots[n][t].ts \in Nat /\ mtxnSnapshots[n][t].ts < ts
  BY SMT, CommitsAfterOwnSnapshot, ReachableTimesNatural
     DEF CommitTransaction, CommitPreparedTransaction
<1> QED BY SMTT(20), <1>1, CommitSnapshotAppend, DurableAppendForm
   DEF Inv, SnapshotShape, DataShape, TimestampShape, Lifecycle,
       CommitTransaction, CommitPreparedTransaction, ActiveTransactions,
       CommitTxnToLog, CommitLogEntry, DurableEntry, SnapshotUpdatedKeys

THEOREM CommitSnapshotQuiet ==
  CommitProvenance /\ CommitSnapshot /\ CommittedFrozen /\ mlog'=mlog => CommitSnapshot'
BY SMT DEF CommitProvenance, CommitSnapshot, CommittedFrozen

THEOREM PreparePreservesCommitSnapshot ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, LogShape, CommitProvenance,
         CommitSnapshot, CommittedFrozen, PrepareTransaction(n,t,ts)
  PROVE CommitSnapshot'
BY SMT, CommitSnapshotAppend DEF PrepareTransaction, PrepareTxnToLog

THEOREM CommitSnapshotStep ==
  Inv /\ Lifecycle /\ LogShape /\ DataShape /\ TimestampShape /\ TimestampBound /\
  PreparedOrder /\ CommitProvenance /\ CommitSnapshot /\ [EpochNext]_vars => CommitSnapshot'
<1>1. ASSUME Inv, Lifecycle, LogShape, DataShape, TimestampShape, TimestampBound,
             PreparedOrder, CommitProvenance, CommitSnapshot, [EpochNext]_vars
      PROVE CommitSnapshot'
  <2>1. CommittedFrozen BY SMT, <1>1, CommittedFrozenStep, EpochActionProjection
  <2> QED BY SMTT(20), <1>1, <2>1, CommitEstablishesSnapshot, CommitSnapshotQuiet,
             PreparePreservesCommitSnapshot, NaturalTimestampDomain
     DEF EpochNext, vars, StartTransaction, TransactionWrite, TransactionRead,
         TransactionRemove, AbortTransaction, SetStableTimestamp, SetOldestTimestamp
<1> QED BY SMT, <1>1

THEOREM EpochCommitIdentity == EpochSpec => []CommitIdentity
BY EpochBehaviorProjection, FullNextShape, FullNextLifecycle, EpochLogShape,
   EpochCommitProvenance, CommitIdentityInitial, CommitIdentityStep, PTL DEF EpochSpec

THEOREM EpochCommitSnapshot == EpochSpec => []CommitSnapshot
BY EpochBehaviorProjection, FullNextShape, FullNextLifecycle, EpochLogShape,
   EpochDataShape, EpochTimestampShape, EpochTimestampBound, EpochPreparedOrder,
   EpochCommitProvenance, CommitIdentityInitial, CommitSnapshotStep, PTL DEF EpochSpec
=============================================================================

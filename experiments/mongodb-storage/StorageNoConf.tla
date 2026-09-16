--------------------------- MODULE StorageNoConf ---------------------------
EXTENDS StorageOrderWitness

CommitWriteSnapshotOrder ==
  \A n \in Node : \A i,j \in CommitPositions(n) :
    (i<j /\ DOMAIN mlog[n][i].data \cap DOMAIN mlog[n][j].data # {}) =>
      mlog[n][i].ts <= mtxnSnapshots[n][mlog[n][j].tid].ts

THEOREM KeyGapInitial == Init => CommitWriteSnapshotOrder
BY SMT DEF Init, CommitWriteSnapshotOrder, CommitPositions

THEOREM KeyGapQuiet ==
  CommitProvenance /\ CommitWriteSnapshotOrder /\ CommittedFrozen /\ mlog'=mlog => CommitWriteSnapshotOrder'
BY SMT DEF CommitProvenance, CommitWriteSnapshotOrder, CommitPositions, CommittedFrozen

THEOREM KeyGapAppend ==
  ASSUME NEW n \in Node, NEW e, LogShape, CommitProvenance, CommitWriteSnapshotOrder,
         CommittedFrozen, mlog'=[mlog EXCEPT ![n]=Append(@,e)],
         \A i \in CommitPositions(n) :
           ("data" \in DOMAIN e /\ DOMAIN mlog[n][i].data \cap DOMAIN e.data # {}) =>
             mlog[n][i].ts <= mtxnSnapshots'[n][e.tid].ts
  PROVE CommitWriteSnapshotOrder'
BY SMTT(20), AppendEntries, SequenceDomain
   DEF LogShape, CommitProvenance, CommitWriteSnapshotOrder, CommitPositions, CommittedFrozen

THEOREM CommitKeyGap ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts, NEW dts,
         Inv, TimestampShape, LogShape, FreshWrites, CommitProvenance,
         CommitWriteSnapshotOrder, CommittedFrozen,
         CommitTransaction(n,t,ts) \/ CommitPreparedTransaction(n,t,ts,dts)
  PROVE CommitWriteSnapshotOrder'
<1>1. \A i \in CommitPositions(n) :
        DOMAIN mlog[n][i].data \cap SnapshotUpdatedKeys(n,t) # {} =>
          mlog[n][i].ts <= mtxnSnapshots[n][t].ts
  BY SMT DEF FreshWrites, CommitPositions, SnapshotUpdatedKeys,
             CommitTransaction, CommitPreparedTransaction
<1>2. mtxnSnapshots'[n][t].ts=mtxnSnapshots[n][t].ts
  BY SMT DEF Inv, SnapshotShape, TimestampShape, ActiveTransactions,
             CommitTransaction, CommitPreparedTransaction
<1> QED BY SMT, <1>1, <1>2, KeyGapAppend, DurableAppendForm
   DEF CommitTransaction, CommitPreparedTransaction, CommitTxnToLog, CommitLogEntry, DurableEntry

THEOREM PrepareKeyGap ==
  ASSUME NEW n \in Node, NEW t \in MTxId, NEW ts,
         LogShape, CommitProvenance, CommitWriteSnapshotOrder, CommittedFrozen,
         PrepareTransaction(n,t,ts)
  PROVE CommitWriteSnapshotOrder'
BY SMT, KeyGapAppend DEF PrepareTransaction, PrepareTxnToLog

THEOREM KeyGapStep ==
  Inv /\ Lifecycle /\ TimestampShape /\ LogShape /\ FreshWrites /\ CommitProvenance /\
  CommitWriteSnapshotOrder /\ [EpochNext]_vars => CommitWriteSnapshotOrder'
<1>1. ASSUME Inv, Lifecycle, TimestampShape, LogShape, FreshWrites, CommitProvenance,
             CommitWriteSnapshotOrder, [EpochNext]_vars
      PROVE CommitWriteSnapshotOrder'
  <2>1. CommittedFrozen BY SMT, <1>1, CommittedFrozenStep, EpochActionProjection
  <2> QED BY SMT, <1>1, <2>1, KeyGapQuiet, CommitKeyGap, PrepareKeyGap
     DEF EpochNext, vars, StartTransaction, TransactionWrite, TransactionRead,
         TransactionRemove, AbortTransaction, SetStableTimestamp, SetOldestTimestamp
<1> QED BY SMT, <1>1

THEOREM EpochKeyGap == EpochSpec => []CommitWriteSnapshotOrder
BY EpochBehaviorProjection, FullNextShape, FullNextLifecycle, EpochTimestampShape,
   EpochLogShape, EpochFreshWrites, EpochCommitProvenance, KeyGapInitial, KeyGapStep,
   PTL DEF EpochSpec

NoInterveningWrite ==
  \A n \in Node : \A c,j \in CommitPositions(n) :
    (Before(n,j,c) /\ j \notin ReadCut(n,mlog[n][c].tid)) =>
      DOMAIN mlog[n][j].data \cap DOMAIN mlog[n][c].data = {}

THEOREM NoConfWitness ==
  Inv /\ LogShape /\ TimestampBound /\ PerKeyStrictOrder /\ CommitWriteSnapshotOrder => NoInterveningWrite
<1>1. ASSUME Inv, LogShape, TimestampBound, PerKeyStrictOrder, CommitWriteSnapshotOrder,
             NEW n \in Node, NEW c \in CommitPositions(n), NEW j \in CommitPositions(n), Before(n,j,c),
             j \notin ReadCut(n,mlog[n][c].tid),
             DOMAIN mlog[n][j].data \cap DOMAIN mlog[n][c].data # {}
      PROVE FALSE
  <2>1. /\ c \in Nat /\ j \in Nat /\ mlog[n][c].ts \in Nat /\ mlog[n][j].ts \in Nat
    BY SMT, <1>1, CommitPositionTypes
  <2>2. DOMAIN mlog[n][c].data \cap DOMAIN mlog[n][j].data # {}
    BY SMT, <1>1
  <2>3. c<j => mlog[n][c].ts < mlog[n][j].ts
    BY SMT, <1>1, <2>2 DEF PerKeyStrictOrder, CommitPositions
  <2>4. j<c
    BY SMT, <1>1, <2>1, <2>3 DEF Before
  <2>5. mlog[n][j].ts <= mtxnSnapshots[n][mlog[n][c].tid].ts
    BY SMT, <1>1, <2>4 DEF CommitWriteSnapshotOrder
  <2> QED BY SMT, <1>1, <2>5 DEF ReadCut
<1> QED BY SMT, <1>1 DEF NoInterveningWrite

THEOREM EpochNoInterveningWrite == EpochSpec => []NoInterveningWrite
BY EpochBehaviorProjection, FullNextShape, EpochLogShape, EpochTimestampBound,
   EpochPerKeyStrictOrder, EpochKeyGap, NoConfWitness, PTL
=============================================================================

------------------------ MODULE StorageSICertificate ------------------------
EXTENDS StorageHistoricalReads, StorageLocalHistory, StorageNoConf

WitnessPayloads ==
  \A n \in Node : \A c \in CommitPositions(n) :
    LET h == history[n][mlog[n][c].tid] IN
      /\ DOMAIN mlog[n][c].data = HistoryWriteKeys(h)
      /\ \A k \in DOMAIN mlog[n][c].data :
           \E i \in DOMAIN h : LastWrite(h,k,i) /\ mlog[n][c].data[k]=h[i].value

WitnessReads ==
  \A n \in Node : \A c \in CommitPositions(n) :
    LET t == mlog[n][c].tid
        h == history[n][t] IN
      \A i \in DOMAIN h : h[i].op="read" =>
        \/ LocalReadWitness(h,i)
        \/ /\ ExternalReadAt(h,i)
           /\ \/ /\ Visible(mlog[n],h[i].key,mtxnSnapshots[n][t].ts)={}
                  /\ h[i].value=NoValue
              \/ \E j \in ReadCut(n,t) :
                   /\ LatestAtCut(n,h[i].key,mtxnSnapshots[n][t].ts,j)
                   /\ h[i].value=mlog[n][j].data[h[i].key]

\* Concrete relational certificate. This is NOT ClientCentric!SnapshotIsolation.
\* The sequence/execution and Complete/NoConf bridge remains a separate target.
TimestampSICertificate ==
  /\ LogShape /\ HistoryShape /\ HistoryOpShape
  /\ CommitIdentity /\ CommitProvenance
  /\ StrictTotalCommitOrder /\ ReadCutBeforeCommit
  /\ NoInterveningWrite /\ WitnessPayloads /\ WitnessReads

THEOREM PayloadWitnessFromHistory ==
  CommitProvenance /\ CommitSnapshot /\ UsedSnapshotShape /\ HistoryFidelity => WitnessPayloads
<1>1. ASSUME CommitProvenance, CommitSnapshot, UsedSnapshotShape, HistoryFidelity,
             NEW n \in Node, NEW c \in CommitPositions(n)
      PROVE LET h == history[n][mlog[n][c].tid] IN
        /\ DOMAIN mlog[n][c].data = HistoryWriteKeys(h)
        /\ \A k \in DOMAIN mlog[n][c].data :
             \E i \in DOMAIN h : LastWrite(h,k,i) /\ mlog[n][c].data[k]=h[i].value
  <2>1. /\ mlog[n][c].tid \in MTxId /\ mtxnSnapshots[n][mlog[n][c].tid].committed
    BY SMT, <1>1 DEF CommitProvenance, CommitPositions
  <2>2. /\ mtxnSnapshots[n][mlog[n][c].tid].writeSet \subseteq Keys
          /\ HistoryState(history[n][mlog[n][c].tid],mtxnSnapshots[n][mlog[n][c].tid].writeSet,
                          mtxnSnapshots[n][mlog[n][c].tid].data)
    BY SMT, <1>1, <2>1 DEF UsedSnapshotShape, HistoryFidelity
  <2>3. /\ DOMAIN mlog[n][c].data=Keys \cap mtxnSnapshots[n][mlog[n][c].tid].writeSet
          /\ \A k \in DOMAIN mlog[n][c].data :
               mlog[n][c].data[k]=mtxnSnapshots[n][mlog[n][c].tid].data[k]
    BY SMT, <1>1 DEF CommitSnapshot, CommitPositions
  <2>4. DOMAIN mlog[n][c].data=mtxnSnapshots[n][mlog[n][c].tid].writeSet
    BY SMT, <2>2, <2>3
  <2> QED BY SMT, <2>2, <2>3, <2>4 DEF HistoryState
<1> QED BY SMT, <1>1 DEF WitnessPayloads

THEOREM ReadWitnessFromHistory ==
  Inv /\ LogShape /\ TimestampBound /\ PerKeyStrictOrder /\ CommitProvenance /\
  HistoricalExternalCoherence /\ LocalHistoryCorrect /\ HistoryOpShape => WitnessReads
BY SMTT(20), LogReadWitness
   DEF WitnessReads, CommitPositions, CommitProvenance, HistoricalExternalCoherence,
       UsedTransactions, CommittedTransactions, ExternalValues, ReadValues,
       LocalHistoryCorrect, LocalReads, ReadCut, LatestAtCut, HistoryOpShape

THEOREM CallerTimestampSICertificate == CallerHistoryEpochSpec => []TimestampSICertificate
BY CallerHistoryProjection, CallerEpochProjection, EpochBehaviorProjection,
   CallerHistoryToFullHistory, FullNextShape, EpochLogShape, EpochTimestampBound,
   EpochPerKeyStrictOrder, EpochCommitProvenance, EpochCommitIdentity, EpochCommitSnapshot,
   EpochOrderWitness, EpochNoInterveningWrite, FullNextUsedShape, FullHistoryFidelity, FullHistoryShape,
   CallerHistoricalExternalCoherence, FullLocalHistoryCorrect, FullHistoryOpShape,
   PayloadWitnessFromHistory, ReadWitnessFromHistory, PTL DEF TimestampSICertificate
=============================================================================

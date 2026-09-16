------------------------ MODULE StorageOrderWitness ------------------------
EXTENDS StorageCommitIdentity

CommitPositions(n) == {i \in DOMAIN mlog[n] : "data" \in DOMAIN mlog[n][i]}
Before(n,i,j) ==
  mlog[n][i].ts < mlog[n][j].ts \/ (mlog[n][i].ts=mlog[n][j].ts /\ i<j)
ReadCut(n,t) == {i \in CommitPositions(n) : mlog[n][i].ts <= mtxnSnapshots[n][t].ts}

StrictTotalCommitOrder ==
  \A n \in Node :
    /\ \A i \in CommitPositions(n) : ~Before(n,i,i)
    /\ \A i,j \in CommitPositions(n) : i#j => (Before(n,i,j) \/ Before(n,j,i))
    /\ \A i,j,k \in CommitPositions(n) : (Before(n,i,j) /\ Before(n,j,k)) => Before(n,i,k)

ReadCutBeforeCommit ==
  \A n \in Node : \A c \in CommitPositions(n) :
    LET t == mlog[n][c].tid IN
      /\ \A i \in ReadCut(n,t) : Before(n,i,c)
      /\ \A i \in ReadCut(n,t), j \in CommitPositions(n) :
           Before(n,j,i) => j \in ReadCut(n,t)

THEOREM CommitPositionTypes ==
  Inv /\ LogShape /\ TimestampBound =>
    \A n \in Node : \A i \in CommitPositions(n) : /\ i \in Nat /\ mlog[n][i].ts \in Nat
BY SMT, SequenceDomain, ReachableTimesNatural DEF LogShape, CommitPositions

THEOREM CommitOrderTotal ==
  Inv /\ LogShape /\ TimestampBound => StrictTotalCommitOrder
BY SMT, CommitPositionTypes DEF StrictTotalCommitOrder, Before

THEOREM SnapshotCutsArePrefixes ==
  Inv /\ LogShape /\ TimestampBound /\ CommitSnapshot => ReadCutBeforeCommit
BY SMT, CommitPositionTypes
   DEF ReadCutBeforeCommit, ReadCut, Before, CommitPositions, CommitSnapshot

LatestAtCut(n,k,ts,i) ==
  /\ i \in CommitPositions(n)
  /\ k \in DOMAIN mlog[n][i].data /\ mlog[n][i].ts <= ts
  /\ \A j \in CommitPositions(n) :
       (k \in DOMAIN mlog[n][j].data /\ mlog[n][j].ts <= ts) =>
          (j=i \/ Before(n,j,i))

THEOREM VisibleIndicesAreCommits ==
  ASSUME NEW n, NEW k, NEW ts
  PROVE Visible(mlog[n],k,ts) =
    {i \in CommitPositions(n) : k \in DOMAIN mlog[n][i].data /\ mlog[n][i].ts <= ts}
BY SMT DEF Visible, CommitPositions

THEOREM LogMaximumIsLatestInOrder ==
  ASSUME NEW n \in Node, NEW k, NEW ts, Inv, LogShape, TimestampBound,
         PerKeyStrictOrder, Visible(mlog[n],k,ts) # {}
  PROVE LatestAtCut(n,k,ts,Max(Visible(mlog[n],k,ts)))
<1>1. Max(Visible(mlog[n],k,ts)) \in Visible(mlog[n],k,ts)
  BY SMT, VisibleMaximum DEF LogShape
<1>2. /\ Visible(mlog[n],k,ts) \subseteq 0..Len(mlog[n]) /\ Len(mlog[n]) \in Nat
  BY SMT, SequenceDomain DEF LogShape, Visible
<1>3. \A j \in Visible(mlog[n],k,ts) : j <= Max(Visible(mlog[n],k,ts))
  BY SMT, <1>1, <1>2, BoundedMaximum
<1>4. ASSUME NEW j \in Visible(mlog[n],k,ts)
      PROVE j=Max(Visible(mlog[n],k,ts)) \/ Before(n,j,Max(Visible(mlog[n],k,ts)))
  <2>1. j#Max(Visible(mlog[n],k,ts)) => j<Max(Visible(mlog[n],k,ts))
    BY SMT, <1>4, <1>1, <1>2, <1>3
  <2>2. /\ j \in DOMAIN mlog[n] /\ Max(Visible(mlog[n],k,ts)) \in DOMAIN mlog[n]
          /\ "data" \in DOMAIN mlog[n][j]
          /\ "data" \in DOMAIN mlog[n][Max(Visible(mlog[n],k,ts))]
          /\ k \in DOMAIN mlog[n][j].data \cap DOMAIN mlog[n][Max(Visible(mlog[n],k,ts))].data
    BY SMT, <1>4, <1>1, VisibleIndicesAreCommits DEF CommitPositions
  <2>3. j#Max(Visible(mlog[n],k,ts)) => mlog[n][j].ts < mlog[n][Max(Visible(mlog[n],k,ts))].ts
    BY SMT, <2>1, <2>2 DEF PerKeyStrictOrder
  <2> QED BY SMT, <2>3 DEF Before
<1> QED BY SMT, <1>1, <1>4, VisibleIndicesAreCommits DEF LatestAtCut

THEOREM LogReadWitness ==
  ASSUME NEW n \in Node, NEW k, NEW ts, Inv, LogShape, TimestampBound, PerKeyStrictOrder
  PROVE (Visible(mlog[n],k,ts)={} /\ LogRead(mlog[n],k,ts)=NoValue)
    \/ (\E i \in CommitPositions(n) : LatestAtCut(n,k,ts,i) /\ LogRead(mlog[n],k,ts)=mlog[n][i].data[k])
BY SMT, LogMaximumIsLatestInOrder DEF LogRead, LatestAtCut

THEOREM EpochOrderWitness == EpochSpec => ( []StrictTotalCommitOrder /\ []ReadCutBeforeCommit )
BY EpochBehaviorProjection, FullNextShape, EpochLogShape, EpochTimestampBound,
   EpochCommitSnapshot, CommitOrderTotal, SnapshotCutsArePrefixes, PTL
=============================================================================

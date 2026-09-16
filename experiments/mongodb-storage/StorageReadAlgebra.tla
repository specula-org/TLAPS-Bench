------------------------ MODULE StorageReadAlgebra ------------------------
EXTENDS StorageLogAlgebra, StorageArithmetic

Visible(lg,key,ts) ==
  {i \in DOMAIN lg :
    /\ "data" \in DOMAIN lg[i]
    /\ \E k \in DOMAIN lg[i].data : k = key
    /\ lg[i].ts <= ts}

LogRead(lg,k,ts) ==
  IF Visible(lg,k,ts) = {} THEN NoValue
  ELSE lg[Max(Visible(lg,k,ts))].data[k]

LatePrepared(lg,t,k,ts) ==
  \E other \in MTxId \ {t} : \E p,c \in DOMAIN lg :
    /\ "prepare" \in DOMAIN lg[p]
    /\ lg[p].tid = other
    /\ "data" \in DOMAIN lg[c]
    /\ lg[c].tid = other
    /\ lg[c].ts <= ts
    /\ k \in DOMAIN lg[c].data

LogReadResult(lg,k,ts) ==
  IF Visible(lg,k,ts) = {} THEN NotFoundReadResult
  ELSE [mlogIndex |-> Max(Visible(lg,k,ts)), value |-> lg[Max(Visible(lg,k,ts))].data[k]]

THEOREM SnapshotReadResultForm ==
  ASSUME NEW n, NEW k, NEW ts
  PROVE SnapshotRead(n,k,ts) = LogReadResult(mlog[n],k,ts)
BY DEF SnapshotRead, LogReadResult, Visible

THEOREM LogReadResultValue ==
  ASSUME NEW lg, NEW k, NEW ts
  PROVE LogReadResult(lg,k,ts).value = LogRead(lg,k,ts)
BY SMT DEF LogReadResult, LogRead, NotFoundReadResult

THEOREM SnapshotReadValue ==
  ASSUME NEW n, NEW k, NEW ts
  PROVE SnapshotRead(n,k,ts).value = LogRead(mlog[n],k,ts)
BY SMT, SnapshotReadResultForm, LogReadResultValue

THEOREM TxnReadChoice ==
  ASSUME NEW n, NEW t, NEW k, k \notin mtxnSnapshots[n][t].writeSet
  PROVE TxnRead(n,t,k) =
    IF LatePrepared(mlog[n],t,k,mtxnSnapshots[n][t].ts)
    THEN LogRead(mlog[n],k,mtxnSnapshots[n][t].ts)
    ELSE mtxnSnapshots[n][t].data[k]
BY SMT, SnapshotReadValue DEF TxnRead, LatePrepared

THEOREM InvisibleAppend ==
  ASSUME NEW lg, NEW e, NEW k, NEW ts, IsSeq(lg),
         ~("data" \in DOMAIN e /\ k \in DOMAIN e.data /\ e.ts <= ts)
  PROVE Visible(Append(lg,e),k,ts) = Visible(lg,k,ts)
BY SMT, AppendEntries, SequenceDomain DEF Visible

THEOREM VisibleMaximum ==
  ASSUME NEW lg, NEW k, NEW ts, IsSeq(lg), Visible(lg,k,ts) # {}
  PROVE Max(Visible(lg,k,ts)) \in Visible(lg,k,ts)
<1>1. /\ Len(lg) \in Nat /\ Visible(lg,k,ts) \subseteq 0..Len(lg)
  BY SMT, SequenceDomain DEF Visible
<1> QED BY SMT, <1>1, BoundedMaximum

THEOREM InvisibleAppendRead ==
  ASSUME NEW lg, NEW e, NEW k, NEW ts, IsSeq(lg),
         ~("data" \in DOMAIN e /\ k \in DOMAIN e.data /\ e.ts <= ts)
  PROVE LogRead(Append(lg,e),k,ts) = LogRead(lg,k,ts)
<1>1. Visible(Append(lg,e),k,ts) = Visible(lg,k,ts)
  BY SMT, InvisibleAppend
<1>2. CASE Visible(lg,k,ts) = {}
  BY SMT, <1>1, <1>2 DEF LogRead
<1>3. CASE Visible(lg,k,ts) # {}
  <2>0. /\ Max(Visible(lg,k,ts)) \in Visible(lg,k,ts)
          /\ Visible(lg,k,ts) \subseteq DOMAIN lg
    <3>1. Max(Visible(lg,k,ts)) \in Visible(lg,k,ts)
      BY SMT, <1>3, VisibleMaximum
    <3>2. Visible(lg,k,ts) \subseteq DOMAIN lg BY SMT DEF Visible
    <3> QED BY SMT, <3>1, <3>2
  <2>1. Max(Visible(lg,k,ts)) \in DOMAIN lg BY SMT, <2>0
  <2>2. Append(lg,e)[Max(Visible(lg,k,ts))] = lg[Max(Visible(lg,k,ts))]
    BY SMT, <2>1, AppendEntries
  <2> QED BY SMT, <1>1, <2>2 DEF LogRead
<1> QED BY SMT, <1>2, <1>3

THEOREM LatePreparedAppendMonotone ==
  ASSUME NEW lg, NEW e, NEW t, NEW k, NEW ts, IsSeq(lg),
         LatePrepared(lg,t,k,ts)
  PROVE LatePrepared(Append(lg,e),t,k,ts)
<1>1. PICK other \in MTxId \ {t}, p,c \in DOMAIN lg :
        /\ "prepare" \in DOMAIN lg[p] /\ lg[p].tid = other
        /\ "data" \in DOMAIN lg[c] /\ lg[c].tid = other
        /\ lg[c].ts <= ts /\ k \in DOMAIN lg[c].data
  BY SMT DEF LatePrepared
<1>2. /\ p \in DOMAIN Append(lg,e) /\ c \in DOMAIN Append(lg,e)
        /\ Append(lg,e)[p] = lg[p] /\ Append(lg,e)[c] = lg[c]
  BY SMT, <1>1, AppendEntries, SequenceDomain
<1> QED BY SMT, <1>1, <1>2 DEF LatePrepared

THEOREM PreparedAppendVisible ==
  ASSUME NEW lg, NEW e, NEW t \in MTxId, NEW reader \in MTxId \ {t},
         NEW k, NEW ts, IsSeq(lg),
         \E p \in DOMAIN lg : "prepare" \in DOMAIN lg[p] /\ lg[p].tid = t,
         "data" \in DOMAIN e, e.tid = t, e.ts <= ts, k \in DOMAIN e.data
  PROVE LatePrepared(Append(lg,e),reader,k,ts)
<1>1. PICK p \in DOMAIN lg : "prepare" \in DOMAIN lg[p] /\ lg[p].tid = t
  BY SMT
<1>2. /\ p \in DOMAIN Append(lg,e)
        /\ Len(lg)+1 \in DOMAIN Append(lg,e)
        /\ Append(lg,e)[p] = lg[p]
        /\ Append(lg,e)[Len(lg)+1] = e
  BY SMT, <1>1, AppendEntries, SequenceDomain
<1>3. t \in MTxId \ {reader} BY SMT
<1> QED BY SMTT(20), <1>1, <1>2, <1>3 DEF LatePrepared

THEOREM PreparedAppendRead ==
  ASSUME NEW lg, NEW e, NEW t \in MTxId, NEW reader \in MTxId \ {t},
         NEW k, NEW ts, IsSeq(lg), e.tid = t,
         \E p \in DOMAIN lg : "prepare" \in DOMAIN lg[p] /\ lg[p].tid = t
  PROVE LogRead(Append(lg,e),k,ts) = LogRead(lg,k,ts)
        \/ LatePrepared(Append(lg,e),reader,k,ts)
<1>1. CASE ~("data" \in DOMAIN e /\ k \in DOMAIN e.data /\ e.ts <= ts)
  BY SMT, <1>1, InvisibleAppendRead
<1>2. CASE "data" \in DOMAIN e /\ k \in DOMAIN e.data /\ e.ts <= ts
  BY SMT, <1>2, PreparedAppendVisible
<1> QED BY SMT, <1>1, <1>2
=============================================================================

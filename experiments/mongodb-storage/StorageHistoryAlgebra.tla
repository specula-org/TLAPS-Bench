----------------------- MODULE StorageHistoryAlgebra -----------------------
EXTENDS StorageHistory, StorageSeqLemmas

HistoryWriteKeys(h) == {h[i].key : i \in {j \in DOMAIN h : h[j].op = "write"}}
LastWrite(h,k,i) ==
  /\ i \in DOMAIN h /\ h[i].op = "write" /\ h[i].key = k
  /\ \A j \in DOMAIN h : i < j => ~(h[j].op = "write" /\ h[j].key = k)

HistoryState(h,ws,data) ==
  /\ ws = HistoryWriteKeys(h)
  /\ \A k \in ws : \E i \in DOMAIN h : LastWrite(h,k,i) /\ data[k] = h[i].value

THEOREM EmptyHistoryState ==
  ASSUME NEW data
  PROVE HistoryState(<<>>,{},data)
BY SMT DEF HistoryState, HistoryWriteKeys

THEOREM ReadHistoryState ==
  ASSUME NEW h, NEW ws, NEW data, NEW k, NEW v, IsSeq(h), HistoryState(h,ws,data)
  PROVE HistoryState(Append(h,ReadOp(k,v)),ws,data)
BY SMTT(20), AppendEntries, SequenceDomain
   DEF HistoryState, HistoryWriteKeys, LastWrite, ReadOp

THEOREM WriteHistoryState ==
  ASSUME NEW h, NEW ws, NEW data, NEW k \in DOMAIN data, NEW v,
         IsSeq(h), ws \subseteq DOMAIN data, HistoryState(h,ws,data)
  PROVE HistoryState(Append(h,WriteOp(k,v)),ws \cup {k},[data EXCEPT ![k]=v])
<1>1. HistoryWriteKeys(Append(h,WriteOp(k,v))) = ws \cup {k}
  BY SMT, AppendEntries, SequenceDomain DEF HistoryState, HistoryWriteKeys, WriteOp
<1>2. /\ LastWrite(Append(h,WriteOp(k,v)),k,Len(h)+1)
        /\ Append(h,WriteOp(k,v))[Len(h)+1].value = v
  BY SMT, AppendEntries, SequenceDomain DEF LastWrite, WriteOp
<1>3. ASSUME NEW key \in ws \ {k}
      PROVE \E i \in DOMAIN Append(h,WriteOp(k,v)) :
        LastWrite(Append(h,WriteOp(k,v)),key,i) /\
        [data EXCEPT ![k]=v][key] = Append(h,WriteOp(k,v))[i].value
  <2>1. PICK i \in DOMAIN h : LastWrite(h,key,i) /\ data[key]=h[i].value
    BY SMT, <1>3 DEF HistoryState
  <2>2. /\ i \in DOMAIN Append(h,WriteOp(k,v))
          /\ Append(h,WriteOp(k,v))[i] = h[i]
          /\ LastWrite(Append(h,WriteOp(k,v)),key,i)
    BY SMT, <1>3, <2>1, AppendEntries, SequenceDomain DEF LastWrite, WriteOp
  <2>3. [data EXCEPT ![k]=v][key] = Append(h,WriteOp(k,v))[i].value
    BY SMT, <1>3, <2>1, <2>2
  <2> QED BY SMT, <2>2, <2>3
<1>4. /\ Len(h)+1 \in DOMAIN Append(h,WriteOp(k,v))
        /\ LastWrite(Append(h,WriteOp(k,v)),k,Len(h)+1)
        /\ [data EXCEPT ![k]=v][k] = Append(h,WriteOp(k,v))[Len(h)+1].value
  BY SMT, <1>2, AppendEntries, SequenceDomain
<1> QED BY SMT, <1>1, <1>3, <1>4 DEF HistoryState
=============================================================================

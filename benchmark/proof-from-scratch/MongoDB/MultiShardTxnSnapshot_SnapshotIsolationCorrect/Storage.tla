---- MODULE Storage ----
EXTENDS Sequences, Naturals, Integers, Util, TLC

CONSTANT Keys 
CONSTANT MTxId
CONSTANT Timestamps

CONSTANT NoValue

CONSTANT Node
CONSTANT RC 

VARIABLE mlog

VARIABLE mcommitIndex

VARIABLE mtxnSnapshots

VARIABLE txnStatus

VARIABLE stableTs

VARIABLE oldestTs

VARIABLE allDurableTs

STATUS_OK == "OK"
STATUS_ROLLBACK == "WT_ROLLBACK"
STATUS_NOTFOUND == "WT_NOTFOUND"
STATUS_PREPARE_CONFLICT == "WT_PREPARE_CONFLICT"

NotFoundReadResult == [
    mlogIndex |-> 0,
    value |-> NoValue
]

Max(S) == CHOOSE x \in S : \A y \in S : x >= y

--------------------------------------------------------

PrepareOrCommitTimestamps(n) == {IF "ts" \in DOMAIN e THEN e.ts ELSE  0 : e \in Range(mlog[n])}
CommitEntries(n, lg) == {e \in Range(lg[n]) : ("ts" \in DOMAIN e) /\ ("prepare" \notin DOMAIN e)}
CommitOnlyTimestamps(n, lg) == {e.ts : e \in CommitEntries(n, lg)}
CommitTimestamps(n) == {mlog[n][i].ts : i \in DOMAIN mlog[n]}

ActiveReadTimestamps(n) == { IF ~mtxnSnapshots[n][tx]["active"] THEN 0 ELSE mtxnSnapshots[n][tx].ts : tx \in DOMAIN mtxnSnapshots[n]}

NextTs(n) == Max(PrepareOrCommitTimestamps(n) \cup ActiveReadTimestamps(n)) + 1

ActiveTransactions(n) == {tid \in MTxId : mtxnSnapshots[n][tid]["active"]}
PreparedTransactions(n) == {tid \in ActiveTransactions(n) : mtxnSnapshots[n][tid].prepared}

CommittedTransactions(n, txnSnapshots) == {tid \in MTxId : txnSnapshots[n][tid]["committed"]}

AllDurableTs(n) == IF CommittedTransactions(n, mtxnSnapshots') = {} THEN 0 ELSE Max(CommitOnlyTimestamps(n, mlog'))

SnapshotRead(n, key, ts) == 
    LET snapshotKeyWrites == 
        { i \in DOMAIN mlog[n] :
            /\ "data" \in DOMAIN mlog[n][i] 
            /\ \E k \in DOMAIN mlog[n][i].data : k = key
            
            /\ mlog[n][i].ts <= ts } IN
        IF snapshotKeyWrites = {}
            THEN NotFoundReadResult
            ELSE [mlogIndex |-> Max(snapshotKeyWrites), value |-> mlog[n][Max(snapshotKeyWrites)].data[key]]

SnapshotKV(n, ts, rc, ignorePrepare) == 
    
    LET txnReadTs == IF rc = "snapshot" THEN ts ELSE Len(mlog[n]) IN
    [
        ts |-> txnReadTs,
        data |-> [k \in Keys |-> SnapshotRead(n, k, txnReadTs).value],
        prepared |-> FALSE,
        prepareTs |-> 0,
        aborted |-> FALSE,
        committed |-> FALSE,
        readSet |-> {},
        writeSet |-> {},
        active |-> TRUE,
        ignorePrepare |-> ignorePrepare
    ]

WriteConflictExists(n, tid, k) ==

    \E tOther \in MTxId \ {tid}:
        
        \/ /\ tid \in ActiveTransactions(n)
           /\ tOther \in ActiveTransactions(n)
           /\ k \in mtxnSnapshots[n][tOther].writeSet

        \/ \E ind \in DOMAIN mlog[n] :
            /\ "data" \in DOMAIN mlog[n][ind]
            /\ mlog[n][ind].ts > mtxnSnapshots[n][tid].ts
            /\ k \in (DOMAIN mlog[n][ind].data)

TxnRead(n, tid, k) == 

    IF  \E tOther \in MTxId \ {tid}:
        \E pmind \in DOMAIN mlog[n] :
        \E cmind \in DOMAIN mlog[n] :
            
            /\ "prepare" \in DOMAIN mlog[n][pmind]
            /\ mlog[n][pmind].tid = tOther
            
            /\ "data" \in DOMAIN mlog[n][cmind]
            /\ mlog[n][cmind].tid = tOther
            /\ mlog[n][cmind].ts <= mtxnSnapshots[n][tid].ts
            /\ k \in DOMAIN mlog[n][cmind].data
            
            /\ k \notin mtxnSnapshots[n][tid].writeSet
        
        THEN SnapshotRead(n, k, mtxnSnapshots[n][tid].ts).value 
        
        ELSE mtxnSnapshots[n][tid].data[k]

SnapshotUpdatedKeys(n, tid) == {
    k \in Keys : 
        /\ tid \in ActiveTransactions(n)
        /\ k \in mtxnSnapshots[n][tid]["writeSet"]
}

CommitLogEntry(n, tid, commitTs) == [
    data |-> [key \in SnapshotUpdatedKeys(n, tid) |-> mtxnSnapshots[n][tid].data[key]],
    ts |-> commitTs, 
    tid |-> tid
]

CommitTxnToLog(n, tid, commitTs) == 
    
    Append(mlog[n], CommitLogEntry(n, tid, commitTs))

CommitTxnToLogWithDurable(n, tid, commitTs, durableTs) == 
    
    Append(mlog[n], CommitLogEntry(n, tid, commitTs) @@ [durableTs |-> durableTs])

PrepareTxnToLog(n, tid, prepareTs) ==
    Append(mlog[n], [prepare |-> TRUE, ts |-> prepareTs, tid |-> tid])

PrepareConflict(n, tid, k) ==
    
    \E tother \in MTxId :
        /\ tother # tid
        /\ tother \in ActiveTransactions(n)
        /\ mtxnSnapshots[n][tother].prepared
        /\ k \in SnapshotUpdatedKeys(n, tother)
        /\ mtxnSnapshots[n][tother].prepareTs <= mtxnSnapshots[n][tid].ts

---------------------------------------------------------------------

TransactionPostOpStatus(n, tid) == txnStatus'[n][tid]

StartTransaction(n, tid, readTs, rc, ignorePrepare) == 

    /\ tid \notin ActiveTransactions(n)
    
    /\ ~mtxnSnapshots[n][tid]["committed"]
    /\ ~mtxnSnapshots[n][tid]["aborted"]
    
    /\ ~\E i \in DOMAIN (mlog[n]) : mlog[n][i].tid = tid
    /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid] = SnapshotKV(n, readTs, rc, ignorePrepare)]
    /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
    /\ UNCHANGED <<mlog, mcommitIndex, stableTs, oldestTs>>
    /\ allDurableTs' = [allDurableTs EXCEPT ![n] = AllDurableTs(n)]

TransactionWrite(n, tid, k, v, ignoreWriteConflicts) == 

    /\ tid \in ActiveTransactions(n)
    /\ tid \notin PreparedTransactions(n)
    /\ ~mtxnSnapshots[n][tid]["aborted"]
    
    /\ mtxnSnapshots[n][tid]["ignorePrepare"] # "true"
    
    /\ v = tid
    /\ \/ /\ ~WriteConflictExists(n, tid, k) \/ ignoreWriteConflicts = "true"
          
          /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["writeSet"] = @ \cup {k}, 
                                                    ![n][tid].data[k] = tid]
          /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
       \/ /\ WriteConflictExists(n, tid, k)
          /\ ignoreWriteConflicts = "false"
          
          /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_ROLLBACK]
          /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["aborted"] = TRUE]
    /\ UNCHANGED <<mlog, mcommitIndex, stableTs, oldestTs, allDurableTs>>

TransactionRead(n, tid, k, v) ==
    /\ tid \in ActiveTransactions(n)    
    /\ tid \notin PreparedTransactions(n)
    /\ ~mtxnSnapshots[n][tid]["aborted"]
    /\ v = TxnRead(n, tid, k)
    /\ \/ /\ ~PrepareConflict(n, tid, k) \/ mtxnSnapshots[n][tid]["ignorePrepare"] \in {"true", "force"}
          /\ v # NoValue
          /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
          /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["readSet"] = @ \cup {k}]
       
       \/ /\ ~PrepareConflict(n, tid, k) \/ mtxnSnapshots[n][tid]["ignorePrepare"] \in {"true", "force"}
          /\ v = NoValue
          /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_NOTFOUND]
          /\ UNCHANGED mtxnSnapshots
      
       \/ /\ PrepareConflict(n, tid, k)
          /\ mtxnSnapshots[n][tid]["ignorePrepare"] = "false"
          /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_PREPARE_CONFLICT]
          /\ UNCHANGED mtxnSnapshots
    /\ UNCHANGED <<mlog, mcommitIndex, stableTs, oldestTs, allDurableTs>>

CommitTransaction(n, tid, commitTs) == 

    /\ commitTs > stableTs[n] 
    /\ tid \in ActiveTransactions(n)
    /\ tid \notin PreparedTransactions(n)
    /\ ~mtxnSnapshots[n][tid]["aborted"]
    
    /\ (ActiveReadTimestamps(n) \cup CommitTimestamps(n)) # {} => commitTs > Max(ActiveReadTimestamps(n) \cup CommitTimestamps(n))
    
    /\ mlog' = [mlog EXCEPT ![n] = CommitTxnToLog(n, tid, commitTs)]
    /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["active"] = FALSE, ![n][tid]["committed"] = TRUE]
    /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
    /\ allDurableTs' = [allDurableTs EXCEPT ![n] = AllDurableTs(n)]
    /\ UNCHANGED <<mcommitIndex, stableTs, oldestTs>>

CommitPreparedTransaction(n, tid, commitTs, durableTs) == 

    /\ commitTs = durableTs 
    /\ commitTs > stableTs[n] 
    /\ tid \in ActiveTransactions(n)
    /\ tid \in PreparedTransactions(n)
    /\ ~mtxnSnapshots[n][tid]["aborted"]

    /\ commitTs >= mtxnSnapshots[n][tid].prepareTs
    /\ mlog' = [mlog EXCEPT ![n] = CommitTxnToLogWithDurable(n, tid, commitTs, durableTs)]
    /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["active"] = FALSE, ![n][tid]["committed"] = TRUE]
    /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
    /\ allDurableTs' = [allDurableTs EXCEPT ![n] = AllDurableTs(n)]
    /\ UNCHANGED <<mcommitIndex, stableTs, oldestTs>>

PrepareTransaction(n, tid, prepareTs) == 

    /\ prepareTs > stableTs[n]
    /\ tid \in ActiveTransactions(n)
    /\ ~mtxnSnapshots[n][tid]["prepared"]
    /\ ~mtxnSnapshots[n][tid]["aborted"]

    /\ prepareTs > Max(ActiveReadTimestamps(n))
    /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["prepared"] = TRUE, ![n][tid]["prepareTs"] = prepareTs]
    /\ mlog' = [mlog EXCEPT ![n] = PrepareTxnToLog(n,tid, prepareTs)]
    /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
    /\ UNCHANGED <<mcommitIndex, stableTs, oldestTs, allDurableTs>>

AbortTransaction(n, tid) == 
    /\ tid \in ActiveTransactions(n)
    /\ mtxnSnapshots' = [mtxnSnapshots EXCEPT ![n][tid]["active"] = FALSE, ![n][tid]["aborted"] = TRUE]
    /\ txnStatus' = [txnStatus EXCEPT ![n][tid] = STATUS_OK]
    /\ UNCHANGED <<mlog, mcommitIndex, stableTs, oldestTs, allDurableTs>>

Init_mlog == <<>>
Init_mcommitIndex == 0
Init_mtxnSnapshots == [t \in MTxId |-> [active |-> FALSE, committed |-> FALSE, aborted |-> FALSE]]

---------------------------------------------------------------------

===============================================================================

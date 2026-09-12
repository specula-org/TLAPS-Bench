--------------------------- MODULE MultiShardTxn ---------------------------------

EXTENDS Integers, Sequences, FiniteSets, Util, TLC

CONSTANTS Keys, TxId

CONSTANT Router, Shard

CONSTANT NoValue

CONSTANTS RC

CONSTANT Timestamps

CONSTANT IgnorePrepareBlocking
CONSTANT IgnoreWriteConflicts

CC == INSTANCE ClientCentric WITH Keys <- Keys, Values <- TxId \union {NoValue}          

wOp(k,v) == CC!w(k,v)
rOp(k,v) == CC!r(k,v)    
InitialState == [k \in Keys |-> NoValue]  

VARIABLE rtxn

VARIABLE rTxnReadTs

VARIABLE rInCommit

VARIABLE rParticipants

VARIABLE rCatalog

VARIABLE shardTxnReqs 

VARIABLES shardTxns

VARIABLE shardPreparedTxns

VARIABLE coordCommitVotes

VARIABLE aborted 

VARIABLE coordInfo

VARIABLE msgsPrepare
VARIABLE msgsVoteCommit
VARIABLE msgsAbort
VARIABLE msgsCommit

VARIABLE shardOps

VARIABLE ops

VARIABLE catalog

VARIABLE log 
VARIABLE commitIndex 

VARIABLE txnSnapshots

VARIABLE txnStatus
VARIABLE stableTs, oldestTs, allDurableTs

vars == << shardTxns, rInCommit, shardTxnReqs, aborted, log, commitIndex, rtxn, txnSnapshots, ops, shardOps, rParticipants, coordInfo, msgsPrepare, msgsVoteCommit, msgsAbort, coordCommitVotes, catalog, msgsCommit, rTxnReadTs, shardPreparedTxns, rCatalog, txnStatus, stableTs, oldestTs, allDurableTs >>
varsRouter == << rtxn, rInCommit, rTxnReadTs, rParticipants>>
varsNetwork == << msgsPrepare, msgsVoteCommit, msgsAbort, msgsCommit >>

Storage(s) == INSTANCE Storage WITH 
                    mlog <- log, 
                    mcommitIndex <- commitIndex, 
                    mtxnSnapshots <- txnSnapshots,
                    txnStatus <- txnStatus,
                    stableTs <- stableTs,
                    oldestTs <- oldestTs,
                    allDurableTs <- allDurableTs,
                    MTxId <- TxId,
                    NoValue <- NoValue,
                    Node <- Shard,
                    Timestamps <- Timestamps

Ops == {"read", "write", "coordCommit"}
CreateEntry(k, op, s, coord, start, ts) == [
    k |-> k, 
    op |-> op, 
    shard |-> s, 
    coord |-> coord, 
    start |-> start, 
    readTs |-> ts,
    rc |-> RC 
]
CreateCoordCommitEntry(op, s, p) == [op |-> op, shard |-> s, participants |-> p]

Init ==
    /\ catalog \in [Keys -> Shard]
    /\ ops = [s \in TxId |-> <<>>]
    
    /\ rtxn = [r \in Router |-> [t \in TxId |-> 0]]
    /\ rParticipants = [r \in Router |-> [t \in TxId |-> <<>>]]
    /\ rTxnReadTs = [r \in Router |-> [t \in TxId |-> NoValue]]
    /\ rInCommit = [r \in Router |-> [t \in TxId |-> FALSE]]
    
    /\ rCatalog = [r \in Router |-> catalog]
    
    /\ shardTxnReqs = [s \in Shard |-> [t \in TxId |->  <<>>]]
    /\ shardTxns = [s \in Shard |-> {}]
    /\ shardPreparedTxns = [s \in Shard |-> {}]
    /\ coordInfo = [s \in Shard |-> [t \in TxId |-> [self |-> FALSE, participants |-> <<>>, committing |-> FALSE]]]
    /\ coordCommitVotes = [s \in Shard |-> [t \in TxId |-> {}]]
    /\ shardOps = [s \in Shard |-> [t \in TxId |-> <<>>]]
    /\ aborted = [s \in Shard |-> [t \in TxId |-> FALSE]]
    
    /\ msgsPrepare = {}
    /\ msgsVoteCommit = {}
    /\ msgsAbort = {}
    /\ msgsCommit = {}
    
    /\ log = [s \in Shard |-> Storage(s)!Init_mlog]
    /\ commitIndex = [s \in Shard |-> Storage(s)!Init_mcommitIndex]
    /\ txnSnapshots = [s \in Shard |-> Storage(s)!Init_mtxnSnapshots]
    /\ txnStatus = [s \in Shard |-> [t \in TxId |-> Storage(s)!STATUS_OK]]
    /\ stableTs = [s \in Shard |-> 0]
    /\ oldestTs = [s \in Shard |-> 0]
    /\ allDurableTs = [s \in Shard |-> 0]

-------------------------------------------------

UpdateParticipants(r, tid, snew, op) == 
    (IF (\E el \in Range(rParticipants[r][tid]) : el[1] = snew) 
        THEN [ind \in DOMAIN rParticipants[r][tid] |-> 
                (IF rParticipants[r][tid][ind][1] = snew 
                    THEN <<snew, rParticipants[r][tid][ind][2] \cup {op}>> 
                    ELSE rParticipants[r][tid][ind])] 
        ELSE Append(rParticipants[r][tid], <<snew, {op}>>))

RouterTxnStart(r, tid, readTs) == 

    /\ \A other \in Router : rTxnReadTs[other][tid] = NoValue
    
    /\ rTxnReadTs' = [rTxnReadTs EXCEPT ![r][tid] = IF RC = "snapshot" THEN readTs ELSE 0]
    /\ UNCHANGED << rCatalog, shardTxns, rParticipants, shardTxnReqs, rtxn,  aborted, log, commitIndex, txnSnapshots, ops,coordInfo, coordCommitVotes, catalog, shardPreparedTxns, rInCommit, shardOps, varsNetwork, txnStatus, stableTs, oldestTs, allDurableTs >>

RouterTxnOp(r, s, tid, k, op) == 
    /\ op \in {"read", "write"}
    
    /\ ~\E as \in Shard : aborted[as][tid]
    
    /\ rInCommit[r][tid] = FALSE
    /\ rTxnReadTs[r][tid] # NoValue
    
    /\ rCatalog[r][k] = s

    /\ shardTxnReqs[s][tid] = <<>>
    
    /\ rParticipants' = [rParticipants EXCEPT ![r][tid] = UpdateParticipants(r, tid, s, op)]
    
    /\ LET firstShardOp == ~\E el \in Range(rParticipants[r][tid]) : el[1] = s IN
           shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = Append(shardTxnReqs[s][tid], CreateEntry(k, op, s, rtxn[r][tid] = 0, firstShardOp, rTxnReadTs[r][tid]))]
    /\ rtxn' = [rtxn EXCEPT ![r][tid] = rtxn[r][tid]+1]
    /\ UNCHANGED << rCatalog, shardTxns, rTxnReadTs,  aborted, log, commitIndex, txnSnapshots, ops,coordInfo, coordCommitVotes, catalog, shardPreparedTxns, rInCommit, shardOps, varsNetwork, txnStatus, stableTs, oldestTs, allDurableTs >>

RouterTxnCoordinateCommit(r, s, tid, op) == 
    /\ op = "coordCommit"
    
    /\ shardTxnReqs[s][tid] = <<>>
    
    /\ Len(rParticipants[r][tid]) > 1
    /\ ~rInCommit[r][tid]
    
    /\ ~\E as \in Shard : aborted[as][tid]
    /\ s = rParticipants[r][tid][1][1] 
    
    /\ shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = Append(shardTxnReqs[s][tid], CreateCoordCommitEntry(op, s, [i \in DOMAIN rParticipants[r][tid] |-> rParticipants[r][tid][i][1]]))]
    /\ rInCommit' = [rInCommit EXCEPT ![r][tid] = TRUE]
    /\ UNCHANGED << rCatalog, shardTxns,  rtxn, aborted, log, commitIndex, txnSnapshots, ops, rParticipants, coordInfo, coordCommitVotes, catalog, rTxnReadTs, shardPreparedTxns, shardOps, varsNetwork, txnStatus, stableTs, oldestTs, allDurableTs >>

RouterTxnCommitReadOnly(r, s, tid) == 
    
    /\ Len(rParticipants[r][tid]) > 1
    
    /\ \A p \in Range(rParticipants[r][tid]) : p[2] = {"read"}
    
    /\ shardTxnReqs[s][tid] = <<>>
    /\ ~rInCommit[r][tid]
    
    /\ ~aborted[s][tid]
    
    /\ msgsCommit' = msgsCommit \cup { [shard |-> sp[1], tid |-> tid, commitTs |-> NoValue] : sp \in Range(rParticipants[r][tid])}
    /\ rInCommit' = [rInCommit EXCEPT ![r][tid] = TRUE]
    /\ UNCHANGED << rCatalog, shardTxns,   aborted, shardTxnReqs, rtxn, log, commitIndex, txnSnapshots, ops, rParticipants, coordInfo, msgsVoteCommit, coordCommitVotes, catalog, msgsAbort, msgsPrepare, rTxnReadTs, shardPreparedTxns, shardOps, txnStatus, stableTs, oldestTs, allDurableTs >>

RouterTxnCommitSingleShard(r, s, tid) == 
    
    /\ Len(rParticipants[r][tid]) = 1 /\ rParticipants[r][tid][1][1] = s
    
    /\ shardTxnReqs[s][tid] = <<>>
    
    /\ ~aborted[s][tid]
    /\ ~rInCommit[r][tid]
    
    /\ msgsCommit' = msgsCommit \cup { [shard |-> s, tid |-> tid, commitTs |-> NoValue] }
    /\ rInCommit' = [rInCommit EXCEPT ![r][tid] = TRUE]
    /\ UNCHANGED << rCatalog, shardTxns,   aborted, shardTxnReqs, rtxn, log, commitIndex, txnSnapshots, ops, rParticipants, coordInfo, msgsVoteCommit, coordCommitVotes, catalog, msgsAbort, msgsPrepare, rTxnReadTs, shardPreparedTxns, shardOps, txnStatus, stableTs, oldestTs, allDurableTs >>

ShardTxnStart(s, tid) == 
    
    /\ shardTxnReqs[s][tid] # <<>>
    /\ Head(shardTxnReqs[s][tid]).op \in {"read", "write"}
    
    /\ Head(shardTxnReqs[s][tid]).start
    /\ tid \notin shardTxns[s]

    /\ shardTxns' = [shardTxns EXCEPT ![s] = shardTxns[s] \union {tid}]
    /\ coordInfo' = [coordInfo EXCEPT ![s][tid] = [self |-> Head(shardTxnReqs[s][tid]).coord, participants |-> <<s>>, committing |-> FALSE]]
    /\ Storage(s)!StartTransaction(s, tid, Head(shardTxnReqs[s][tid]).readTs, Head(shardTxnReqs[s][tid]).rc, IgnorePrepareBlocking)
    /\ UNCHANGED << rCatalog, shardTxnReqs,  aborted,  log, commitIndex, ops, msgsPrepare, msgsVoteCommit, coordCommitVotes, catalog, msgsAbort, msgsCommit, shardPreparedTxns, shardOps, varsRouter >>   

ShardTxnRead(s, tid, k, v) == 
    
    /\ shardTxnReqs[s][tid] # <<>>
    
    /\ tid \in shardTxns[s]
    
    /\ tid \notin shardPreparedTxns[s]
    /\ Head(shardTxnReqs[s][tid]).op = "read"
    /\ Head(shardTxnReqs[s][tid]).k = k
    
    /\ shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = Tail(shardTxnReqs[s][tid])]

    /\ shardOps' = [shardOps EXCEPT ![s][tid] = shardOps[s][tid] \o <<rOp(k, v)>>]
    /\ Storage(s)!TransactionRead(s, tid, k, v)
    
    /\ Storage(s)!TransactionPostOpStatus(s, tid) # Storage(s)!STATUS_PREPARE_CONFLICT
    /\ UNCHANGED << rCatalog, shardTxns, aborted, coordInfo, msgsPrepare, msgsVoteCommit, coordCommitVotes, catalog, msgsAbort, msgsCommit, shardPreparedTxns, ops, varsRouter, log, commitIndex >>    

ShardTxnWrite(s, tid, k) == 
    
    /\ tid \in shardTxns[s]
    
    /\ tid \notin shardPreparedTxns[s]
    /\ shardTxnReqs[s][tid] # <<>>
    /\ Head(shardTxnReqs[s][tid]).op = "write"
    /\ Head(shardTxnReqs[s][tid]).k = k
    /\ shardOps' = [shardOps EXCEPT ![s][tid] = Append( shardOps[s][tid], wOp(k, tid) )]
    
    /\ shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = Tail(shardTxnReqs[s][tid])]
    /\ Storage(s)!TransactionWrite(s, tid, k, tid, IgnoreWriteConflicts)
    /\ UNCHANGED << rCatalog, shardTxns, log, commitIndex, aborted, coordInfo, msgsPrepare, msgsVoteCommit, coordCommitVotes, catalog, msgsAbort, msgsCommit, shardPreparedTxns, ops, varsRouter >>

ShardTxnCoordinateCommit(s, tid) == 
    /\ tid \in shardTxns[s]
    /\ shardTxnReqs[s][tid] # <<>>
    /\ Head(shardTxnReqs[s][tid]).op = "coordCommit"
    
    /\ coordInfo[s][tid].self  
    
    /\ coordInfo' = [coordInfo EXCEPT ![s][tid] = [self |-> TRUE, participants |-> (Head(shardTxnReqs[s][tid]).participants), committing |-> TRUE]] 
    /\ coordCommitVotes' = [coordCommitVotes EXCEPT ![s][tid] = {}]
    
    /\ msgsPrepare' = msgsPrepare \cup {[shard |-> p, tid |-> tid, coordinator |-> s] : p \in Range(coordInfo'[s][tid].participants)}
    
    /\ shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = Tail(shardTxnReqs[s][tid])]
    /\ UNCHANGED << rCatalog, shardTxns, log, commitIndex, aborted, txnSnapshots, msgsVoteCommit, ops, catalog, msgsAbort, msgsCommit, shardPreparedTxns, shardOps, varsRouter, txnStatus, stableTs, oldestTs, allDurableTs >>

ShardTxnCoordinatorRecvCommitVote(s, tid, from) == 
    /\ tid \in shardTxns[s]
    
    /\ coordInfo[s][tid].self 
    /\ coordInfo[s][tid].committing 
    /\ \E m \in msgsVoteCommit : 
        /\ m.shard = from 
        /\ m.tid = tid
        /\ msgsVoteCommit' = msgsVoteCommit \ {m}
        /\ coordCommitVotes' = [coordCommitVotes EXCEPT ![s][tid] = coordCommitVotes[s][tid] \union {<<from,m.prepareTs>>}]
    /\ UNCHANGED << rCatalog, shardTxns, log, commitIndex,  shardTxnReqs, rtxn,  aborted, txnSnapshots, coordInfo, msgsPrepare, ops, catalog, msgsAbort, msgsCommit, shardPreparedTxns, shardOps, varsRouter, txnStatus, stableTs, oldestTs, allDurableTs >>

ShardTxnCoordinatorDecideCommit(s, tid) == 
    
    /\ tid \in shardTxns[s]
    
    /\ coordInfo[s][tid].self
    /\ {v[1] : v \in coordCommitVotes[s][tid]} = Range(coordInfo[s][tid].participants)
    /\ LET commitTs == max({v[2] : v \in coordCommitVotes[s][tid]}) IN
            msgsCommit' = msgsCommit \cup { [shard |-> p, tid |-> tid, commitTs |-> commitTs] : p \in Range(coordInfo[s][tid].participants) }
    /\ UNCHANGED << rCatalog, shardTxns, log, commitIndex,  shardTxnReqs,  aborted, txnSnapshots, coordInfo, msgsPrepare, msgsVoteCommit, ops, coordCommitVotes, catalog, msgsAbort, shardPreparedTxns, shardOps, varsRouter, txnStatus, stableTs, oldestTs, allDurableTs >>

ShardTxnPrepare(s, tid) == 
    \E m \in msgsPrepare : 
        
        /\ m.shard = s /\ m.tid = tid
        /\ tid \in shardTxns[s]
        /\ tid \notin shardPreparedTxns[s]
        
        /\ ~aborted[s][tid]
        /\ shardPreparedTxns' = [shardPreparedTxns EXCEPT ![s] = shardPreparedTxns[s] \union {tid}]

        /\ LET prepareTs == Storage(s)!NextTs(s) IN
            /\ msgsVoteCommit' = msgsVoteCommit \cup { [shard |-> s, tid |-> tid, to |-> m.coordinator, prepareTs |-> prepareTs] }
            
            /\ Storage(s)!PrepareTransaction(s, tid, prepareTs)
        /\ UNCHANGED << rCatalog, shardTxns,  shardTxnReqs,  aborted, coordInfo, msgsPrepare, ops, coordCommitVotes, catalog, msgsAbort, msgsCommit, shardOps, varsRouter, commitIndex >>

ShardTxnCommit(s, tid) == 
    /\ tid \in shardTxns[s]
    /\ \E m \in msgsCommit : 
        /\ m.shard = s 
        /\ m.tid = tid
        /\ msgsCommit' = msgsCommit \ {m}
        /\ shardTxns' = [shardTxns EXCEPT ![s] = shardTxns[s] \ {tid}]
        /\ shardPreparedTxns' = [shardPreparedTxns EXCEPT ![s] = shardPreparedTxns[s] \ {tid}]
        
        /\ shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = <<>>]
        /\ ops' = [ops EXCEPT ![tid] = ops[tid] \o shardOps[s][tid]]
        /\  
            
            \/ /\ m.commitTs = NoValue 
               /\ Storage(s)!CommitTransaction(s, tid, Storage(s)!NextTs(s))
            \/ /\ m.commitTs # NoValue
               /\ Storage(s)!CommitPreparedTransaction(s, tid, m.commitTs, m.commitTs)
    /\ UNCHANGED <<rCatalog, coordInfo, msgsPrepare, msgsVoteCommit, coordCommitVotes, catalog, msgsAbort, aborted, shardOps, varsRouter, commitIndex >>

ShardTxnAbort(s, tid) == 
    /\ tid \in shardTxns[s]
    /\ aborted' = [aborted EXCEPT ![s][tid] = TRUE]
    /\ shardTxns' = [shardTxns EXCEPT ![s] = shardTxns[s] \ {tid}]

    /\ shardOps' = [shardOps EXCEPT ![s][tid] = <<>>]
    
    /\ shardTxnReqs' = [shardTxnReqs EXCEPT ![s][tid] = <<>>]
    /\ Storage(s)!AbortTransaction(s, tid)
    /\ UNCHANGED << rCatalog, msgsAbort, log, commitIndex, coordInfo, msgsPrepare, msgsVoteCommit, coordCommitVotes, catalog, msgsCommit, shardPreparedTxns, ops, varsRouter>>

Next == 
    
    \/ \E r \in Router, t \in TxId, ts \in Timestamps : RouterTxnStart(r, t, ts)
    \/ \E r \in Router, s \in Shard, t \in TxId, k \in Keys, op \in Ops : RouterTxnOp(r, s, t, k, op)
    \/ \E r \in Router, s \in Shard, t \in TxId, op \in Ops: RouterTxnCoordinateCommit(r, s, t, op)
    \/ \E r \in Router, s \in Shard, t \in TxId: RouterTxnCommitReadOnly(r, s, t)
    \/ \E r \in Router, s \in Shard, t \in TxId: RouterTxnCommitSingleShard(r, s, t)

    \/ \E s \in Shard, tid \in TxId: ShardTxnStart(s, tid)
    \/ \E s \in Shard, tid \in TxId, k \in Keys, v \in TxId \cup {NoValue} : ShardTxnRead(s, tid, k, v)
    \/ \E s \in Shard, tid \in TxId, k \in Keys: ShardTxnWrite(s, tid, k)
    
    \/ \E s \in Shard, tid \in TxId, k \in Keys: ShardTxnCoordinateCommit(s, tid)
    \/ \E s, from \in Shard, tid \in TxId, k \in Keys: ShardTxnCoordinatorRecvCommitVote(s, tid, from)
    \/ \E s \in Shard, tid \in TxId, k \in Keys: ShardTxnCoordinatorDecideCommit(s, tid)
    \/ \E s \in Shard, tid \in TxId, k \in Keys: ShardTxnPrepare(s, tid)
    \/ \E s \in Shard, tid \in TxId, k \in Keys: ShardTxnCommit(s, tid)
    \/ \E s \in Shard, tid \in TxId, k \in Keys: ShardTxnAbort(s, tid)

Spec == Init /\ [][Next]_vars

-----------------------------------------

SnapshotIsolation == CC!SnapshotIsolation(InitialState, Range(ops))

===========================================================================

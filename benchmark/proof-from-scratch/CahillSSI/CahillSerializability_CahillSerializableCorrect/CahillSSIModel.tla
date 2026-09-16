------------------- MODULE CahillSSIModel -------------------

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS TxnId, Key
NoLock == CHOOSE x : x \notin (Key \union TxnId)         

VARIABLES  
           history,             
           holdingXLocks,      
           waitingForXLock,

           inConflict,         
           outConflict, 
           holdingSIREADlocks  

allvars == <<history, holdingXLocks, waitingForXLock, inConflict, outConflict, holdingSIREADlocks>>

Range(f) == {f[x] : x \in DOMAIN f}

SelectEvents(h, Test(_)) == {e \in Range(h): Test(e)}

ActiveOrFinalizedTxns(h) == {e.txnid : e \in Range(h)}        
CommittedTxns(h)         == {e.txnid : e \in SelectEvents(h, LAMBDA e : e.op \in {"commit"})}
AbortedTxns(h)           == {e.txnid : e \in SelectEvents(h, LAMBDA e : e.op \in {"abort"})}
FinalizedTxns(h)         == CommittedTxns(h) \union AbortedTxns(h)
ActiveTxns(h)            == ActiveOrFinalizedTxns(h) \ FinalizedTxns(h)

StartTime(h, txn) == CHOOSE pos \in 1 .. Len(h) : h[pos] = [op |-> "begin", txnid |-> txn]

KeysThatTxnHasDoneOperationOn(h, txn, operation) == 
    LET txn_ops == SelectEvents(h, LAMBDA e : e.txnid = txn  /\  e.op = operation) 
    IN {e.key : e \in txn_ops}

CommittedWriteHistoryOfKey(h, key) ==
    SelectSeq(h,
              LAMBDA e : /\ e.op = "write" 
                         /\ e.key = key
                         /\ e.txnid \in CommittedTxns(h))

IndexOfOpInHistory(h, op) == 
    IF op \in Range(h) THEN CHOOSE i \in 1..Len(h) : h[i] = op
                       ELSE -1

KeysCurrentlyXLockedByActiveTxn(txn) == holdingXLocks[txn]

KeysCurrentlyXLockedByAnyTxn == UNION Range(holdingXLocks) 

StartedAndCanDoPublicOperation(txn) ==
       
    /\ txn \in ActiveTxns(history)

    /\ waitingForXLock[txn] = NoLock    

WritersCommittedToKeySinceTxnBegan(txn, key) ==

    LET hSinceTxnBegan == SubSeq(history, StartTime(history, txn), Len(history))
        cSinceTxnBegan == CommittedTxns(hSinceTxnBegan) 
    IN  
        {t \in cSinceTxnBegan : key \in KeysThatTxnHasDoneOperationOn(history, t, "write")}  

LatestCommittedVersionOfKeyWhenTxnBegan(txn, key) ==

    LET hBeforeTxnBegan == SubSeq(history, 1, StartTime(history, txn))
        cwhkbtb         == CommittedWriteHistoryOfKey(hBeforeTxnBegan, key)                       
    IN  
        
        IF Len(cwhkbtb) = 0 THEN {} 
                            ELSE {cwhkbtb[Len(cwhkbtb)].txnid}

VersionThatWouldBeReadBy(txn, key) ==
    IF key \in KeysCurrentlyXLockedByActiveTxn(txn) THEN

        {txn}         
    ELSE  

        LatestCommittedVersionOfKeyWhenTxnBegan(txn, key)

VersionIDsOfKeyNewerThanReadByTxn(txn, key) ==
    LET write_history_of_key_by_all_txns 
            == SelectSeq(history, LAMBDA e : e.op = "write" /\ e.key = key)

        readVerSet == VersionThatWouldBeReadBy(txn, key)
              
        index_of_write_op_that_will_be_read_by_txn 
            == CHOOSE i \in 1..Len(write_history_of_key_by_all_txns) : 
                        write_history_of_key_by_all_txns[i] = [op |-> "write",  txnid |-> (CHOOSE ver \in readVerSet : TRUE), key |-> key]

        write_history_newer_than_write_op_that_will_be_read_by_txn
            == SubSeq(write_history_of_key_by_all_txns, 
                      index_of_write_op_that_will_be_read_by_txn + 1,   
                      Len(write_history_of_key_by_all_txns))            
    IN 
        {write_op.txnid : write_op \in Range(write_history_newer_than_write_op_that_will_be_read_by_txn)}

internalAbort(txn, reason) == 
    /\ history'         = Append(history, [op |-> "abort", txnid |-> txn, reason |-> reason])
    /\ holdingXLocks'   = [holdingXLocks EXCEPT ![txn] = {}]        
    /\ waitingForXLock' = [waitingForXLock EXCEPT ![txn] = NoLock]    

    /\ inConflict'         = [inConflict EXCEPT ![txn] = FALSE]
    /\ outConflict'        = [outConflict EXCEPT ![txn] = FALSE]
    /\ holdingSIREADlocks' = [holdingSIREADlocks EXCEPT ![txn] = {}]

Begin(txn) == 
    /\ txn \notin ActiveOrFinalizedTxns(history)
    /\ history' = Append(history, [op |-> "begin", txnid |-> txn]) 
    /\ UNCHANGED <<holdingXLocks, waitingForXLock, inConflict, outConflict, holdingSIREADlocks>>

Commit(txn) == 
    /\ StartedAndCanDoPublicOperation(txn)

    /\ IF inConflict[txn] /\  outConflict[txn] THEN

         internalAbort(txn, "in attempted commit, to preserve serializability")
       ELSE

         /\ LET  XLocksHeldByCommittingTxn == 
                     KeysCurrentlyXLockedByActiveTxn(txn)
                      
                 LoserTxns == 
                     {blockedTxn \in TxnId : waitingForXLock[blockedTxn] \in XLocksHeldByCommittingTxn}
                      
                 AbortOpSeq(Txns) ==
                     LET BuildAbortOpSeq[RemainingTxns \in SUBSET Txns] == 
                             IF RemainingTxns = {} THEN 
                                 <<>>  
                             ELSE 
                                 LET t == CHOOSE t \in RemainingTxns : TRUE
                                 IN     <<[op |-> "abort", txnid |-> t, reason |-> "forced by First Committer Wins"]>> 
                                     \o BuildAbortOpSeq[RemainingTxns \ {t}]
                     IN  
                         BuildAbortOpSeq[Txns]
            IN 
               /\ history'            = Append(history, [op |-> "commit", txnid |-> txn]) \o AbortOpSeq(LoserTxns)
               /\ holdingXLocks'      = [t \in TxnId |-> IF t \in {txn} \union LoserTxns 
                                                         THEN {}              
                                                         ELSE holdingXLocks[t]]
               /\ waitingForXLock'    = [t \in TxnId |-> IF t \in LoserTxns 
                                                         THEN NoLock           
                                                         ELSE waitingForXLock[t]]
               /\ inConflict'         = [t \in TxnId |-> IF t \in LoserTxns 
                                                         THEN FALSE           
                                                         ELSE inConflict[t]]   
               /\ outConflict'        = [t \in TxnId |-> IF t \in LoserTxns 
                                                         THEN FALSE           
                                                         ELSE outConflict[t]]  
               /\ holdingSIREADlocks' = [t \in TxnId |-> IF t \in LoserTxns 
                                                         THEN {}              
                                                         ELSE holdingSIREADlocks[t]]

ChooseToAbort(txn) == 
    /\ StartedAndCanDoPublicOperation(txn)
    /\ internalAbort(txn, "voluntary")

Read(txn, key) == 
    /\ StartedAndCanDoPublicOperation(txn)
    /\ key \notin KeysThatTxnHasDoneOperationOn(history, txn, "read")   
    /\ LET readVerSet == VersionThatWouldBeReadBy(txn, key) 
       IN
         /\ readVerSet /= {} 

         /\ LET 

                versionids_of_key_newer_than_read_by_txn == VersionIDsOfKeyNewerThanReadByTxn(txn, key)
            IN
              IF \E xNewCreator \in versionids_of_key_newer_than_read_by_txn
                   : /\ xNewCreator \in CommittedTxns(history) 
                     /\ outConflict[xNewCreator] 
              THEN

                internalAbort(txn, "in attempted read, to preserve serializability")

              ELSE

                /\ history' = Append(history, [op |-> "read", txnid |-> txn, 
                                     key |-> key, ver |-> CHOOSE ver \in readVerSet : TRUE])
                /\ UNCHANGED <<holdingXLocks, waitingForXLock>>

                /\ holdingSIREADlocks' = [holdingSIREADlocks EXCEPT ![txn] = @ \union {key}]

                /\ LET newInConflictTxns == versionids_of_key_newer_than_read_by_txn 
                                               \union  {t \in (TxnId \ {txn}) : key \in holdingXLocks[t]}
                   IN inConflict' = [t \in TxnId |-> IF t \in newInConflictTxns 
                                                     THEN TRUE
                                                     ELSE inConflict[t]]   

                /\ IF \/ versionids_of_key_newer_than_read_by_txn /= {} 
                      \/ \E xlock_owner \in (TxnId \ {txn}) : key \in holdingXLocks[xlock_owner]  
                   THEN outConflict' = [outConflict EXCEPT ![txn] = TRUE]                
                   ELSE UNCHANGED outConflict

findConcurrentSIREADlockOwners(txn, key) ==    

    {concurrent_SIREADlock_owner \in 
            {t \in TxnId \ {txn} : key \in holdingSIREADlocks[t]} 
        : 

        \/ concurrent_SIREADlock_owner \notin CommittedTxns(history)   

        \/ 
           IndexOfOpInHistory(history, [op |-> "commit", txnid |-> concurrent_SIREADlock_owner])   
             > IndexOfOpInHistory(history, [op |-> "begin", txnid |-> txn])
    }         

snapshotIsolationWriteAction(txn, key) ==    
    /\ history'         = Append(history, [op |-> "write", txnid |-> txn, key |-> key])
    /\ holdingXLocks'   = [holdingXLocks EXCEPT ![txn] = @ \union {key}]  
    /\ waitingForXLock' = [waitingForXLock EXCEPT ![txn] = NoLock]

HelperWriteCanAcquireXLock(txn, key) ==

    LET concurrent_sireadlock_owners == findConcurrentSIREADlockOwners(txn, key)
    IN
      IF concurrent_sireadlock_owners /= {} THEN 

        IF \E sireadlock_owner \in concurrent_sireadlock_owners
               : \/ sireadlock_owner \in CommittedTxns(history)  
                 \/ inConflict[sireadlock_owner]
        THEN

            internalAbort(txn, "in attempted write, to preserve serializability")
        ELSE

            /\ snapshotIsolationWriteAction(txn, key)

            /\ outConflict'  = [t \in TxnId |-> IF t \in concurrent_sireadlock_owners 
                                                THEN TRUE
                                                ELSE outConflict[t]] 

            /\ inConflict'   = [inConflict EXCEPT ![txn] = TRUE]

            /\ UNCHANGED holdingSIREADlocks
      ELSE

        /\ snapshotIsolationWriteAction(txn, key)

        /\ UNCHANGED <<inConflict, outConflict, holdingSIREADlocks>>

HelperWriteConflictsWithXLock(txn, key) ==

    LET activeTxns == ActiveTxns(history)

        xlockIsHeldBy == 
            [k \in Key |->
                LET holder == {t \in activeTxns : k \in KeysCurrentlyXLockedByActiveTxn(t)}
                IN  IF holder /= {} THEN CHOOSE t \in holder : TRUE
                                    ELSE NoLock]

        proposedWaitingForXLock == [waitingForXLock EXCEPT ![txn] = key] 

        newWaitingForXLockHeldByEdges == 
            {waitEdge \in activeTxns \X activeTxns :
                LET from == waitEdge[1] to == waitEdge[2] IN
                \E k \in Key :  /\ proposedWaitingForXLock[from] = k
                                /\ xlockIsHeldBy[k]              = to}

        pathThatCyclesFromTxnToTxn ==

            LET nonemptyPaths == {path \in Seq(activeTxns) : Len(path) > 0}

                extendPath[currPath \in nonemptyPaths] ==
                    LET from == currPath[Len(currPath)]
                        outgoingEdges == {candidateEdge \in newWaitingForXLockHeldByEdges : candidateEdge[1] = from} 
                    IN  IF outgoingEdges = {} 
                        THEN {}             
                        ELSE LET edge == CHOOSE selectedEdge \in outgoingEdges : TRUE 
                             IN  IF edge[2] = txn THEN {currPath}   
                                                  ELSE extendPath[Append(currPath, edge[2])]
            IN extendPath[<<txn>>]
    IN
        IF pathThatCyclesFromTxnToTxn = {} THEN

            /\ waitingForXLock' = [waitingForXLock EXCEPT ![txn] = key] 
            /\ UNCHANGED <<history, holdingXLocks, inConflict, outConflict, holdingSIREADlocks>>
        ELSE

            \E to_abort \in Range(CHOOSE anyPathSeq \in pathThatCyclesFromTxnToTxn : TRUE) :
                /\ history' = Append(history, [op |-> "abort", txnid |-> to_abort, reason |-> "forced by deadlock-prevention"])
                /\ IF to_abort = txn THEN

                    /\ holdingXLocks' = [holdingXLocks EXCEPT ![txn] = {}]  
                    /\ UNCHANGED <<waitingForXLock>>    
                   ELSE

                    /\ holdingXLocks'   = [holdingXLocks EXCEPT ![to_abort] = {}]       
                    /\ waitingForXLock' = [waitingForXLock EXCEPT ![txn]      = key, 
                                                                  ![to_abort] = NoLock] 
                /\ inConflict'         = [inConflict EXCEPT ![to_abort] = FALSE] 
                /\ outConflict'        = [outConflict EXCEPT ![to_abort] = FALSE] 
                /\ holdingSIREADlocks' = [holdingSIREADlocks EXCEPT ![to_abort] = {}] 

StartWriteMayBlock(txn, key) == 
    /\ StartedAndCanDoPublicOperation(txn)
    /\ key \notin KeysCurrentlyXLockedByActiveTxn(txn)  

    /\ IF WritersCommittedToKeySinceTxnBegan(txn, key) /= {} THEN
        
        /\ history'            = Append(history, [op |-> "abort", txnid |-> txn, reason |-> "forced by First Committer Wins"])
        /\ holdingXLocks'      = [holdingXLocks EXCEPT ![txn] = {}]  
        /\ inConflict'         = [inConflict EXCEPT ![txn] = FALSE] 
        /\ outConflict'        = [outConflict EXCEPT ![txn] = FALSE] 
        /\ holdingSIREADlocks' = [holdingSIREADlocks EXCEPT ![txn] = {}] 
        /\ UNCHANGED <<waitingForXLock>>    
       ELSE
        IF key \in KeysCurrentlyXLockedByAnyTxn THEN
            
            HelperWriteConflictsWithXLock(txn, key)
        ELSE
            
            HelperWriteCanAcquireXLock(txn, key)

FinishBlockedWrite(txn) ==
    /\ waitingForXLock[txn] /= NoLock
    /\ LET key == waitingForXLock[txn] 
       IN  /\ key \notin KeysCurrentlyXLockedByAnyTxn
           /\ HelperWriteCanAcquireXLock(txn, key)

Init == /\ history            = <<>>
        /\ holdingXLocks      = [txn \in TxnId |-> {}] 
        /\ waitingForXLock    = [txn \in TxnId |-> NoLock]
        /\ inConflict         = [txn \in TxnId |-> FALSE]
        /\ outConflict        = [txn \in TxnId |-> FALSE]
        /\ holdingSIREADlocks = [txn \in TxnId |-> {}]

LegitimateTermination ==  FinalizedTxns(history) = TxnId

Next == \/ \E txn \in TxnId :

            \/ Begin(txn)
            \/ Commit(txn)
            \/ ChooseToAbort(txn) 
            \/ \E key \in Key : 
                \/ Read(txn, key)
                \/ StartWriteMayBlock(txn, key)

            \/ FinishBlockedWrite(txn)

        \/ (LegitimateTermination /\ UNCHANGED allvars) 

Spec == Init  /\  [][Next]_allvars  /\  WF_allvars(Next)           

FindAllNodesInAnyCycle(edges) ==

    LET nodes == UNION {{edge[1], edge[2]} : edge \in edges}

        findCycleNodes[node \in nodes, visitedSet \in SUBSET nodes] ==
            IF node \in visitedSet THEN
                {node}  
            ELSE
                LET newVisited == visitedSet \union {node}
                    neighbors == {link[2] : link \in {outgoing \in edges : outgoing[1] = node}}
                IN  
                    UNION {findCycleNodes[neighbor, newVisited] : neighbor \in neighbors}
                    
        startPoints == {link[1] : link \in edges}  
    IN 
        UNION {findCycleNodes[node, {}] : node \in startPoints}
       
IsCycle(edges) == FindAllNodesInAnyCycle(edges) /= {}

CahillMVSG(h) ==

    LET ct == CommittedTxns(h)
        ch == SelectSeq(h, LAMBDA e : e.txnid \in CommittedTxns(h))
    IN

        {transactionPair \in ct \X ct :
                LET T1 == transactionPair[1] T2 == transactionPair[2] IN
                
               T1 /= T2
            /\ \E x \in Key :
                LET iT1w == IndexOfOpInHistory(ch, [op |-> "write",  txnid |-> T1, key |-> x])
                    iT2w == IndexOfOpInHistory(ch, [op |-> "write",  txnid |-> T2, key |-> x])
                IN      

                        /\ iT1w /= -1    
                        /\ iT2w /= -1      
                        /\ iT1w < iT2w  

                    \/  

                        LET iT1c == IndexOfOpInHistory(ch, [op |-> "commit", txnid |-> T1])
                            iT2b == IndexOfOpInHistory(ch, [op |-> "begin", txnid |-> T2])
                        IN  
                            /\ iT1w /= -1                                                
                            /\ x \in KeysThatTxnHasDoneOperationOn(ch, T2, "read")   
                            /\ iT1c < iT2b                                            
                    \/  

                        LET iT1b == IndexOfOpInHistory(ch, [op |-> "begin", txnid |-> T1])
                            iT2c == IndexOfOpInHistory(ch, [op |-> "commit", txnid |-> T2])
                        IN 
                            /\ x \in KeysThatTxnHasDoneOperationOn(h, T1, "read")  
                            /\ iT2w /= -1                                          
                            /\ iT1b < iT2c                                         
        }

CahillSerializable(h) ==  ~ IsCycle(CahillMVSG(h))

=============================================================================


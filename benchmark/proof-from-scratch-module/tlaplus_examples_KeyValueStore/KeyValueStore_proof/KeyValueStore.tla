--------------------------- MODULE KeyValueStore ---------------------------

CONSTANTS   Key,            
            Val,            
            TxId            
VARIABLES   store,          
            tx,             
            snapshotStore,  
            written,        
            missed          
----------------------------------------------------------------------------
NoVal ==    
    CHOOSE v : v \notin Val

Store ==    
    [Key -> Val \cup {NoVal}]

Init == 
    /\ store = [k \in Key |-> NoVal]        
    /\ tx = {}                              
    /\ snapshotStore =                      
        [t \in TxId |-> [k \in Key |-> NoVal]]
    /\ written = [t \in TxId |-> {}]        
    /\ missed = [t \in TxId |-> {}]         
    
TypeInvariant ==    
    /\ store \in Store
    /\ tx \subseteq TxId
    /\ snapshotStore \in [TxId -> Store]
    /\ written \in [TxId -> SUBSET Key]
    /\ missed \in [TxId -> SUBSET Key]
    
TxLifecycle ==
    /\ \A t \in tx :    
        \A k \in Key : (store[k] /= snapshotStore[t][k] /\ k \notin written[t]) => k \in missed[t]
    /\ \A t \in TxId \ tx : 
        /\ \A k \in Key : snapshotStore[t][k] = NoVal
        /\ written[t] = {}
        /\ missed[t] = {}

OpenTx(t) ==    
    /\ t \notin tx
    /\ tx' = tx \cup {t}
    /\ snapshotStore' = [snapshotStore EXCEPT ![t] = store]
    /\ UNCHANGED <<written, missed, store>>

Add(t, k, v) == 
    /\ t \in tx
    /\ snapshotStore[t][k] = NoVal
    /\ snapshotStore' = [snapshotStore EXCEPT ![t][k] = v]
    /\ written' = [written EXCEPT ![t] = @ \cup {k}]
    /\ UNCHANGED <<tx, missed, store>>
    
Update(t, k, v) ==  
    /\ t \in tx
    /\ snapshotStore[t][k] \notin {NoVal, v}
    /\ snapshotStore' = [snapshotStore EXCEPT ![t][k] = v]
    /\ written' = [written EXCEPT ![t] = @ \cup {k}]
    /\ UNCHANGED <<tx, missed, store>>
    
Remove(t, k) == 
    /\ t \in tx
    /\ snapshotStore[t][k] /= NoVal
    /\ snapshotStore' = [snapshotStore EXCEPT ![t][k] = NoVal]
    /\ written' = [written EXCEPT ![t] = @ \cup {k}]
    /\ UNCHANGED <<tx, missed, store>>
    
RollbackTx(t) ==    
    /\ t \in tx
    /\ tx' = tx \ {t}
    /\ snapshotStore' = [snapshotStore EXCEPT ![t] = [k \in Key |-> NoVal]]
    /\ written' = [written EXCEPT ![t] = {}]
    /\ missed' = [missed EXCEPT ![t] = {}]
    /\ UNCHANGED store

CloseTx(t) ==   
    /\ t \in tx
    /\ missed[t] \cap written[t] = {}   
    /\ store' =                         
        [k \in Key |-> IF k \in written[t] THEN snapshotStore[t][k] ELSE store[k]]
    /\ tx' = tx \ {t}
    /\ missed' =    
        [otherTx \in TxId |-> IF otherTx \in tx' THEN missed[otherTx] \cup written[t] ELSE {}]
    /\ snapshotStore' = [snapshotStore EXCEPT ![t] = [k \in Key |-> NoVal]]
    /\ written' = [written EXCEPT ![t] = {}]

Next == 
    \/ \E t \in TxId : OpenTx(t)
    \/ \E t \in tx : \E k \in Key : \E v \in Val : Add(t, k, v)
    \/ \E t \in tx : \E k \in Key : \E v \in Val : Update(t, k, v)
    \/ \E t \in tx : \E k \in Key : Remove(t, k)
    \/ \E t \in tx : RollbackTx(t)
    \/ \E t \in tx : CloseTx(t)
        
Spec == 
    Init /\ [][Next]_<<store, tx, snapshotStore, written, missed>>
----------------------------------------------------------------------------
=============================================================================


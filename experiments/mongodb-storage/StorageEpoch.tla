---------------------------- MODULE StorageEpoch ----------------------------
EXTENDS StorageSafety

\* Recovery-free behavior starting at upstream Init. Every action except
\* RollbackToStable is retained; this is not recovery-inclusive SI.
EpochNext ==
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps, ip \in IgnorePrepareOptions : StartTransaction(n,t,ts,RC,ip)
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values : TransactionWrite(n,t,k,v,"false")
    \/ \E n \in Node, t \in MTxId, k \in Keys, v \in Values \cup {NoValue} : TransactionRead(n,t,k,v)
    \/ \E n \in Node, t \in MTxId, k \in Keys : TransactionRemove(n,t,k)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : PrepareTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts \in Timestamps : CommitTransaction(n,t,ts)
    \/ \E n \in Node, t \in MTxId, ts, dts \in Timestamps : CommitPreparedTransaction(n,t,ts,dts)
    \/ \E n \in Node, t \in MTxId : AbortTransaction(n,t)
    \/ \E n \in Node, ts \in Timestamps : SetStableTimestamp(n,ts)
    \/ \E n \in Node, ts \in Timestamps : SetOldestTimestamp(n,ts)

EpochSpec == Init /\ [][EpochNext]_vars

THEOREM EpochActionProjection == EpochNext => Next
BY SMT DEF EpochNext, Next

THEOREM EpochBehaviorProjection == EpochSpec => Spec
BY EpochActionProjection, PTL DEF EpochSpec, Spec
=============================================================================

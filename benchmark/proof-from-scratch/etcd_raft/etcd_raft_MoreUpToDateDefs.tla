--------------------------------- MODULE etcd_raft_MoreUpToDateDefs ---------------------------------

EXTENDS etcd_raftModel

Committed(i) == SubSeq(log[i],1,commitIndex[i])

MoreUpToDateCorrectInv ==
    \A i \in Server :
       (\E Q \in Quorum(GetConfig(i)) :
           \A j \in Q :
               \/ LastTerm(log[i]) > LastTerm(log[j])
               \/ /\ LastTerm(log[i]) = LastTerm(log[j])
                  /\ Len(log[i]) >= Len(log[j])) =>
       \A j \in Server : IsPrefix(Committed(j), log[i])

===============================================================================


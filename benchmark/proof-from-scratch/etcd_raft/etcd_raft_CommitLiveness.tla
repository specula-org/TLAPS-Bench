---- MODULE etcd_raft_CommitLiveness ----
EXTENDS etcd_raft_CommitLivenessDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM CommitLiveness ==
    \A l \in InitServer : \A Q \in Quorum(InitServer) : \A n \in Nat \ {0} :
        LiveSpec(l, Q, n) => CommitProgress(l, n)
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

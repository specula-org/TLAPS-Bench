--------------------------------- MODULE etcd_raft_LeaderCompletenessDefs ---------------------------------

EXTENDS etcd_raftModel

LeaderCompletenessInv ==
    \A c \in commitHistory, e \in electionHistory :
        c.term < e.term => IsPrefix(c.entries, e.entries)

===============================================================================


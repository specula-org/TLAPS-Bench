---- MODULE etcd_raft ----
EXTENDS etcd_raftDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Spec => []LogInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_LogInv.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_LogInv.tla

THEOREM CommittedIsDurable == Spec => []CommittedIsDurableInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_CommittedIsDurable.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_CommittedIsDurable.tla

THEOREM ElectionSafety == Spec => []ElectionSafetyInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_ElectionSafety.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_ElectionSafety.tla

THEOREM LeaderCompleteness == Spec => []LeaderCompletenessInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_LeaderCompleteness.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_LeaderCompleteness.tla

THEOREM LogMatching == Spec => []LogMatchingInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_LogMatching.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_LogMatching.tla

THEOREM MoreThanOneLeader == Spec => []MoreThanOneLeaderInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_MoreThanOneLeader.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_MoreThanOneLeader.tla

THEOREM MoreUpToDate == Spec => []MoreUpToDateCorrectInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_MoreUpToDate.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_MoreUpToDate.tla

THEOREM QuorumLog == Spec => []QuorumLogInv
\* BEGIN AGENT PROOF etcd_raft/etcd_raft_QuorumLog.tla
PROOF OMITTED
\* END AGENT PROOF etcd_raft/etcd_raft_QuorumLog.tla
====

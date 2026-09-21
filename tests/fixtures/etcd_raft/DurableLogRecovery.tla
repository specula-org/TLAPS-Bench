---- MODULE DurableLogRecovery ----
EXTENDS etcd_raftDefs
CONSTANTS s1,s2,s3, RecoveryCase
MCServer == {s1,s2,s3}
MCInitServer == {s1,s2,s3}

VARIABLE pc

Step(n, A) == pc = n /\ pc' = n+1 /\ A

RecvT(ty, d) == \E m \in DOMAIN messages : m.mtype = ty /\ m.mdest = d /\ Receive(m)

SInit == Init /\ pc = 0

SNext ==
  \/ Step(0,  Timeout(s1))
  \/ Step(1,  Ready(s1))
  \/ Step(2,  RequestVote(s1,s1))
  \/ Step(3,  RequestVote(s1,s2))
  \/ Step(4,  Ready(s1))
  \/ Step(5,  RecvT(RequestVoteResponse, s1))
  \/ Step(6,  RecvT(RequestVoteRequest, s2))
  \/ Step(7,  RecvT(RequestVoteRequest, s2))
  \/ Step(8,  Ready(s2))
  \/ Step(9,  RecvT(RequestVoteResponse, s1))
  \/ Step(10, BecomeLeader(s1))
  \/ Step(11, ClientRequest(s1, 0))
  \/ Step(12, Ready(s1))
  \/ Step(13, Timeout(s3))
  \/ Step(14, Timeout(s3))
  \/ Step(15, Ready(s3))
  \/ Step(16, RequestVote(s3,s3))
  \/ Step(17, RequestVote(s3,s2))
  \/ Step(18, Ready(s3))
  \/ Step(19, RecvT(RequestVoteResponse, s3))
  \/ Step(20, RecvT(RequestVoteRequest, s2))
  \/ Step(21, RecvT(RequestVoteRequest, s2))
  \/ Step(22, Ready(s2))
  \/ Step(23, RecvT(RequestVoteResponse, s3))
  \/ Step(24, BecomeLeader(s3))
  \/ Step(25, ClientRequest(s3, 0))
  \/ Step(26, AppendEntries(s3, s1, <<1,2>>))
  \/ Step(27, Ready(s3))
  \/ Step(28, RecvT(AppendEntriesRequest, s1))
  \/ Step(29, RecvT(AppendEntriesRequest, s1))
  \/ Step(30, IF RecoveryCase = "truncate" THEN UNCHANGED vars
              ELSE RecvT(AppendEntriesRequest, s1))
  \/ Step(31, IF RecoveryCase = "persist" THEN Ready(s1) ELSE UNCHANGED vars)
  \/ Step(32, Restart(s1))
  \/ (pc = 33 /\ UNCHANGED <<pc, vars>>)

SSpec == SInit /\ [][SNext]_<<pc, vars>>

DurLogLeqLen == \A i \in Server : durableState[i].log <= Len(log[i])
RefinesNext == [][Next]_vars
RecoveredLog == pc = 33 =>
  log[s1] = <<[term |-> IF RecoveryCase = "persist" THEN 2 ELSE 1,
              type |-> ValueEntry, value |-> [val |-> 0]]>>
====

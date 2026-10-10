---- MODULE LeaderCompleteness ----
EXTENDS etcd_raftDefs
CONSTANTS CommitOnFollower, CrashBeforeElection, ElectionNode
VARIABLE pc

Voter == IF ElectionNode = 2 THEN 3 ELSE 1
TraceMessage(ty, src, dst, t) ==
    CHOOSE m \in DOMAIN messages :
        m.mtype = ty /\ m.msource = src /\ m.mdest = dst /\ m.mterm = t

TraceInit == Init /\ pc = 0

\* Terms 1 and 2 elect leaders with conflicting, uncommitted entries.
\* Term 3 commits the term-1 entry; term 4 must retain that committed prefix.
TraceAction ==
    CASE pc = 0 -> Timeout(1)
      [] pc = 1 -> RequestVote(1,1)
      [] pc = 2 -> RequestVote(1,3)
      [] pc = 3 -> Ready(1)
      [] pc = 4 -> Receive(TraceMessage(RequestVoteRequest,1,3,1))
      [] pc = 5 -> Receive(TraceMessage(RequestVoteRequest,1,3,1))
      [] pc = 6 -> Ready(3)
      [] pc = 7 -> Receive(TraceMessage(RequestVoteResponse,1,1,1))
      [] pc = 8 -> Receive(TraceMessage(RequestVoteResponse,3,1,1))
      [] pc = 9 -> BecomeLeader(1)
      [] pc = 10 -> ClientRequest(1,0)
      [] pc = 11 -> Ready(1)
      [] pc = 12 -> Timeout(2)
      [] pc = 13 -> Timeout(2)
      [] pc = 14 -> RequestVote(2,2)
      [] pc = 15 -> RequestVote(2,3)
      [] pc = 16 -> Ready(2)
      [] pc = 17 -> Receive(TraceMessage(RequestVoteRequest,2,3,2))
      [] pc = 18 -> Receive(TraceMessage(RequestVoteRequest,2,3,2))
      [] pc = 19 -> Ready(3)
      [] pc = 20 -> Receive(TraceMessage(RequestVoteResponse,2,2,2))
      [] pc = 21 -> Receive(TraceMessage(RequestVoteResponse,3,2,2))
      [] pc = 22 -> BecomeLeader(2)
      [] pc = 23 -> ClientRequest(2,0)
      [] pc = 24 -> Ready(2)
      [] pc = 25 -> StepDownToFollower(1)
      [] pc = 26 -> Timeout(1)
      [] pc = 27 -> Timeout(1)
      [] pc = 28 -> RequestVote(1,1)
      [] pc = 29 -> RequestVote(1,3)
      [] pc = 30 -> Ready(1)
      [] pc = 31 -> Receive(TraceMessage(RequestVoteRequest,1,3,3))
      [] pc = 32 -> Receive(TraceMessage(RequestVoteRequest,1,3,3))
      [] pc = 33 -> Ready(3)
      [] pc = 34 -> Receive(TraceMessage(RequestVoteResponse,1,1,3))
      [] pc = 35 -> Receive(TraceMessage(RequestVoteResponse,3,1,3))
      [] pc = 36 -> BecomeLeader(1)
      [] pc = 37 -> ClientRequest(1,0)
      [] pc = 38 -> AppendEntriesToSelf(1)
      [] pc = 39 -> AppendEntries(1,3,<<1,3>>)
      [] pc = 40 -> Ready(1)
      [] pc = 41 -> Receive(TraceMessage(AppendEntriesResponse,1,1,3))
      [] pc = 42 -> Receive(TraceMessage(AppendEntriesRequest,1,3,3))
      [] pc = 43 -> (Receive(TraceMessage(AppendEntriesRequest,1,3,3)) /\ AppendEntriesAlreadyDone(3,1,1,TraceMessage(AppendEntriesRequest,1,3,3)))
      [] pc = 44 -> Ready(3)
      [] pc = 45 -> Receive(TraceMessage(AppendEntriesResponse,3,1,3))
      [] pc = 46 -> AdvanceCommitIndex(1)
      [] pc = 47 -> IF CommitOnFollower THEN AppendEntries(1,3,<<3,3>>) ELSE UNCHANGED vars
      [] pc = 48 -> IF CommitOnFollower THEN Ready(1) ELSE UNCHANGED vars
      [] pc = 49 -> IF CommitOnFollower THEN (Receive(TraceMessage(AppendEntriesRequest,1,3,3)) /\ AppendEntriesAlreadyDone(3,1,3,TraceMessage(AppendEntriesRequest,1,3,3))) ELSE UNCHANGED vars
      [] pc = 50 -> IF CommitOnFollower THEN Ready(3) ELSE UNCHANGED vars
      [] pc = 51 -> IF CrashBeforeElection THEN Restart(1) ELSE Ready(1)
      [] pc = 52 -> IF ElectionNode = 2 THEN StepDownToFollower(2) ELSE UNCHANGED vars
      [] pc = 53 -> IF ElectionNode = 2 THEN Timeout(2) ELSE UNCHANGED vars
      [] pc = 54 -> Timeout(ElectionNode)
      [] pc = 55 -> RequestVote(ElectionNode,ElectionNode)
      [] pc = 56 -> RequestVote(ElectionNode,Voter)
      [] pc = 57 -> Ready(ElectionNode)
      [] pc = 58 -> Receive(TraceMessage(RequestVoteRequest,ElectionNode,Voter,4))
      [] pc = 59 -> Receive(TraceMessage(RequestVoteRequest,ElectionNode,Voter,4))
      [] pc = 60 -> Ready(Voter)
      [] pc = 61 -> Receive(TraceMessage(RequestVoteResponse,ElectionNode,ElectionNode,4))
      [] pc = 62 -> Receive(TraceMessage(RequestVoteResponse,Voter,ElectionNode,4))
      [] pc = 63 -> BecomeLeader(ElectionNode)
      [] pc = 64 -> Restart(ElectionNode)
      [] pc = 65 -> Restart(1)
      [] OTHER -> FALSE

TraceNext == TraceAction /\ RecordEvents /\ pc' = pc+1
TraceSpec == TraceInit /\ [][TraceNext]_<<pc, vars>>
             /\ WF_<<pc, vars>>(TraceNext)
EventuallyCompletes == <>(pc = 66)
RefinesProtocol == [][ProtocolNext]_protocolVars

ExpectedPrefix == <<[term |-> 1, type |-> ValueEntry, value |-> [val |-> 0]],
                    [term |-> 3, type |-> ValueEntry, value |-> [val |-> 0]]>>

\* The previous predicate is retained only as a regression oracle.
CreationTermCompleteness ==
    \A i \in Server :
        \A idx \in 1..commitIndex[i] :
            \A l \in {s \in Server : state[s] = Leader} :
                currentTerm[l] > log[i][idx].term => log[l][idx] = log[i][idx]

LateCommitWitness == pc = 47 =>
    /\ currentTerm = <<3, 2, 3>>
    /\ state = <<Leader, Leader, Follower>>
    /\ commitIndex = <<2, 0, 0>>
    /\ log[1] = ExpectedPrefix
    /\ ~CreationTermCompleteness

HistoryRetained == pc >= 47 =>
    [server |-> 1, term |-> 3, entries |-> ExpectedPrefix] \in commitHistory

Completed == pc = 66 =>
    /\ [server |-> ElectionNode, term |-> 4, entries |-> ExpectedPrefix]
         \in electionHistory
    /\ (CommitOnFollower =>
         [server |-> 3, term |-> 3, entries |-> ExpectedPrefix] \in commitHistory)
    /\ (CrashBeforeElection => commitIndex[1] = 0)
====

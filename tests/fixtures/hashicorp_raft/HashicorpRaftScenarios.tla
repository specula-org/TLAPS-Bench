---- MODULE HashicorpRaftScenarios ----
EXTENDS HashicorpRaftRuntime
CONSTANTS A, B, C, V, W, Scenario
VARIABLE step

GrantNew(from, to) ==
    \E m \in DOMAIN messages :
        /\ m.mtype = RequestVoteRequest /\ m.msource = from /\ m.mdest = to
        /\ m.mterm = currentTerm[from]
        /\ HandleRequestVoteRequest(to, m)
        /\ pendingVote'[to] # Nil

GrantSame(from, to) ==
    \E m \in DOMAIN messages :
        /\ m.mtype = RequestVoteRequest /\ m.msource = from /\ m.mdest = to
        /\ m.mterm = currentTerm[from] /\ m.mterm = currentTerm[to]
        /\ HandleRequestVoteRequest(to, m)
        /\ persistedVotedFor'[to] = from

CollectVote(from, to) ==
    \E m \in DOMAIN messages :
        /\ m.mtype = RequestVoteResponse /\ m.msource = from /\ m.mdest = to
        /\ m.mterm = currentTerm[to] /\ m.mvoteGranted
        /\ HandleRequestVoteResponse(to, m)

Deliver(from, to, n, committed) ==
    \E m \in DOMAIN messages :
        /\ m.mtype = AppendEntriesRequest /\ m.msubtype = "replicate"
        /\ m.msource = from /\ m.mdest = to /\ m.mterm = currentTerm[from]
        /\ m.mprevLogIndex + Len(m.mentries) = n /\ m.mcommitIndex = committed
        /\ HandleAppendEntriesRequest(to, m)

Ack(from, to, n) ==
    \E m \in DOMAIN messages :
        /\ m.mtype = AppendEntriesResponse /\ m.msubtype = "replicate"
        /\ m.msource = from /\ m.mdest = to /\ m.mterm = currentTerm[to]
        /\ m.msuccess /\ m.mmatchIndex = n
        /\ HandleReplicateResponse(to, m)

DeliverHeartbeat(from, to) ==
    \E m \in DOMAIN messages :
        /\ m.mtype = AppendEntriesRequest /\ m.msubtype = "heartbeat"
        /\ m.msource = from /\ m.mdest = to /\ m.mterm = currentTerm[from]
        /\ HandleAppendEntriesRequest(to, m)

NoGrant(from, to) ==
    ~\E m \in DOMAIN messages :
        /\ m.mtype = RequestVoteResponse /\ m.msource = from /\ m.mdest = to
        /\ m.mvoteGranted

Trace1 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> ReplicateEntries(A, B)
      [] step = 7 -> Deliver(A, B, 1, 0)
      [] step = 8 -> Ack(B, A, 1)
      [] step = 9 -> AdvanceCommitIndex(A)
      [] step = 10 -> ReplicateEntries(A, B)
      [] step = 11 -> Deliver(A, B, 1, 1)
      [] step = 12 -> Ack(B, A, 1)
      [] step = 13 -> ProposeConfigChange(A, C)
      [] step = 14 -> ReplicateEntries(A, B)
      [] step = 15 -> Deliver(A, B, 2, 1)
      [] step = 16 -> Ack(B, A, 2)
      [] step = 17 -> AdvanceCommitIndex(A)
      [] step = 18 -> ReplicateEntries(A, B)
      [] step = 19 -> Deliver(A, B, 2, 2)
      [] step = 20 -> Ack(B, A, 2)
      [] step = 21 -> ClientRequest(A, W)
      [] step = 22 -> ReplicateEntries(A, B)
      [] step = 23 -> Deliver(A, B, 3, 2)
      [] step = 24 -> Ack(B, A, 3)
      [] step = 25 -> AdvanceCommitIndex(A)
      [] step = 26 -> ReplicateEntries(A, B)
      [] step = 27 -> Deliver(A, B, 3, 3)
      [] step = 28 -> Ack(B, A, 3)
      [] step = 29 -> Crash(A)
      [] step = 30 -> Timeout(B)
      [] step = 31 -> GrantNew(B, A)
      [] step = 32 -> CompletePersistVote(A)
      [] step = 33 -> CollectVote(A, B)
      [] step = 34 -> BecomeLeader(B)
      [] step = 35 -> ClientRequest(B, V)
      [] step = 36 -> ReplicateEntries(B, A)
      [] step = 37 -> Deliver(B, A, 4, 3)
      [] step = 38 -> Ack(A, B, 4)
      [] step = 39 -> AdvanceCommitIndex(B)
      [] step = 40 -> ProposeConfigChange(B, C)
      [] step = 41 -> ReplicateEntries(B, A)
      [] step = 42 -> Deliver(B, A, 5, 4)
      [] step = 43 -> Ack(A, B, 5)
      [] step = 44 -> AdvanceCommitIndex(B)
      [] step = 45 -> ReplicateEntries(B, A)
      [] step = 46 -> Deliver(B, A, 5, 5)
      [] step = 47 -> Ack(A, B, 5)
      [] step = 48 -> Crash(A)
      [] step = 49 -> Crash(B)

Trace2 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> ReplicateEntries(A, B)
      [] step = 7 -> ClientRequest(A, W)
      [] step = 8 -> ReplicateEntries(A, B)
      [] step = 9 -> Deliver(A, B, 2, 0)
      [] step = 10 -> Ack(B, A, 2)
      [] step = 11 -> AdvanceCommitIndex(A)
      [] step = 12 -> ReplicateEntries(A, B)
      [] step = 13 -> Deliver(A, B, 2, 2)
      [] step = 14 -> Ack(B, A, 2)
      [] step = 15 -> Deliver(A, B, 1, 0)

Trace3 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> Crash(B)
      [] step = 3 -> Timeout(C)
      [] step = 4 -> GrantSame(C, B)
      [] step = 5 -> CollectVote(B, C)
      [] step = 6 -> BecomeLeader(C)
      [] step = 7 -> Timeout(A)
      [] step = 8 -> GrantNew(A, B)
      [] step = 9 -> Crash(B)

Trace4 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> ReplicateEntries(A, B)
      [] step = 7 -> Deliver(A, B, 1, 0)
      [] step = 8 -> Ack(B, A, 1)
      [] step = 9 -> AdvanceCommitIndex(A)
      [] step = 10 -> ReplicateEntries(A, B)
      [] step = 11 -> Deliver(A, B, 1, 1)
      [] step = 12 -> Ack(B, A, 1)
      [] step = 13 -> ProposeConfigChange(A, C)
      [] step = 14 -> ReplicateEntries(A, B)
      [] step = 15 -> Deliver(A, B, 2, 1)
      [] step = 16 -> Ack(B, A, 2)
      [] step = 17 -> AdvanceCommitIndex(A)
      [] step = 18 -> ReplicateEntries(A, B)
      [] step = 19 -> Deliver(A, B, 2, 2)
      [] step = 20 -> Ack(B, A, 2)
      [] step = 21 -> Crash(A)
      [] step = 22 -> Timeout(B)
      [] step = 23 -> GrantNew(B, A)
      [] step = 24 -> CompletePersistVote(A)
      [] step = 25 -> CollectVote(A, B)
      [] step = 26 -> BecomeLeader(B)

Trace5 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)

Trace6 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> ReplicateEntries(A, B)
      [] step = 7 -> Deliver(A, B, 1, 0)
      [] step = 8 -> Ack(B, A, 1)
      [] step = 9 -> AdvanceCommitIndex(A)
      [] step = 10 -> ReplicateEntries(A, B)
      [] step = 11 -> Deliver(A, B, 1, 1)
      [] step = 12 -> Ack(B, A, 1)
      [] step = 13 -> ProposeConfigChange(A, A)
      [] step = 14 -> ReplicateEntries(A, B)
      [] step = 15 -> Deliver(A, B, 2, 1)
      [] step = 16 -> Ack(B, A, 2)
      [] step = 17 -> ReplicateEntries(A, C)
      [] step = 18 -> Deliver(A, C, 2, 1)
      [] step = 19 -> Ack(C, A, 2)
      [] step = 20 -> AdvanceCommitIndex(A)

Trace7 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> AdvanceCommitIndex(A)
      [] step = 7 -> Crash(A)
      [] step = 8 -> Timeout(C)
      [] step = 9 -> Timeout(C)
      [] step = 10 -> GrantNew(C, B)
      [] step = 11 -> CompletePersistVote(B)
      [] step = 12 -> CollectVote(B, C)
      [] step = 13 -> BecomeLeader(C)
      [] step = 14 -> ClientRequest(C, W)
      [] step = 15 -> AdvanceCommitIndex(C)

Trace8 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> Crash(B)
      [] step = 3 -> Timeout(C)
      [] step = 4 -> GrantSame(C, B)
      [] step = 5 -> CollectVote(B, C)
      [] step = 6 -> BecomeLeader(C)
      [] step = 7 -> CollectVote(B, A)
      [] step = 8 -> BecomeLeader(A)

Trace9 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> ReplicateEntries(A, B)
      [] step = 7 -> Deliver(A, B, 1, 0)
      [] step = 8 -> Ack(B, A, 1)
      [] step = 9 -> AdvanceCommitIndex(A)
      [] step = 10 -> Timeout(C)
      [] step = 11 -> Timeout(C)
      [] step = 12 -> GrantNew(C, B)
      [] step = 13 -> CompletePersistVote(B)
      [] step = 14 -> CollectVote(B, C)
      [] step = 15 -> BecomeLeader(C)
      [] step = 16 -> ClientRequest(C, W)

Trace10 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> CompletePersistVote(B)
      [] step = 3 -> CollectVote(B, A)
      [] step = 4 -> BecomeLeader(A)
      [] step = 5 -> ClientRequest(A, V)
      [] step = 6 -> ReplicateEntries(A, B)
      [] step = 7 -> Deliver(A, B, 1, 0)
      [] step = 8 -> Ack(B, A, 1)
      [] step = 9 -> AdvanceCommitIndex(A)
      [] step = 10 -> ProposeConfigChange(A, C)
      [] step = 11 -> ProposeConfigChange(A, B)

Trace11 ==
    CASE step = 0 -> Timeout(A)
      [] step = 1 -> GrantNew(A, B)
      [] step = 2 -> Timeout(C)
      [] step = 3 -> Timeout(C)
      [] step = 4 -> GrantNew(C, A)
      [] step = 5 -> CompletePersistVote(A)
      [] step = 6 -> CollectVote(A, C)
      [] step = 7 -> BecomeLeader(C)
      [] step = 8 -> SendHeartbeat(C, B)
      [] step = 9 -> DeliverHeartbeat(C, B)
      [] step = 10 -> CompletePersistVote(B)

TraceLength == CASE Scenario = 1 -> 50
                 [] Scenario = 2 -> 16
                 [] Scenario = 3 -> 10
                 [] Scenario = 4 -> 27
                 [] Scenario = 5 -> 2
                 [] Scenario = 6 -> 21
                 [] Scenario = 7 -> 16
                 [] Scenario = 8 -> 9
                 [] Scenario = 9 -> 17
                 [] Scenario = 10 -> 12
                 [] Scenario = 11 -> 11

StepAction == CASE Scenario = 1 -> Trace1
                [] Scenario = 2 -> Trace2
                [] Scenario = 3 -> Trace3
                [] Scenario = 4 -> Trace4
                [] Scenario = 5 -> Trace5
                [] Scenario = 6 -> Trace6
                [] Scenario = 7 -> Trace7
                [] Scenario = 8 -> Trace8
                [] Scenario = 9 -> Trace9
                [] Scenario = 10 -> Trace10
                [] Scenario = 11 -> Trace11

ExpectedFinal == CASE Scenario = 1 -> /\ Cardinality(electionHistory) = 2
          /\ latestConfig[A] = Server /\ latestConfig[B] = Server
          /\ Len(log[A]) = 5 /\ log[A] = log[B]
          /\ commitIndex[A] = 0 /\ commitIndex[B] = 0
          /\ \E c \in commitHistory : Len(c.entries) = 5
                   [] Scenario = 2 -> /\ Len(log[B]) = 2
          /\ \E m \in DOMAIN messages :
                /\ m.mtype = AppendEntriesResponse /\ m.msubtype = "replicate"
                /\ m.msource = B /\ m.mdest = A /\ m.msuccess
                /\ m.mmatchIndex = 1
                   [] Scenario = 3 -> /\ votedFor[B] = Nil
          /\ persistedVoteTerm[B] < currentTerm[B]
          /\ NoGrant(B, A)
          /\ state[C] = Leader /\ Cardinality(electionHistory) = 1
                   [] Scenario = 4 -> /\ state[B] = Leader /\ currentTerm[B] = 2
          /\ log[B][commitIndex[B]].term = 1
          /\ ~ENABLED ProposeConfigChange(B, C)
                   [] Scenario = 5 -> /\ pendingVote[B] # Nil
          /\ persistedVoteTerm[B] < currentTerm[B]
          /\ NoGrant(B, A)
                   [] Scenario = 6 -> /\ state[A] = Follower
          /\ A \notin committedConfig[A]
          /\ commitIndex[A] = 2
          /\ \E c \in commitHistory : c.server = A /\ Len(c.entries) = 2
                   [] Scenario = 7 -> TRUE
                   [] Scenario = 8 -> TRUE
                   [] Scenario = 9 -> TRUE
                   [] Scenario = 10 -> TRUE
                   [] Scenario = 11 -> /\ currentTerm[B] = 2 /\ persistedVoteTerm[B] = 1 /\ votedFor[B] = Nil /\ pendingVote[B] = Nil

TraceInit == Init /\ step = 0
TraceNext == /\ step < TraceLength /\ StepAction /\ RecordEvents /\ step' = step + 1
TraceVars == <<vars, step>>
TraceSpec == TraceInit /\ [][TraceNext]_TraceVars
Completed == step = TraceLength => ExpectedFinal
====

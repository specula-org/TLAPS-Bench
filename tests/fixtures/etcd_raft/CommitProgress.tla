---- MODULE CommitProgress ----
EXTENDS etcd_raftDefs
CONSTANT EntryIndex
VARIABLE pc

Message(ty, src, dst) ==
    CHOOSE m \in DOMAIN messages :
        m.mtype = ty /\ m.msource = src /\ m.mdest = dst

PrefixAction ==
    CASE pc = 0 -> Timeout(1)
      [] pc = 1 -> RequestVote(1,1)
      [] pc = 2 -> RequestVote(1,2)
      [] pc = 3 -> Ready(1)
      [] pc = 4 -> Receive(Message(RequestVoteRequest,1,2))
      [] pc = 5 -> Receive(Message(RequestVoteRequest,1,2))
      [] pc = 6 -> Ready(2)
      [] pc = 7 -> Receive(Message(RequestVoteResponse,1,1))
      [] pc = 8 -> Receive(Message(RequestVoteResponse,2,1))
      [] pc = 9 -> BecomeLeader(1)
      [] pc = 10 -> ClientRequest(1,0)
      [] pc = 11 -> ClientRequest(1,0)
      [] pc = 12 -> Ready(1)
      [] OTHER -> FALSE

PrefixNext == PrefixAction /\ RecordEvents /\ pc' = pc + 1
NetworkIdle == messages = EmptyBag /\ pendingMessages = EmptyBag

LoopNext ==
    /\ pc = 13 /\ UNCHANGED pc
    /\ \/ \E j \in {1,2} : Ready(j) /\ RecordEvents
       \/ /\ NetworkIdle /\ SendThrough(1,2,EntryIndex)
       \/ /\ NetworkIdle /\ matchIndex[1][1] < EntryIndex
          /\ AppendEntriesToSelf(1) /\ RecordEvents
       \/ /\ \E m \in DOMAIN messages : Receive(m)
          /\ RecordEvents
       \/ AdvanceCommitIndex(1) /\ RecordEvents

TestSpec == Init /\ pc = 0 /\ [][PrefixNext \/ LoopNext]_<<vars,pc>>
            /\ WF_<<vars,pc>>(PrefixNext)

ProgressClaim == (StableReplication(1,{1,2}) /\ ReplicationFairness(1,{1,2},EntryIndex)) => CommitProgress(1,EntryIndex)
NonVacuous == <> (pc = 13 /\ CurrentTermEntry(1,EntryIndex))

\* A deterministic fair witness must satisfy the actual liveness assumptions.
WitnessAction ==
    CASE pc < 13 -> PrefixAction
      [] pc = 13 -> AppendEntriesToSelf(1)
      [] pc = 14 -> Ready(1)
      [] pc = 15 -> Receive(Message(AppendEntriesResponse,1,1))
      [] pc = 16 -> AppendEntries(1,2,<<1,3>>)
      [] pc = 17 -> Ready(1)
      [] pc = 18 -> Receive(Message(AppendEntriesRequest,1,2))
      [] pc = 19 -> /\ Receive(Message(AppendEntriesRequest,1,2))
                     /\ AppendEntriesAlreadyDone(2,1,1,Message(AppendEntriesRequest,1,2))
      [] pc = 20 -> Ready(2)
      [] pc = 21 -> Receive(Message(AppendEntriesResponse,2,1))
      [] pc = 22 -> AdvanceCommitIndex(1)
      [] pc = 23 -> Ready(1)
      [] OTHER -> FALSE
WitnessNext == WitnessAction /\ RecordEvents /\ pc' = pc+1
WitnessSpec == Init /\ pc = 0 /\ [][WitnessNext]_<<vars,pc>>
               /\ WF_<<vars,pc>>(WitnessNext)
WitnessAssumptions == StableReplication(1,{1,2}) /\ ReplicationFairness(1,{1,2},EntryIndex)
WitnessCompletes == <> (pc = 24 /\ commitIndex[1] = 2)
====

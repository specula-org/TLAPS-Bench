--------------------------------- MODULE etcd_raftDefs ---------------------------------

EXTENDS etcd_raftModel

MaxOrZero(s) == IF s = {} THEN 0 ELSE Max(s)

Committed(i) == SubSeq(log[i],1,commitIndex[i])

LogInv ==
    \A i, j \in Server :
        \/ IsPrefix(Committed(i),Committed(j)) 
        \/ IsPrefix(Committed(j),Committed(i))

MoreThanOneLeaderInv ==
    \A i,j \in Server :
        (/\ currentTerm[i] = currentTerm[j]
         /\ state[i] = Leader
         /\ state[j] = Leader)
        => i = j

ElectionSafetyInv ==
    \A i \in Server :
        state[i] = Leader =>
        \A j \in Server :
            MaxOrZero({n \in DOMAIN log[i] : log[i][n].term = currentTerm[i]}) >=
            MaxOrZero({n \in DOMAIN log[j] : log[j][n].term = currentTerm[i]})

LogMatchingInv ==
    \A i, j \in Server :
        \A n \in (1..Len(log[i])) \cap (1..Len(log[j])) :
            log[i][n].term = log[j][n].term =>
            SubSeq(log[i],1,n) = SubSeq(log[j],1,n)

QuorumLogInv ==
    \A i \in Server :
    \A S \in Quorum(GetConfig(i)) :
        \E j \in S :
            IsPrefix(Committed(i), log[j])

MoreUpToDateCorrectInv ==
    \A i \in Server :
       (\E Q \in Quorum(GetConfig(i)) :
           \A j \in Q :
               \/ LastTerm(log[i]) > LastTerm(log[j])
               \/ /\ LastTerm(log[i]) = LastTerm(log[j])
                  /\ Len(log[i]) >= Len(log[j])) =>
       \A j \in Server : IsPrefix(Committed(j), log[i])

LeaderCompletenessInv ==
    \A c \in commitHistory, e \in electionHistory :
        c.term < e.term => IsPrefix(c.entries, e.entries)

CommittedIsDurableInv ==
    \A i \in Server :
        state[i] = Leader => commitIndex[i] <= durableState[i].log

StableReplicationNext(l, Q) ==
    /\ RecordEvents
    /\ currentTerm'[l] = currentTerm[l]
    /\ state'[l] = Leader
    /\ \/ ReplicationNext
       \/ \E i \in Server \ Q : Restart(i)
       \/ \E i \in Server \ {l} : StepDownToFollower(i)
       \/ \E m \in DOMAIN messages :
           /\ messages[m] = 1
           /\ \/ DuplicateMessage(m)
              \/ /\ ~(m.msource \in Q /\ m.mdest \in Q)
                 /\ DropMessage(m)

StableReplication(l, Q) ==
    /\ l \in Q
    /\ <>[] (state[l] = Leader /\ \A j \in Q : currentTerm[j] <= currentTerm[l])
    /\ <>[][StableReplicationNext(l, Q)]_vars

SendThrough(l, j, n) ==
    /\ n \in 1..Len(log[l])
    /\ matchIndex[l][j] < n
    /\ AppendEntries(l, j, <<matchIndex[l][j] + 1, n + 1>>)
    /\ RecordEvents

ReceiveThrough(l, j, n) ==
    /\ \E m \in DOMAIN messages :
        /\ m.mtype = AppendEntriesRequest
        /\ m.msource = l /\ m.mdest = j
        /\ m.mterm = currentTerm[l]
        /\ m.msubtype = "app"
        /\ m.mprevLogIndex < n
        /\ m.mprevLogIndex + Len(m.mentries) >= n
        /\ Receive(m)
    /\ RecordEvents

ReceiveAckThrough(l, j, n) ==
    /\ \E m \in DOMAIN messages :
        /\ m.mtype = AppendEntriesResponse
        /\ m.msource = j /\ m.mdest = l
        /\ m.mterm = currentTerm[l]
        /\ m.msuccess /\ m.mmatchIndex >= n
        /\ Receive(m)
    /\ RecordEvents

ReplicationFairness(l, Q, n) ==
    /\ \A j \in Q : WF_vars(Ready(j) /\ RecordEvents)
    /\ WF_vars(matchIndex[l][l] < n /\ AppendEntriesToSelf(l) /\ RecordEvents)
    /\ WF_vars(AdvanceCommitIndex(l) /\ RecordEvents)
    /\ \A j \in Q : SF_vars(ReceiveAckThrough(l, j, n))
    /\ \A j \in Q \ {l} :
        /\ WF_vars(SendThrough(l, j, n))
        /\ SF_vars(ReceiveThrough(l, j, n))

LiveSpec(l, Q, n) ==
    /\ Spec
    /\ StableReplication(l, Q)
    /\ ReplicationFairness(l, Q, n)

CurrentTermEntry(l, n) ==
    /\ state[l] = Leader
    /\ n \in 1..Len(log[l])
    /\ log[l][n].term = currentTerm[l]

CommitProgress(l, n) == <>[] (CurrentTermEntry(l, n) ~> commitIndex[l] >= n)

===============================================================================


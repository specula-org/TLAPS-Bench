---- MODULE HashicorpRaftRuntime ----

EXTENDS Naturals, FiniteSets, Sequences, Bags

CONSTANT Server, Values

CONSTANTS Follower,
          Candidate,
          Leader

CONSTANT Nil

CONSTANTS ValueEntry,
          ConfigEntry

CONSTANTS RequestVoteRequest,
          RequestVoteResponse,
          AppendEntriesRequest,
          AppendEntriesResponse

ASSUME ServerDomain == IsFiniteSet(Server) /\ Server # {}
ASSUME ValueDomain == Values # {}
ASSUME SentinelDomain == Nil \notin Server \cup Values
ASSUME RoleDomain == Cardinality({Follower, Candidate, Leader}) = 3
ASSUME EntryDomain == ValueEntry # ConfigEntry
ASSUME MessageDomain == Cardinality({RequestVoteRequest, RequestVoteResponse,
                                     AppendEntriesRequest, AppendEntriesResponse}) = 4

VARIABLE currentTerm
VARIABLE votedFor
VARIABLE log

VARIABLE state
VARIABLE commitIndex

VARIABLE nextIndex
VARIABLE matchIndex

VARIABLE votesGranted

VARIABLE messages

VARIABLE leaseContact

VARIABLE diskBlocked

VARIABLE committedConfig
VARIABLE committedConfigIndex, latestConfigIndex
VARIABLE latestConfig

VARIABLE persistedTerm
VARIABLE persistedVoteTerm
VARIABLE persistedVotedFor
VARIABLE pendingVote

serverVars   == <<currentTerm, votedFor, state>>
logVars      == <<log, commitIndex>>
leaderVars   == <<nextIndex, matchIndex>>
candidateVars == <<votesGranted>>
leaseVars    == <<leaseContact>>
diskVars     == <<diskBlocked>>
configVars   == <<committedConfig, latestConfig, committedConfigIndex, latestConfigIndex>>
persistVars  == <<persistedTerm, persistedVoteTerm, persistedVotedFor, pendingVote>>

protocolVars == <<serverVars, logVars, leaderVars, candidateVars, messages,
          leaseVars, diskVars, configVars, persistVars>>

Min(a, b) == IF a <= b THEN a ELSE b
Max(a, b) == IF a >= b THEN a ELSE b

SetMax(S) == CHOOSE x \in S : \A y \in S : x >= y

LastLogIndex(i) == Len(log[i])
LastLogTerm(i)  == IF Len(log[i]) > 0 THEN log[i][Len(log[i])].term ELSE 0
LogTerm(i, idx) == IF idx > 0 /\ idx <= Len(log[i]) THEN log[i][idx].term ELSE 0

IsQuorum(S, voters) == Cardinality(S) * 2 > Cardinality(voters)

LogUpToDate(cLastTerm, cLastIdx, vLastTerm, vLastIdx) ==
    \/ cLastTerm > vLastTerm
    \/ (cLastTerm = vLastTerm /\ cLastIdx >= vLastIdx)

MergeEntries(existingLog, prevIdx, entries) ==
    IF Len(entries) = 0 THEN existingLog
    ELSE LET

        firstNew == CHOOSE k \in 1..(Len(entries) + 1) :
            /\ \A j \in 1..(k-1) :
                /\ prevIdx + j <= Len(existingLog)
                /\ existingLog[prevIdx + j].term = entries[j].term
            /\ \/ k = Len(entries) + 1
               \/ prevIdx + k > Len(existingLog)
               \/ existingLog[prevIdx + k].term /= entries[k].term
    IN IF firstNew = Len(entries) + 1
       THEN existingLog
       ELSE SubSeq(existingLog, 1, prevIdx + firstNew - 1)
            \o SubSeq(entries, firstNew, Len(entries))

LatestConfigIn(logSeq, maxIdx) ==
    LET bound == Min(maxIdx, Len(logSeq))
        indices == {k \in 1..bound : logSeq[k].type = ConfigEntry}
    IN IF indices = {} THEN Server
       ELSE logSeq[SetMax(indices)].config

ConfigIndices(entries) == {k \in 1..Len(entries) : entries[k].type = ConfigEntry}
LastConfigIndex(entries) == IF ConfigIndices(entries) = {} THEN 0 ELSE SetMax(ConfigIndices(entries))
PreviousConfigIndex(entries) ==
    LET older == ConfigIndices(entries) \ {LastConfigIndex(entries)}
    IN IF older = {} THEN 0 ELSE SetMax(older)
ConfigAt(entries, k) == IF k = 0 THEN Server ELSE entries[k].config

Send(m) == messages' = messages (+) SetToBag({m})
SendAll(ms) == messages' = messages (+) SetToBag(ms)
Discard(m) == messages' = messages (-) SetToBag({m})
Reply(resp, req) ==
    messages' = (messages (-) SetToBag({req})) (+) SetToBag({resp})

ProtocolInit ==
    /\ currentTerm      = [s \in Server |-> 0]
    /\ votedFor          = [s \in Server |-> Nil]
    /\ log               = [s \in Server |-> <<>>]
    /\ state             = [s \in Server |-> Follower]
    /\ commitIndex       = [s \in Server |-> 0]
    /\ nextIndex         = [s \in Server |-> [t \in Server |-> 1]]
    /\ matchIndex        = [s \in Server |-> [t \in Server |-> 0]]
    /\ votesGranted      = [s \in Server |-> {}]
    /\ messages          = EmptyBag
    /\ leaseContact      = [s \in Server |-> {}]
    /\ diskBlocked       = [s \in Server |-> FALSE]
    /\ committedConfig   = [s \in Server |-> Server]
    /\ latestConfig      = [s \in Server |-> Server]
    /\ committedConfigIndex = [s \in Server |-> 0]
    /\ latestConfigIndex = [s \in Server |-> 0]
    /\ persistedTerm     = [s \in Server |-> 0]
    /\ persistedVoteTerm = [s \in Server |-> 0]
    /\ persistedVotedFor = [s \in Server |-> Nil]
    /\ pendingVote       = [s \in Server |-> Nil]

Timeout(i) ==
    /\ state[i] \in {Follower, Candidate}

    /\ i \in latestConfig[i]

    /\ pendingVote[i] = Nil
    /\ LET newTerm == currentTerm[i] + 1
       IN

       /\ currentTerm' = [currentTerm EXCEPT ![i] = newTerm]
       /\ state' = [state EXCEPT ![i] = Candidate]
       /\ votedFor' = [votedFor EXCEPT ![i] = i]
       /\ votesGranted' = [votesGranted EXCEPT ![i] = {i}]

       /\ persistedTerm' = [persistedTerm EXCEPT ![i] = newTerm]
       /\ persistedVoteTerm' = [persistedVoteTerm EXCEPT ![i] = newTerm]
       /\ persistedVotedFor' = [persistedVotedFor EXCEPT ![i] = i]
       /\ UNCHANGED pendingVote

       /\ SendAll({[mtype        |-> RequestVoteRequest,
                    mterm        |-> newTerm,
                    mlastLogTerm |-> LastLogTerm(i),
                    mlastLogIndex |-> LastLogIndex(i),
                    msource      |-> i,
                    mdest        |-> j] : j \in latestConfig[i] \ {i}})
    /\ UNCHANGED <<log, commitIndex, leaderVars, leaseVars, diskVars, configVars>>

HandleRequestVoteRequest(i, m) ==
    /\ m.mtype = RequestVoteRequest
    /\ m.mdest = i
    /\ pendingVote[i] = Nil
    /\ m.msource \in latestConfig[i]
    /\ LET mterm    == m.mterm

           logOk    == LogUpToDate(m.mlastLogTerm, m.mlastLogIndex,
                                   LastLogTerm(i), LastLogIndex(i))

           canGrant == /\ logOk
                       /\ \/ mterm > currentTerm[i]
                          \/ /\ mterm = currentTerm[i]
                             /\ votedFor[i] \in {Nil, m.msource}
       IN
       \/

          /\ state[i] = Follower
          /\ Reply([mtype        |-> RequestVoteResponse,
                    mterm        |-> currentTerm[i],
                    mvoteGranted |-> FALSE,
                    msource      |-> i,
                    mdest        |-> m.msource], m)
          /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars, persistVars>>

       \/

          /\ \/ mterm < currentTerm[i]
             \/ /\ mterm >= currentTerm[i]
                /\ ~canGrant
          /\ Reply([mtype        |-> RequestVoteResponse,
                    mterm        |-> Max(currentTerm[i], mterm),
                    mvoteGranted |-> FALSE,
                    msource      |-> i,
                    mdest        |-> m.msource], m)

          /\ IF mterm > currentTerm[i]
             THEN /\ currentTerm' = [currentTerm EXCEPT ![i] = mterm]
                  /\ votedFor' = [votedFor EXCEPT ![i] = Nil]
                  /\ state' = [state EXCEPT ![i] = Follower]
                  /\ persistedTerm' = [persistedTerm EXCEPT ![i] = mterm]
                  /\ UNCHANGED <<persistedVoteTerm, persistedVotedFor, pendingVote>>
             ELSE UNCHANGED <<serverVars, persistVars>>
          /\ UNCHANGED <<logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars>>

       \/

          /\ mterm = currentTerm[i]
          /\ canGrant
          /\ votedFor' = [votedFor EXCEPT ![i] = m.msource]
          /\ persistedVoteTerm' = [persistedVoteTerm EXCEPT ![i] = mterm]
          /\ persistedVotedFor' = [persistedVotedFor EXCEPT ![i] = m.msource]
          /\ Reply([mtype        |-> RequestVoteResponse,
                    mterm        |-> currentTerm[i],
                    mvoteGranted |-> TRUE,
                    msource      |-> i,
                    mdest        |-> m.msource], m)
          /\ UNCHANGED <<currentTerm, state, persistedTerm, pendingVote>>
          /\ UNCHANGED <<logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars>>

       \/

          /\ mterm > currentTerm[i]
          /\ canGrant
          /\ currentTerm' = [currentTerm EXCEPT ![i] = mterm]
          /\ votedFor' = [votedFor EXCEPT ![i] = m.msource]
          /\ state' = [state EXCEPT ![i] = Follower]
          /\ persistedTerm' = [persistedTerm EXCEPT ![i] = mterm]
          /\ pendingVote' = [pendingVote EXCEPT ![i] =
                [candidate |-> m.msource, term |-> mterm]]
          /\ UNCHANGED <<persistedVoteTerm, persistedVotedFor>>

          /\ Discard(m)
          /\ UNCHANGED <<logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars>>

CompletePersistVote(i) ==
    /\ pendingVote[i] /= Nil
    /\ persistedVoteTerm' = [persistedVoteTerm EXCEPT ![i] = pendingVote[i].term]
    /\ persistedVotedFor' = [persistedVotedFor EXCEPT ![i] = pendingVote[i].candidate]
    /\ pendingVote' = [pendingVote EXCEPT ![i] = Nil]
    /\ Send([mtype        |-> RequestVoteResponse,
             mterm        |-> pendingVote[i].term,
             mvoteGranted |-> TRUE,
             msource      |-> i,
             mdest        |-> pendingVote[i].candidate])
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                   leaseVars, diskVars, configVars, persistedTerm>>

HandleRequestVoteResponse(i, m) ==
    /\ m.mtype = RequestVoteResponse
    /\ m.mdest = i
    /\ state[i] = Candidate
    /\ IF m.mterm > currentTerm[i]
       THEN /\ currentTerm' = [currentTerm EXCEPT ![i] = m.mterm]
            /\ votedFor' = [votedFor EXCEPT ![i] = Nil]
            /\ state' = [state EXCEPT ![i] = Follower]
            /\ persistedTerm' = [persistedTerm EXCEPT ![i] = m.mterm]
            /\ UNCHANGED <<votesGranted, persistedVoteTerm, persistedVotedFor, pendingVote>>
       ELSE /\ votesGranted' = IF m.mterm = currentTerm[i] /\ m.mvoteGranted
                               THEN [votesGranted EXCEPT ![i] = @ \cup {m.msource}]
                               ELSE votesGranted
            /\ UNCHANGED <<serverVars, persistVars>>
    /\ Discard(m)
    /\ UNCHANGED <<logVars, leaderVars, leaseVars, diskVars, configVars>>

BecomeLeader(i) ==
    /\ state[i] = Candidate
    /\ IsQuorum(votesGranted[i] \cap latestConfig[i], latestConfig[i])
    /\ state' = [state EXCEPT ![i] = Leader]

    /\ nextIndex'  = [nextIndex  EXCEPT ![i] = [j \in Server |-> LastLogIndex(i) + 1]]
    /\ matchIndex' = [matchIndex EXCEPT ![i] = [j \in Server |-> 0]]
    /\ leaseContact' = [leaseContact EXCEPT ![i] = {}]
    /\ UNCHANGED <<currentTerm, votedFor, logVars, candidateVars, messages,
                   diskVars, configVars, persistVars>>

ClientRequest(i, value) ==
    /\ state[i] = Leader
    /\ ~diskBlocked[i]
    /\ LET entry == [term |-> currentTerm[i], type |-> ValueEntry, config |-> {}, value |-> value]
       IN log' = [log EXCEPT ![i] = Append(@, entry)]
    /\ UNCHANGED <<serverVars, commitIndex, leaderVars, candidateVars, messages,
                   leaseVars, diskVars, configVars, persistVars>>

ProposeConfigChange(i, s) ==
    /\ state[i] = Leader
    /\ ~diskBlocked[i]
    /\ committedConfigIndex[i] = latestConfigIndex[i]
    /\ commitIndex[i] > 0
    /\ log[i][commitIndex[i]].term = currentTerm[i]
    /\ \/ /\ s \notin latestConfig[i] /\ s \in Server
       \/ /\ s \in latestConfig[i] /\ Cardinality(latestConfig[i]) > 1
    /\ LET newConfig == IF s \in latestConfig[i]
                        THEN latestConfig[i] \ {s}
                        ELSE latestConfig[i] \cup {s}
           entry == [term |-> currentTerm[i], type |-> ConfigEntry,
                     config |-> newConfig, value |-> Nil]
       IN /\ log' = [log EXCEPT ![i] = Append(@, entry)]
          /\ latestConfig' = [latestConfig EXCEPT ![i] = newConfig]
          /\ latestConfigIndex' = [latestConfigIndex EXCEPT ![i] = Len(log'[i])]
          /\ matchIndex' = [matchIndex EXCEPT ![i] =
                [j \in Server |-> IF j \in newConfig \cap latestConfig[i]
                                  THEN matchIndex[i][j] ELSE 0]]
    /\ UNCHANGED <<serverVars, commitIndex, nextIndex, candidateVars, messages,
                   leaseVars, diskVars, committedConfig, committedConfigIndex, persistVars>>

ReplicateEntries(i, j) ==
    /\ state[i] = Leader
    /\ i /= j
    /\ ~diskBlocked[i]
    /\ LET prevIdx  == nextIndex[i][j] - 1
           prevTerm == LogTerm(i, prevIdx)

           lastIdx  == LastLogIndex(i)
           entries  == IF nextIndex[i][j] > lastIdx THEN <<>>
                       ELSE SubSeq(log[i], nextIndex[i][j], lastIdx)
       IN Send([mtype        |-> AppendEntriesRequest,
                msubtype     |-> "replicate",
                mterm        |-> currentTerm[i],
                mprevLogIndex |-> prevIdx,
                mprevLogTerm |-> prevTerm,
                mentries     |-> entries,
                mcommitIndex |-> commitIndex[i],
                msource      |-> i,
                mdest        |-> j])
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                   leaseVars, diskVars, configVars, persistVars>>

SendHeartbeat(i, j) ==
    /\ state[i] = Leader
    /\ i /= j

    /\ Send([mtype        |-> AppendEntriesRequest,
             msubtype     |-> "heartbeat",
             mterm        |-> currentTerm[i],
             mprevLogIndex |-> 0,
             mprevLogTerm |-> 0,
             mentries     |-> <<>>,
             mcommitIndex |-> 0,
             msource      |-> i,
             mdest        |-> j])
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                   leaseVars, diskVars, configVars, persistVars>>

HandleAppendEntriesRequest(i, m) ==
    /\ m.mtype = AppendEntriesRequest
    /\ m.mdest = i
    /\ (pendingVote[i] = Nil \/ m.msubtype = "heartbeat")
    /\ LET mterm   == m.mterm

           logOk   == \/ m.mprevLogIndex = 0
                      \/ /\ m.mprevLogIndex > 0
                         /\ m.mprevLogIndex <= LastLogIndex(i)
                         /\ LogTerm(i, m.mprevLogIndex) = m.mprevLogTerm
       IN
       \/
          /\ mterm < currentTerm[i]
          /\ Reply([mtype        |-> AppendEntriesResponse,
                    msubtype     |-> m.msubtype,
                    mterm        |-> currentTerm[i],
                    msuccess     |-> FALSE,
                    mmatchIndex  |-> 0,
                    msource      |-> i,
                    mdest        |-> m.msource], m)
          /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars, persistVars>>

       \/
          /\ mterm >= currentTerm[i]
          /\ ~logOk
          /\ Reply([mtype        |-> AppendEntriesResponse,
                    msubtype     |-> m.msubtype,
                    mterm        |-> mterm,
                    msuccess     |-> FALSE,
                    mmatchIndex  |-> 0,
                    msource      |-> i,
                    mdest        |-> m.msource], m)

          /\ currentTerm' = [currentTerm EXCEPT ![i] = mterm]
          /\ state' = [state EXCEPT ![i] = Follower]
          /\ votedFor' = IF mterm > currentTerm[i]
                         THEN [votedFor EXCEPT ![i] = Nil]
                         ELSE votedFor
          /\ IF mterm > currentTerm[i]
             THEN persistedTerm' = [persistedTerm EXCEPT ![i] = mterm]
             ELSE UNCHANGED persistedTerm
          /\ UNCHANGED <<logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars,
                         persistedVoteTerm, persistedVotedFor, pendingVote>>

       \/
          /\ mterm >= currentTerm[i]
          /\ logOk
          /\ LET

                 newLog == MergeEntries(log[i], m.mprevLogIndex, m.mentries)
                 newLastIdx == Len(newLog)
                 newLatest == LastConfigIndex(newLog)
                 priorConfig == PreviousConfigIndex(newLog)

                 newCommitIdx == IF m.mcommitIndex > commitIndex[i]
                                 THEN Min(m.mcommitIndex, newLastIdx)
                                 ELSE commitIndex[i]
             IN
             /\ log' = [log EXCEPT ![i] = newLog]
             /\ commitIndex' = [commitIndex EXCEPT ![i] = newCommitIdx]

             /\ latestConfig' = [latestConfig EXCEPT ![i] = ConfigAt(newLog, newLatest)]
             /\ latestConfigIndex' = [latestConfigIndex EXCEPT ![i] = newLatest]
             /\ committedConfigIndex' = [committedConfigIndex EXCEPT ![i] =
                   IF newLatest <= newCommitIdx THEN newLatest
                   ELSE Max(priorConfig, Min(committedConfigIndex[i], newLatest))]
             /\ committedConfig' = [committedConfig EXCEPT ![i] =
                   ConfigAt(newLog, committedConfigIndex'[i])]
             /\ Reply([mtype        |-> AppendEntriesResponse,
                       msubtype     |-> m.msubtype,
                       mterm        |-> mterm,
                       msuccess     |-> TRUE,
                       mmatchIndex  |-> m.mprevLogIndex + Len(m.mentries),
                       msource      |-> i,
                       mdest        |-> m.msource], m)

          /\ currentTerm' = [currentTerm EXCEPT ![i] = mterm]
          /\ state' = [state EXCEPT ![i] = Follower]
          /\ votedFor' = IF mterm > currentTerm[i]
                         THEN [votedFor EXCEPT ![i] = Nil]
                         ELSE votedFor
          /\ IF mterm > currentTerm[i]
             THEN persistedTerm' = [persistedTerm EXCEPT ![i] = mterm]
             ELSE UNCHANGED persistedTerm
          /\ UNCHANGED <<leaderVars, candidateVars, leaseVars, diskVars,
                         persistedVoteTerm, persistedVotedFor, pendingVote>>

HandleReplicateResponse(i, m) ==
    /\ m.mtype = AppendEntriesResponse
    /\ m.msubtype = "replicate"
    /\ m.mdest = i
    /\ state[i] = Leader
    /\ \/

          /\ m.mterm > currentTerm[i]
          /\ currentTerm' = [currentTerm EXCEPT ![i] = m.mterm]
          /\ state' = [state EXCEPT ![i] = Follower]
          /\ votedFor' = [votedFor EXCEPT ![i] = Nil]
          /\ persistedTerm' = [persistedTerm EXCEPT ![i] = m.mterm]
          /\ leaseContact' = [leaseContact EXCEPT ![i] = {}]
          /\ Discard(m)
          /\ UNCHANGED <<logVars, leaderVars, candidateVars,
                         diskVars, configVars, persistedVoteTerm, persistedVotedFor, pendingVote>>

       \/
          /\ m.mterm = currentTerm[i]
          /\ IF m.msuccess
             THEN
                  /\ nextIndex'  = [nextIndex  EXCEPT ![i][m.msource] = Max(nextIndex[i][m.msource], m.mmatchIndex + 1)]
                  /\ matchIndex' = [matchIndex EXCEPT ![i][m.msource] = Max(matchIndex[i][m.msource], m.mmatchIndex)]

                  /\ leaseContact' = [leaseContact EXCEPT ![i] = @ \cup {m.msource}]
             ELSE
                  /\ nextIndex' = [nextIndex EXCEPT ![i][m.msource] = Max(1, nextIndex[i][m.msource] - 1)]
                  /\ UNCHANGED <<matchIndex, leaseContact>>
          /\ Discard(m)
          /\ UNCHANGED <<serverVars, logVars, candidateVars,
                         diskVars, configVars, persistVars>>

       \/
          /\ m.mterm < currentTerm[i]
          /\ Discard(m)
          /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                         leaseVars, diskVars, configVars, persistVars>>

HandleHeartbeatResponse(i, m) ==
    /\ m.mtype = AppendEntriesResponse
    /\ m.msubtype = "heartbeat"
    /\ m.mdest = i
    /\ state[i] = Leader

    /\ leaseContact' = [leaseContact EXCEPT ![i] = @ \cup {m.msource}]
    /\ Discard(m)
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                   diskVars, configVars, persistVars>>

AdvanceCommitIndex(i) ==
    /\ state[i] = Leader
    /\ LET Agree(idx) == {i} \cup {s \in Server : matchIndex[i][s] >= idx}
           agreeIdxs == {idx \in (commitIndex[i]+1)..LastLogIndex(i) :
                          /\ IsQuorum(Agree(idx) \cap latestConfig[i], latestConfig[i])
                          /\ log[i][idx].term = currentTerm[i]}
       IN /\ agreeIdxs /= {}
          /\ LET newCommitIdx == SetMax(agreeIdxs)
             IN /\ commitIndex' = [commitIndex EXCEPT ![i] = newCommitIdx]
                /\ committedConfigIndex' = [committedConfigIndex EXCEPT ![i] =
                       IF latestConfigIndex[i] <= newCommitIdx
                       THEN latestConfigIndex[i] ELSE committedConfigIndex[i]]
                /\ committedConfig' = [committedConfig EXCEPT ![i] =
                       ConfigAt(log[i], committedConfigIndex'[i])]
                /\ state' = IF i \in committedConfig'[i]
                            THEN state ELSE [state EXCEPT ![i] = Follower]
    /\ UNCHANGED <<currentTerm, votedFor, log, leaderVars, candidateVars, messages,
                   leaseVars, diskVars, latestConfig, latestConfigIndex, persistVars>>

CheckLeaderLease(i) ==
    /\ state[i] = Leader
    /\ LET contacted == leaseContact[i] \cup {i}
           voters    == latestConfig[i]
       IN
       /\ IF IsQuorum(contacted \cap voters, voters)
          THEN
               /\ UNCHANGED state
               /\ leaseContact' = [leaseContact EXCEPT ![i] = {}]
          ELSE
               /\ state' = [state EXCEPT ![i] = Follower]
               /\ leaseContact' = [leaseContact EXCEPT ![i] = {}]
    /\ UNCHANGED <<currentTerm, votedFor, logVars, leaderVars, candidateVars,
                   messages, diskVars, configVars, persistVars>>

DiskBlock(i) ==
    /\ ~diskBlocked[i]
    /\ diskBlocked' = [diskBlocked EXCEPT ![i] = TRUE]
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars, messages,
                   leaseVars, configVars, persistVars>>

DiskUnblock(i) ==
    /\ diskBlocked[i]
    /\ diskBlocked' = [diskBlocked EXCEPT ![i] = FALSE]
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars, messages,
                   leaseVars, configVars, persistVars>>

Crash(i) ==
    /\ state' = [state EXCEPT ![i] = Follower]

    /\ commitIndex'  = [commitIndex  EXCEPT ![i] = 0]
    /\ nextIndex'    = [nextIndex    EXCEPT ![i] = [j \in Server |-> 1]]
    /\ matchIndex'   = [matchIndex   EXCEPT ![i] = [j \in Server |-> 0]]
    /\ votesGranted' = [votesGranted EXCEPT ![i] = {}]
    /\ leaseContact' = [leaseContact EXCEPT ![i] = {}]
    /\ diskBlocked'  = [diskBlocked  EXCEPT ![i] = FALSE]

    /\ currentTerm' = [currentTerm EXCEPT ![i] = persistedTerm[i]]
    /\ votedFor'    = [votedFor    EXCEPT ![i] = IF persistedVoteTerm[i] = persistedTerm[i]
                                            THEN persistedVotedFor[i] ELSE Nil]
    /\ pendingVote' = [pendingVote EXCEPT ![i] = Nil]

    /\ latestConfig'    = [latestConfig    EXCEPT ![i] = LatestConfigIn(log[i], Len(log[i]))]
    /\ latestConfigIndex' = [latestConfigIndex EXCEPT ![i] = LastConfigIndex(log[i])]
    /\ committedConfigIndex' = [committedConfigIndex EXCEPT ![i] = PreviousConfigIndex(log[i])]
    /\ committedConfig' = [committedConfig EXCEPT ![i] =
          ConfigAt(log[i], committedConfigIndex'[i])]

    /\ UNCHANGED <<log, messages, persistedTerm, persistedVoteTerm, persistedVotedFor>>

LoseMessage(m) ==
    /\ m \in DOMAIN messages
    /\ Discard(m)
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                   leaseVars, diskVars, configVars, persistVars>>

DropStaleMessage(m) ==
    /\ m \in DOMAIN messages
    /\ \/ /\ m.mtype = RequestVoteRequest
          /\ m.mterm < currentTerm[m.mdest]
       \/ /\ m.mtype = RequestVoteResponse
          /\ m.mterm < currentTerm[m.mdest]
       \/ /\ m.mtype = AppendEntriesRequest
          /\ m.mterm < currentTerm[m.mdest]
       \/ /\ m.mtype = AppendEntriesResponse
          /\ m.mterm < currentTerm[m.mdest]
    /\ Discard(m)
    /\ UNCHANGED <<serverVars, logVars, leaderVars, candidateVars,
                   leaseVars, diskVars, configVars, persistVars>>

ProtocolNext ==
    \/ \E i \in Server :
        \/ Timeout(i)
        \/ BecomeLeader(i)
        \/ CompletePersistVote(i)
        \/ CheckLeaderLease(i)
        \/ DiskBlock(i)
        \/ DiskUnblock(i)
        \/ Crash(i)
        \/ AdvanceCommitIndex(i)
    \/ \E i \in Server, value \in Values : ClientRequest(i, value)
    \/ \E i, j \in Server :
        \/ ReplicateEntries(i, j)
        \/ SendHeartbeat(i, j)
        \/ ProposeConfigChange(i, j)
    \/ \E m \in DOMAIN messages :
        \/ HandleRequestVoteRequest(m.mdest, m)
        \/ HandleRequestVoteResponse(m.mdest, m)
        \/ HandleAppendEntriesRequest(m.mdest, m)
        \/ HandleReplicateResponse(m.mdest, m)
        \/ HandleHeartbeatResponse(m.mdest, m)
        \/ DropStaleMessage(m)
        \/ LoseMessage(m)

VARIABLE electionHistory, commitHistory
historyVars == <<electionHistory, commitHistory>>
vars == <<protocolVars, historyVars>>

Init == ProtocolInit /\ electionHistory = {} /\ commitHistory = {}

RecordEvents ==
    /\ electionHistory' = electionHistory \cup
         {[server |-> s, term |-> currentTerm'[s], entries |-> log'[s]] :
            s \in {i \in Server : state[i] # Leader /\ state'[i] = Leader}}
    /\ commitHistory' = commitHistory \cup
         {[server |-> s, entries |-> SubSeq(log'[s], 1, commitIndex'[s])] :
            s \in {i \in Server : commitIndex'[i] > commitIndex[i]}}

Next == ProtocolNext /\ RecordEvents
Spec == Init /\ [][Next]_vars

LogMatching ==
    \A a, b \in Server :
        \A k \in 1..Min(Len(log[a]), Len(log[b])) :
            log[a][k].term = log[b][k].term =>
                SubSeq(log[a], 1, k) = SubSeq(log[b], 1, k)

====

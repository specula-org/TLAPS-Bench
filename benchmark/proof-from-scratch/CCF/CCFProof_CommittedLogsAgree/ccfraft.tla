--------------------------------- MODULE ccfraft ---------------------------------

EXTENDS Naturals, FiniteSets, Sequences, TLC, FiniteSetsExt, SequencesExt, Functions

------------------------------------------------------------------------------

CONSTANT
    OrderedNoDup,
    Ordered,
    ReorderedNoDup,
    Reordered,
    Guarantee

CONSTANTS

    Follower,
    PreVoteCandidate,
    Candidate,
    Leader,

    None

LeadershipStates == {
    Follower,
    PreVoteCandidate,
    Candidate,
    Leader,
    None
    }

CONSTANTS
    
    Active,

    RetirementOrdered,

    RetirementSigned,

    RetirementCompleted,

    RetiredCommitted

MembershipStates == {
    Active,
    RetirementOrdered,
    RetirementSigned,
    RetirementCompleted,
    RetiredCommitted
    }

CONSTANTS
    RequestVoteRequest,
    RequestVoteResponse,
    AppendEntriesRequest,
    AppendEntriesResponse,
    ProposeVoteRequest

CONSTANTS
    TypeEntry,
    TypeSignature,
    TypeReconfiguration,
    TypeRetired

CONSTANTS Servers
ASSUME ServerSetAssumption == Servers /= {} /\ IsFiniteSet(Servers)

StartTerm == 2

Nil ==

  CHOOSE v : v \notin Servers

------------------------------------------------------------------------------

CONSTANTS
  
  PreVoteDisabled,
  
  PreVoteCapable,
  
  PreVoteEnabled
VARIABLE
    preVoteStatus

VARIABLE messages

Network == INSTANCE Network

messageVars == <<
    messages
>>

------------------------------------------------------------------------------

VARIABLE configurations

VARIABLE hasJoined

VARIABLE retirementCompleted

reconfigurationVars == << 
    configurations,
    hasJoined,
    retirementCompleted
>>

VARIABLE currentTerm

VARIABLE leadershipState

VARIABLE membershipState

VARIABLE votedFor

VARIABLE isNewFollower

serverVars == <<currentTerm, leadershipState, membershipState, votedFor, isNewFollower>>

VARIABLE log

VARIABLE commitIndex

logVars == <<log, commitIndex>>

CommittableIndices(i) ==
    {idx \in DOMAIN log[i] : log[i][idx].contentType = TypeSignature}

VARIABLE votesGranted

candidateVars == <<votesGranted>>

VARIABLE sentIndex

VARIABLE matchIndex

leaderVars == <<sentIndex, matchIndex>>

------------------------------------------------------------------------------

vars == <<
    preVoteStatus,
    reconfigurationVars, 
    messageVars, 
    serverVars, 
    candidateVars, 
    leaderVars, 
    logVars 
>>

------------------------------------------------------------------------------

min(a, b) == IF a < b THEN a ELSE b

max(a, b) == IF a > b THEN a ELSE b

Send(m) == messages' =
    Network!WithMessage(m, messages)

Discard(m) == messages' = Network!WithoutMessage(m, messages)

Reply(response, request) ==
    messages' = Network!WithoutMessage(request, Network!WithMessage(response, messages))

HasTypeSignature(e) == e.contentType = TypeSignature
HasTypeReconfiguration(e) == e.contentType = TypeReconfiguration

LastCommittableIndex(i) ==
    
    Max({commitIndex[i]} \cup CommittableIndices(i))

LastCommittableTerm(i) ==
    
    IF LastCommittableIndex(i) = 0 THEN 0 ELSE log[i][LastCommittableIndex(i)].term

MaxCommittableIndex(xlog) ==
    SelectLastInSeq(xlog, HasTypeSignature)

MaxCommittableIndexAt(xlog, idx) ==
    MaxCommittableIndex(SubSeq(xlog, 1, min(idx, Len(xlog))))

MaxCommittableTerm(xlog) ==
    LET iMax == MaxCommittableIndex(xlog)
    IN IF iMax = 0 THEN 0 ELSE xlog[iMax].term

FindHighestPossibleMatch(xlog, index, term) ==
    
    SelectLastInSeq(SubSeq(xlog, 1, min(index, Len(xlog))), LAMBDA e: e.term <= term)

Quorums ==
    
    [ s \in SUBSET Servers |-> {i \in SUBSET(s) : Cardinality(i) * 2 > Cardinality(s)} ]

GetServerSet(server) ==
    UNION (Range(configurations[server]))

IsInServerSet(candidate, server) ==
    \E i \in DOMAIN (configurations[server]) :
        candidate \in configurations[server][i]

MaxConfigurationIndex(server) ==

    Max(DOMAIN configurations[server])

MaxConfiguration(server) ==
    configurations[server][MaxConfigurationIndex(server)]

HighestConfigurationWithNode(server, node) ==
    
    Max({configIndex \in DOMAIN configurations[server] : node \in configurations[server][configIndex]} \union {0})

NextConfigurationIndex(server) ==
    
    LET dom == DOMAIN configurations[server]
    IN Min(dom \ {Min(dom)})

ConfigurationsToIndex(server, index) ==
     RestrictDomain(configurations[server], LAMBDA c : c <= index)

LastConfigurationToIndex(server, index) ==
    LET configsBeforeIndex == {c \in DOMAIN configurations[server] : c <= index}
    IN IF configsBeforeIndex = {} THEN 0 ELSE Max(configsBeforeIndex)

Committed(i) ==
    IF commitIndex[i] = 0
    THEN << >>
    ELSE SubSeq(log[i],1,commitIndex[i])

RetirementIndexLog(node_log, i) ==
    LET 
        inIndexes == {index \in DOMAIN node_log: 
            /\ node_log[index].contentType = TypeReconfiguration
            /\ i \in node_log[index].configuration}
        outIndexes == {index \in DOMAIN node_log: 
            /\ node_log[index].contentType = TypeReconfiguration
            /\ i \notin node_log[index].configuration}
    IN IF 
        
        inIndexes # {}
    THEN 
        LET retiredIndexes == {k \in outIndexes: k > Max(inIndexes)}
        IN IF retiredIndexes = {} 
        THEN 0 
        ELSE Min(retiredIndexes)
    ELSE 0

IsRetiredCommittedLog(log_i, commit_index_i, i) ==
    \E idx \in 1..commit_index_i:
        /\ log_i[idx].contentType = TypeRetired
        /\ i \in log_i[idx].retired

CalcMembershipState(log_i, commit_index_i, i) ==
    LET retirement_index == RetirementIndexLog(log_i,i)
    IN IF retirement_index # 0
       THEN IF retirement_index <= commit_index_i 
            THEN IF IsRetiredCommittedLog(log_i, commit_index_i, i)
                  THEN RetiredCommitted
                  ELSE RetirementCompleted
            ELSE IF retirement_index < MaxCommittableIndex(log_i)
                 THEN RetirementSigned
                 ELSE RetirementOrdered
       ELSE Active

AllRetiredCommittedTxns(log_i) ==
    UNION {log_i[idx].retired: idx \in {k \in DOMAIN log_i: log_i[k].contentType = TypeRetired}}

AllRetired(log_i) ==
    {n \in Servers: RetirementIndexLog(log_i, n) # 0}

NextRetirementCompleted(current_retired_completed_i, current_configurations_i, next_log_i, next_commit_index_i, i) ==
    
    LET retiredCommittedNodes == {rc \in current_retired_completed_i : CalcMembershipState(next_log_i, next_commit_index_i, rc) = RetiredCommitted}
        nextCurrentConfigIndex == LastConfigurationToIndex(i, next_commit_index_i)
        
        nodesInCommittedOutConfigs == IF nextCurrentConfigIndex > 0 THEN (UNION Range(RestrictDomain(current_configurations_i, LAMBDA c : c < nextCurrentConfigIndex))) ELSE {}
        
        nodesOnlyInCommittedOutConfigs == IF nextCurrentConfigIndex > 0 THEN nodesInCommittedOutConfigs \ current_configurations_i[nextCurrentConfigIndex] ELSE {}
    IN (current_retired_completed_i \cup nodesOnlyInCommittedOutConfigs) \ retiredCommittedNodes

AppendEntriesBatchsize(i, j) ==

    {sentIndex[i][j] + 1}

PlausibleSucessorNodes(i) ==

    LET
        all_other_nodes == GetServerSet(i) \ {i}
        highestMatchServers == {n \in all_other_nodes : \A m \in all_other_nodes : matchIndex[i][n] >= matchIndex[i][m]}
    IN {n \in highestMatchServers : \A m \in highestMatchServers: HighestConfigurationWithNode(i, n) >= HighestConfigurationWithNode(i, m)} \ {i}

StartLog(startNode, _ignored) ==
    << [term |-> StartTerm, contentType |-> TypeReconfiguration, configuration |-> startNode],
       [term |-> StartTerm, contentType |-> TypeSignature] >>

InitLogConfigServerVars(startNodes, logPrefix(_,_)) ==
    /\ votedFor    = [i \in Servers |-> Nil]
    /\ isNewFollower = [i \in Servers |-> TRUE]
    /\ currentTerm = [i \in Servers |-> IF i \in startNodes THEN StartTerm ELSE 0]
    /\ \E sn \in startNodes:

        /\ log         = [i \in Servers |-> IF i \in startNodes THEN logPrefix({sn}, startNodes) ELSE << >>]
        /\ leadershipState = [i \in Servers |-> IF i = sn THEN Leader ELSE IF i \in startNodes THEN Follower ELSE None]
        /\ membershipState = [i \in Servers |-> Active]
        /\ commitIndex = [i \in Servers |-> IF i \in startNodes THEN Len(logPrefix({sn}, startNodes)) ELSE 0]
        /\ hasJoined = [i \in Servers |-> IF i \in startNodes THEN TRUE ELSE FALSE]
        /\ sentIndex  = [i \in Servers |-> IF i = sn 
            THEN [j \in Servers |-> Len(logPrefix({sn}, startNodes))] 
            ELSE [j \in Servers |-> 0]]
    /\ configurations = [i \in Servers |-> IF i \in startNodes  THEN (Len(log[i])-1 :> startNodes) ELSE << >>]
    /\ retirementCompleted = [i \in Servers |-> {}]
    
------------------------------------------------------------------------------

InitReconfigurationVars ==
    \E startNode \in Servers:
        InitLogConfigServerVars({startNode}, StartLog)

InitMessagesVars ==
    /\ Network!InitMessageVar

InitCandidateVars ==
    /\ votesGranted   = [i \in Servers |-> {}]

InitLeaderVars ==
    /\ matchIndex = [i \in Servers |-> [j \in Servers |-> 0]]

InitPreVoteStatus ==
    /\ preVoteStatus = [i \in Servers |-> {PreVoteDisabled}]

Init ==
    /\ InitReconfigurationVars
    /\ InitMessagesVars
    /\ InitCandidateVars
    /\ InitLeaderVars
    /\ InitPreVoteStatus

------------------------------------------------------------------------------

BecomePreVoteCandidate(i) ==
    /\ PreVoteEnabled \in preVoteStatus[i]
    
    /\ membershipState[i] \in (MembershipStates \ {RetiredCommitted})

    /\ leadershipState[i] \in {Follower, PreVoteCandidate, Candidate}
    /\
        
        \/ \E c \in DOMAIN configurations[i] :
            /\ i \in configurations[i][c]
            /\ MaxCommittableIndex(log[i]) >= c
        
        \/ i \in retirementCompleted[i]
    /\ leadershipState' = [leadershipState EXCEPT ![i] = PreVoteCandidate]
    /\ votesGranted' = [votesGranted EXCEPT ![i] = {i}]
    /\ UNCHANGED <<currentTerm, membershipState, votedFor, isNewFollower, preVoteStatus, messageVars, reconfigurationVars, leaderVars, logVars>>

BecomeCandidate(i) ==
    
    /\ membershipState[i] \in (MembershipStates \ {RetiredCommitted})
    
    /\ leadershipState[i] \in {Follower, PreVoteCandidate, Candidate} 
    /\
        
        \/ \E c \in DOMAIN configurations[i] :
            /\ i \in configurations[i][c]
            /\ MaxCommittableIndex(log[i]) >= c
        
        \/ i \in retirementCompleted[i]
    /\ leadershipState' = [leadershipState EXCEPT ![i] = Candidate]
    /\ currentTerm' = [currentTerm EXCEPT ![i] = currentTerm[i] + 1]
    
    /\ votedFor' = [votedFor EXCEPT ![i] = i]
    /\ votesGranted'   = [votesGranted EXCEPT ![i] = {i}]
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, leaderVars, logVars, membershipState, isNewFollower>>

BecomeCandidateFromPreVoteCandidate(i) ==
  /\ PreVoteEnabled \in preVoteStatus[i]
  /\ leadershipState[i] = PreVoteCandidate

  /\ \A c \in DOMAIN configurations[i] : 
    (votesGranted[i] \intersect configurations[i][c]) \in Quorums[configurations[i][c]]
  /\ BecomeCandidate(i)
  /\ UNCHANGED messageVars

Timeout(i) ==
    IF PreVoteEnabled \notin preVoteStatus[i]
    THEN BecomeCandidate(i) /\ UNCHANGED messageVars
    ELSE BecomePreVoteCandidate(i)

RequestVote(i,j) ==
    LET
        isPreVote == leadershipState[i] = PreVoteCandidate
        msg == [type         |-> RequestVoteRequest,
                term         |-> currentTerm[i],

                lastCommittableTerm  |-> LastCommittableTerm(i),
                lastCommittableIndex |-> LastCommittableIndex(i),
                source       |-> i,
                dest         |-> j,
                isPreVote    |-> isPreVote]
    IN
    
    /\ i /= j
    
    /\ leadershipState[i] \in {PreVoteCandidate, Candidate}
    
    /\ IsInServerSet(j, i)
    /\ Send(msg)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, votesGranted, leaderVars, logVars>>

AppendEntries(i, j) ==
    
    /\ leadershipState[i] = Leader
    
    /\ i /= j
    /\ \/ IsInServerSet(j, i)
       \/ j \in retirementCompleted[i]

    /\ LET prevLogIndex == sentIndex[i][j]
           prevLogTerm == IF prevLogIndex \in DOMAIN log[i] THEN
                              log[i][prevLogIndex].term
                          ELSE
                              
                              0
           
           lastEntry(idx) == min(Len(log[i]), idx)
           index == sentIndex[i][j] + 1
           msg(idx) == 
               [type          |-> AppendEntriesRequest,
                term          |-> currentTerm[i],
                prevLogIndex  |-> prevLogIndex,
                prevLogTerm   |-> prevLogTerm,
                entries       |-> SubSeq(log[i], index, lastEntry(idx)),
                commitIndex   |-> commitIndex[i],
                source        |-> i,
                dest          |-> j]
       IN
       /\ \E b \in AppendEntriesBatchsize(i, j):
            LET m == msg(b) IN
            /\ \/ membershipState[i] # RetiredCommitted
               \/ m.entries # <<>>
            /\ Send(m)

            /\ sentIndex' = [sentIndex EXCEPT ![i][j] = @ + Len(m.entries)]
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, candidateVars, matchIndex, logVars, membershipState>>

BecomeLeader(i) ==
    
    /\ leadershipState[i] = Candidate

    /\ \A c \in DOMAIN configurations[i] : (votesGranted[i] \intersect configurations[i][c]) \in Quorums[configurations[i][c]]
    /\ leadershipState' = [leadershipState EXCEPT ![i] = Leader]

    /\ log' = [log EXCEPT ![i] = SubSeq(log[i],1, MaxCommittableIndex(log[i]))]
    
    /\ sentIndex'  = [sentIndex EXCEPT ![i] = [j \in Servers |-> Len(log'[i])]]
    /\ matchIndex' = [matchIndex EXCEPT ![i] = [j \in Servers |-> 0]]
    
    /\ configurations' = [configurations EXCEPT ![i] = ConfigurationsToIndex(i, Len(log'[i]))]

    /\ membershipState' = [membershipState EXCEPT ![i] = 
        IF @ = RetirementOrdered THEN Active ELSE @]
    /\ UNCHANGED <<preVoteStatus, messageVars, currentTerm, votedFor, isNewFollower, candidateVars, commitIndex, hasJoined, retirementCompleted>>

ClientRequest(i) ==
    
    /\ leadershipState[i] = Leader
    
    /\ membershipState[i] # RetiredCommitted
    
    /\ log' = [log EXCEPT ![i] = Append(@, [term  |-> currentTerm[i], contentType |-> TypeEntry]) ]
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, messageVars, serverVars, candidateVars, leaderVars, commitIndex>>

SignCommittableMessages(i) ==
    
    /\ leadershipState[i] = Leader
    
    /\ membershipState[i] # RetiredCommitted
    
    /\ log[i] # << >>
    
    /\ log' = [log EXCEPT ![i] = @ \o <<[term  |-> currentTerm[i], contentType  |-> TypeSignature]>>]
    
    /\ IF membershipState[i] = RetirementOrdered
       THEN membershipState' = [membershipState EXCEPT ![i] = RetirementSigned]
       ELSE UNCHANGED membershipState
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, messageVars, currentTerm, leadershipState, votedFor, isNewFollower, candidateVars, leaderVars, commitIndex>>

ChangeConfigurationInt(i, newConfiguration) ==
    
    /\ leadershipState[i] = Leader
    
    /\ newConfiguration /= MaxConfiguration(i)
    /\ LET addedNodes == newConfiguration \ MaxConfiguration(i)
       IN

        /\ \A n \in addedNodes : hasJoined[n] = FALSE
        /\ hasJoined' = [n \in Servers |-> IF n \in addedNodes THEN TRUE ELSE hasJoined[n]]

        /\ LET newSentIndex == [ k \in Servers |-> IF k \in addedNodes THEN Len(log[i]) ELSE sentIndex[i][k]]
            IN sentIndex' = [sentIndex EXCEPT ![i] = newSentIndex]
        /\ log' = [log EXCEPT ![i] = Append(log[i],
                                            [term |-> currentTerm[i],
                                             configuration |-> newConfiguration,
                                             contentType |-> TypeReconfiguration])]
        /\ configurations' = [configurations EXCEPT ![i] = configurations[i] @@ Len(log'[i]) :> newConfiguration]
        
        /\ IF membershipState[i] = Active /\ i \notin newConfiguration
            THEN membershipState' = [membershipState EXCEPT ![i] = RetirementOrdered]
            ELSE UNCHANGED membershipState
        /\ UNCHANGED <<preVoteStatus, messageVars, currentTerm, leadershipState, votedFor, isNewFollower, candidateVars, matchIndex, commitIndex, retirementCompleted>>

ChangeConfiguration(i) ==

    \E newConfiguration \in SUBSET(Servers) \ {{}}:
        ChangeConfigurationInt(i, newConfiguration)

AppendRetiredCommitted(i) ==
    /\ leadershipState[i] = Leader
    /\ membershipState[i] # RetiredCommitted
    /\ LET 
        
        retire_committed_nodes == AllRetired(SubSeq(log[i],1,commitIndex[i])) \ AllRetiredCommittedTxns(log[i]) 
        IN 
        /\ retire_committed_nodes # {}
        /\ log' = [log EXCEPT ![i] = Append(@, [
                    term  |-> currentTerm[i], 
                    contentType |-> TypeRetired, 
                    retired |-> retire_committed_nodes])]
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, messageVars, serverVars, candidateVars, leaderVars, commitIndex>>

AdvanceCommitIndex(i) ==
    /\ leadershipState[i] = Leader
    /\ LET

            HasConsensusWatermark(idx) ==
                \A config \in {c \in DOMAIN(configurations[i]) : idx >= c } :
                    
                    LET config_servers == configurations[i][config]
                        required_quorum == Quorums[config_servers]
                        agree_servers == {k \in config_servers : matchIndex[i][k] >= idx}
                    IN (IF i \in config_servers THEN {i} ELSE {}) \cup agree_servers \in required_quorum

            highestCommittableIndex == Max({0} \cup { j \in (commitIndex[i]+1)..Len(log[i]) : 
                                                                    /\ log[i][j].term = currentTerm[i] 
                                                                    /\ log[i][j].contentType = TypeSignature
                                                                    /\ HasConsensusWatermark(j) })
        IN
         
        /\ commitIndex[i] < highestCommittableIndex
        /\ commitIndex' = [commitIndex EXCEPT ![i] = highestCommittableIndex]
        
        /\ membershipState' = [membershipState EXCEPT ![i] = CalcMembershipState(log[i], commitIndex'[i], i)]
        /\ leadershipState' = [leadershipState EXCEPT ![i] = 
            IF membershipState'[i] = RetiredCommitted THEN Follower ELSE @]
        
        /\ IF /\ Cardinality(DOMAIN configurations[i]) > 1
              /\ highestCommittableIndex >= NextConfigurationIndex(i)
           THEN
              LET new_configurations == RestrictDomain(configurations[i], 
                                            LAMBDA c : c >= LastConfigurationToIndex(i, highestCommittableIndex))
              IN
              /\ configurations' = [configurations EXCEPT ![i] = new_configurations]
            ELSE UNCHANGED <<configurations>>
        /\ IF /\ membershipState[i] = RetirementCompleted
              /\ membershipState'[i] = RetiredCommitted
            THEN \E j \in PlausibleSucessorNodes(i) :
                    /\ LET msg == [type        |-> ProposeVoteRequest,
                                   term        |-> currentTerm[i],
                                   source      |-> i,
                                   dest        |-> j ]
                        IN Send(msg)
            ELSE UNCHANGED <<messageVars>>
        /\ retirementCompleted' = [retirementCompleted EXCEPT ![i] = NextRetirementCompleted(retirementCompleted[i], configurations[i], log[i], commitIndex'[i], i)]
    /\ UNCHANGED <<preVoteStatus, candidateVars, leaderVars, log, currentTerm, votedFor, isNewFollower, hasJoined>>

CheckQuorum(i) ==
    
    /\ leadershipState[i] = Leader
    
    /\ \E c \in DOMAIN configurations[i]:
       \E n \in configurations[i][c]: n /= i
    /\ leadershipState' = [leadershipState EXCEPT ![i] = Follower]
    /\ isNewFollower' = [isNewFollower EXCEPT ![i] = TRUE]
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, messageVars, currentTerm, votedFor, candidateVars, leaderVars, logVars, membershipState>>

SigTermProposeVote(i) ==
    /\ leadershipState[i] = Leader
    /\ \E j \in PlausibleSucessorNodes(i):
       /\ LET msg == [type        |-> ProposeVoteRequest,
                      term        |-> currentTerm[i],
                      source      |-> i,
                      dest        |-> j ]
           IN Send(msg)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, candidateVars, leaderVars, logVars>> 

------------------------------------------------------------------------------

HandleRequestVoteRequest(i, j, m) ==
    LET logOk == \/ m.lastCommittableTerm > MaxCommittableTerm(log[i])
                 \/ /\ m.lastCommittableTerm = MaxCommittableTerm(log[i])

                    /\ m.lastCommittableIndex >= MaxCommittableIndex(log[i])
        grant_pre_vote_disabled == /\ m.term = currentTerm[i]
                                   /\ logOk
                                   /\ votedFor[i] \in {Nil, j}
        grant_pre_vote_capable  == /\ logOk 
                                   /\ IF ~m.isPreVote
                                      THEN /\ m.term = currentTerm[i]
                                           /\ votedFor[i] \in {Nil, j}
                                      ELSE m.term >= currentTerm[i]
        grant == IF PreVoteDisabled \in preVoteStatus[i]
                 THEN grant_pre_vote_disabled
                 ELSE grant_pre_vote_capable
    IN /\ m.term <= currentTerm[i]
       /\ \/ grant /\ IF PreVoteCapable \in preVoteStatus[i] /\ m.isPreVote
                      THEN UNCHANGED votedFor
                      ELSE votedFor' = [votedFor EXCEPT ![i] = j]
          \/ ~grant /\ UNCHANGED votedFor
       /\ Reply([type        |-> RequestVoteResponse,
                 term        |-> currentTerm[i],
                 voteGranted |-> grant,
                 isPreVote   |-> m.isPreVote,
                 source      |-> i,
                 dest        |-> j],
                 m)
       /\ UNCHANGED <<preVoteStatus, reconfigurationVars, leadershipState, currentTerm, 
        candidateVars, leaderVars, logVars, membershipState, isNewFollower>>

HandleRequestVoteResponse(i, j, m) ==
    /\ m.term = currentTerm[i]
    
    /\ \/  m.isPreVote /\ leadershipState[i] = PreVoteCandidate
       \/ ~m.isPreVote /\ leadershipState[i] = Candidate
    /\ \/ /\ m.voteGranted
          /\ votesGranted' = [votesGranted EXCEPT ![i] =
                                  votesGranted[i] \cup {j}]
       \/ /\ ~m.voteGranted
          /\ UNCHANGED votesGranted
    /\ Discard(m)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, votedFor, leaderVars, 
        logVars, membershipState, isNewFollower>>

RejectAppendEntriesRequest(i, j, m, logOk) ==
    
    /\ \/ /\ m.term < currentTerm[i]
          /\ Reply([type        |-> AppendEntriesResponse,
                 success        |-> FALSE,
                 term           |-> currentTerm[i],
                 lastLogIndex   |-> Len(log[i]),
                 source         |-> i,
                 dest           |-> j],
                 m)
       \/ /\ m.term >= currentTerm[i]
          /\ leadershipState[i] = Follower
          /\ ~logOk

          /\ LET prevTerm == IF m.prevLogIndex = 0 THEN 0
                             ELSE IF m.prevLogIndex > Len(log[i]) THEN 0 ELSE log[i][Len(log[i])].term
             IN /\ m.prevLogTerm # prevTerm
                /\ \/ /\ prevTerm = 0
                      /\ Reply([type        |-> AppendEntriesResponse,
                             success        |-> FALSE,
                             term           |-> currentTerm[i],
                             lastLogIndex   |-> Len(log[i]),
                             source         |-> i,
                             dest           |-> j],
                             m)
                   \/ /\ prevTerm # 0
                      /\ LET lli == FindHighestPossibleMatch(log[i], m.prevLogIndex, m.prevLogTerm)
                         IN Reply([type        |-> AppendEntriesResponse,
                                success        |-> FALSE,
                                term           |-> IF lli = 0 THEN StartTerm ELSE log[i][lli].term,
                                lastLogIndex   |-> lli,
                                source         |-> i,
                                dest           |-> j],
                                m)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, logVars, membershipState, isNewFollower, candidateVars, leaderVars>>

ReturnToFollowerState(i, m) ==
    /\ m.term = currentTerm[i]
    /\ leadershipState[i] \in {PreVoteCandidate, Candidate}
    /\ leadershipState' = [leadershipState EXCEPT ![i] = Follower]
    /\ isNewFollower' = [isNewFollower EXCEPT ![i] = TRUE]
    
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, currentTerm, votedFor, logVars, 
        messages, membershipState, candidateVars, leaderVars>>

AppendEntriesAlreadyDone(i, j, index, m) ==
    /\ \/ m.entries = << >>
       \/ /\ m.entries /= << >>
          /\ Len(log[i]) >= index + (Len(m.entries) - 1)
          /\ \A idx \in 1..Len(m.entries) :
                log[i][index + (idx - 1)].term = m.entries[idx].term
    
    /\ LET requestEndIndex == m.prevLogIndex + Len(m.entries)
           newCommitIndex == max(MaxCommittableIndexAt(log[i], min(m.commitIndex, requestEndIndex)), commitIndex[i])
           newConfigurationIndex == LastConfigurationToIndex(i, newCommitIndex)
       IN /\ commitIndex' = [commitIndex EXCEPT ![i] = newCommitIndex]
          
          /\ configurations' = [configurations EXCEPT ![i] = RestrictDomain(@, LAMBDA c : c >= newConfigurationIndex)]
          
          /\ retirementCompleted' = [retirementCompleted EXCEPT ![i] = NextRetirementCompleted(retirementCompleted[i], configurations[i], log[i], commitIndex'[i], i)]

          /\ membershipState' = [membershipState EXCEPT ![i] = CalcMembershipState(log[i], commitIndex'[i], i)]
    /\ Reply([type           |-> AppendEntriesResponse,
              term           |-> currentTerm[i],
              success        |-> TRUE,
              lastLogIndex   |-> m.prevLogIndex + Len(m.entries),
              source         |-> i,
              dest           |-> j],
              m)
    /\ UNCHANGED <<preVoteStatus, currentTerm, leadershipState, votedFor, isNewFollower, log, candidateVars, leaderVars, hasJoined>>

ConflictAppendEntriesRequest(i, index, m) ==
    /\ m.entries /= << >>
    /\ \E idx \in 1..Len(m.entries) :
        /\ (index + (idx - 1)) \in DOMAIN log[i]
        /\ log[i][index + (idx - 1)].term # m.entries[idx].term
    /\ isNewFollower[i]
    /\ LET new_log == [index2 \in 1..m.prevLogIndex |-> log[i][index2]] 
       IN /\ log' = [log EXCEPT ![i] = new_log]
          
          /\ configurations' = [configurations EXCEPT ![i] = ConfigurationsToIndex(i,Len(new_log))]
          /\ membershipState' = [membershipState EXCEPT ![i] = CalcMembershipState(log'[i], commitIndex[i], i)]
    /\ isNewFollower' = [isNewFollower EXCEPT ![i] = FALSE]
    /\ UNCHANGED <<preVoteStatus, currentTerm, leadershipState, votedFor, commitIndex, messages, candidateVars, leaderVars, hasJoined, retirementCompleted>>

NoConflictAppendEntriesRequest(i, j, m) ==
    /\ m.entries /= << >>
    /\ m.prevLogIndex <= Len(log[i])
    /\ Len(log[i]) < m.prevLogIndex + Len(m.entries)
    
    /\ \A k \in 1 .. (Len(log[i]) - m.prevLogIndex) :
            log[i][m.prevLogIndex + k] = m.entries[k]
    /\ log' = [log EXCEPT ![i] = SubSeq(@, 1, m.prevLogIndex) \o m.entries]

    /\ LET
        request_end_index == m.prevLogIndex + Len(m.entries)
        new_commit_index == max(MaxCommittableIndexAt(log'[i], min(m.commitIndex, request_end_index)), commitIndex[i])
        new_indexes == m.prevLogIndex + 1 .. m.prevLogIndex + Len(m.entries)
        
        new_log_entries == 
            [idx \in new_indexes |-> m.entries[idx - m.prevLogIndex]]
        
        reconfig_indexes == 
            {idx \in DOMAIN new_log_entries : HasTypeReconfiguration(new_log_entries[idx])}
        
        new_configs == 
            configurations[i] @@ [idx \in reconfig_indexes |-> new_log_entries[idx].configuration]
        new_committed_configs == {c \in DOMAIN new_configs : c <= new_commit_index}
        new_conf_index == IF new_committed_configs = {} THEN 0 ELSE
            Max(new_committed_configs)
        new_retirement_index == RetirementIndexLog(log'[i],i)
        IN
        /\ commitIndex' = [commitIndex EXCEPT ![i] = new_commit_index]
        /\ configurations' = 
                [configurations EXCEPT ![i] = RestrictDomain(new_configs, LAMBDA c : c >= new_conf_index)]
        /\ retirementCompleted' = [retirementCompleted EXCEPT ![i] = NextRetirementCompleted(retirementCompleted[i], configurations[i], log'[i], commitIndex'[i], i)]
        
        /\ IF /\ leadershipState[i] = None
              /\ \E conf_index \in DOMAIN(new_configs) : i \in new_configs[conf_index]
           THEN leadershipState' = [leadershipState EXCEPT ![i] = Follower ]
           ELSE UNCHANGED leadershipState
          
          /\ membershipState' = [membershipState EXCEPT ![i] = CalcMembershipState(log'[i], commitIndex'[i], i)]
    /\ Reply([type           |-> AppendEntriesResponse,
              term           |-> currentTerm[i],
              success        |-> TRUE,
              lastLogIndex   |-> Len(log'[i]),
              source         |-> i,
              dest           |-> j],
              m)
    /\ UNCHANGED <<preVoteStatus, currentTerm, votedFor, isNewFollower, candidateVars, leaderVars, hasJoined>>

AcceptAppendEntriesRequest(i, j, logOk, m) ==
    /\ m.term = currentTerm[i]
    /\ leadershipState[i] \in {Follower, None}
    /\ logOk
    
    /\ m.prevLogIndex >= commitIndex[i]
    /\ LET index == m.prevLogIndex + 1
       IN \/ AppendEntriesAlreadyDone(i, j, index, m)
          \/ NoConflictAppendEntriesRequest(i, j, m)
          \/ ConflictAppendEntriesRequest(i, index, m) \cdot AppendEntriesAlreadyDone(i, j, index, m)
          \/ ConflictAppendEntriesRequest(i, index, m) \cdot NoConflictAppendEntriesRequest(i, j, m)

HandleAppendEntriesRequest(i, j, m) ==
    LET logOk == \/ m.prevLogIndex = 0
                 \/ /\ m.prevLogIndex > 0
                    /\ m.prevLogIndex <= Len(log[i])
                    /\ m.prevLogTerm = log[i][m.prevLogIndex].term
    IN /\ m.term <= currentTerm[i]
       /\ \/ RejectAppendEntriesRequest(i, j, m, logOk)
          \/ ReturnToFollowerState(i, m)
          \/ AcceptAppendEntriesRequest(i, j, logOk, m)

HandleAppendEntriesResponse(i, j, m) ==
    /\ \/ /\ m.term = currentTerm[i]
          /\ leadershipState[i] = Leader 
          /\ m.success 
          
          /\ matchIndex' = [matchIndex EXCEPT ![i][j] = max(@, m.lastLogIndex)]
          
          /\ UNCHANGED sentIndex
       \/ /\ \lnot m.success 
          /\ LET tm == FindHighestPossibleMatch(log[i], m.lastLogIndex, m.term)
             IN sentIndex' = [sentIndex EXCEPT ![i][j] = max(min(tm, sentIndex[i][j]), matchIndex[i][j])]

          /\ UNCHANGED matchIndex
    /\ Discard(m)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, candidateVars, logVars>>

UpdateTerm(i, j, m) ==
    /\ m.type /= ProposeVoteRequest
    /\ m.term > currentTerm[i]
    /\ currentTerm'    = [currentTerm EXCEPT ![i] = m.term]
    
    /\ leadershipState' = [leadershipState EXCEPT 
         ![i] = IF @ \in {Leader, Candidate, PreVoteCandidate, None} THEN Follower ELSE @]
    /\ isNewFollower' = [isNewFollower EXCEPT ![i] = TRUE]
    /\ votedFor'       = [votedFor    EXCEPT ![i] = Nil]
    
    /\ UNCHANGED <<preVoteStatus, messageVars, candidateVars, leaderVars, logVars, hasJoined, retirementCompleted, membershipState, configurations>>

DropStaleResponse(i, j, m) ==
    /\ m.term < currentTerm[i]
    /\ Discard(m)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, candidateVars, leaderVars,
        logVars, membershipState>>

DropResponseWhenNotInState(i, j, m) ==
    \/ /\ m.type = AppendEntriesResponse
       /\ leadershipState[i] \in LeadershipStates \ { Leader }
    \/ /\ m.type = RequestVoteResponse
       /\ \/  m.isPreVote /\ leadershipState[i] /= PreVoteCandidate
          \/ ~m.isPreVote /\ leadershipState[i] /= Candidate
    /\ Discard(m)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, candidateVars, leaderVars, logVars>>

DropIgnoredMessage(i,j,m) ==

    /\ m.type /= RequestVoteRequest
    
    /\
       
       \/ /\ leadershipState[i] = None
          
          /\ m.type /= AppendEntriesRequest
       
       \/ /\ m.type = ProposeVoteRequest
          /\ m.term /= currentTerm[i]
       
       \/ /\ leadershipState[i] /= None
        
          /\ \lnot IsInServerSet(j, i)

       \/ /\ membershipState[i] = RetiredCommitted
          /\ m.type /= AppendEntriesRequest

       \/ /\ m.type = AppendEntriesRequest
          /\ m.prevLogIndex < commitIndex[i]
    /\ Discard(m)
    /\ UNCHANGED <<preVoteStatus, reconfigurationVars, serverVars, candidateVars, leaderVars, logVars>>

RcvDropIgnoredMessage(i, j) ==
    
    \E m \in Network!MessagesTo(i, j) :
        /\ j = m.source
        /\ DropIgnoredMessage(m.dest,m.source,m)

RcvUpdateTerm(i, j) ==

    \E m \in Network!MessagesTo(i, j) : 
        /\ j = m.source
        /\ UpdateTerm(m.dest, m.source, m)

RcvRequestVoteRequest(i, j) ==
    \E m \in Network!MessagesTo(i, j) : 
        /\ j = m.source
        /\ m.type = RequestVoteRequest
        /\ HandleRequestVoteRequest(m.dest, m.source, m)

RcvRequestVoteResponse(i, j) ==
    \E m \in Network!MessagesTo(i, j) : 
        /\ j = m.source
        /\ m.type = RequestVoteResponse
        /\ \/ HandleRequestVoteResponse(m.dest, m.source, m)
           \/ DropResponseWhenNotInState(m.dest, m.source, m)
           \/ DropStaleResponse(m.dest, m.source, m)

RcvAppendEntriesRequest(i, j) ==
    \E m \in Network!MessagesTo(i, j) : 
        /\ j = m.source
        /\ m.type = AppendEntriesRequest
        /\ HandleAppendEntriesRequest(m.dest, m.source, m)

RcvAppendEntriesResponse(i, j) ==
    \E m \in Network!MessagesTo(i, j) : 
        /\ j = m.source
        /\ m.type = AppendEntriesResponse
        /\ \/ HandleAppendEntriesResponse(m.dest, m.source, m)
           \/ DropResponseWhenNotInState(m.dest, m.source, m)

           \/ /\ m.success
              /\ DropStaleResponse(m.dest, m.source, m)

RcvProposeVoteRequest(i, j) ==
    \E m \in Network!MessagesTo(i, j) :
        /\ j = m.source
        /\ m.type = ProposeVoteRequest
        /\ m.term = currentTerm[i]
        /\ BecomeCandidate(m.dest)
        /\ Discard(m)

Receive(i, j) ==
    \/ RcvDropIgnoredMessage(i, j)
    \/ RcvUpdateTerm(i, j)
    \/ RcvRequestVoteRequest(i, j)
    \/ RcvRequestVoteResponse(i, j)
    \/ RcvAppendEntriesRequest(i, j)
    \/ RcvAppendEntriesResponse(i, j)
    \/ RcvProposeVoteRequest(i, j)

------------------------------------------------------------------------------

NextInt(i) ==
    \/ Timeout(i)
    \/ BecomeCandidateFromPreVoteCandidate(i)
    \/ BecomeLeader(i)
    \/ ClientRequest(i)
    \/ SignCommittableMessages(i)
    \/ ChangeConfiguration(i)
    \/ AppendRetiredCommitted(i)
    \/ AdvanceCommitIndex(i)
    \/ CheckQuorum(i)
    \/ SigTermProposeVote(i)
    \/ \E j \in Servers : RequestVote(i, j)
    \/ \E j \in Servers : AppendEntries(i, j)
    \/ \E j \in Servers : Receive(i, j)

Next ==
    \E i \in Servers: NextInt(i)

Fairness ==
    
    /\ \A i, j \in Servers : WF_vars(RcvDropIgnoredMessage(i, j))
    /\ \A i, j \in Servers : WF_vars(RcvUpdateTerm(i, j))
    /\ \A i, j \in Servers : WF_vars(RcvRequestVoteRequest(i, j))
    /\ \A i, j \in Servers : WF_vars(RcvRequestVoteResponse(i, j))
    /\ \A i, j \in Servers : WF_vars(RcvAppendEntriesRequest(i, j))
    /\ \A i, j \in Servers : WF_vars(RcvAppendEntriesResponse(i, j))
    /\ \A i, j \in Servers : WF_vars(RcvProposeVoteRequest(i, j))
    
    /\ \A s, t \in Servers : WF_vars(AppendEntries(s, t))
    /\ \A s, t \in Servers : WF_vars(RequestVote(s, t))
    /\ \A s \in Servers : WF_vars(SignCommittableMessages(s))
    /\ \A s \in Servers : WF_vars(AdvanceCommitIndex(s))
    /\ \A s \in Servers : WF_vars(AppendRetiredCommitted(s))
    /\ \A s \in Servers : SF_vars(BecomeCandidateFromPreVoteCandidate(s))
    /\ \A s \in Servers : WF_vars(BecomeLeader(s))
    /\ \A s \in Servers : WF_vars(Timeout(s))
    /\ \A s \in Servers : WF_vars(ChangeConfiguration(s))

Spec == 
    /\ Init
    /\ [][Next]_vars
    /\ Fairness

------------------------------------------------------------------------------

LogInv ==
    \A i, j \in Servers :
        \/ IsPrefix(Committed(i),Committed(j)) 
        \/ IsPrefix(Committed(j),Committed(i))

----

----

------------------------------------------------------------------------------

------------------------------------------------------------------------------

MappingToAbs == 
  INSTANCE abs WITH
    Servers <- Servers,
    StartTerm <- StartTerm,
    Terms <- Nat \ 0..StartTerm-1,
    cLogs <- [i \in Servers |-> [j \in 1..commitIndex[i] |-> log[i][j].term]]

------------------------------------------------------------------------------

===============================================================================

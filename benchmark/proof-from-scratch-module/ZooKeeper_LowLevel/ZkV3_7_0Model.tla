------------------------ MODULE ZkV3_7_0Model ------------------------

EXTENDS FastLeaderElection

CONSTANT MAXEPOCH
ASSUME MaxEpochNat == MAXEPOCH \in Nat \ {0}

Value == Nat

ELECTION        == "ELECTION"
DISCOVERY       == "DISCOVERY"
SYNCHRONIZATION == "SYNCHRONIZATION"
BROADCAST       == "BROADCAST"

DIFF  == "DIFF"
TRUNC == "TRUNC"
SNAP  == "SNAP"

FOLLOWERINFO == "FOLLOWERINFO"
LEADERINFO   == "LEADERINFO"
ACKEPOCH     == "ACKEPOCH"
NEWLEADER    == "NEWLEADER"
ACKLD        == "ACKLD"
UPTODATE     == "UPTODATE"
PROPOSAL     == "PROPOSAL"
ACK          == "ACK"
COMMIT       == "COMMIT"

ONLINE  == "ONLINE"
OFFLINE == "OFFLINE"

VARIABLES zabState,      
                         
          acceptedEpoch, 
                         
          lastCommitted, 

          lastSnapshot,  
                         
          initialHistory 

VARIABLES learners,       
                          
          connecting,     

          electing,       

          ackldRecv,      

          forwarding,     

          tempMaxEpoch    

VARIABLES connectInfo, 

          packetsSync  

VARIABLE msgs       

VARIABLES status,    
          partition  

VARIABLES epochLeader,       
          proposalMsgsLog   

serverVars == <<state, currentEpoch, lastProcessed, zabState, acceptedEpoch,
                history, lastCommitted, lastSnapshot, initialHistory>>       
electionVars == electionVarsL  
leaderVars == <<leadingVoteSet, learners, connecting, electing, 
                 ackldRecv, forwarding, tempMaxEpoch>>                                           
followerVars == <<connectInfo, packetsSync>>                
verifyVars == <<proposalMsgsLog, epochLeader>>
msgVars == <<msgs, electionMsgs>>
envVars == <<status, partition>>                        

vars == <<serverVars, electionVars, leaderVars, followerVars,
          verifyVars, msgVars, envVars>> 

BootstrapProposalMsgs ==
    { [ source |-> s,
        epoch  |-> 0,
        zxid   |-> BootstrapZxid,
        data   |-> 0 ] : s \in Server }

Maximum(S) == IF S = {} THEN -1
                        ELSE CHOOSE n \in S: \A m \in S: n >= m

Minimum(S) == IF S = {} THEN -1
                        ELSE CHOOSE n \in S: \A m \in S: n <= m

IsON(s)  == status[s] = ONLINE 
IsOFF(s) == status[s] = OFFLINE

IsLeader(s)   == state[s] = LEADING
IsFollower(s) == state[s] = FOLLOWING
IsLooking(s)  == state[s] = LOOKING

IsMyLearner(i, j) == j \in learners[i]
IsMyLeader(i, j)  == connectInfo[i].sid = j
HasNoLeader(i)    == connectInfo[i].sid = NullPoint
HasLeader(i)      == connectInfo[i].sid /= NullPoint
MyVote(i)         == currentVote[i].proposedLeader 

IsQuorum(s) == s \in Quorums

HasPartitioned(i, j) == /\ partition[i][j] = TRUE 
                        /\ partition[j][i] = TRUE

TxnZxidEqual(txn, z) == txn.zxid[1] = z[1] /\ txn.zxid[2] = z[2]

PendingFOLLOWERINFO(i, j) == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = FOLLOWERINFO
PendingLEADERINFO(i, j)   == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = LEADERINFO
PendingACKEPOCH(i, j)     == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = ACKEPOCH
PendingNEWLEADER(i, j)    == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = NEWLEADER
PendingACKLD(i, j)        == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = ACKLD
PendingUPTODATE(i, j)     == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = UPTODATE
PendingPROPOSAL(i, j)     == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = PROPOSAL
PendingACK(i, j)          == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = ACK
PendingCOMMIT(i, j)       == /\ msgs[j][i] /= << >>
                             /\ msgs[j][i][1].mtype = COMMIT

Send(i, j, m) == msgs' = [msgs EXCEPT ![i][j] = Append(msgs[i][j], m)]
SendPackets(i, j, ms) == msgs' = [msgs EXCEPT ![i][j] = msgs[i][j] \o ms ]
DiscardAndSendPackets(i, j, ms) == msgs' = [msgs EXCEPT ![j][i] = Tail(msgs[j][i]), 
                                                ![i][j] = msgs[i][j] \o ms ]

Discard(i, j) == msgs' = IF msgs[i][j] /= << >> THEN [msgs EXCEPT ![i][j] = Tail(msgs[i][j])]
                                                ELSE msgs

Broadcast(i, m) == msgs' = [msgs EXCEPT ![i] = [v \in Server |-> IF /\ v \in forwarding[i]
                                                                    /\ v /= i
                                                                 THEN Append(msgs[i][v], m)
                                                                 ELSE msgs[i][v]]]                                                           
DiscardAndBroadcast(i, j, m) ==
        msgs' = [msgs EXCEPT ![j][i] = Tail(msgs[j][i]),
                             ![i] = [v \in Server |-> IF /\ v \in forwarding[i]
                                                         /\ v /= i
                                                      THEN Append(msgs[i][v], m)
                                                      ELSE msgs[i][v]]]            

DiscardAndBroadcastLEADERINFO(i, j, m) ==
        LET new_connecting_quorum == {c \in connecting'[i]: c.connected = TRUE }
            new_sid_connecting == {c.sid: c \in new_connecting_quorum }
        IN 
        msgs' = [msgs EXCEPT ![j][i] = Tail(msgs[j][i]),
                             ![i] = [v \in Server |-> IF /\ v \in new_sid_connecting
                                                         /\ v \in learners[i] 
                                                         /\ v /= i
                                                      THEN Append(msgs[i][v], m)
                                                      ELSE msgs[i][v] ] ]

DiscardAndBroadcastUPTODATE(i, j, m) ==
        LET new_ackldRecv_quorum == {a \in ackldRecv'[i]: a.connected = TRUE }
            new_sid_ackldRecv == {a.sid: a \in new_ackldRecv_quorum}
        IN
        msgs' = [msgs EXCEPT ![j][i] = Tail(msgs[j][i]),
                             ![i] = [v \in Server |-> IF /\ v \in new_sid_ackldRecv
                                                         /\ v \in learners[i] 
                                                         /\ v /= i
                                                      THEN Append(msgs[i][v], m)
                                                      ELSE msgs[i][v] ] ]

Reply(i, j, m) == msgs' = [msgs EXCEPT ![j][i] = Tail(msgs[j][i]),
                                       ![i][j] = Append(msgs[i][j], m)]

Clean(i, j) == msgs' = [msgs EXCEPT ![j][i] = << >>, ![i][j] = << >>]     
CleanInputBuffer(i) == msgs' = [s \in Server |-> [v \in Server |-> IF v = i THEN << >>
                                                                   ELSE msgs[s][v]]]  
CleanInputBufferInCluster(S) == msgs' = [s \in Server |-> 
                                            [v \in Server |-> IF v \in S THEN << >>
                                                              ELSE msgs[s][v] ] ]                      

InitServerVars == /\ InitServerVarsL
                  /\ zabState      = [s \in Server |-> ELECTION]
                  /\ acceptedEpoch = [s \in Server |-> 0]
                  /\ lastCommitted = [s \in Server |-> [ index |-> 1,
                                                         zxid  |-> BootstrapZxid ] ]
                  /\ lastSnapshot  = [s \in Server |-> [ index |-> 0,
                                                         zxid  |-> <<0, 0>> ] ]
                  /\ initialHistory = [s \in Server |-> <<BootstrapTxn>>]

InitLeaderVars == /\ InitLeaderVarsL
                  /\ learners         = [s \in Server |-> {}]
                  /\ connecting       = [s \in Server |-> {}]
                  /\ electing         = [s \in Server |-> {}]
                  /\ ackldRecv        = [s \in Server |-> {}]
                  /\ forwarding       = [s \in Server |-> {}]
                  /\ tempMaxEpoch     = [s \in Server |-> 0]

InitElectionVars == InitElectionVarsL

InitFollowerVars == /\ connectInfo = [s \in Server |-> [sid |-> NullPoint,
                                                        syncMode |-> NONE,
                                                        nlRcv |-> FALSE ] ]
                    /\ packetsSync = [s \in Server |->
                                        [ notCommitted |-> << >>,
                                          committed    |-> << >> ] ]

InitVerifyVars == /\ proposalMsgsLog    = BootstrapProposalMsgs
                  /\ epochLeader        = [e \in 1..MAXEPOCH |-> {} ]
                   
InitMsgVars == /\ msgs         = [s \in Server |-> [v \in Server |-> << >>] ]
               /\ electionMsgs = [s \in Server |-> [v \in Server |-> << >>] ]

InitEnvVars == /\ status    = [s \in Server |-> ONLINE ]
               /\ partition = [s \in Server |-> [v \in Server |-> FALSE] ]
                
Init == /\ InitServerVars
        /\ InitLeaderVars
        /\ InitElectionVars
        /\ InitFollowerVars
        /\ InitVerifyVars
        /\ InitMsgVars
        /\ InitEnvVars
ZabTurnToLeading(i) ==
        /\ zabState'       = [zabState   EXCEPT ![i] = DISCOVERY]
        /\ learners'       = [learners   EXCEPT ![i] = {i}]
        /\ connecting'     = [connecting EXCEPT ![i] = { [ sid       |-> i,
                                                           connected |-> TRUE ] }]
        /\ electing'       = [electing   EXCEPT ![i] = { [ sid          |-> i,
                                                           peerLastZxid |-> <<-1,-1>>,
                                                           inQuorum     |-> TRUE ] }]
        /\ ackldRecv'      = [ackldRecv  EXCEPT ![i] = { [ sid       |-> i,
                                                           connected |-> TRUE ] }]
        /\ forwarding'     = [forwarding EXCEPT ![i] = {}]
        /\ initialHistory' = [initialHistory EXCEPT ![i] = history'[i]]
        /\ tempMaxEpoch'   = [tempMaxEpoch   EXCEPT ![i] = acceptedEpoch[i] + 1]

ZabTurnToFollowing(i) ==
        /\ zabState' = [zabState EXCEPT ![i] = DISCOVERY]
        /\ initialHistory' = [initialHistory EXCEPT ![i] = history'[i]]
        /\ packetsSync' = [packetsSync EXCEPT ![i].notCommitted = << >>, 
                                              ![i].committed = << >> ]

FLEReceiveNotmsg(i, j) ==
        /\ IsON(i)
        /\ ReceiveNotmsg(i, j)
        /\ UNCHANGED <<zabState, acceptedEpoch, lastCommitted, learners, connecting, 
                      initialHistory, electing, ackldRecv, forwarding, tempMaxEpoch,
                      lastSnapshot, followerVars, verifyVars, envVars, msgs>>

FLENotmsgTimeout(i) ==
        /\ TRUE 
        /\ IsON(i)
        /\ NotmsgTimeout(i)
        /\ UNCHANGED <<zabState, acceptedEpoch, lastCommitted, learners, connecting, 
                       initialHistory, electing, ackldRecv, forwarding, tempMaxEpoch, 
                       lastSnapshot, followerVars, verifyVars, envVars, msgs>>

FLEHandleNotmsg(i) ==
        /\ IsON(i)
        /\ HandleNotmsg(i)
        /\ LET newState == state'[i]
           IN
           \/ /\ newState = LEADING
              /\ ZabTurnToLeading(i)
              /\ UNCHANGED packetsSync
           \/ /\ newState = FOLLOWING
              /\ ZabTurnToFollowing(i)
              /\ UNCHANGED <<learners, connecting, electing, ackldRecv, 
                            forwarding, tempMaxEpoch>>
           \/ /\ newState = LOOKING
              /\ UNCHANGED <<zabState, learners, connecting, electing, ackldRecv,
                             forwarding, tempMaxEpoch, packetsSync, initialHistory>>
        /\ UNCHANGED <<lastCommitted, lastSnapshot, acceptedEpoch,
                       connectInfo, verifyVars, envVars, msgs>>

FLEWaitNewNotmsg(i) ==
        /\ IsON(i)
        /\ WaitNewNotmsg(i)
        /\ LET newState == state'[i]
           IN
           \/ /\ newState = LEADING
              /\ ZabTurnToLeading(i)
              /\ UNCHANGED packetsSync
           \/ /\ newState = FOLLOWING
              /\ ZabTurnToFollowing(i)
              /\ UNCHANGED <<learners, connecting, electing, ackldRecv, forwarding,
                             tempMaxEpoch>>
           \/ /\ newState = LOOKING
              /\ UNCHANGED <<zabState, learners, connecting, electing, ackldRecv,
                             forwarding, tempMaxEpoch, initialHistory, packetsSync>>
        /\ UNCHANGED <<lastCommitted, lastSnapshot, acceptedEpoch,
                       connectInfo, verifyVars, envVars, msgs>>
InitialVotes == [ vote    |-> InitialVote,
                  round   |-> 0,
                  state   |-> LOOKING,
                  version |-> 0 ]

InitialConnectInfo == [sid        |-> NullPoint,
                       syncMode   |-> NONE,
                       nlRcv      |-> FALSE ]

ZabTimeoutInCluster(S) ==
        /\ state' = [s \in Server |-> IF s \in S THEN LOOKING ELSE state[s] ]
        /\ lastProcessed' = [s \in Server |-> IF s \in S THEN InitLastProcessed(s)
                                                         ELSE lastProcessed[s] ]
        /\ logicalClock' = [s \in Server |-> IF s \in S THEN logicalClock[s] + 1 
                                                        ELSE logicalClock[s] ]
        /\ currentVote' = [s \in Server |-> IF s \in S THEN
                                                       [proposedLeader |-> s,
                                                        proposedZxid   |-> lastProcessed'[s].zxid,
                                                        proposedEpoch  |-> currentEpoch[s] ]
                                                       ELSE currentVote[s] ]
        /\ receiveVotes' = [s \in Server |-> IF s \in S THEN [v \in Server |-> InitialVotes]
                                                        ELSE receiveVotes[s] ]
        /\ outOfElection' = [s \in Server |-> IF s \in S THEN [v \in Server |-> InitialVotes]
                                                         ELSE outOfElection[s] ]
        /\ recvQueue' = [s \in Server |-> IF s \in S THEN << [mtype |-> NONE] >> 
                                                     ELSE recvQueue[s] ]
        /\ waitNotmsg' = [s \in Server |-> IF s \in S THEN FALSE ELSE waitNotmsg[s] ]
        /\ leadingVoteSet' = [s \in Server |-> IF s \in S THEN {} ELSE leadingVoteSet[s] ]
        /\ UNCHANGED <<electionMsgs, currentEpoch, history>>
        /\ zabState' = [s \in Server |-> IF s \in S THEN ELECTION ELSE zabState[s] ]
        /\ connectInfo' = [s \in Server |-> IF s \in S THEN InitialConnectInfo
                                                       ELSE connectInfo[s] ]
        /\ CleanInputBufferInCluster(S)

FollowerShutdown(i) ==
        /\ ZabTimeout(i)
        /\ zabState'    = [zabState    EXCEPT ![i] = ELECTION]
        /\ connectInfo' = [connectInfo EXCEPT ![i] = InitialConnectInfo]

LeaderShutdown(i) ==
        /\ LET cluster == {i} \union learners[i]
           IN ZabTimeoutInCluster(cluster)
        /\ learners'   = [learners   EXCEPT ![i] = {}]
        /\ forwarding' = [forwarding EXCEPT ![i] = {}]

RemoveElecting(set, sid) ==
        LET sid_electing == {s.sid: s \in set }
        IN IF sid \notin sid_electing THEN set
           ELSE LET info == CHOOSE s \in set: s.sid = sid
                    new_info == [ sid          |-> sid,
                                  peerLastZxid |-> <<-1, -1>>,
                                  inQuorum     |-> info.inQuorum ]
                IN (set \ {info}) \union {new_info}
RemoveConnectingOrAckldRecv(set, sid) ==
        LET sid_set == {s.sid: s \in set}
        IN IF sid \notin sid_set THEN set
           ELSE LET info == CHOOSE s \in set: s.sid = sid
                    new_info == [ sid       |-> sid,
                                  connected |-> FALSE ]
                IN (set \ {info}) \union {new_info}

RemoveLearner(i, j) ==
        /\ learners'   = [learners   EXCEPT ![i] = @ \ {j}] 
        /\ forwarding' = [forwarding EXCEPT ![i] = IF j \in forwarding[i] 
                                                   THEN @ \ {j} ELSE @ ]
        /\ electing'   = [electing   EXCEPT ![i] = RemoveElecting(@, j) ]
        /\ connecting' = [connecting EXCEPT ![i] = RemoveConnectingOrAckldRecv(@, j) ]
        /\ ackldRecv'  = [ackldRecv  EXCEPT ![i] = RemoveConnectingOrAckldRecv(@, j) ]

PartitionStart(i, j) ==
        /\ TRUE 
        /\ i /= j
        /\ IsON(i)
        /\ IsON(j)
        /\ \lnot HasPartitioned(i, j)
        /\ \/ /\ IsLeader(i)   /\ IsMyLearner(i, j)
              /\ IsFollower(j) /\ IsMyLeader(j, i)
              /\ LET newLearners == learners[i] \ {j}
                 IN \/ /\ IsQuorum(newLearners)   
                       /\ RemoveLearner(i, j)
                       /\ FollowerShutdown(j)
                       /\ Clean(i ,j)
                    \/ /\ ~IsQuorum(newLearners)  
                       /\ LeaderShutdown(i)
                       /\ UNCHANGED <<connecting, electing, ackldRecv>>
           \/ /\ IsLooking(i)
              /\ IsLooking(j)
              /\ IdCompare(i, j)
              /\ UNCHANGED <<varsL, zabState, connectInfo, msgs, learners,
                             forwarding, connecting, electing, ackldRecv>>
        /\ partition' = [partition EXCEPT ![i][j] = TRUE, ![j][i] = TRUE ]
        /\ UNCHANGED <<acceptedEpoch, lastCommitted, lastSnapshot, tempMaxEpoch,
                       initialHistory, verifyVars, packetsSync, status>>

PartitionRecover(i, j) ==
        /\ IsON(i)
        /\ IsON(j)
        /\ IdCompare(i, j)
        /\ HasPartitioned(i, j)
        /\ partition' = [partition EXCEPT ![i][j] = FALSE, ![j][i] = FALSE ]
        /\ UNCHANGED <<serverVars, leaderVars, electionVars, followerVars,
                       verifyVars, msgVars, status>>

NodeCrash(i) ==
        /\ TRUE 
        /\ IsON(i)
        /\ status' = [status EXCEPT ![i] = OFFLINE ]
        /\ \/ /\ IsLooking(i)
              /\ UNCHANGED <<varsL, zabState, connectInfo, msgs, learners,
                             forwarding, connecting, electing, ackldRecv>>
           \/ /\ IsFollower(i)
              /\ LET connectedWithLeader == HasLeader(i)
                 IN \/ /\ connectedWithLeader
                       /\ LET leader == connectInfo[i].sid
                              newCluster == learners[leader] \ {i}
                          IN 
                          \/ /\ IsQuorum(newCluster)
                             /\ RemoveLearner(leader, i) 
                             /\ FollowerShutdown(i)
                             /\ Clean(leader, i)
                          \/ /\ ~IsQuorum(newCluster)
                             /\ LeaderShutdown(leader)
                             /\ UNCHANGED <<electing, connecting, ackldRecv>>
                    \/ /\ ~connectedWithLeader
                       /\ FollowerShutdown(i)
                       /\ CleanInputBuffer({i})
                       /\ UNCHANGED <<learners, forwarding, connecting, electing, ackldRecv>>
           \/ /\ IsLeader(i)
              /\ LeaderShutdown(i)
              /\ UNCHANGED <<electing, connecting, ackldRecv>>
        /\ UNCHANGED <<acceptedEpoch, lastCommitted, lastSnapshot, tempMaxEpoch,
                       initialHistory, verifyVars, packetsSync, partition>>

NodeStart(i) ==
        /\ IsOFF(i)
        /\ status' = [status EXCEPT ![i] = ONLINE ]
        /\ lastProcessed' = [lastProcessed  EXCEPT ![i] = InitLastProcessed(i)]
        /\ lastCommitted' = [lastCommitted  EXCEPT ![i] = lastSnapshot[i]]
        /\ UNCHANGED <<state, currentEpoch, zabState, acceptedEpoch, history, 
                       lastSnapshot, initialHistory, leaderVars, electionVars, 
                       followerVars, verifyVars, msgVars, partition>>

ConnectAndFollowerSendFOLLOWERINFO(i, j) ==
        /\ IsON(i)     /\ IsON(j)
        /\ IsLeader(i) /\ \lnot IsMyLearner(i, j)
        /\ IsFollower(j) /\ HasNoLeader(j) /\ MyVote(j) = i
        /\ learners'   = [learners   EXCEPT ![i] = learners[i] \union {j}] 
        /\ connectInfo' = [connectInfo EXCEPT ![j].sid = i]
        /\ Send(j, i, [ mtype |-> FOLLOWERINFO,
                        mzxid |-> <<acceptedEpoch[j], 0>> ])  
        /\ UNCHANGED <<serverVars, electionVars, leadingVoteSet, connecting, 
                       electing, ackldRecv, forwarding, tempMaxEpoch,
                       verifyVars, envVars, electionMsgs, packetsSync>>

WaitingForNewEpoch(i, set) == (i \in set /\ IsQuorum(set)) = FALSE
WaitingForNewEpochTurnToFalse(i, set) == /\ i \in set
                                         /\ IsQuorum(set) 

UpdateConnectingOrAckldRecv(oldSet, sid) ==
        LET sid_set == {s.sid: s \in oldSet}
        IN IF sid \in sid_set
           THEN LET old_info == CHOOSE info \in oldSet: info.sid = sid
                    follower_info == [ sid       |-> sid,
                                       connected |-> TRUE ]
                IN (oldSet \ {old_info} ) \union {follower_info}
           ELSE LET follower_info == [ sid       |-> sid,
                                       connected |-> TRUE ]
                IN oldSet \union {follower_info}

LeaderProcessFOLLOWERINFO(i, j) ==
        /\ IsON(i)
        /\ IsLeader(i)
        /\ PendingFOLLOWERINFO(i, j)
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLearner(i, j)
               lastAcceptedEpoch == msg.mzxid[1]
               sid_connecting == {c.sid: c \in connecting[i]}
           IN 
           /\ infoOk
           /\ \/ 
                 /\ WaitingForNewEpoch(i, sid_connecting)
                 /\ \/ /\ zabState[i] = DISCOVERY
                    \/ /\ zabState[i] /= DISCOVERY
                 /\ tempMaxEpoch' = [tempMaxEpoch EXCEPT ![i] = IF lastAcceptedEpoch >= tempMaxEpoch[i] 
                                                                THEN lastAcceptedEpoch + 1
                                                                ELSE @]
                 /\ connecting'   = [connecting   EXCEPT ![i] = UpdateConnectingOrAckldRecv(@, j) ]
                 /\ LET new_sid_connecting == {c.sid: c \in connecting'[i]}
                    IN
                    \/ /\ WaitingForNewEpochTurnToFalse(i, new_sid_connecting)
                       /\ acceptedEpoch' = [acceptedEpoch EXCEPT ![i] = tempMaxEpoch'[i]]
                       /\ LET newLeaderZxid == <<acceptedEpoch'[i], 0>>
                              m == [ mtype |-> LEADERINFO,
                                     mzxid |-> newLeaderZxid ]
                          IN DiscardAndBroadcastLEADERINFO(i, j, m)
                    \/ /\ ~WaitingForNewEpochTurnToFalse(i, new_sid_connecting)
                       /\ Discard(j, i)
                       /\ UNCHANGED acceptedEpoch
              \/  
                 /\ ~WaitingForNewEpoch(i, sid_connecting)
                 /\ Reply(i, j, [ mtype |-> LEADERINFO,
                                  mzxid |-> <<acceptedEpoch[i], 0>> ] )
                 /\ UNCHANGED <<tempMaxEpoch, connecting, acceptedEpoch>>
        /\ UNCHANGED <<state, currentEpoch, lastProcessed, zabState, history, lastCommitted, 
                       followerVars, electionVars, initialHistory, leadingVoteSet, learners, 
                       electing, ackldRecv, forwarding, proposalMsgsLog, epochLeader, 
                       lastSnapshot, electionMsgs, envVars>>

FollowerProcessLEADERINFO(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingLEADERINFO(i, j)
        /\ LET msg      == msgs[j][i][1]
               newEpoch == msg.mzxid[1]
               infoOk   == IsMyLeader(i, j)
               epochOk  == newEpoch >= acceptedEpoch[i]
               stateOk  == zabState[i] = DISCOVERY
           IN /\ infoOk
              /\ \/ 
                    /\ epochOk   
                    /\ \/ /\ stateOk
                          /\ \/ /\ newEpoch > acceptedEpoch[i]
                                /\ acceptedEpoch' = [acceptedEpoch EXCEPT ![i] = newEpoch]
                                /\ LET epochBytes == currentEpoch[i]
                                       m == [ mtype  |-> ACKEPOCH,
                                              mzxid  |-> lastProcessed[i].zxid, 
                                              mepoch |-> epochBytes ] 
                                   IN Reply(i, j, m)
                             \/ /\ newEpoch = acceptedEpoch[i]
                                /\ LET m == [ mtype  |-> ACKEPOCH,
                                              mzxid  |-> lastProcessed[i].zxid,
                                              mepoch |-> -1 ]
                                   IN Reply(i, j, m)
                                /\ UNCHANGED acceptedEpoch
                          /\ zabState' = [zabState EXCEPT ![i] = SYNCHRONIZATION]
                       \/ /\ ~stateOk
                          /\ Discard(j, i)
                          /\ UNCHANGED <<acceptedEpoch, zabState>>
                    /\ UNCHANGED <<varsL, connectInfo, learners, forwarding, electing,
                                   connecting, ackldRecv>>
                 \/ 
                    /\ ~epochOk 
                    /\ FollowerShutdown(i)
                    /\ Clean(i, connectInfo[i].sid)
                    /\ RemoveLearner(connectInfo[i].sid, i)
                    /\ UNCHANGED <<acceptedEpoch>>
        /\ UNCHANGED <<history, lastCommitted, tempMaxEpoch, initialHistory, lastSnapshot,
                       proposalMsgsLog, epochLeader, packetsSync, envVars>>
UpdateAckSidHelper(his, cur, end, target) ==
        LET updateTxn(txn) == [ zxid   |-> txn.zxid,
                                value  |-> txn.value,
                                ackSid |-> IF target \in txn.ackSid THEN txn.ackSid
                                           ELSE txn.ackSid \union {target},
                                epoch  |-> txn.epoch ]
            numToProcess == end - cur + 1
        IN [i \in 1..Len(his) |-> IF i <= numToProcess THEN updateTxn(his[i]) ELSE his[i]]

UpdateAckSid(his, lastSeenIndex, target) ==
        IF Len(his) = 0 \/ lastSeenIndex = 0 THEN his
        ELSE UpdateAckSidHelper(his, 1, Minimum( { Len(his), lastSeenIndex} ), target)

ZxidToIndexHepler(his, zxid, cur, appeared) == 
        LET matches == {i \in cur..Len(his) : TxnZxidEqual(his[i], zxid)}
        IN IF appeared = TRUE THEN (IF matches = {} THEN Len(his) + 1 ELSE -1)
           ELSE CASE Cardinality(matches) = 0 -> Len(his) + 1
                []   Cardinality(matches) = 1 -> CHOOSE i \in matches : TRUE
                []   OTHER -> -1

ZxidToIndex(his, zxid) == IF ZxidEqual( zxid, <<0, 0>> ) THEN 0
                          ELSE IF Len(his) = 0 THEN 1
                               ELSE LET len == Len(his) IN
                                    IF \E idx \in 1..len: TxnZxidEqual(his[idx], zxid)
                                    THEN ZxidToIndexHepler(his, zxid, 1, FALSE)
                                    ELSE len + 1

IndexOfZxidHelper(his, zxid, cur, end) ==
        LET greaterIndices == {i \in cur..end : ZxidCompare(his[i].zxid, zxid)}
        IN IF greaterIndices = {} THEN end
           ELSE (CHOOSE i \in greaterIndices : \A j \in greaterIndices : i <= j) - 1

IndexOfZxid(his, zxid) == IF Len(his) = 0 THEN 0
                          ELSE LET idx == ZxidToIndex(his, zxid)
                                   len == Len(his)
                               IN 
                               IF idx <= len THEN idx
                               ELSE IndexOfZxidHelper(his, zxid, 1, len)

queuePackets(queue, his, cur, committed, end) == 
        LET packets(i) == IF i <= committed 
                          THEN << [ mtype |-> PROPOSAL, mzxid |-> his[i].zxid, mdata |-> his[i].value ],
                                  [ mtype |-> COMMIT,   mzxid |-> his[i].zxid ] >>
                          ELSE << [ mtype |-> PROPOSAL, mzxid |-> his[i].zxid, mdata |-> his[i].value ] >>
            F[n \in Nat] == IF n < cur THEN queue
                            ELSE F[n - 1] \o packets(n)
        IN IF end < cur THEN queue ELSE F[end]

setPacketsForChecking(set, src, ep, his, cur, end) ==
        set \union { [ source |-> src,
                       epoch  |-> ep,
                       zxid   |-> his[i].zxid,
                       data   |-> his[i].value ] : i \in cur..end }

SerializeSnapshot(i, idx) == IF idx <= 0 THEN << >>
                             ELSE SubSeq(history[i], 1, idx)

SendSyncMsgs(i, j, lastSeenZxid, lastSeenIndex, mode, needRemoveHead) ==
        /\ LET lastCommittedIndex == IF zabState[i] = BROADCAST 
                                     THEN lastCommitted[i].index
                                     ELSE Len(history[i])
               lastProposedIndex  == Len(history[i])
               queue_origin == IF lastSeenIndex >= lastProposedIndex 
                               THEN << >>
                               ELSE queuePackets(<< >>, history[i], 
                                    lastSeenIndex + 1, lastCommittedIndex,
                                    lastProposedIndex)
               set_forChecking == IF lastSeenIndex >= lastProposedIndex 
                                  THEN {}
                                  ELSE setPacketsForChecking( { }, i, 
                                        acceptedEpoch[i], history[i],
                                        lastSeenIndex + 1, lastProposedIndex)
               m_trunc == [ mtype |-> TRUNC, mtruncZxid |-> lastSeenZxid ]
               m_diff  == [ mtype |-> DIFF,  mzxid |-> lastSeenZxid ]
               m_snap  == [ mtype |-> SNAP,  msnapZxid |-> lastSeenZxid,
                                             msnapshot |-> SerializeSnapshot(i, lastSeenIndex) ]
               newLeaderZxid == <<acceptedEpoch[i], 0>>
               m_newleader == [ mtype |-> NEWLEADER,
                                mzxid |-> newLeaderZxid ]
               queue_toSend == CASE mode = TRUNC -> (<<m_trunc>> \o queue_origin) \o <<m_newleader>>
                               []   mode = DIFF  -> (<<m_diff>>  \o queue_origin) \o <<m_newleader>>
                               []   mode = SNAP  -> (<<m_snap>>  \o queue_origin) \o <<m_newleader>>
           IN /\ \/ /\ needRemoveHead
                    /\ DiscardAndSendPackets(i, j, queue_toSend)
                 \/ /\ ~needRemoveHead
                    /\ SendPackets(i, j, queue_toSend)
              /\ proposalMsgsLog' = proposalMsgsLog \union set_forChecking
        /\ forwarding' = [forwarding EXCEPT ![i] = @ \union {j} ]
        /\ \/ /\ mode = TRUNC \/ mode = DIFF 
              /\ history' = [history EXCEPT ![i] = UpdateAckSid(@, lastSeenIndex, j) ]
           \/ /\ mode = SNAP
              /\ UNCHANGED history 

SyncFollower(i, j, peerLastZxid, needRemoveHead) ==
        LET 
            lastProcessedZxid == lastProcessed[i].zxid
            minCommittedIdx   == lastSnapshot[i].index + 1
            maxCommittedIdx   == IF zabState[i] = BROADCAST THEN lastCommitted[i].index
                                 ELSE Len(history[i])
            committedLogEmpty == minCommittedIdx > maxCommittedIdx
            minCommittedLog   == IF committedLogEmpty THEN lastProcessedZxid
                                 ELSE history[i][minCommittedIdx].zxid
            maxCommittedLog   == IF committedLogEmpty THEN lastProcessedZxid
                                 ELSE IF maxCommittedIdx = 0 THEN << 0, 0>>
                                      ELSE history[i][maxCommittedIdx].zxid

        IN \/ 
              
              /\ ZxidEqual(peerLastZxid, lastProcessedZxid)
              /\ SendSyncMsgs(i, j, peerLastZxid, lastProcessed[i].index, 
                                    DIFF, needRemoveHead)
           \/ /\ ~ZxidEqual(peerLastZxid, lastProcessedZxid)
              /\ \/ 
                    
                    /\ ZxidCompare(peerLastZxid, maxCommittedLog)
                    /\ SendSyncMsgs(i, j, maxCommittedLog, maxCommittedIdx, 
                                          TRUNC, needRemoveHead)
                 \/ 
                    /\ ~ZxidCompare(peerLastZxid, maxCommittedLog)
                    /\ ~ZxidCompare(minCommittedLog, peerLastZxid)
                    /\ LET lastSeenIndex == ZxidToIndex(history[i], peerLastZxid)
                           exist == /\ lastSeenIndex >= minCommittedIdx
                                    /\ lastSeenIndex <= Len(history[i])
                           lastIndex == IF exist THEN lastSeenIndex
                                        ELSE IndexOfZxid(history[i], peerLastZxid)
                           
                           lastZxid  == IF exist THEN peerLastZxid
                                        ELSE IF lastIndex = 0 THEN <<0, 0>>
                                             ELSE history[i][lastIndex].zxid
                       IN 
                       \/ 

                          /\ exist
                          /\ SendSyncMsgs(i, j, peerLastZxid, lastSeenIndex, 
                                                DIFF, needRemoveHead)
                       \/ 

                          /\ ~exist
                          /\ SendSyncMsgs(i, j, lastZxid, lastIndex, 
                                                TRUNC, needRemoveHead)
                 \/ 
                    
                    /\ ZxidCompare(minCommittedLog, peerLastZxid)
                    /\ SendSyncMsgs(i, j, lastProcessedZxid, maxCommittedIdx,
                                          SNAP, needRemoveHead)

IsMoreRecentThan(ss1, ss2) == \/ ss1.currentEpoch > ss2.currentEpoch
                              \/ /\ ss1.currentEpoch = ss2.currentEpoch
                                 /\ ZxidCompare(ss1.lastZxid, ss2.lastZxid)

ElectionFinished(i, set) == /\ i \in set
                            /\ IsQuorum(set)

UpdateElecting(oldSet, sid, peerLastZxid, inQuorum) ==
        LET sid_electing == {s.sid: s \in oldSet }
        IN IF sid \in sid_electing 
           THEN LET old_info == CHOOSE info \in oldSet : info.sid = sid
                    follower_info == 
                             [ sid          |-> sid,
                               peerLastZxid |-> peerLastZxid,
                               inQuorum     |-> (inQuorum \/ old_info.inQuorum) ]
                IN (oldSet \ {old_info} ) \union {follower_info}
           ELSE LET follower_info == 
                             [ sid          |-> sid,
                               peerLastZxid |-> peerLastZxid,
                               inQuorum     |-> inQuorum ]
                IN oldSet \union {follower_info}

LeaderTurnToSynchronization(i) ==
        /\ currentEpoch' = [currentEpoch EXCEPT ![i] = acceptedEpoch[i]]
        /\ zabState'     = [zabState     EXCEPT ![i] = SYNCHRONIZATION]

LeaderProcessACKEPOCH(i, j) ==
        /\ IsON(i)
        /\ IsLeader(i)
        /\ PendingACKEPOCH(i, j)
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLearner(i, j)           
               leaderStateSummary   == [ currentEpoch |-> currentEpoch[i], 
                                         lastZxid     |-> lastProcessed[i].zxid ]
               followerStateSummary == [ currentEpoch |-> msg.mepoch,  
                                         lastZxid     |-> msg.mzxid ]
               logOk == 
                        ~IsMoreRecentThan(followerStateSummary, leaderStateSummary)
               electing_quorum == {e \in electing[i]: e.inQuorum = TRUE }
               sid_electing == {s.sid: s \in electing_quorum }
           IN /\ infoOk
              /\ \/ 

                    /\ ElectionFinished(i, sid_electing)
                    /\ electing' = [electing EXCEPT ![i] = UpdateElecting(@, j, msg.mzxid, FALSE) ]
                    /\ Discard(j, i)
                    /\ UNCHANGED <<varsL, zabState, forwarding, connectInfo, 
                                   learners, epochLeader>>
                 \/ /\ ~ElectionFinished(i, sid_electing)
                    /\ \/ /\ zabState[i] = DISCOVERY
                       \/ /\ zabState[i] /= DISCOVERY
                    /\ \/ /\ followerStateSummary.currentEpoch = -1
                          /\ electing' = [electing EXCEPT ![i] = UpdateElecting(@, j, 
                                                                msg.mzxid, FALSE) ]
                          /\ Discard(j, i)
                          /\ UNCHANGED <<varsL, zabState, forwarding, connectInfo, 
                                         learners, epochLeader>>
                       \/ /\ followerStateSummary.currentEpoch > -1
                          /\ \/ 
                                /\ logOk
                                /\ electing' = [electing EXCEPT ![i] = 
                                            UpdateElecting(@, j, msg.mzxid, TRUE) ]
                                /\ LET new_electing_quorum == {e \in electing'[i]: e.inQuorum = TRUE }
                                       new_sid_electing == {s.sid: s \in new_electing_quorum }
                                   IN 
                                   \/ 
                                      
                                      /\ ElectionFinished(i, new_sid_electing) 
                                      /\ LeaderTurnToSynchronization(i)
                                      /\ LET newLeaderEpoch == acceptedEpoch[i]
                                         IN epochLeader' = [epochLeader EXCEPT ![newLeaderEpoch]
                                                = @ \union {i} ] 
                                   \/ 
                                      /\ ~ElectionFinished(i, new_sid_electing)
                                      /\ UNCHANGED <<currentEpoch, zabState, epochLeader>>
                                /\ Discard(j, i)
                                /\ UNCHANGED <<state, lastProcessed, electionVars, leadingVoteSet,
                                               electionMsgs, connectInfo, learners, history, forwarding>>
                             \/ 
                                /\ ~logOk 
                                /\ LeaderShutdown(i)
                                /\ UNCHANGED <<electing, epochLeader>>
        /\ UNCHANGED <<acceptedEpoch, lastCommitted, lastSnapshot, connecting, ackldRecv,
                       tempMaxEpoch, initialHistory, packetsSync, proposalMsgsLog, envVars>>

LeaderSyncFollower(i, j) ==
        /\ IsON(i)
        /\ IsLeader(i)
        /\ LET electing_quorum == {e \in electing[i]: e.inQuorum = TRUE }
               electionFinished == ElectionFinished(i, {s.sid: s \in electing_quorum } )
               toSync == {s \in electing[i] : /\ ~ZxidEqual( s.peerLastZxid, <<-1, -1>>)
                                              /\ s.sid \in learners[i] }
               canSync == toSync /= {}
           IN
           /\ electionFinished
           /\ canSync
           /\ \E s \in toSync: s.sid = j
           /\ LET chosen == CHOOSE s \in toSync: s.sid = j
                  newChosen == [ sid          |-> chosen.sid,
                                 peerLastZxid |-> <<-1, -1>>, 
                                 inQuorum     |-> chosen.inQuorum ] 
              IN /\ SyncFollower(i, chosen.sid, chosen.peerLastZxid, FALSE)
                 /\ electing' = [electing EXCEPT ![i] = (@ \ {chosen}) \union {newChosen} ]
        /\ UNCHANGED <<state, currentEpoch, lastProcessed, zabState, acceptedEpoch, 
                    lastCommitted, initialHistory, electionVars, leadingVoteSet,
                    learners, connecting, ackldRecv, tempMaxEpoch, followerVars, 
                    lastSnapshot, epochLeader, electionMsgs, envVars>>

TruncateLog(his, index) == IF index <= 0 THEN << >>
                           ELSE SubSeq(his, 1, index)

FollowerProcessSyncMessage(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ msgs[j][i] /= << >>
        /\ \/ msgs[j][i][1].mtype = DIFF 
           \/ msgs[j][i][1].mtype = TRUNC
           \/ msgs[j][i][1].mtype = SNAP
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               stateOk == zabState[i] = SYNCHRONIZATION
           IN /\ infoOk
              /\ \/ 
                    /\ ~stateOk
                    /\ UNCHANGED <<history, initialHistory, lastProcessed, lastCommitted, connectInfo>>
                 \/ /\ stateOk
                    /\ \/ /\ msg.mtype = DIFF
                          /\ connectInfo' = [connectInfo EXCEPT ![i].syncMode = DIFF]         
                          /\ UNCHANGED <<history, initialHistory, lastProcessed, lastCommitted>>
                       \/ /\ msg.mtype = TRUNC
                          /\ connectInfo' = [connectInfo EXCEPT ![i].syncMode = TRUNC]
                          /\ LET truncZxid  == msg.mtruncZxid
                                 truncIndex == ZxidToIndex(history[i], truncZxid)
                                 truncOk    == /\ truncIndex >= lastCommitted[i].index
                                               /\ truncIndex <= Len(history[i])
                             IN
                             \/ /\ ~truncOk
                                /\ UNCHANGED <<history, initialHistory, lastProcessed, lastCommitted>>
                             \/ /\ truncOk
                                /\ history' = [history EXCEPT 
                                                    ![i] = TruncateLog(history[i], truncIndex)]
                                /\ initialHistory' = [initialHistory EXCEPT ![i] = history'[i]]
                                /\ lastProcessed' = [lastProcessed EXCEPT 
                                                    ![i] = [ index |-> truncIndex,
                                                             zxid  |-> truncZxid] ]
                                /\ lastCommitted' = [lastCommitted EXCEPT 
                                                    ![i] = [ index |-> truncIndex,
                                                             zxid  |-> truncZxid] ]
                       \/ /\ msg.mtype = SNAP
                          /\ connectInfo' = [connectInfo EXCEPT ![i].syncMode = SNAP]
                          /\ history' = [history EXCEPT ![i] = msg.msnapshot]
                          /\ initialHistory' = [initialHistory EXCEPT ![i] = history'[i]]
                          /\ lastProcessed' = [lastProcessed EXCEPT 
                                                    ![i] = [ index |-> Len(history'[i]),
                                                             zxid  |-> msg.msnapZxid] ]
                          /\ lastCommitted' = [lastCommitted EXCEPT 
                                                    ![i] = [ index |-> Len(history'[i]),
                                                             zxid  |-> msg.msnapZxid] ]
        /\ Discard(j, i)
        /\ UNCHANGED <<state, currentEpoch, zabState, acceptedEpoch, electionVars,
                       leaderVars, tempMaxEpoch, packetsSync, lastSnapshot,
                       proposalMsgsLog, epochLeader, electionMsgs, envVars>>

SnapshotNeeded(i) == \/ connectInfo[i].syncMode = TRUNC
                     \/ connectInfo[i].syncMode = SNAP

WriteToTxnLog(i) == IF \/ connectInfo[i].syncMode = DIFF
                       \/ connectInfo[i].nlRcv = TRUE
                    THEN TRUE ELSE FALSE

LastProposed(i) == IF Len(history[i]) = 0 THEN [ index |-> 0, 
                                                 zxid  |-> <<0, 0>> ]
                   ELSE
                   LET lastIndex == Len(history[i])
                       entry     == history[i][lastIndex]
                   IN [ index |-> lastIndex,
                        zxid  |-> entry.zxid ]

LastQueued(i) == IF ~IsFollower(i) \/ zabState[i] /= SYNCHRONIZATION 
                 THEN LastProposed(i)
                 ELSE 
                      LET packetsInSync == packetsSync[i].notCommitted
                          lenSync  == Len(packetsInSync)
                          totalLen == Len(history[i]) + lenSync
                      IN IF lenSync = 0 THEN LastProposed(i)
                         ELSE [ index |-> totalLen,
                                zxid  |-> packetsInSync[lenSync].zxid ]

IsNextZxid(curZxid, nextZxid) ==
            \/ 
               /\ nextZxid[2] = 1
               /\ curZxid[1] < nextZxid[1]
            \/ 
               /\ nextZxid[2] > 1
               /\ curZxid[1] = nextZxid[1]
               /\ curZxid[2] + 1 = nextZxid[2]

FollowerProcessPROPOSALInSync(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingPROPOSAL(i, j)
        /\ zabState[i] = SYNCHRONIZATION
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               isNext == IsNextZxid(LastQueued(i).zxid, msg.mzxid)
               newTxn == [ zxid   |-> msg.mzxid,
                           value  |-> msg.mdata,
                           ackSid |-> {},    
                           epoch  |-> acceptedEpoch[i] ] 
           IN /\ infoOk
              /\ \/ /\ isNext
                    /\ packetsSync' = [packetsSync EXCEPT ![i].notCommitted 
                                = Append(packetsSync[i].notCommitted, newTxn) ]
                 \/ /\ ~isNext
                    /\ UNCHANGED packetsSync

        /\ Discard(j, i)
        /\ UNCHANGED <<serverVars, electionVars, leaderVars, connectInfo,
                       verifyVars, electionMsgs, envVars>>

LastCommitted(i) == IF zabState[i] = BROADCAST THEN lastCommitted[i]
                    ELSE CASE IsLeader(i)   -> 
                            LET lastInitialIndex == Len(initialHistory[i])
                            IN IF lastInitialIndex = 0 THEN [ index |-> 0,
                                                              zxid  |-> <<0, 0>> ]
                               ELSE [ index |-> lastInitialIndex,
                                      zxid  |-> history[i][lastInitialIndex].zxid ]
                         []   IsFollower(i) ->
                            LET completeHis == history[i] \o packetsSync[i].notCommitted
                                packetsCommitted == packetsSync[i].committed
                                lenCommitted == Len(packetsCommitted)
                            IN IF lenCommitted = 0 
                               THEN LET lastIndex == Len(history[i])
                                        lastInitialIndex == Len(initialHistory[i])
                                    IN IF lastIndex = lastInitialIndex
                                       THEN IF lastIndex = 0
                                            THEN [ index |-> 0,
                                                   zxid  |-> <<0, 0>> ]
                                            ELSE [ index |-> lastIndex ,
                                                   zxid  |-> history[i][lastIndex].zxid ]
                                       ELSE IF lastInitialIndex < lastCommitted[i].index
                                            THEN lastCommitted[i]
                                            ELSE IF lastInitialIndex = 0
                                                 THEN [ index |-> 0,
                                                        zxid  |-> <<0, 0>> ]
                                                 ELSE [ index |-> lastInitialIndex,
                                                        zxid  |-> history[i][lastInitialIndex].zxid ]
                               ELSE                
                                    LET committedIndex == ZxidToIndex(completeHis, 
                                                     packetsCommitted[lenCommitted] )
                                    IN [ index |-> committedIndex, 
                                         zxid  |-> packetsCommitted[lenCommitted] ]
                         []   OTHER -> lastCommitted[i]

TxnWithIndex(i, idx) == IF ~IsFollower(i) \/ zabState[i] /= SYNCHRONIZATION 
                        THEN history[i][idx]
                        ELSE LET completeHis == history[i] \o packetsSync[i].notCommitted
                             IN completeHis[idx]

FollowerProcessCOMMITInSync(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingCOMMIT(i, j)
        /\ zabState[i] = SYNCHRONIZATION
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               committedIndex == LastCommitted(i).index + 1
               exist == /\ committedIndex <= LastQueued(i).index
                        /\ IsNextZxid(LastCommitted(i).zxid, msg.mzxid)
               match == ZxidEqual(msg.mzxid, TxnWithIndex(i, committedIndex).zxid )
           IN /\ infoOk 
              /\ \/ /\ exist
                    /\ \/ /\ match
                          /\ LET writeToTxnLog == WriteToTxnLog(i)
                             IN
                             \/ /\ ~writeToTxnLog 
                                /\ LET committedTxn == packetsSync[i].notCommitted[1]
                                   IN 
                                   /\ history' = [ history EXCEPT ![i] 
                                               = Append(@, committedTxn)]
                                   /\ lastCommitted' = [ lastCommitted EXCEPT ![i]
                                                     = [index |-> Len(history'[i]),
                                                        zxid  |-> committedTxn.zxid ] ]
                                   /\ lastProcessed' = [ lastProcessed EXCEPT ![i]
                                                     = lastCommitted'[i] ]
                                   /\ packetsSync' = [ packetsSync EXCEPT ![i].notCommitted
                                                   = Tail(@) ]
                             \/ /\ writeToTxnLog  
                                /\ packetsSync' = [ packetsSync EXCEPT ![i].committed
                                                = Append(packetsSync[i].committed, msg.mzxid) ]
                                /\ UNCHANGED <<history, lastCommitted, lastProcessed>>
                       \/ /\ ~match
                          /\ UNCHANGED <<history, lastCommitted, lastProcessed, packetsSync>>
                 \/ /\ ~exist
                    /\ UNCHANGED <<history, lastCommitted, lastProcessed, packetsSync>>
        /\ Discard(j, i)
        /\ UNCHANGED <<state, currentEpoch, zabState, acceptedEpoch,
                       lastSnapshot, initialHistory, electionVars, leaderVars,
                       connectInfo, epochLeader, proposalMsgsLog, electionMsgs, envVars>>

ShouldSnapshot(i) == lastCommitted[i].index - lastSnapshot[i].index >= 2

 TakeSnapshot(i) == LET snapOk == lastSnapshot[i].index <= lastCommitted[i].index
                    IN \/ /\ snapOk
                          /\ lastSnapshot' = [ lastSnapshot EXCEPT ![i] = lastCommitted[i] ]
                       \/ /\ ~snapOk
                          /\ UNCHANGED lastSnapshot

ACKInBatches(queue, packets) ==
        queue \o [i \in 1..Len(packets) |-> [ mtype |-> ACK,
                                               mzxid |-> packets[i].zxid ]]

FollowerProcessNEWLEADER(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingNEWLEADER(i, j)
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               packetsInSync == packetsSync[i].notCommitted
               m_ackld == [ mtype |-> ACKLD,
                            mzxid |-> msg.mzxid ]
               ms_ack  == ACKInBatches( << >>, packetsInSync )
               queue_toSend == <<m_ackld>> \o ms_ack 
           IN /\ infoOk
              /\ currentEpoch' = [currentEpoch EXCEPT ![i] = acceptedEpoch[i] ]
              /\ history'      = [history      EXCEPT ![i] = @ \o packetsInSync ]
              /\ packetsSync'  = [packetsSync  EXCEPT ![i].notCommitted = << >> ]
              /\ connectInfo'  = [connectInfo  EXCEPT ![i].nlRcv = TRUE,
                                                      ![i].syncMode = NONE ]
              /\ \/ /\ SnapshotNeeded(i)
                    /\ TakeSnapshot(i)
                 \/ /\ ~SnapshotNeeded(i)
                    /\ UNCHANGED <<lastSnapshot>>
              /\ DiscardAndSendPackets(i, j, queue_toSend)
        /\ UNCHANGED <<state, lastProcessed, zabState, acceptedEpoch, lastCommitted, 
                       electionVars, leaderVars, initialHistory,
                       proposalMsgsLog, epochLeader, electionMsgs, envVars>>

QuorumFormed(i, set) == i \in set /\ IsQuorum(set)

UpdateElectionVote(i, epoch) == UpdateProposal(i, currentVote[i].proposedLeader,
                                    currentVote[i].proposedZxid, epoch)

StartZkServer(i) ==
        LET latest == LastProposed(i)
        IN /\ lastCommitted' = [lastCommitted EXCEPT ![i] = latest]
           /\ lastProcessed' = [lastProcessed EXCEPT ![i] = latest]
           /\ lastSnapshot'  = [lastSnapshot  EXCEPT ![i] = latest]
           /\ UpdateElectionVote(i, acceptedEpoch[i])

LeaderTurnToBroadcast(i) ==
        /\ StartZkServer(i)
        /\ zabState' = [zabState EXCEPT ![i] = BROADCAST]

LeaderProcessACKLD(i, j) ==
        /\ IsON(i)
        /\ IsLeader(i)
        /\ PendingACKLD(i, j)
        /\ LET msg    == msgs[j][i][1]
               infoOk == IsMyLearner(i, j)
               match  == ZxidEqual(msg.mzxid, <<acceptedEpoch[i], 0>>)
               currentZxid == <<acceptedEpoch[i], 0>>
               m_uptodate == [ mtype |-> UPTODATE,
                               mzxid |-> currentZxid ] 
               sid_ackldRecv == {a.sid: a \in ackldRecv[i]}
           IN /\ infoOk
              /\ \/ 
                    /\ QuorumFormed(i, sid_ackldRecv)
                    /\ Reply(i, j, m_uptodate)
                    /\ UNCHANGED <<ackldRecv, zabState, lastCommitted, lastProcessed,
                                   lastSnapshot, currentVote>>
                 \/ /\ ~QuorumFormed(i, sid_ackldRecv)
                    /\ \/ /\ match
                          /\ ackldRecv' = [ackldRecv EXCEPT ![i] = UpdateConnectingOrAckldRecv(@, j) ]
                          /\ LET new_sid_ackldRecv == {a.sid: a \in ackldRecv'[i]}
                             IN
                             \/ 
                                
                                /\ QuorumFormed(i, new_sid_ackldRecv)
                                /\ LeaderTurnToBroadcast(i)
                                /\ DiscardAndBroadcastUPTODATE(i, j, m_uptodate)
                             \/ 
                                /\ ~QuorumFormed(i, new_sid_ackldRecv)
                                /\ Discard(j, i)
                                /\ UNCHANGED <<zabState, lastCommitted, lastProcessed,
                                               lastSnapshot, currentVote>>
                       \/ /\ ~match
                          /\ Discard(j, i)
                          /\ UNCHANGED <<ackldRecv, zabState, lastCommitted, 
                                         lastSnapshot, lastProcessed, currentVote>>
        /\ UNCHANGED <<state, currentEpoch, acceptedEpoch, history, logicalClock, receiveVotes, 
                    outOfElection, recvQueue, waitNotmsg, leadingVoteSet, learners, connecting, 
                    electing, forwarding, tempMaxEpoch, initialHistory, followerVars, 
                    proposalMsgsLog, epochLeader, electionMsgs ,envVars>>

PendingTxns(i) == IF ~IsFollower(i) \/ zabState[i] /= SYNCHRONIZATION 
                  THEN SubSeq(history[i], lastCommitted[i].index + 1, Len(history[i]))
                  ELSE LET packetsCommitted == packetsSync[i].committed
                           completeHis == history[i] \o packetsSync[i].notCommitted
                       IN IF Len(packetsCommitted) = 0 
                          THEN SubSeq(completeHis, Len(history[i]) + 1, Len(completeHis))
                          ELSE SubSeq(completeHis, LastCommitted(i).index + 1, Len(completeHis))

CommittedTxns(i) == IF ~IsFollower(i) \/ zabState[i] /= SYNCHRONIZATION 
                    THEN SubSeq(history[i], 1, lastCommitted[i].index)
                    ELSE LET packetsCommitted == packetsSync[i].committed
                             completeHis == history[i] \o packetsSync[i].notCommitted
                         IN IF Len(packetsCommitted) = 0 THEN history[i]
                            ELSE SubSeq( completeHis, 1, LastCommitted(i).index )

TxnsAndCommittedMatch(txns, packetsCommitted) ==
        LET len1 == Len(txns)
            len2 == Len(packetsCommitted)
        IN IF len2 = 0 THEN TRUE 
           ELSE IF len1 < len2 THEN FALSE 
                ELSE \A i \in 1..len2 : 
                       ZxidEqual(txns[len1 - len2 + i].zxid, packetsCommitted[i])

FollowerLogRequestInBatches(i, leader, ms_ack, packetsNotCommitted) ==
        /\ history' = [history EXCEPT ![i] = @ \o packetsNotCommitted ]
        /\ DiscardAndSendPackets(i, leader, ms_ack)

FollowerCommitInBatches(i) ==
        LET committedTxns == CommittedTxns(i)
            packetsCommitted == packetsSync[i].committed
            match == TxnsAndCommittedMatch(committedTxns, packetsCommitted)
        IN 
        \/ /\ match 
           /\ lastCommitted' = [lastCommitted EXCEPT ![i] = LastCommitted(i)]
           /\ lastProcessed' = [lastProcessed EXCEPT ![i] = lastCommitted'[i]]
        \/ /\ ~match
           /\ UNCHANGED <<lastCommitted, lastProcessed>>

FollowerProcessUPTODATE(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingUPTODATE(i, j)
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               packetsNotCommitted == packetsSync[i].notCommitted
               ms_ack == ACKInBatches(<< >>, packetsNotCommitted)
           IN /\ infoOk
              
              /\ UpdateElectionVote(i, acceptedEpoch[i])
              /\ FollowerLogRequestInBatches(i, j, ms_ack, packetsNotCommitted)
              /\ FollowerCommitInBatches(i)
              /\ packetsSync' = [packetsSync EXCEPT ![i].notCommitted = << >>,
                                                    ![i].committed = << >> ]
              /\ zabState' = [zabState EXCEPT ![i] = BROADCAST ]
        /\ UNCHANGED <<state, currentEpoch, acceptedEpoch, logicalClock, lastSnapshot,
                receiveVotes, outOfElection, recvQueue, waitNotmsg, leaderVars, envVars,
                initialHistory, connectInfo, epochLeader, proposalMsgsLog, electionMsgs>>
IncZxid(s, zxid) == IF currentEpoch[s] = zxid[1] THEN <<zxid[1], zxid[2] + 1>>
                    ELSE <<currentEpoch[s], 1>>

LeaderProcessRequest(i) ==
        /\ IsON(i)
        /\ IsLeader(i)
        /\ zabState[i] = BROADCAST
        /\ LET inBroadcast == {s \in forwarding[i]: zabState[s] = BROADCAST} \union {i}
           IN IsQuorum(inBroadcast)
        /\ LET request_value == CHOOSE v \in Value : TRUE 
               newTxn == [ zxid   |-> IncZxid(i, LastProposed(i).zxid),
                           value  |-> request_value, 
                           ackSid |-> {i}, 
                           epoch  |-> acceptedEpoch[i] ]
               m_proposal == [ mtype |-> PROPOSAL,
                               mzxid |-> newTxn.zxid,
                               mdata |-> request_value ]
               m_proposal_for_checking == [ source |-> i,
                                            epoch  |-> acceptedEpoch[i],
                                            zxid   |-> newTxn.zxid,
                                            data   |-> request_value ]
           IN /\ history' = [history EXCEPT ![i] = Append(@, newTxn) ]
              /\ \/ /\ ShouldSnapshot(i)
                    /\ TakeSnapshot(i)
                 \/ /\ ~ShouldSnapshot(i)
                    /\ UNCHANGED <<lastSnapshot>>
              /\ Broadcast(i, m_proposal)
              /\ proposalMsgsLog' = proposalMsgsLog \union {m_proposal_for_checking}
        /\ UNCHANGED <<state, currentEpoch, lastProcessed, zabState, acceptedEpoch,
                       lastCommitted, electionVars, leaderVars, followerVars,
                       initialHistory, epochLeader, electionMsgs, envVars>>

FollowerProcessPROPOSAL(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingPROPOSAL(i, j)
        /\ zabState[i] = BROADCAST
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               isNext == IsNextZxid( LastQueued(i).zxid, msg.mzxid)
               newTxn == [ zxid   |-> msg.mzxid,
                           value  |-> msg.mdata,
                           ackSid |-> {},
                           epoch  |-> acceptedEpoch[i] ]
               m_ack  == [ mtype |-> ACK,
                           mzxid |-> msg.mzxid ]
          IN /\ infoOk
             /\ \/ /\ isNext
                   /\ history' = [history EXCEPT ![i] = Append(@, newTxn)]
                   /\ \/ /\ ShouldSnapshot(i)
                         /\ TakeSnapshot(i)
                      \/ /\ ~ShouldSnapshot(i)
                         /\ UNCHANGED <<lastSnapshot>>
                   /\ Reply(i, j, m_ack)
                \/ /\ ~isNext
                   /\ UNCHANGED <<history, lastSnapshot, msgs>>
        /\ UNCHANGED <<state, currentEpoch, lastProcessed, zabState, acceptedEpoch,
                 lastCommitted, electionVars, leaderVars, followerVars, initialHistory,
                 epochLeader, proposalMsgsLog, electionMsgs, envVars>>

LastAckIndexFromFollower(i, j) == 
        LET set_index == {idx \in 1..Len(history[i]): j \in history[i][idx].ackSid }
        IN Maximum(set_index)

LeaderCommit(s, follower, index, zxid) ==
        /\ lastCommitted' = [lastCommitted EXCEPT ![s] = [ index |-> index,
                                                           zxid  |-> zxid ] ]
        /\ LET m_commit == [ mtype |-> COMMIT,
                             mzxid |-> zxid ]
           IN DiscardAndBroadcast(s, follower, m_commit)

LeaderTryToCommit(s, index, zxid, newTxn, follower) ==
        LET allTxnsBeforeCommitted == lastCommitted[s].index >= index - 1

            hasAllQuorums == IsQuorum(newTxn.ackSid)

            ordered == lastCommitted[s].index + 1 = index
                    
        IN \/ /\ 
                 \/ ~allTxnsBeforeCommitted
                 \/ ~hasAllQuorums
              /\ Discard(follower, s)
              /\ UNCHANGED <<lastCommitted, lastProcessed>>
           \/ /\ allTxnsBeforeCommitted
              /\ hasAllQuorums
              /\ \/ /\ ~ordered
                 \/ /\ ordered
              /\ LeaderCommit(s, follower, index, zxid)
              /\ lastProcessed' = [lastProcessed EXCEPT ![s] = [ index |-> index,
                                                                 zxid  |-> zxid ] ]

LeaderProcessACK(i, j) ==
        /\ IsON(i)
        /\ IsLeader(i)
        /\ PendingACK(i, j)
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLearner(i, j)
               outstanding == LastCommitted(i).index < LastProposed(i).index
                        
               hasCommitted == ~ZxidCompare( msg.mzxid, LastCommitted(i).zxid)
                        
               index == ZxidToIndex(history[i], msg.mzxid)
               exist == index >= 1 /\ index <= LastProposed(i).index
                        
               ackIndex == LastAckIndexFromFollower(i, j)
               monotonicallyInc == \/ ackIndex = -1
                                   \/ ackIndex + 1 = index
                        
           IN /\ infoOk 
              /\ \/ /\ exist
                    /\ monotonicallyInc
                    /\ LET txn == history[i][index]
                           txnAfterAddAck == [ zxid   |-> txn.zxid,
                                               value  |-> txn.value,
                                               ackSid |-> txn.ackSid \union {j} ,
                                               epoch  |-> txn.epoch ]   
                       IN 
                       /\ history' = [history EXCEPT ![i][index] = txnAfterAddAck ] 
                       /\ \/ /\ 
                                
                                \/ ~outstanding
                                \/ hasCommitted
                             /\ Discard(j, i)
                             /\ UNCHANGED <<lastCommitted, lastProcessed>>
                          \/ /\ outstanding
                             /\ ~hasCommitted
                             /\ LeaderTryToCommit(i, index, msg.mzxid, txnAfterAddAck, j)
                 \/ /\ \/ ~exist
                       \/ ~monotonicallyInc
                    /\ Discard(j, i)
                    /\ UNCHANGED <<history, lastCommitted, lastProcessed>>
        /\ UNCHANGED <<state, currentEpoch, zabState, acceptedEpoch, electionVars,
                    leaderVars, initialHistory, followerVars, proposalMsgsLog, epochLeader, 
                    lastSnapshot, electionMsgs, envVars>>

FollowerProcessCOMMIT(i, j) ==
        /\ IsON(i)
        /\ IsFollower(i)
        /\ PendingCOMMIT(i, j)
        /\ zabState[i] = BROADCAST
        /\ LET msg == msgs[j][i][1]
               infoOk == IsMyLeader(i, j)
               pendingTxns == PendingTxns(i)
               noPending == Len(pendingTxns) = 0
           IN
           /\ infoOk 
           /\ \/ /\ noPending
                 /\ UNCHANGED <<lastCommitted, lastProcessed>>
              \/ /\ ~noPending
                 /\ LET firstElementZxid == pendingTxns[1].zxid
                        match == ZxidEqual(firstElementZxid, msg.mzxid)
                    IN 
                    \/ /\ ~match
                       /\ UNCHANGED <<lastCommitted, lastProcessed>>
                    \/ /\ match
                       /\ lastCommitted' = [lastCommitted EXCEPT 
                                ![i] = [ index |-> lastCommitted[i].index + 1,
                                         zxid  |-> firstElementZxid ] ]
                       /\ lastProcessed' = [lastProcessed EXCEPT 
                                ![i] = [ index |-> lastCommitted[i].index + 1,
                                         zxid  |-> firstElementZxid ] ]
        /\ Discard(j, i)
        /\ UNCHANGED <<state, currentEpoch, zabState, acceptedEpoch, history,
                    electionVars, leaderVars, initialHistory, followerVars,
                    lastSnapshot, proposalMsgsLog, epochLeader, electionMsgs, envVars>>

Next == 
        
            \/ \E i, j \in Server: FLEReceiveNotmsg(i, j)
            \/ \E i \in Server:    FLENotmsgTimeout(i)
            \/ \E i \in Server:    FLEHandleNotmsg(i)
            \/ \E i \in Server:    FLEWaitNewNotmsg(i)
        
            \/ \E i, j \in Server: PartitionStart(i, j)
            \/ \E i, j \in Server: PartitionRecover(i, j)
            \/ \E i \in Server:    NodeCrash(i)
            \/ \E i \in Server:    NodeStart(i)
        
            \/ \E i, j \in Server: ConnectAndFollowerSendFOLLOWERINFO(i, j)
            \/ \E i, j \in Server: LeaderProcessFOLLOWERINFO(i, j)
            \/ \E i, j \in Server: FollowerProcessLEADERINFO(i, j)
            \/ \E i, j \in Server: LeaderProcessACKEPOCH(i, j)
            \/ \E i, j \in Server: LeaderSyncFollower(i, j)
            \/ \E i, j \in Server: FollowerProcessSyncMessage(i, j)
            \/ \E i, j \in Server: FollowerProcessPROPOSALInSync(i, j)
            \/ \E i, j \in Server: FollowerProcessCOMMITInSync(i, j)
            \/ \E i, j \in Server: FollowerProcessNEWLEADER(i, j)
            \/ \E i, j \in Server: LeaderProcessACKLD(i, j)
            \/ \E i, j \in Server: FollowerProcessUPTODATE(i, j)
        
            \/ \E i \in Server:    LeaderProcessRequest(i)
            \/ \E i, j \in Server: FollowerProcessPROPOSAL(i, j)
            \/ \E i, j \in Server: LeaderProcessACK(i, j)
            \/ \E i, j \in Server: FollowerProcessCOMMIT(i, j)

Spec == Init /\ [][Next]_vars

=============================================================================

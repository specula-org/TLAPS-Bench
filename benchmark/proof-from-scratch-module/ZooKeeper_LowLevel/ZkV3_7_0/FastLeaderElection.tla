------------------------- MODULE FastLeaderElection -------------------------

EXTENDS Integers, FiniteSets, Sequences, Naturals, TLAPS

-----------------------------------------------------------------------------

CONSTANT Server

CONSTANT NullPoint

ASSUME ServerFinite == IsFiniteSet(Server)
ASSUME NullPointNotServer == NullPoint \notin Server

LOOKING   == "LOOKING"
FOLLOWING == "FOLLOWING"
LEADING   == "LEADING"

NOTIFICATION == "NOTIFICATION"

NONE == "NONE"
-----------------------------------------------------------------------------
Quorums == {Q \in SUBSET Server: Cardinality(Q)*2 > Cardinality(Server)}

BootstrapZxid == <<0, 1>>
BootstrapTxn == [ zxid   |-> BootstrapZxid,
                  value  |-> 0,
                  ackSid |-> Server,
                  epoch  |-> 0 ]

-----------------------------------------------------------------------------

VARIABLE state

VARIABLE history

VARIABLE currentEpoch

VARIABLE lastProcessed

VARIABLE currentVote

VARIABLE logicalClock

VARIABLE receiveVotes

VARIABLE outOfElection

VARIABLE recvQueue

VARIABLE waitNotmsg

VARIABLE leadingVoteSet

VARIABLE electionMsgs

serverVarsL == <<state, currentEpoch, lastProcessed, history>>

electionVarsL == <<currentVote, logicalClock, receiveVotes, outOfElection, recvQueue, waitNotmsg>>

leaderVarsL == <<leadingVoteSet>>

varsL == <<serverVarsL, electionVarsL, leaderVarsL, electionMsgs>>
-----------------------------------------------------------------------------

BroadcastNotmsg(i, m) == electionMsgs' = [electionMsgs EXCEPT ![i] = [v \in Server |-> IF v /= i
                                                                                       THEN Append(electionMsgs[i][v], m)
                                                                                       ELSE electionMsgs[i][v]]]

DiscardNotmsg(i, j) == electionMsgs' = [electionMsgs EXCEPT ![i][j] = IF electionMsgs[i][j] /= << >>
                                                                      THEN Tail(electionMsgs[i][j])
                                                                      ELSE << >>]

ReplyNotmsg(i, j, m) == electionMsgs' = [electionMsgs EXCEPT ![i][j] = Append(electionMsgs[i][j], m),
                                                             ![j][i] = Tail(electionMsgs[j][i])]
                                               
-----------------------------------------------------------------------------

RemoveNone(seq) == SelectSeq(seq, LAMBDA m: m.mtype /= NONE) 

InitializeIdTable(Remaining) == 
  LET IIT[R \in SUBSET Server] == 
        IF R = {} THEN {}
        ELSE LET chosen == CHOOSE i \in R: TRUE
                 re     == R \ {chosen}
             IN {<<chosen, Cardinality(R)>>} \union IIT[re]
  IN IIT[Remaining]

IdTable == InitializeIdTable(Server) 

IdCompare(id1,id2) == LET item1 == CHOOSE item \in IdTable: item[1] = id1
                          item2 == CHOOSE item \in IdTable: item[1] = id2
                      IN item1[2] > item2[2]

ZxidCompare(zxid1, zxid2) == \/ zxid1[1] > zxid2[1]
                             \/ /\ zxid1[1] = zxid2[1]
                                /\ zxid1[2] > zxid2[2]

ZxidEqual(zxid1, zxid2) == zxid1[1] = zxid2[1] /\ zxid1[2] = zxid2[2]

TotalOrderPredicate(vote1, vote2) == \/ vote1.proposedEpoch > vote2.proposedEpoch
                                     \/ /\ vote1.proposedEpoch = vote2.proposedEpoch
                                        /\ \/ ZxidCompare(vote1.proposedZxid, vote2.proposedZxid)
                                           \/ /\ ZxidEqual(vote1.proposedZxid, vote2.proposedZxid)
                                              /\ IdCompare(vote1.proposedLeader, vote2.proposedLeader)

VoteEqual(vote1, round1, vote2, round2) == /\ vote1.proposedLeader = vote2.proposedLeader
                                           /\ ZxidEqual(vote1.proposedZxid, vote2.proposedZxid)
                                           /\ vote1.proposedEpoch  = vote2.proposedEpoch
                                           /\ round1 = round2

InitLastProcessed(i) == IF Len(history[i]) = 0 THEN [ index |-> 0, 
                                                 zxid |-> <<0, 0>> ]
                        ELSE
                        LET lastIndex == Len(history[i])
                            entry     == history[i][lastIndex]
                        IN [ index |-> lastIndex,
                             zxid  |-> entry.zxid ]

InitAcksidInTxns(txns, src) == 
  [i \in 1..Len(txns) |-> [ zxid   |-> txns[i].zxid,
                             value  |-> txns[i].value,
                             ackSid |-> {src},
                             epoch  |-> txns[i].epoch ]]

InitHistory(i) == LET newState == state'[i] IN 
                    IF newState = LEADING THEN InitAcksidInTxns(history[i], i)
                    ELSE history[i]
-----------------------------------------------------------------------------

InitialVote == [proposedLeader |-> NullPoint,
                proposedZxid   |-> <<0, 0>>,
                proposedEpoch  |-> 0]

SelfVote(i) == [proposedLeader |-> i,
                proposedZxid   |-> lastProcessed[i].zxid,
                proposedEpoch  |-> currentEpoch[i]]

UpdateProposal(i, nid, nzxid, nepoch) == currentVote' = [currentVote EXCEPT ![i].proposedLeader = nid, 
                                                                            ![i].proposedZxid   = nzxid,
                                                                            ![i].proposedEpoch  = nepoch]  
                                                                            
-----------------------------------------------------------------------------

RvPut(i, id, mvote, mround, mstate) == receiveVotes' = CASE receiveVotes[i][id].round < mround -> [receiveVotes EXCEPT ![i][id].vote    = mvote,
                                                                                                                       ![i][id].round   = mround,
                                                                                                                       ![i][id].state   = mstate,
                                                                                                                       ![i][id].version = 1]
                                                       []   receiveVotes[i][id].round = mround -> [receiveVotes EXCEPT ![i][id].vote    = mvote,
                                                                                                                       ![i][id].state   = mstate,
                                                                                                                       ![i][id].version = @ + 1]
                                                       []   receiveVotes[i][id].round > mround -> receiveVotes

Put(i, id, rcvset, mvote, mround, mstate) == CASE rcvset[id].round < mround -> [rcvset EXCEPT ![id].vote    = mvote,
                                                                                              ![id].round   = mround,
                                                                                              ![id].state   = mstate,
                                                                                              ![id].version = 1]
                                             []   rcvset[id].round = mround -> [rcvset EXCEPT ![id].vote    = mvote,
                                                                                              ![id].state   = mstate,
                                                                                              ![id].version = @ + 1]
                                             []   rcvset[id].round > mround -> rcvset

RvClearAndPut(i, id, vote, round) == receiveVotes' = LET oneVote == [vote    |-> vote, 
                                                                     round   |-> round, 
                                                                     state   |-> LOOKING,
                                                                     version |-> 1]
                                                     IN [receiveVotes EXCEPT ![i] = [v \in Server |-> IF v = id THEN oneVote
                                                                                                                ELSE [vote    |-> InitialVote,
                                                                                                                      round   |-> 0,
                                                                                                                      state   |-> LOOKING,
                                                                                                                      version |-> 0]]]                     

VoteSet(i, msource, rcvset, thisvote, thisround) == {msource} \union {s \in (Server \ {msource}): VoteEqual(rcvset[s].vote, 
                                                                                                            rcvset[s].round,
                                                                                                            thisvote,
                                                                                                            thisround)}

HasQuorums(i, msource, rcvset, thisvote, thisround) == LET Q == VoteSet(i, msource, rcvset, thisvote, thisround)
                                                       IN IF Q \in Quorums THEN TRUE ELSE FALSE

CheckLeader(i, votes, thisleader, thisround) == IF thisleader = i THEN (IF thisround = logicalClock[i] THEN TRUE ELSE FALSE)
                                                ELSE (IF votes[thisleader].vote.proposedLeader = NullPoint THEN FALSE
                                                      ELSE (IF votes[thisleader].state = LEADING THEN TRUE 
                                                                                                 ELSE FALSE))

-----------------------------------------------------------------------------    
InitServerVarsL == /\ state         = [s \in Server |-> LOOKING]
                   /\ currentEpoch  = [s \in Server |-> 0]
                   /\ lastProcessed = [s \in Server |-> [index |-> 1,
                                                         zxid  |-> BootstrapZxid] ]
                   /\ history       = [s \in Server |-> <<BootstrapTxn>>]

InitElectionVarsL == /\ currentVote   = [s \in Server |-> SelfVote(s)]
                     /\ logicalClock  = [s \in Server |-> 0]
                     /\ receiveVotes  = [s \in Server |-> [v \in Server |-> [vote    |-> InitialVote,
                                                                             round   |-> 0,
                                                                             state   |-> LOOKING,
                                                                             version |-> 0]]]
                     /\ outOfElection = [s \in Server |-> [v \in Server |-> [vote    |-> InitialVote,
                                                                             round   |-> 0,
                                                                             state   |-> LOOKING,
                                                                             version |-> 0]]]
                     /\ recvQueue     = [s \in Server |-> << >>]
                     /\ waitNotmsg    = [s \in Server |-> FALSE]

InitLeaderVarsL == leadingVoteSet = [s \in Server |-> {}]

-----------------------------------------------------------------------------

ZabTimeout(i) ==
        /\ state[i] \in {LEADING, FOLLOWING}
        /\ state'          = [state          EXCEPT ![i] = LOOKING]
        /\ lastProcessed'  = [lastProcessed  EXCEPT ![i] = InitLastProcessed(i)]
        /\ logicalClock'   = [logicalClock   EXCEPT ![i] = logicalClock[i] + 1]
        /\ currentVote'    = [currentVote    EXCEPT ![i] = [proposedLeader |-> i,
                                                            proposedZxid   |-> lastProcessed'[i].zxid,
                                                            proposedEpoch  |-> currentEpoch[i]]]
        /\ receiveVotes'   = [receiveVotes   EXCEPT ![i] = [v \in Server |-> [vote    |-> InitialVote,
                                                                              round   |-> 0,
                                                                              state   |-> LOOKING,
                                                                              version |-> 0]]]
        /\ outOfElection'  = [outOfElection  EXCEPT ![i] = [v \in Server |-> [vote    |-> InitialVote,
                                                                              round   |-> 0,
                                                                              state   |-> LOOKING,
                                                                              version |-> 0]]]
        /\ recvQueue'      = [recvQueue      EXCEPT ![i] = << >>]  
        /\ waitNotmsg'     = [waitNotmsg     EXCEPT ![i] = FALSE]
        /\ leadingVoteSet' = [leadingVoteSet EXCEPT ![i] = {}]
        /\ BroadcastNotmsg(i, [mtype   |-> NOTIFICATION,
                               msource |-> i,
                               mstate  |-> LOOKING,
                               mround  |-> logicalClock'[i],
                               mvote   |-> currentVote'[i]])
        /\ UNCHANGED <<currentEpoch, history>>

ReceiveNotmsg(i, j) ==
        /\ electionMsgs[j][i] /= << >>
        /\ LET notmsg == electionMsgs[j][i][1]
               toSend == [mtype   |-> NOTIFICATION,
                          msource |-> i,
                          mstate  |-> state[i],
                          mround  |-> logicalClock[i],
                          mvote   |-> currentVote[i]]
           IN \/ /\ state[i] = LOOKING
                 /\ recvQueue' = [recvQueue EXCEPT ![i] = Append(RemoveNone(recvQueue[i]), notmsg)]
                 /\ LET replyOk == /\ notmsg.mstate = LOOKING
                                   /\ notmsg.mround < logicalClock[i]
                    IN 
                    \/ /\ replyOk
                       /\ ReplyNotmsg(i, j, toSend)
                    \/ /\ ~replyOk
                       /\ DiscardNotmsg(j, i)
              \/ /\ state[i] \in {LEADING, FOLLOWING}
                 /\ \/ 
                       /\ notmsg.mstate = LOOKING
                       /\ ReplyNotmsg(i, j, toSend)
                    \/ 
                       /\ notmsg.mstate /= LOOKING
                       /\ DiscardNotmsg(j, i)
                 /\ UNCHANGED recvQueue
        /\ UNCHANGED <<serverVarsL, currentVote, logicalClock, receiveVotes, outOfElection, waitNotmsg, leaderVarsL>>
        
NotmsgTimeout(i) == 
        /\ state[i] = LOOKING
        /\ \A j \in Server: electionMsgs[j][i] = << >>
        /\ recvQueue[i] = << >>
        /\ recvQueue' = [recvQueue EXCEPT ![i] = Append(recvQueue[i], [mtype |-> NONE])]
        /\ UNCHANGED <<serverVarsL, currentVote, logicalClock, receiveVotes, outOfElection, waitNotmsg, leaderVarsL, electionMsgs>>

-----------------------------------------------------------------------------

ReceivedFollowingAndLeadingNotification(i, n) ==
        LET newVotes    == Put(i, n.msource, receiveVotes[i], n.mvote, n.mround, n.mstate)
            voteSet1    == VoteSet(i, n.msource, newVotes, n.mvote, n.mround)
            hasQuorums1 == voteSet1 \in Quorums
            check1      == CheckLeader(i, newVotes, n.mvote.proposedLeader, n.mround)
            leaveOk1    == /\ n.mround = logicalClock[i]
                           /\ hasQuorums1
                           /\ check1    
        IN
        /\ \/ /\ n.mround = logicalClock[i]
              /\ receiveVotes' = [receiveVotes EXCEPT ![i] = newVotes]
           \/ /\ n.mround /= logicalClock[i]
              /\ UNCHANGED receiveVotes
        /\ \/ /\ leaveOk1
              /\ state' = [state EXCEPT ![i] = IF n.mvote.proposedLeader = i THEN LEADING ELSE FOLLOWING]
              /\ leadingVoteSet' = [leadingVoteSet EXCEPT ![i] = IF n.mvote.proposedLeader = i THEN voteSet1 ELSE @]
              /\ UpdateProposal(i, n.mvote.proposedLeader, n.mvote.proposedZxid, n.mvote.proposedEpoch)
              /\ UNCHANGED <<logicalClock, outOfElection>>
           \/ /\ ~leaveOk1
              /\ outOfElection' = [outOfElection EXCEPT ![i] = Put(i, n.msource, outOfElection[i], n.mvote,n.mround, n.mstate)]
              /\ LET voteSet2    == VoteSet(i, n.msource, outOfElection'[i], n.mvote, n.mround)
                     hasQuorums2 == voteSet2 \in Quorums
                     check2      == CheckLeader(i, outOfElection'[i], n.mvote.proposedLeader, n.mround)
                     leaveOk2    == /\ hasQuorums2
                                    /\ check2
                 IN
                 \/ /\ leaveOk2
                    /\ logicalClock' = [logicalClock EXCEPT ![i] = n.mround]
                    /\ state' = [state EXCEPT ![i] = IF n.mvote.proposedLeader = i THEN LEADING ELSE FOLLOWING]
                    /\ leadingVoteSet' = [leadingVoteSet EXCEPT ![i] = IF n.mvote.proposedLeader = i THEN voteSet2 ELSE @]
                    /\ UpdateProposal(i, n.mvote.proposedLeader, n.mvote.proposedZxid, n.mvote.proposedEpoch)
                 \/ /\ ~leaveOk2
                    /\ LET leaveOk3 == /\ n.mstate = LEADING
                                       /\ n.mround = logicalClock[i]
                       IN
                       \/ /\ leaveOk3
                          /\ state' = [state EXCEPT ![i] = IF n.mvote.proposedLeader = i THEN LEADING ELSE FOLLOWING]
                          /\ UpdateProposal(i, n.mvote.proposedLeader, n.mvote.proposedZxid, n.mvote.proposedEpoch)
                       \/ /\ ~leaveOk3
                          /\ UNCHANGED <<state, currentVote>>
                    /\ UNCHANGED <<logicalClock, leadingVoteSet>>

HandleNotmsg(i) ==
        /\ state[i] = LOOKING
        /\ \lnot waitNotmsg[i]
        /\ recvQueue[i] /= << >>
        /\ LET n         == recvQueue[i][1]
               rawToSend == [mtype   |-> NOTIFICATION,
                             msource |-> i,
                             mstate  |-> LOOKING,
                             mround  |-> logicalClock[i],
                             mvote   |-> currentVote[i]]
           IN \/ /\ n.mtype = NONE
                 /\ BroadcastNotmsg(i, rawToSend)
                 /\ UNCHANGED <<history, logicalClock, currentVote, receiveVotes, waitNotmsg, outOfElection, state, leadingVoteSet>>
              \/ /\ n.mtype = NOTIFICATION
                 /\ \/ /\ n.mstate = LOOKING
                       /\ \/ 
                             /\ n.mround >= logicalClock[i]
                             /\ \/ 
                                   /\ n.mround > logicalClock[i]
                                   /\ logicalClock' = [logicalClock EXCEPT ![i] = n.mround] 
                                   /\ LET selfinfo == [proposedLeader |-> i,
                                                       proposedZxid   |-> lastProcessed[i].zxid,
                                                       proposedEpoch  |-> currentEpoch[i]]
                                          peerOk   == TotalOrderPredicate(n.mvote, selfinfo)
                                      IN \/ /\ peerOk
                                            /\ UpdateProposal(i, n.mvote.proposedLeader, n.mvote.proposedZxid, n.mvote.proposedEpoch)
                                         \/ /\ ~peerOk
                                            /\ UpdateProposal(i, i, lastProcessed[i].zxid, currentEpoch[i])
                                   /\ BroadcastNotmsg(i, [mtype   |-> NOTIFICATION,
                                                          msource |-> i,
                                                          mstate  |-> LOOKING,
                                                          mround  |-> n.mround,
                                                          mvote   |-> currentVote'[i]])
                                \/ 
                                   /\ n.mround = logicalClock[i]
                                   /\ LET peerOk == TotalOrderPredicate(n.mvote, currentVote[i])
                                      IN \/ /\ peerOk
                                            /\ UpdateProposal(i, n.mvote.proposedLeader, n.mvote.proposedZxid, n.mvote.proposedEpoch)
                                            /\ BroadcastNotmsg(i, [mtype   |-> NOTIFICATION,
                                                                   msource |-> i,
                                                                   mstate  |-> LOOKING,
                                                                   mround  |-> logicalClock[i],
                                                                   mvote   |-> n.mvote])
                                         \/ /\ ~peerOk
                                            /\ UNCHANGED <<currentVote, electionMsgs>>
                                   /\ UNCHANGED logicalClock
                             /\ LET rcvsetModifiedTwice == n.mround > logicalClock[i]
                                IN \/ /\ rcvsetModifiedTwice   
                                      /\ RvClearAndPut(i, n.msource, n.mvote, n.mround)  
                                   \/ /\ ~rcvsetModifiedTwice
                                      /\ RvPut(i, n.msource, n.mvote, n.mround, n.mstate)          
                             /\ LET hasQuorums == HasQuorums(i, i, receiveVotes'[i], currentVote'[i], n.mround)
                                IN \/ /\ hasQuorums 
                                      /\ waitNotmsg' = [waitNotmsg EXCEPT ![i] = TRUE] 
                                   \/ /\ ~hasQuorums                            
                                      /\ UNCHANGED waitNotmsg
                          \/ 
                             /\ n.mround < logicalClock[i]
                             /\ UNCHANGED <<logicalClock, currentVote, electionMsgs, receiveVotes, waitNotmsg>>
                       /\ UNCHANGED <<state, history, outOfElection, leadingVoteSet>>
                    \/ 
                       /\ n.mstate \in {LEADING, FOLLOWING}
                       /\ ReceivedFollowingAndLeadingNotification(i, n)
                       /\ history' = [history EXCEPT ![i] = InitHistory(i) ]
                       /\ UNCHANGED <<electionMsgs, waitNotmsg>>
        /\ recvQueue' = [recvQueue EXCEPT ![i] = Tail(recvQueue[i])]
        /\ UNCHANGED <<currentEpoch, lastProcessed>>

WaitNewNotmsg(i) ==
        /\ state[i] = LOOKING
        /\ waitNotmsg[i] = TRUE
        /\ \/ /\ recvQueue[i] /= << >>
              /\ recvQueue[i][1].mtype = NOTIFICATION
              /\ LET n == recvQueue[i][1]
                     peerOk == TotalOrderPredicate(n.mvote, currentVote[i])
                 IN \/ /\ peerOk
                       /\ waitNotmsg' = [waitNotmsg EXCEPT ![i] = FALSE]
                       /\ recvQueue'  = [recvQueue  EXCEPT ![i] = Append(Tail(@), n)]
                    \/ /\ ~peerOk
                       /\ recvQueue' = [recvQueue EXCEPT ![i] = Tail(@)]
                       /\ UNCHANGED waitNotmsg
              /\ UNCHANGED <<serverVarsL, currentVote, logicalClock, receiveVotes, outOfElection, 
                             leaderVarsL, electionMsgs>>
           \/ /\ \/ recvQueue[i] = << >>
                 \/ /\ recvQueue[i] /= << >>
                    /\ recvQueue[i][1].mtype = NONE
              /\ state' = [state EXCEPT ![i] = IF currentVote[i].proposedLeader = i THEN LEADING
                                               ELSE FOLLOWING ]
              /\ leadingVoteSet' = [leadingVoteSet EXCEPT ![i] = 
                                                           IF currentVote[i].proposedLeader = i 
                                                           THEN VoteSet(i, i, receiveVotes[i], currentVote[i],
                                                                        logicalClock[i])
                                                           ELSE @]
              /\ history' = [history EXCEPT ![i] = InitHistory(i)]
              /\ UNCHANGED <<currentEpoch, lastProcessed, electionVarsL, electionMsgs>>
-----------------------------------------------------------------------------

=============================================================================

---- MODULE HandlerEdges ----
EXTENDS SnapshotRecovery
CONSTANT Edge

\* Unit preconditions injected after the reachable synchronization prefix.
\* Setup itself is not claimed to be a protocol transition.
Setup ==
    /\ pc = 125 /\ pc' = 126
    /\ LET packet ==
           CASE Edge = "reject" -> [mtype |-> TRUNC, mtruncZxid |-> <<9,1>>]
             [] Edge = "truncate" -> [mtype |-> TRUNC, mtruncZxid |-> <<2,1>>]
             [] Edge = "snapshot" ->
                  [mtype |-> SNAP, msnapZxid |-> <<2,1>>,
                   msnapshot |-> SubSeq(history[s1],1,2)]
       IN msgs' = [msgs EXCEPT ![s3][s1] = <<packet>> \o @]
    /\ lastSnapshot' = [lastSnapshot EXCEPT ![s1] = lastCommitted[s1]]
    /\ UNCHANGED <<state,currentEpoch,lastProcessed,zabState,acceptedEpoch,
                   history,lastCommitted,initialHistory,electionVars,leaderVars,
                   followerVars,verifyVars,electionMsgs,envVars>>

EdgeNext ==
    \/ Prefix /\ pc'=pc+1
    \/ Setup
    \/ /\ pc=126 /\ pc'=127 /\ FollowerProcessSyncMessage(s1,s3)
    \/ /\ pc=127 /\ pc'=128
       /\ IF Edge="reject" THEN UNCHANGED vars
          ELSE FollowerProcessNEWLEADER(s1,s3)

EdgeSpec == TraceInit /\ [][EdgeNext]_<<vars,pc>> /\ WF_<<vars,pc>>(EdgeNext)
EdgeCompletes == <>(pc=128)
HandlerRefinesNext == [][pc>=126 => Next]_vars
Rejected == pc>=127 /\ Edge="reject" => status[s1]=OFFLINE
Replaced == pc=128 /\ Edge#"reject" =>
    /\ Len(history[s1])=2
    /\ lastCommitted[s1].index=2
    /\ lastSnapshot[s1].index=2
    /\ connectInfo[s1].nlRcv
====

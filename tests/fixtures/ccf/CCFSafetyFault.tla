---- MODULE CCFSafetyFault ----
EXTENDS CCFProof
CONSTANTS First, Second, Fault, Corrupt

FaultInit == Init /\ leadershipState[First] = Leader

\* Deliberately inject an illegal committed-log update to exercise each oracle.
\* Corrupt = FALSE supplies the matching safe control.
FaultNext ==
    IF Fault = "agreement"
    THEN /\ log' = [log EXCEPT ![Second] =
                StartLog(IF Corrupt THEN {Second} ELSE {First}, {First})]
         /\ commitIndex' = [commitIndex EXCEPT ![Second] = 2]
         /\ UNCHANGED <<preVoteStatus, reconfigurationVars, messageVars,
                         serverVars, candidateVars, leaderVars>>
    ELSE IF Corrupt
         THEN /\ log' = [log EXCEPT ![First] = <<>>]
              /\ commitIndex' = [commitIndex EXCEPT ![First] = 0]
              /\ UNCHANGED <<preVoteStatus, reconfigurationVars, messageVars,
                              serverVars, candidateVars, leaderVars>>
         ELSE UNCHANGED vars

FaultSpec == FaultInit /\ [][FaultNext]_vars
====

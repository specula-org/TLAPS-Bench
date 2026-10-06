---- MODULE PirateShipScenarios ----
EXTENDS PirateShipProof
VARIABLE phase
CONSTANT Scenario

Start == /\ Init /\ leader[IF Scenario = "Byzantine" THEN 3 ELSE 0] /\ phase = 0

Step(n, action) == /\ phase = n /\ action /\ phase' = n + 1
Send(p, tx) == /\ SendEntries(p) /\ Last(branch'[p]).tx = <<tx>>

\* Reach audited prefixes, then replace the leader while preserving them.
ViewChangePath ==
    \/ Step(0, Send(0, 2))
    \/ Step(1, ReceiveEntries(1, 0))
    \/ Step(2, ReceiveVote(0, 1))
    \/ Step(3, ReceiveEntries(2, 0))
    \/ Step(4, ReceiveVote(0, 2))
    \/ Step(5, Send(0, 1))
    \/ Step(6, ReceiveEntries(1, 0))
    \/ Step(7, ReceiveVote(0, 1))
    \/ Step(8, ReceiveEntries(2, 0))
    \/ Step(9, ReceiveVote(0, 2))
    \/ Step(10, Send(0, 2))
    \/ Step(11, ReceiveEntries(1, 0))
    \/ Step(12, ReceiveVote(0, 1))
    \/ Step(13, ReceiveEntries(2, 0))
    \/ Step(14, ReceiveVote(0, 2))
    \/ Step(15, Timeout(0))
    \/ Step(16, Timeout(1))
    \/ Step(17, Timeout(2))
    \/ Step(18, BecomeLeader(Leader(1)))
    \/ Step(19, ReceiveNewView(0, Leader(1)))
    \/ Step(20, ReceiveVote(Leader(1), 0))
    \/ Step(21, ReceiveNewView(2, Leader(1)))
    \/ Step(22, ReceiveVote(Leader(1), 2))
    \/ Step(23, Send(Leader(1), 1))
    \/ Step(24, ReceiveEntries(0, Leader(1)))
    \/ Step(25, ReceiveVote(Leader(1), 0))
    \/ Step(26, ReceiveEntries(2, Leader(1)))
    \/ Step(27, ReceiveVote(Leader(1), 2))

\* Both modeled Byzantine action families execute, with honest replicas
\* temporarily observing different uncommitted transactions.
ByzantinePath ==
    \/ Step(0, Send(3, 2))
    \/ Step(1, /\ ByzLeaderEquivocate(3)
               /\ Head(network'[0][3]).branch[1].tx = <<1>>)
    \/ Step(2, ReceiveEntries(0, 3))
    \/ Step(3, ReceiveVote(3, 0))
    \/ Step(4, ReceiveEntries(1, 3))
    \/ Step(5, ReceiveVote(3, 1))
    \/ Step(6, Timeout(0))
    \/ Step(7, Timeout(1))
    \/ Step(8, Timeout(2))
    \/ Step(9, BecomeLeader(Leader(1)))
    \/ Step(10, DiscardMessages)
    \/ Step(11, ReceiveNewView(0, Leader(1)))
    \/ Step(12, ReceiveVote(Leader(1), 0))
    \/ Step(13, ReceiveNewView(2, Leader(1)))
    \/ Step(14, ReceiveVote(Leader(1), 2))
    \/ Step(15, Timeout(3))
    \/ Step(16, ReceiveNewView(3, Leader(1)))
    \/ Step(17, /\ DiscardMessages /\ Head(network'[Leader(1)][3]).type = "Vote")
    \/ Step(18, ReceiveVote(Leader(1), 3))
    \/ Step(19, Send(Leader(1), 2))
    \/ Step(20, ByzOmitEntries(3, Leader(1)))
    \/ Step(21, ReceiveVote(Leader(1), 3))
    \/ Step(22, ReceiveEntries(0, Leader(1)))
    \/ Step(23, ReceiveVote(Leader(1), 0))
    \/ Step(24, ReceiveEntries(2, Leader(1)))
    \/ Step(25, ReceiveVote(Leader(1), 2))
    \/ Step(26, Send(Leader(1), 1))
    \/ Step(27, ReceiveEntries(0, Leader(1)))
    \/ Step(28, ReceiveVote(Leader(1), 0))
    \/ Step(29, ReceiveEntries(2, Leader(1)))
    \/ Step(30, ReceiveVote(Leader(1), 2))

EndPhase == IF Scenario = "Byzantine" THEN 31 ELSE 28
Continue ==
    \/ IF Scenario = "Byzantine" THEN ByzantinePath ELSE ViewChangePath
    \/ /\ phase = EndPhase /\ UNCHANGED <<vars, phase>>

ScenarioSpec == Start /\ [][Continue]_<<vars, phase>> /\ WF_<<vars, phase>>(Continue)

Allowed == Init /\ [][Next]_vars
Completion == <> (phase = EndPhase)
AuditedBeforeViewChange ==
    Scenario = "ViewChange" /\ phase = 15 => \A r \in HR: auditIndex[r] >= 1
AuditedAfterViewChange ==
    phase = EndPhase => \A r \in HR: auditIndex[r] >= 2
ByzantineActionsExercised ==
    Scenario = "Byzantine" /\ phase = EndPhase => byzActions = 2
====

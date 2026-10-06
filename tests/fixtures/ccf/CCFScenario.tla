---- MODULE CCFScenario ----
EXTENDS CCFProof
CONSTANTS First, Second, Scenario
VARIABLE step

ScenarioInit == Init /\ leadershipState[First] = Leader /\ step = 0

Join ==
    CASE step = 0 -> ChangeConfigurationInt(First, {First, Second}) /\ step' = 1
      [] step = 1 -> SignCommittableMessages(First) /\ step' = 2
      [] step = 2 -> AppendEntries(First, Second) /\ step' = 3
      [] step = 3 -> RcvUpdateTerm(Second, First) /\ step' = 4
      [] step = 4 -> RcvAppendEntriesRequest(Second, First) /\ step' = 5
      [] step = 5 -> RcvAppendEntriesResponse(First, Second) /\ step' = 6
      [] step = 6 -> AppendEntries(First, Second) /\ step' = 7
      [] step = 7 -> RcvAppendEntriesRequest(Second, First) /\ step' = 8
      [] step = 8 -> RcvAppendEntriesResponse(First, Second) /\ step' = 9
      [] step = 9 -> AppendEntries(First, Second) /\ step' = 10
      [] step = 10 -> RcvAppendEntriesRequest(Second, First) /\ step' = 11
      [] step = 11 -> RcvAppendEntriesResponse(First, Second) /\ step' = 12
      [] step = 12 -> AppendEntries(First, Second) /\ step' = 13
      [] step = 13 -> RcvAppendEntriesRequest(Second, First) /\ step' = 14
      [] step = 14 -> RcvAppendEntriesResponse(First, Second) /\ step' = 15
      [] step = 15 -> AppendEntries(First, Second) /\ step' = 16
      [] step = 16 -> RcvAppendEntriesRequest(Second, First) /\ step' = 17
      [] step = 17 -> RcvAppendEntriesResponse(First, Second) /\ step' = 18
      [] step = 18 -> AdvanceCommitIndex(First) /\ step' = 19
      [] step = 19 -> AppendEntries(First, Second) /\ step' = 20
      [] step = 20 -> RcvAppendEntriesRequest(Second, First) /\ step' = 21
      [] step = 21 -> RcvAppendEntriesResponse(First, Second) /\ step' = 22
      [] OTHER -> FALSE

ElectionAndRollback ==
    CASE step = 22 -> ClientRequest(First) /\ step' = 23
      [] step = 23 -> CheckQuorum(First) /\ step' = 24
      [] step = 24 -> Timeout(Second) /\ step' = 25
      [] step = 25 -> RequestVote(Second, First) /\ step' = 26
      [] step = 26 -> RcvUpdateTerm(First, Second) /\ step' = 27
      [] step = 27 -> RcvRequestVoteRequest(First, Second) /\ step' = 28
      [] step = 28 -> RcvRequestVoteResponse(Second, First) /\ step' = 29
      [] step = 29 -> BecomeLeader(Second) /\ step' = 30
      [] step = 30 -> ClientRequest(Second) /\ step' = 31
      [] step = 31 -> SignCommittableMessages(Second) /\ step' = 32
      [] step = 32 -> AppendEntries(Second, First) /\ step' = 33
      [] step = 33 -> RcvAppendEntriesRequest(First, Second) /\ step' = 34
      [] step = 34 -> RcvAppendEntriesResponse(Second, First) /\ step' = 35
      [] step = 35 -> AppendEntries(Second, First) /\ step' = 36
      [] step = 36 -> RcvAppendEntriesRequest(First, Second) /\ step' = 37
      [] step = 37 -> RcvAppendEntriesResponse(Second, First) /\ step' = 38
      [] step = 38 -> AdvanceCommitIndex(Second) /\ step' = 39
      [] step = 39 -> AppendEntries(Second, First) /\ step' = 40
      [] step = 40 -> RcvAppendEntriesRequest(First, Second) /\ step' = 41
      [] step = 41 -> RcvAppendEntriesResponse(Second, First) /\ step' = 42
      [] OTHER -> FALSE

Retirement ==
    CASE step = 22 -> ChangeConfigurationInt(First, {Second}) /\ step' = 23
      [] step = 23 -> SignCommittableMessages(First) /\ step' = 24
      [] step = 24 -> AppendEntries(First, Second) /\ step' = 25
      [] step = 25 -> RcvAppendEntriesRequest(Second, First) /\ step' = 26
      [] step = 26 -> RcvAppendEntriesResponse(First, Second) /\ step' = 27
      [] step = 27 -> AppendEntries(First, Second) /\ step' = 28
      [] step = 28 -> RcvAppendEntriesRequest(Second, First) /\ step' = 29
      [] step = 29 -> RcvAppendEntriesResponse(First, Second) /\ step' = 30
      [] step = 30 -> AdvanceCommitIndex(First) /\ step' = 31
      [] step = 31 -> AppendEntries(First, Second) /\ step' = 32
      [] step = 32 -> RcvAppendEntriesRequest(Second, First) /\ step' = 33
      [] step = 33 -> RcvAppendEntriesResponse(First, Second) /\ step' = 34
      [] step = 34 -> AppendRetiredCommitted(First) /\ step' = 35
      [] step = 35 -> SignCommittableMessages(First) /\ step' = 36
      [] step = 36 -> AppendEntries(First, Second) /\ step' = 37
      [] step = 37 -> RcvAppendEntriesRequest(Second, First) /\ step' = 38
      [] step = 38 -> RcvAppendEntriesResponse(First, Second) /\ step' = 39
      [] step = 39 -> AppendEntries(First, Second) /\ step' = 40
      [] step = 40 -> RcvAppendEntriesRequest(Second, First) /\ step' = 41
      [] step = 41 -> RcvAppendEntriesResponse(First, Second) /\ step' = 42
      [] step = 42 -> AdvanceCommitIndex(First) /\ step' = 43
      [] OTHER -> FALSE

JoinLength == 22
TailLength == IF Scenario = "election" THEN 20 ELSE 21

Done == step = JoinLength + TailLength
ScenarioNext ==
    /\ ~Done
    /\ IF step < JoinLength THEN Join
       ELSE IF Scenario = "election" THEN ElectionAndRollback ELSE Retirement
ScenarioSpec == ScenarioInit /\ [][ScenarioNext]_<<vars, step>>

\* Every scheduled transition must also be an unchanged upstream protocol step.
FollowsProtocol == Init /\ [][Next]_vars
NotDone == ~Done
Outcome == Done =>
    /\ commitIndex[First] = commitIndex[Second]
          \/ Scenario = "retirement"
    /\ IF Scenario = "election"
       THEN /\ currentTerm[Second] = StartTerm + 1
            /\ leadershipState[Second] = Leader
            /\ commitIndex[Second] = 6
            /\ log[First][5].term = StartTerm + 1
       ELSE /\ membershipState[First] = RetiredCommitted
            /\ leadershipState[First] = Follower
            /\ Range(configurations[First]) = {{Second}}
            /\ commitIndex[First] = 8
====

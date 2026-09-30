---- MODULE RecursionComparison ----
EXTENDS PirateShip
Original == INSTANCE pirateship
VARIABLE checked

VoteSets(k) == [1..k -> SUBSET R]
TestBranch(k, votes) ==
    [i \in 1..k |-> [view |-> 0, tx |-> <<1>>,
        auditQC |-> IF i % 2 = 0 THEN {} ELSE {i-1},
        auditQCVotes |-> votes[i], commitQC |-> {}]]

UnanimityMatches ==
    \A k \in 0..3: \A votes \in VoteSets(k), idx \in 0..k, r \in R:
        LET b == TestBranch(k, votes)
        IN HighestUnanimity(b, idx, r) = Original!HighestUnanimity(b, idx, r)

QuorumMatches ==
    \A k \in 0..3: \A default \in 0..k, m \in [R -> 0..4], Q \in {CQ, AQ, {}, {{}}}:
        LET b == [i \in 1..k |-> 0]
        IN MaxQuorum(Q, b, m, default) = Original!MaxQuorum(Q, b, m, default)

InitCheck == /\ Init /\ checked = FALSE
NextCheck == /\ ~checked /\ checked' = TRUE /\ UNCHANGED vars
Matches == UnanimityMatches /\ QuorumMatches
====

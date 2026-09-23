---- MODULE SailfishLeaderDomain ----
EXTENDS SailfishDefs, TLC
CONSTANTS a, b, LeaderInNodes

MCN == {a}
MCF == {}
MCR == 1..3
MCIsQuorum(S) == a \in S
MCIsBlocking(S) == a \in S
MCLeader(r) == IF LeaderInNodes THEN a ELSE b
MCGST == 0

EndpointHasLeader == round[a] = 3 => log[a] = <<<<a, 1>>>>
====

---- MODULE SailfishSmall ----
EXTENDS SailfishDefs, TLC
CONSTANTS a, b, c, d, FourNodes, SyncRound
MCN == IF FourNodes THEN {a, b, c, d} ELSE {a, b, c}
MCF == IF FourNodes THEN {d} ELSE {a}
MCR == IF FourNodes THEN 1..3 ELSE 1..4
MCIsQuorum(Q) == IF FourNodes THEN Cardinality(Q) >= 3 ELSE c \in Q /\ Cardinality(Q) >= 2
MCIsBlocking(B) == IF FourNodes THEN Cardinality(B) >= 2 ELSE c \in B
MCLeader(r) == IF FourNodes THEN CASE r = 1 -> a [] r = 2 -> d [] OTHER -> b
                           ELSE CASE r % 3 = 1 -> a [] r % 3 = 2 -> b [] OTHER -> c
MCGST == SyncRound
====

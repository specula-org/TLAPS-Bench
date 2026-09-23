---- MODULE SailfishReplay ----
EXTENDS SailfishDefs, TLC
CONSTANTS a, b, c, d, e, LiveCase, GoodLeader, Monotone
MCN == IF LiveCase THEN {a, b, c, d, e} ELSE {a, b, c, d}
MCF == IF LiveCase THEN {d, e} ELSE {d}
MCR == IF LiveCase THEN 1..3 ELSE 1..5
Bases == {{a, b, c}, {b, c, d, e}, {a, b, c, d, e}}
MCIsQuorum(S) == IF LiveCase
                   THEN IF Monotone THEN \E Q \in Bases : Q \subseteq S ELSE S \in Bases
                   ELSE Cardinality(S) >= 3
MCIsBlocking(B) == IF LiveCase THEN B \cap {b, c} # {} ELSE Cardinality(B) >= 2
MCLeader(r) == IF LiveCase THEN CASE r = 1 -> a [] r = 2 -> b [] OTHER -> c
                          ELSE IF r = 1 THEN a ELSE d
MCGST == 0

AgreementSchedule == <<
    [node |-> b, rnd |-> 1, parents |-> {Genesis}],
    [node |-> c, rnd |-> 1, parents |-> {Genesis}],
    [node |-> d, rnd |-> 1, parents |-> {Genesis}],
    [node |-> a, rnd |-> 1, parents |-> {Genesis}],
    [node |-> a, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> b, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> c, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> a, rnd |-> 3, parents |-> {<<a, 2>>, <<b, 2>>, <<c, 2>>}],
    [node |-> b, rnd |-> 3, parents |-> {<<a, 2>>, <<b, 2>>, <<c, 2>>}],
    [node |-> d, rnd |-> 2, parents |-> IF GoodLeader THEN {<<a, 1>>, <<b, 1>>, <<d, 1>>} ELSE {<<b, 1>>, <<c, 1>>, <<d, 1>>}],
    [node |-> d, rnd |-> 3, parents |-> {<<a, 2>>, <<b, 2>>, <<d, 2>>}],
    [node |-> c, rnd |-> 3, parents |-> {<<a, 2>>, <<b, 2>>, <<c, 2>>}],
    [node |-> a, rnd |-> 4, parents |-> {<<a, 3>>, <<b, 3>>, <<c, 3>>, <<d, 3>>}],
    [node |-> b, rnd |-> 4, parents |-> {<<a, 3>>, <<b, 3>>, <<c, 3>>, <<d, 3>>}],
    [node |-> c, rnd |-> 4, parents |-> {<<a, 3>>, <<b, 3>>, <<c, 3>>, <<d, 3>>}],
    [node |-> a, rnd |-> 5, parents |-> {<<a, 4>>, <<b, 4>>, <<c, 4>>}]
>>
LivenessSchedule == <<
    [node |-> c, rnd |-> 1, parents |-> {Genesis}],
    [node |-> b, rnd |-> 1, parents |-> {Genesis}],
    [node |-> a, rnd |-> 1, parents |-> {Genesis}],
    [node |-> a, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> b, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> d, rnd |-> 1, parents |-> {Genesis}],
    [node |-> d, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> c, rnd |-> 2, parents |-> {<<a, 1>>, <<b, 1>>, <<c, 1>>}],
    [node |-> e, rnd |-> 1, parents |-> {Genesis}],
    [node |-> e, rnd |-> 2, parents |-> {<<b, 1>>, <<c, 1>>, <<d, 1>>, <<e, 1>>}],
    [node |-> a, rnd |-> 3, parents |-> {<<a, 2>>, <<b, 2>>, <<c, 2>>, <<d, 2>>, <<e, 2>>}]
>>
Schedule == IF LiveCase THEN LivenessSchedule ELSE AgreementSchedule

VARIABLE step
ReplayVars == <<vars, step>>
ReplayInit == Init /\ step = 1
ReplayNext ==
    /\ step <= Len(Schedule)
    /\ Next
    /\ LET action == Schedule[step]
           v == <<action.node, action.rnd>>
       IN /\ vs' = vs \cup {v}
          /\ es' = es \cup {<<v, p>> : p \in action.parents}
          /\ round' = IF action.node \in F THEN round
                         ELSE [round EXCEPT ![action.node] = action.rnd]
    /\ step' = step + 1
ReplaySpec == ReplayInit /\ [][ReplayNext]_ReplayVars

Completed == step = Len(Schedule) + 1
EndpointHasFirstLeader == Completed =>
    IF LiveCase THEN <<a, 1>> \in {log[a][i] : i \in DOMAIN log[a]}
                ELSE \A n \in N \ F : <<a, 1>> \in {log[n][i] : i \in DOMAIN log[n]}
====

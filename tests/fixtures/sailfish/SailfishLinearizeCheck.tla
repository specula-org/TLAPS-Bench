---- MODULE SailfishLinearizeCheck ----
EXTENDS SailfishDefs, TLC
CONSTANTS a, b
MCN == {a, b}
MCF == {}
MCR == 1..2
MCIsQuorum(Q) == Q = MCN
MCIsBlocking(B) == B # {}
MCLeader(r) == IF r = 1 THEN a ELSE b
MCGST == 0
TestVs == {Genesis, <<a, 1>>, <<b, 1>>, <<b, 2>>}
TestEs == {<<<<a, 1>>, Genesis>>, <<<<b, 1>>, Genesis>>,
           <<<<b, 2>>, <<a, 1>>>>, <<<<b, 2>>, <<b, 1>>>>}
TestDag == <<TestVs, TestEs>>
LegacyLinearize(graph, l) ==
    LET linearize[d \in (SUBSET Vertices(graph)) \X (SUBSET Edges(graph)),
                  v \in Vertices(graph)] ==
          IF Vertices(d) = {<<>>} THEN <<>> ELSE
          LET dagOfL == SubDag(d, {v})
              prevL == PreviousLeader(dagOfL, Round(v))
              dagOfPrev == SubDag(d, {prevL})
              remaining == Vertices(dagOfL) \ Vertices(dagOfPrev)
          IN  linearize[dagOfPrev, prevL] \o OrderSet(remaining \ {v}) \o <<v>>
    IN  linearize[graph, l]

InitCheck == Init
NextCheck == UNCHANGED vars
GenesisIsEmpty == Linearize(TestDag, Genesis) = <<>>
SamePositiveHistories == \A v \in TestVs \ {Genesis} : Linearize(TestDag, v) = LegacyLinearize(TestDag, v)
ExpectedOrder == Linearize(TestDag, <<b, 2>>) = <<<<a, 1>>, <<b, 1>>, <<b, 2>>>>
====

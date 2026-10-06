---- MODULE SnapshotPositionWitness ----
EXTENDS MultiShardTxn
VARIABLE step
TraceVars == <<vars, step>>
TraceAction ==
 CASE step = 0 -> RouterTxnStart("r", 1, 0)
 [] step = 1 -> RouterTxnOp("r", "s", 1, "a", "read")
 [] step = 2 -> ShardTxnStart("s", 1)
 [] step = 3 -> ShardTxnRead("s", 1, "a", NoValue)
 [] step = 4 -> RouterTxnOp("r", "s", 1, "b", "read")
 [] step = 5 -> ShardTxnRead("s", 1, "b", NoValue)
 [] step = 6 -> RouterTxnOp("r", "s", 1, "a", "write")
 [] step = 7 -> ShardTxnWrite("s", 1, "a")
 [] step = 8 -> RouterTxnCommitSingleShard("r", "s", 1)
 [] step = 9 -> ShardTxnCommit("s", 1)
 [] step = 10 -> RouterTxnStart("r", 2, 0)
 [] step = 11 -> RouterTxnOp("r", "s", 2, "a", "read")
 [] step = 12 -> ShardTxnStart("s", 2)
 [] step = 13 -> ShardTxnRead("s", 2, "a", NoValue)
 [] step = 14 -> RouterTxnOp("r", "s", 2, "b", "read")
 [] step = 15 -> ShardTxnRead("s", 2, "b", NoValue)
 [] step = 16 -> RouterTxnOp("r", "s", 2, "b", "write")
 [] step = 17 -> ShardTxnWrite("s", 2, "b")
 [] step = 18 -> RouterTxnCommitSingleShard("r", "s", 2)
 [] step = 19 -> ShardTxnCommit("s", 2)
 [] step = 20 -> RouterTxnStart("r", 100, 2)
 [] step = 21 -> RouterTxnOp("r", "s", 100, "a", "read")
 [] step = 22 -> ShardTxnStart("s", 100)
 [] step = 23 -> ShardTxnRead("s", 100, "a", 1)
 [] step = 24 -> RouterTxnOp("r", "s", 100, "b", "read")
 [] step = 25 -> ShardTxnRead("s", 100, "b", 2)
 [] step = 26 -> RouterTxnOp("r", "s", 100, "a", "write")
 [] step = 27 -> ShardTxnWrite("s", 100, "a")
 [] step = 28 -> RouterTxnOp("r", "s", 100, "b", "write")
 [] step = 29 -> ShardTxnWrite("s", 100, "b")
 [] step = 30 -> RouterTxnCommitSingleShard("r", "s", 100)
 [] step = 31 -> ShardTxnCommit("s", 100)
 [] step = 32 -> RouterTxnStart("r", 3, 3)
 [] step = 33 -> RouterTxnOp("r", "s", 3, "a", "read")
 [] step = 34 -> ShardTxnStart("s", 3)
 [] step = 35 -> ShardTxnRead("s", 3, "a", 100)
 [] step = 36 -> RouterTxnOp("r", "s", 3, "b", "read")
 [] step = 37 -> ShardTxnRead("s", 3, "b", 100)
 [] step = 38 -> RouterTxnOp("r", "s", 3, "a", "write")
 [] step = 39 -> ShardTxnWrite("s", 3, "a")
 [] step = 40 -> RouterTxnCommitSingleShard("r", "s", 3)
 [] step = 41 -> ShardTxnCommit("s", 3)
 [] OTHER -> FALSE
TraceInit == Init /\ step = 0
TraceNext == /\ step < 42 /\ TraceAction /\ step' = step + 1
TraceSpec == TraceInit /\ [][TraceNext]_TraceVars /\ WF_TraceVars(TraceNext)
ReachedEnd == <> (step = 42)
SingleWritePerKey ==
 \A t \in Range(ops) : \A i, j \in DOMAIN t :
   (t[i].op = "write" /\ t[j].op = "write" /\ t[i].key = t[j].key) => i = j
ExpectedHistory == step = 42 =>
 /\ ops[1] = <<rOp("a",NoValue),rOp("b",NoValue),wOp("a",1)>>
 /\ ops[2] = <<rOp("a",NoValue),rOp("b",NoValue),wOp("b",2)>>
 /\ ops[100] = <<rOp("a",1),rOp("b",2),wOp("a",100),wOp("b",100)>>
 /\ ops[3] = <<rOp("a",100),rOp("b",100),wOp("a",3)>>
Legacy == INSTANCE LegacyClientCentric WITH Keys <- Keys, Values <- TxId \cup {NoValue}
LegacySI == Legacy!SnapshotIsolation(InitialState, Range(ops))
ExpectedLegacyOutcome == step = 42 => (LegacySI <=> (NoValue # 100))
LegacyFinalSI == step = 42 => LegacySI
====

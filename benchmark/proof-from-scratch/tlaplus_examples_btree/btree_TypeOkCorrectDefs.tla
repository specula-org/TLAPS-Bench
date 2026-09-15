
---- MODULE btree_TypeOkCorrectDefs ----
EXTENDS btreeModel

TypeOk == /\ root \in Nodes
          /\ isLeaf \in [Nodes -> BOOLEAN]
          /\ keysOf \in [Nodes -> SUBSET Keys]
          /\ childOf \in [Nodes \X Keys -> Nodes \union {NIL}]
          /\ lastOf \in [Nodes -> Nodes \union {NIL}]
          /\ valOf \in [Nodes \X Keys -> Vals \union {NIL}]
          /\ focus \in Nodes \union {NIL}
          /\ toSplit \in Seq(Nodes)
          /\ op \in {"get", "insert", "update", NIL}
          /\ ret \in Vals \union {"ok", "error", MISSING, NIL}
          /\ state \in States

====

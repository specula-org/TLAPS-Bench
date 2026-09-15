
---- MODULE btreeDefs ----
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

Leaves == {n \in Nodes : isLeaf[n]}

Inners == {n \in Nodes: ~isLeaf[n]}

InnersMustHaveLast == \A n \in Inners : lastOf[n] # NIL
KeyOrderPreserved == \A n \in Inners : (\A k \in keysOf[n] : (\A kc \in keysOf[childOf[n, k]]: kc < k))
LeavesCantHaveLast == \A n \in Leaves : lastOf[n] = NIL
KeysInLeavesAreUnique ==
    \A n1, n2 \in Leaves : ((keysOf[n1] \intersect keysOf[n2]) # {}) => n1=n2

====

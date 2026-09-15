
---- MODULE btree_KeysInLeavesAreUniqueCorrectDefs ----
EXTENDS btreeModel

Leaves == {n \in Nodes : isLeaf[n]}

KeysInLeavesAreUnique ==
    \A n1, n2 \in Leaves : ((keysOf[n1] \intersect keysOf[n2]) # {}) => n1=n2

====

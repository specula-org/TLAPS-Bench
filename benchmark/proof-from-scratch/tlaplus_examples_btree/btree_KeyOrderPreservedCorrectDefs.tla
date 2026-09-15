
---- MODULE btree_KeyOrderPreservedCorrectDefs ----
EXTENDS btreeModel

Inners == {n \in Nodes: ~isLeaf[n]}

KeyOrderPreserved == \A n \in Inners : (\A k \in keysOf[n] : (\A kc \in keysOf[childOf[n, k]]: kc < k))

====

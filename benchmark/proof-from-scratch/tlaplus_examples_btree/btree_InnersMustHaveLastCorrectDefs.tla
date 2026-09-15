
---- MODULE btree_InnersMustHaveLastCorrectDefs ----
EXTENDS btreeModel

Inners == {n \in Nodes: ~isLeaf[n]}

InnersMustHaveLast == \A n \in Inners : lastOf[n] # NIL

====

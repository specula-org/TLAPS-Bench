
---- MODULE btree_LeavesCantHaveLastCorrectDefs ----
EXTENDS btreeModel

Leaves == {n \in Nodes : isLeaf[n]}

LeavesCantHaveLast == \A n \in Leaves : lastOf[n] = NIL

====

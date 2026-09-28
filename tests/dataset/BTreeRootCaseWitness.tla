---- MODULE BTreeRootCaseWitness ----
EXTENDS btreeDefs
VARIABLE step
NoNode == "nil"
NoValue == "missing"
TraceVars == <<vars,step>>
TraceAction ==
 CASE step = 0 -> InsertReq(1,"v")
 [] step = 1 -> FindLeafToAdd
 [] step = 2 -> AddToLeaf
 [] step = 3 -> InsertReq(2,"v")
 [] step = 4 -> FindLeafToAdd
 [] step = 5 -> AddToLeaf
 [] step = 6 -> InsertReq(3,"v")
 [] step = 7 -> FindLeafToAdd
 [] step = 8 -> WhichToSplit
 [] OTHER -> FALSE
TraceInit == Init /\ step = 0
TraceNext == /\ step < 9 /\ TraceAction /\ step' = step + 1
TraceSpec == TraceInit /\ [][TraceNext]_TraceVars /\ WF_TraceVars(TraceNext)
ReachedEnd == <> (step = 9)
EventuallyBad == <> ~TypeOk
RootHasNoParent == step = 8 =>
 /\ root = Head(toSplit) /\ isLeaf[root] /\ keysOf[root] = {1,2}
 /\ toSplit = <<root>> /\ state = WHICH_TO_SPLIT
 /\ ~\E p \in Nodes : (\E k \in Keys : childOf[p,k] = root) \/ lastOf[p] = root
 /\ ParentOf(root) = NIL /\ AtMaxOccupancy(NIL)
RootStackPreserved == step = 9 => /\ toSplit = <<root>> /\ state = SPLIT_ROOT_LEAF
====

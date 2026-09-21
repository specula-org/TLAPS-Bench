---- MODULE BTreeFunctionEncodingCheck ----
EXTENDS btreeModel

VARIABLE checked

NoNode == 0
NoValue == "missing"

\* Retain the original constructors as an independent transition oracle.
OriginalSplitValues ==
    LET n1 == Head(toSplit)
        n2 == ChooseFreeNode
        pivot == PivotOf(keysOf[n1])
        n2Keys == {x \in keysOf[n1] : x >= pivot}
    IN [n \in Nodes, k \in Keys |->
        CASE n = n1 /\ k \in n2Keys -> NIL
          [] n = n2 /\ k \in n2Keys -> valOf[n1, k]
          [] OTHER -> valOf[n, k]]

OriginalSplitChildren ==
    LET n1 == Head(toSplit)
        n2 == ChooseFreeNode
        newRoot == CHOOSE n \in Nodes : IsFree(n) /\ n # n2
        pivot == PivotOf(keysOf[n1])
        n1Keys == {x \in keysOf[n1] : x < pivot}
        n2Keys == {x \in keysOf[n1] : x > pivot}
    IN [n \in Nodes, k \in Keys |->
        CASE n = newRoot /\ k = pivot -> n1
          [] n = n1 /\ k \in n2Keys -> NIL
          [] n = n1 /\ k \in n1Keys -> childOf[n1, k]
          [] n = n2 /\ k \in n2Keys -> childOf[n1, k]
          [] OTHER -> childOf[n, k]]

CheckInit ==
    \/ /\ Init
       /\ checked =
           /\ childOf = [n \in Nodes, k \in Keys |-> NIL]
           /\ valOf = [n \in Nodes, k \in Keys |-> NIL]
    \/ \E s \in {SPLIT_LEAF, SPLIT_ROOT_LEAF, SPLIT_ROOT_INNER} :
        /\ state = s
        /\ root = IF s = SPLIT_LEAF THEN 2 ELSE 1
        /\ isLeaf = [n \in Nodes |-> ~(n = 2 \/ (n = 1 /\ s = SPLIT_ROOT_INNER))]
        /\ keysOf = [n \in Nodes |-> IF n = 1 THEN 1..4 ELSE IF n = 2 THEN {5} ELSE {}]
        /\ childOf = [p \in Nodes \X Keys |->
                         IF p = <<2, 5>> THEN 1 ELSE IF p[1] = 1 THEN 3 ELSE NIL]
        /\ lastOf = [n \in Nodes |-> IF n = 2 THEN 1 ELSE NIL]
        /\ valOf = [p \in Nodes \X Keys |-> 10 * p[1] + p[2]]
        /\ focus = 1
        /\ toSplit = <<1>>
        /\ op = "insert"
        /\ args = <<5, 42>>
        /\ ret = NIL
        /\ checked = TRUE

CheckNext ==
    \/ /\ SplitRootLeaf
       /\ checked' = (valOf' = OriginalSplitValues)
    \/ /\ SplitLeaf
       /\ checked' = (valOf' = OriginalSplitValues)
    \/ /\ SplitRootInner
       /\ checked' = (childOf' = OriginalSplitChildren)

SameTableValues == checked
====

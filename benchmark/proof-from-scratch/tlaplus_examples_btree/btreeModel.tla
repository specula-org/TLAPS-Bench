
---- MODULE btreeModel ----
EXTENDS Naturals,
        FiniteSets,
        Sequences,
        Relation

CONSTANTS Vals,
          Keys,
          Nodes,
          MaxOccupancy,

          READY,
          GET_VALUE,
          FIND_LEAF_TO_ADD,
          WHICH_TO_SPLIT,
          ADD_TO_LEAF,
          SPLIT_LEAF,
          SPLIT_INNER,
          SPLIT_ROOT_LEAF,
          SPLIT_ROOT_INNER,
          UPDATE_LEAF

States == {READY, GET_VALUE, FIND_LEAF_TO_ADD, WHICH_TO_SPLIT, ADD_TO_LEAF,
           SPLIT_LEAF, SPLIT_INNER, SPLIT_ROOT_LEAF, SPLIT_ROOT_INNER, UPDATE_LEAF}

ASSUME StatesAreDistinct == IsFiniteSet(States) /\ Cardinality(States) = 10

ASSUME KeysAreOrdered == IsStrictlyTotallyOrderedUnder(<, Keys)

ASSUME MaxOccupancyPermitsSplitting == MaxOccupancy \in Nat /\ MaxOccupancy >= 2

ASSUME NodePoolIsNonEmpty == Nodes # {}

NIL == CHOOSE x : x \notin Nodes
MISSING == CHOOSE v : v \notin Vals

VARIABLES root,
          isLeaf, keysOf, childOf, lastOf, valOf,
          focus,
          toSplit,
          op, args, ret,
          state

Max(xs) == CHOOSE x \in xs : (\A y \in xs \ {x} : x > y)

ChildNodeFor(node, key) ==
    LET keys == keysOf[node]
        maxKey == Max(keys)
        closestKey ==  CHOOSE k \in keys : /\ k>key
                                           /\ ~(\E j \in keys \ {k} : j>key /\ j<k)
    IN IF keys = {} \/ key >= maxKey
       THEN lastOf[node]
       
       ELSE
       childOf[node, closestKey]

FindLeafNode(node, key) ==
    LET findLeaf[n \in Nodes] ==
          IF isLeaf[n] THEN n ELSE findLeaf[ChildNodeFor(n, key)]
    IN  findLeaf[node]

AtMaxOccupancy(node) == Cardinality(keysOf[node]) = MaxOccupancy

IsFree(node) == isLeaf[node] /\ keysOf[node] = {}

ChooseFreeNode == CHOOSE n \in Nodes : IsFree(n)

Init == /\ isLeaf = [n \in Nodes |-> TRUE]
        /\ keysOf = [n \in Nodes |-> {}]
        /\ childOf = [n \in Nodes, k \in Keys |-> NIL]
        /\ lastOf = [n \in Nodes |-> NIL]
        /\ valOf = [n \in Nodes, k \in Keys |-> NIL]
        /\ root = ChooseFreeNode
        /\ focus = NIL
        /\ toSplit = <<>>
        /\ op = NIL
        /\ args = NIL
        /\ ret = NIL
        /\ state = READY

GetReq(key) == 
    /\ state = READY
    /\ op' = "get"
    /\ args' = <<key>>
    /\ ret' = NIL
    /\ state' = GET_VALUE
    /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, valOf, focus, toSplit>>

GetValue ==
    LET key == args[1] 
        node == FindLeafNode(root, key) IN
    /\ state = GET_VALUE
    /\ state' = READY
    /\ ret' = IF key \in keysOf[node] THEN valOf[node, key] ELSE MISSING
    /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, valOf, focus, toSplit, args, op>>

InsertReq(key, val) ==
    /\ state = READY
    /\ op' = "insert"
    /\ args' = <<key, val>>
    /\ ret' = NIL
    /\ state' = FIND_LEAF_TO_ADD
    /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, valOf, focus, toSplit>>

UpdateReq(key, val) ==
    LET leaf == FindLeafNode(root, key)
    IN /\ state = READY
       /\ op' = "update"
       /\ args' = <<key, val>>
       /\ ret' = NIL
       /\ focus' = leaf
       /\ state' = UPDATE_LEAF
       /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, valOf, toSplit>>

UpdateLeaf ==
    LET key == args[1]
        val == args[2]
    IN /\ state = UPDATE_LEAF
       /\ valOf' = IF key \in keysOf[focus] THEN [valOf EXCEPT ![focus, key]=val] ELSE valOf
       /\ ret' = IF key \in keysOf[focus] THEN "ok" ELSE "error"
       /\ state' = READY
       /\ focus' = NIL
       /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, toSplit, args, op>>

FindLeafToAdd ==
    LET key == args[1]
        leaf == FindLeafNode(root, key)
    IN /\ state = FIND_LEAF_TO_ADD
       /\ focus' = leaf
       /\ toSplit' = IF AtMaxOccupancy(leaf) THEN <<leaf>> ELSE <<>>
       /\ state' = IF AtMaxOccupancy(leaf) THEN WHICH_TO_SPLIT ELSE ADD_TO_LEAF
       /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, valOf, args, op, ret>>

ParentOf(n) == CHOOSE p \in Nodes: \/ \E k \in Keys: n = childOf[p, k]
                                   \/ lastOf[p]=n

WhichToSplit ==
    LET  node == Head(toSplit)
         parent == ParentOf(node)
         splitParent == AtMaxOccupancy(parent)
         noMoreSplits == ~splitParent  
    IN /\ state = WHICH_TO_SPLIT
       /\ toSplit' =
           CASE node = root   -> toSplit
             [] splitParent   -> <<parent>> \o toSplit
             [] OTHER         -> toSplit
       /\ state' =
            CASE node # root /\ noMoreSplits /\ isLeaf[node]  -> SPLIT_LEAF
              [] node # root /\ noMoreSplits /\ ~isLeaf[node] -> SPLIT_INNER
              [] node = root /\ isLeaf[node]                  -> SPLIT_ROOT_LEAF
              [] node = root /\ ~isLeaf[node]                 -> SPLIT_ROOT_INNER
              [] OTHER                                        -> WHICH_TO_SPLIT
       /\ UNCHANGED <<root, isLeaf, keysOf, childOf, lastOf, valOf, op, args, ret, focus>>

AddToLeaf ==
    LET key == args[1]
        val == args[2] IN
       /\ state = ADD_TO_LEAF
       /\ ret' = IF key \notin keysOf[focus] THEN "ok" ELSE "error"
       /\ keysOf' = IF key \notin keysOf[focus] THEN [keysOf EXCEPT ![focus]=@ \union {key}] ELSE keysOf
       /\ valOf' = IF key \notin keysOf[focus] THEN [valOf EXCEPT ![focus,key]=val] ELSE valOf
       /\ state' = READY
       /\ UNCHANGED <<root, isLeaf, childOf, lastOf, op, args, focus, toSplit>>

PivotOf(keys) == CHOOSE k \in keys :
    LET smaller == {x \in keys : x < k}
        larger == {x \in keys: x > k} IN
     \/ Cardinality(smaller) = Cardinality(larger)
     \/ Cardinality(smaller) = Cardinality(larger)+1

SplitRootLeaf ==
    LET n1 == Head(toSplit)
        n2 == ChooseFreeNode
        newRoot == CHOOSE n \in Nodes : IsFree(n) /\ (n # n2)
        keys == keysOf[n1]
        pivot == PivotOf(keys)
        n1Keys == {x \in keys: x<pivot}
        n2Keys == {x \in keys: x>=pivot} 
        keyToInsert == args[1] IN
    /\ state = SPLIT_ROOT_LEAF
    /\ root' = newRoot
    /\ isLeaf' = [isLeaf EXCEPT ![newRoot]=FALSE, ![n2]=TRUE]
    /\ keysOf' = [keysOf EXCEPT ![newRoot]={pivot}, ![n1]=n1Keys, ![n2]=n2Keys]
    /\ childOf' = [childOf EXCEPT ![newRoot, pivot]=n1]
    /\ lastOf' = [lastOf EXCEPT ![newRoot]=n2]
    /\ valOf' = [n \in Nodes, k \in Keys |->
        CASE n=n1 /\ k \in n2Keys -> NIL
          [] n=n2 /\ k \in n2Keys -> valOf[n1, k]
          [] OTHER                -> valOf[n, k]]

    /\ state' = ADD_TO_LEAF
    /\ focus' = IF keyToInsert < pivot THEN n1 ELSE n2
    /\ UNCHANGED <<op, args, ret, toSplit>>

ParentKeyOf(node) ==
    LET p == ParentOf(node) IN
    CHOOSE k \in keysOf[p]: childOf[p, k] = node

IsLastOfParent(node) == lastOf[ParentOf(node)] = node

SplitRootInner ==
    LET n1 == Head(toSplit)
        n2 == ChooseFreeNode
        newRoot == CHOOSE n \in Nodes : IsFree(n) /\ (n # n2)
        keys == keysOf[n1]
        pivot == PivotOf(keys)
        
        n1Keys == {x \in keys: x<pivot}
        n2Keys == {x \in keys: x>pivot} IN
    /\ state = SPLIT_ROOT_INNER
    /\ root' = newRoot
    /\ isLeaf' = [isLeaf EXCEPT ![newRoot]=FALSE, ![n2]=FALSE]
    /\ keysOf' = [keysOf EXCEPT ![newRoot]={pivot}, ![n1]=n1Keys, ![n2]=n2Keys]
    /\ childOf' = [n \in Nodes, k \in Keys |->
        CASE n=newRoot /\ k=pivot -> n1
          [] n=n1 /\ k \in n2Keys -> NIL
          [] n=n1 /\ k \in n1Keys -> childOf[n1, k]
          [] n=n2 /\ k \in n2Keys -> childOf[n1, k]
          [] OTHER                -> childOf[n, k]]
    /\ lastOf' = [lastOf EXCEPT ![newRoot]=n2, ![n1]=childOf[n1, pivot], ![n2]=lastOf[n1]]
    /\ toSplit' = <<>>
    /\ state' = ADD_TO_LEAF
    /\ UNCHANGED <<op, args, ret, focus, valOf>>

SplitLeaf ==
    LET n1 == Head(toSplit)
        n2 == ChooseFreeNode
        keys == keysOf[n1]
        pivot == PivotOf(keys)
        parent == ParentOf(n1)
        n1Keys == {x \in keys: x<pivot}
        n2Keys == {x \in keys: x>=pivot}
        keyToInsert == args[1]
    IN
    /\ state = SPLIT_LEAF
    /\ isLeaf' = [isLeaf EXCEPT ![n2]=TRUE]
    /\ keysOf' = [keysOf EXCEPT ![parent]=@ \union {pivot}, ![n1]=n1Keys, ![n2]=n2Keys]

    /\ childOf' = IF IsLastOfParent(n1)
                  THEN [childOf EXCEPT ![parent, pivot]=n1]
                  ELSE [childOf EXCEPT ![parent, pivot]=n1, ![parent, ParentKeyOf(n1)]=n2]
    /\ lastOf' = IF IsLastOfParent(n1) THEN [lastOf EXCEPT ![parent]=n2] ELSE lastOf
    /\ valOf' = [n \in Nodes, k \in Keys |->
        CASE n=n1 /\ k \in n2Keys -> NIL
          [] n=n2 /\ k \in n2Keys -> valOf[n1, k]
          [] OTHER                -> valOf[n, k]]
    /\ state' = ADD_TO_LEAF
    /\ focus' = IF keyToInsert < pivot THEN n1 ELSE n2
    /\ UNCHANGED <<root, toSplit, op, args, ret>>

Next == \/ \E key \in Keys, val \in Vals : 
            \/ InsertReq(key, val)
            \/ UpdateReq(key, val)
        \/ \E key \in Keys: GetReq(key)
        \/ GetValue
        \/ FindLeafToAdd
        \/ WhichToSplit
        \/ AddToLeaf
        \/ SplitLeaf
        \/ SplitRootLeaf
        \/ SplitRootInner
        \/ UpdateLeaf

vars == <<root, isLeaf, keysOf, childOf, lastOf, valOf, focus, toSplit, op, args, ret, state>>

Spec == Init /\ [][Next]_vars /\ WF_op(\E key \in Keys: GetReq(key))

====

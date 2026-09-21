---- MODULE BTreeResourceWitness ----
EXTENDS btreeDefs
NoNode == "nil"
NoValue == "missing"
BadChoice == CHOOSE n \in Nodes : TRUE

WitnessNext ==
  /\ lastOf[BadChoice] = NIL
  /\ CASE state = READY ->
              IF keysOf[BadChoice] = {} THEN InsertReq(1, "v")
              ELSE IF keysOf[BadChoice] = {1} THEN InsertReq(2, "v")
              ELSE InsertReq(1, "v")
       [] state = FIND_LEAF_TO_ADD -> FindLeafToAdd
       [] state = ADD_TO_LEAF -> AddToLeaf
       [] state = WHICH_TO_SPLIT -> WhichToSplit
       [] state = SPLIT_ROOT_LEAF -> SplitRootLeaf
       [] OTHER -> FALSE

WitnessSpec == Init /\ [][WitnessNext]_vars /\ WF_vars(WitnessNext)
EventuallyBadLeaf == <>~LeavesCantHaveLast
====

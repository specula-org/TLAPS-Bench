-------------------------- MODULE ivy_examples_split_queue_2_newDefs --------------------------
EXTENDS ivy_examples_split_queue_2_newModel

WorkCompletion ==
  \A x \in Nat : begun[x] ~> done[x]

===========================================================================================

---- MODULE btree ----
EXTENDS btreeDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeOkCorrect == Spec => []TypeOk
\* BEGIN AGENT PROOF tlaplus_examples_btree/btree_TypeOkCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_btree/btree_TypeOkCorrect.tla

THEOREM InnersMustHaveLastCorrect == Spec => []InnersMustHaveLast
\* BEGIN AGENT PROOF tlaplus_examples_btree/btree_InnersMustHaveLastCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_btree/btree_InnersMustHaveLastCorrect.tla

THEOREM LeavesCantHaveLastCorrect == Spec => []LeavesCantHaveLast
\* BEGIN AGENT PROOF tlaplus_examples_btree/btree_LeavesCantHaveLastCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_btree/btree_LeavesCantHaveLastCorrect.tla

THEOREM KeyOrderPreservedCorrect == Spec => []KeyOrderPreserved
\* BEGIN AGENT PROOF tlaplus_examples_btree/btree_KeyOrderPreservedCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_btree/btree_KeyOrderPreservedCorrect.tla

THEOREM KeysInLeavesAreUniqueCorrect == Spec => []KeysInLeavesAreUnique
\* BEGIN AGENT PROOF tlaplus_examples_btree/btree_KeysInLeavesAreUniqueCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_btree/btree_KeysInLeavesAreUniqueCorrect.tla
====

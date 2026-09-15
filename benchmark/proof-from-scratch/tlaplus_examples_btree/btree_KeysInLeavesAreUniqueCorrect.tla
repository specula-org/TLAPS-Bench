---- MODULE btree_KeysInLeavesAreUniqueCorrect ----
EXTENDS btree_KeysInLeavesAreUniqueCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM KeysInLeavesAreUniqueCorrect == Spec => []KeysInLeavesAreUnique
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

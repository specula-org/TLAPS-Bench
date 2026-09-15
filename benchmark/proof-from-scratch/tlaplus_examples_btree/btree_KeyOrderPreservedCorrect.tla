---- MODULE btree_KeyOrderPreservedCorrect ----
EXTENDS btree_KeyOrderPreservedCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM KeyOrderPreservedCorrect == Spec => []KeyOrderPreserved
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

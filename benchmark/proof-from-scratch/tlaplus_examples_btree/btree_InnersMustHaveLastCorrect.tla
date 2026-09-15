---- MODULE btree_InnersMustHaveLastCorrect ----
EXTENDS btree_InnersMustHaveLastCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM InnersMustHaveLastCorrect == Spec => []InnersMustHaveLast
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

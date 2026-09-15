---- MODULE btree_LeavesCantHaveLastCorrect ----
EXTENDS btree_LeavesCantHaveLastCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM LeavesCantHaveLastCorrect == Spec => []LeavesCantHaveLast
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

---- MODULE BufferedRandomAccessFile_Thm_WriteAtMostCorrect ----
EXTENDS BufferedRandomAccessFile_Thm_WriteAtMostCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM Thm_WriteAtMostCorrect == Spec => WriteAtMostCorrect
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

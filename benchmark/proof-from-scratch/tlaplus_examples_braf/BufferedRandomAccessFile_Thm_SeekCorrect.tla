---- MODULE BufferedRandomAccessFile_Thm_SeekCorrect ----
EXTENDS BufferedRandomAccessFile_Thm_SeekCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM Thm_SeekCorrect == Spec => SeekCorrect
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

---- MODULE BufferedRandomAccessFile_Thm_FlushBufferCorrect ----
EXTENDS BufferedRandomAccessFile_Thm_FlushBufferCorrectDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS
THEOREM Thm_FlushBufferCorrect == Spec => FlushBufferCorrect
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

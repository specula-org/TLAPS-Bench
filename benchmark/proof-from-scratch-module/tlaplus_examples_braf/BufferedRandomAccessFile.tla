---- MODULE BufferedRandomAccessFile ----
EXTENDS BufferedRandomAccessFileDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Thm_TypeOK == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_TypeOK.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_TypeOK.tla

THEOREM Thm_Inv1 == Spec => []Inv1
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv1.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv1.tla

THEOREM Thm_Inv3 == Spec => []Inv3
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv3.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv3.tla

THEOREM Thm_Inv4 == Spec => []Inv4
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv4.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv4.tla

THEOREM Thm_Inv5 == Spec => []Inv5
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv5.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv5.tla

THEOREM Thm_Safety == Spec => Safety
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Safety.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Safety.tla

THEOREM Thm_FlushBufferCorrect == Spec => FlushBufferCorrect
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_FlushBufferCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_FlushBufferCorrect.tla

THEOREM Thm_SeekCorrect == Spec => SeekCorrect
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_SeekCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_SeekCorrect.tla

THEOREM Thm_SeekEstablishesInv2 == Spec => SeekEstablishesInv2
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_SeekEstablishesInv2.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_SeekEstablishesInv2.tla

THEOREM Thm_Write1Correct == Spec => Write1Correct
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Write1Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Write1Correct.tla

THEOREM Thm_Read1Correct == Spec => Read1Correct
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Read1Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Read1Correct.tla

THEOREM Thm_WriteAtMostCorrect == Spec => WriteAtMostCorrect
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_WriteAtMostCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_WriteAtMostCorrect.tla

THEOREM Thm_ReadCorrect == Spec => ReadCorrect
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_ReadCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_ReadCorrect.tla

THEOREM Thm_Inv2CanAlwaysBeRestored == Spec => Inv2CanAlwaysBeRestored
\* BEGIN AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv2CanAlwaysBeRestored.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_braf/BufferedRandomAccessFile_Thm_Inv2CanAlwaysBeRestored.tla
====

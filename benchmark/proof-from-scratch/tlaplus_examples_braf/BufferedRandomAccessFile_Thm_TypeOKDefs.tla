

----------------------- MODULE BufferedRandomAccessFile_Thm_TypeOKDefs -----------------------

EXTENDS BufferedRandomAccessFileModel

TypeOK ==
    /\ dirty \in BOOLEAN
    /\ length \in Offset
    /\ curr \in Offset
    /\ lo \in Offset
    /\ buff \in Array(SymbolOrArbitrary, BuffSz)
    /\ diskPos \in Offset

    /\ file_content \in ArrayOfAnyLength(SymbolOrArbitrary)
    /\ ArrayLen(file_content) <= MaxOffset
    /\ file_pointer \in Offset

===============================================================================

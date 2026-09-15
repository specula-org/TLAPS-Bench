

----------------------- MODULE BufferedRandomAccessFile_Thm_WriteAtMostCorrectDefs -----------------------

EXTENDS BufferedRandomAccessFileModel

RelevantBufferContent ==
    ArraySlice(buff, 0, Min(BuffSz, length - lo))

LogicalFileContent == 
    IF ArrayLen(RelevantBufferContent) > 0
    THEN WriteToFile(file_content, lo, RelevantBufferContent)
    ELSE file_content

RAF == INSTANCE RandomAccessFile WITH
    file_content <- LogicalFileContent,
    file_pointer <- curr

WriteAtMostCorrect  == [][\A len \in 1..MaxOffset: \A data \in Array(SymbolOrArbitrary, len): WriteAtMost(data) => \E written \in 1..len: RAF!Write(ArraySlice(data, 0, written))]_vars

===============================================================================



----------------------- MODULE BufferedRandomAccessFile_Thm_Write1CorrectDefs -----------------------

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

Write1Correct       == [][\A symbol \in SymbolOrArbitrary: Write1(symbol) => RAF!Write(SeqToArray(<<symbol>>))]_vars

===============================================================================

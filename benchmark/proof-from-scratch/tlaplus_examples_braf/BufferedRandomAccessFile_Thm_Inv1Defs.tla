

----------------------- MODULE BufferedRandomAccessFile_Thm_Inv1Defs -----------------------

EXTENDS BufferedRandomAccessFileModel

RelevantBufferContent ==
    ArraySlice(buff, 0, Min(BuffSz, length - lo))

LogicalFileContent == 
    IF ArrayLen(RelevantBufferContent) > 0
    THEN WriteToFile(file_content, lo, RelevantBufferContent)
    ELSE file_content

Inv1 ==

    /\ length = ArrayLen(LogicalFileContent)
    /\ diskPos = file_pointer

===============================================================================

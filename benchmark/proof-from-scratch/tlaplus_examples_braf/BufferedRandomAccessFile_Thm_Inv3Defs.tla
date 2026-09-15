

----------------------- MODULE BufferedRandomAccessFile_Thm_Inv3Defs -----------------------

EXTENDS BufferedRandomAccessFileModel

RelevantBufferContent ==
    ArraySlice(buff, 0, Min(BuffSz, length - lo))

LogicalFileContent == 
    IF ArrayLen(RelevantBufferContent) > 0
    THEN WriteToFile(file_content, lo, RelevantBufferContent)
    ELSE file_content

BufferedIndexes == lo .. (Min(lo + BuffSz, length) - 1)

Inv3 ==
    \A i \in BufferedIndexes:
        ArrayGet(LogicalFileContent, i) = ArrayGet(buff, i - lo)

===============================================================================

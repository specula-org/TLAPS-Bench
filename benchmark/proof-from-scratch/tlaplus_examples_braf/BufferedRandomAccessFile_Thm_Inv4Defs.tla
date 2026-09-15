

----------------------- MODULE BufferedRandomAccessFile_Thm_Inv4Defs -----------------------

EXTENDS BufferedRandomAccessFileModel

RelevantBufferContent ==
    ArraySlice(buff, 0, Min(BuffSz, length - lo))

LogicalFileContent == 
    IF ArrayLen(RelevantBufferContent) > 0
    THEN WriteToFile(file_content, lo, RelevantBufferContent)
    ELSE file_content

DiskF(i) == 
    IF i >= 0 /\ i < ArrayLen(file_content)
    THEN ArrayGet(file_content, i)
    ELSE ArbitrarySymbol

BufferedIndexes == lo .. (Min(lo + BuffSz, length) - 1)

Inv4 ==
    \A i \in 0 .. (length - 1):
        i \notin BufferedIndexes =>
            ArrayGet(LogicalFileContent, i) = DiskF(i)

===============================================================================

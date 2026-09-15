

----------------------- MODULE BufferedRandomAccessFile_Thm_Inv5Defs -----------------------

EXTENDS BufferedRandomAccessFileModel

DiskF(i) == 
    IF i >= 0 /\ i < ArrayLen(file_content)
    THEN ArrayGet(file_content, i)
    ELSE ArbitrarySymbol

BufferedIndexes == lo .. (Min(lo + BuffSz, length) - 1)

Inv5 ==
    (\E i \in BufferedIndexes: DiskF(i) /= ArrayGet(buff, i - lo)) =>
    dirty

===============================================================================

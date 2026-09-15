

----------------------- MODULE BufferedRandomAccessFileDefs -----------------------

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

Inv1 ==

    /\ length = ArrayLen(LogicalFileContent)
    /\ diskPos = file_pointer

Inv3 ==
    \A i \in BufferedIndexes:
        ArrayGet(LogicalFileContent, i) = ArrayGet(buff, i - lo)

Inv4 ==
    \A i \in 0 .. (length - 1):
        i \notin BufferedIndexes =>
            ArrayGet(LogicalFileContent, i) = DiskF(i)

Inv5 ==
    (\E i \in BufferedIndexes: DiskF(i) /= ArrayGet(buff, i - lo)) =>
    dirty

RAF == INSTANCE RandomAccessFile WITH
    file_content <- LogicalFileContent,
    file_pointer <- curr

Safety == RAF!Spec

FlushBufferCorrect  == [][FlushBuffer => UNCHANGED RAF!vars]_vars
SeekCorrect         == [][\A offset \in Offset: Seek(offset) => RAF!Seek(offset)]_vars
SeekEstablishesInv2 == [][\A offset \in Offset: Seek(offset) => Inv2']_vars
Write1Correct       == [][\A symbol \in SymbolOrArbitrary: Write1(symbol) => RAF!Write(SeqToArray(<<symbol>>))]_vars
Read1Correct        == [][\A symbol \in SymbolOrArbitrary: Read1(symbol) => RAF!Read(SeqToArray(<<symbol>>))]_vars
WriteAtMostCorrect  == [][\A len \in 1..MaxOffset: \A data \in Array(SymbolOrArbitrary, len): WriteAtMost(data) => \E written \in 1..len: RAF!Write(ArraySlice(data, 0, written))]_vars
ReadCorrect         == [][\A len \in 1..MaxOffset: \A data \in Array(SymbolOrArbitrary, len): Read(data) => RAF!Read(data)]_vars

FlushBufferPossibleWhenDirty == dirty => ENABLED FlushBuffer
FlushBufferMakesProgress == [][FlushBuffer => ~dirty']_vars
SeekCurrPossibleWhenNotDirty == ~dirty => ENABLED Seek(curr)
SeekCurrRestoresInv2 == [][Seek(curr) => Inv2']_vars
Inv2CanAlwaysBeRestored ==
    /\ []FlushBufferPossibleWhenDirty
    /\ FlushBufferMakesProgress
    /\ []SeekCurrPossibleWhenNotDirty
    /\ SeekCurrRestoresInv2

===============================================================================

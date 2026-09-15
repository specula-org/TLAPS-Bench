

----------------------- MODULE BufferedRandomAccessFileModel -----------------------

EXTENDS Naturals, Sequences, TLC, Common

CONSTANT BuffSz

ASSUME BuffSzIsPositive == BuffSz \in Nat \ {0}

VARIABLES
    
    dirty,
    length,
    curr,
    lo,
    buff,
    diskPos,

    file_content,
    file_pointer

vars == <<
    dirty, length, curr, lo, buff, diskPos,
    file_content, file_pointer>>

Inv2 ==
    /\ lo <= curr
    /\ curr < lo + BuffSz

Init ==
    /\ dirty = FALSE
    /\ length = 0
    /\ curr = 0
    /\ lo = 0
    /\ buff \in Array({ArbitrarySymbol}, BuffSz)
    /\ diskPos = 0
    /\ file_pointer = 0
    /\ file_content = EmptyArray

FlushBuffer ==
    /\ dirty
    /\ LET len == Min(length - lo, BuffSz) IN
        /\ IF len > 0
           THEN LET diskPosA == lo IN 
            /\ file_content' = WriteToFile(file_content, diskPosA, ArraySlice(buff, 0, len))
            /\ file_pointer' = diskPosA + len
            /\ diskPos' = lo + len
           ELSE
            UNCHANGED <<diskPos, file_pointer, file_content>>
        /\ dirty' = FALSE
    /\ UNCHANGED <<length, curr, lo, buff>>

FillBuffer ==
    LET diskPosA == lo' IN
    /\ buff' = MkArray(BuffSz, [i \in 0..BuffSz |->
            LET fileOffset == diskPosA + i IN
            IF fileOffset < ArrayLen(file_content)
            THEN ArrayGet(file_content, fileOffset)
            ELSE ArbitrarySymbol])
    /\ file_pointer' = Min(diskPosA + BuffSz, ArrayLen(file_content))
    /\ diskPos' = Min(diskPosA + BuffSz, ArrayLen(file_content))

Seek(pos) ==
    /\ curr' = pos
    /\ IF pos < lo \/ pos >= (lo + BuffSz) THEN
        /\ ~dirty 
        /\ lo' = (pos \div BuffSz) * BuffSz
        /\ FillBuffer
       ELSE
        UNCHANGED <<lo, diskPos, file_pointer, buff>>
    /\ UNCHANGED <<dirty, length, file_content>>

SetLength(newLength) ==
    /\ file_content' = TruncateOrExtendFile(file_content, newLength)
    /\ IF ArrayLen(file_content) > newLength /\ file_pointer > newLength
       THEN file_pointer' = newLength
       ELSE file_pointer' \in Offset
    /\ length' = newLength
    /\ diskPos' = file_pointer'
    /\ IF curr > newLength
       THEN curr' = newLength
       ELSE UNCHANGED curr

    /\ buff' = MkArray(BuffSz, [i \in 0..(BuffSz-1) |->
            IF lo + i < newLength
            THEN ArrayGet(buff, i)
            ELSE ArbitrarySymbol])
    /\ UNCHANGED <<dirty, lo>>

Read1(byte) ==
    /\ Inv2
    /\ curr < length
    /\ byte = ArrayGet(buff, curr - lo)
    /\ curr' = curr + 1
    /\ UNCHANGED <<lo, diskPos, buff, file_pointer, dirty, file_content, length>>

Write1(byte) ==
    /\ curr + 1 <= MaxOffset 
    /\ Inv2
    /\ buff' = ArraySet(buff, curr - lo, byte)
    /\ curr' = curr + 1
    /\ dirty' = TRUE
    /\ length' = Max(length, curr')
    /\ UNCHANGED <<lo, diskPos, file_pointer, file_content>>

Read(data) ==
    LET numReadableWithoutSeeking == Min(lo + BuffSz, length) - curr IN
    /\ Inv2
    /\ numReadableWithoutSeeking >= 0
    /\ LET
            numToRead == Min(ArrayLen(data), numReadableWithoutSeeking)
            buffOff == curr - lo
       IN
        /\ data = ArraySlice(buff, buffOff, buffOff + numToRead)
        /\ curr' = curr + numToRead
    /\ UNCHANGED <<buff, dirty, diskPos, file_content, file_pointer, length, lo>>

WriteAtMost(data) ==
    LET
        numWriteableWithoutSeeking == Min(ArrayLen(data), lo + BuffSz - curr)
        buffOff == curr - lo
    IN
    /\ Inv2
    /\ curr + numWriteableWithoutSeeking <= MaxOffset
    /\ buff' = ArrayConcat(ArrayConcat(
            ArraySlice(buff, 0, buffOff),
            ArraySlice(data, 0, numWriteableWithoutSeeking)),
            ArraySlice(buff, buffOff + numWriteableWithoutSeeking, ArrayLen(buff)))
    /\ dirty' = TRUE
    /\ curr' = curr + numWriteableWithoutSeeking
    /\ length' = Max(length, curr')
    /\ UNCHANGED <<lo, diskPos, file_content, file_pointer>>

Next ==
    \/ FlushBuffer
    \/ \E offset \in Offset:
        \/ Seek(offset)
        \/ SetLength(offset)
    \/ \E symbol \in SymbolOrArbitrary:
        \/ Read1(symbol)
        \/ Write1(symbol)
    \/ \E len \in 1..MaxOffset: \E data \in Array(SymbolOrArbitrary, len):
        \/ WriteAtMost(data)
        \/ Read(data)

Spec == Init /\ [][Next]_vars

===============================================================================

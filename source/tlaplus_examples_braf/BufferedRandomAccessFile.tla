\* Copyright (c) 2024, Oracle and/or its affiliates.

----------------------- MODULE BufferedRandomAccessFile -----------------------
\* This is a model-checkable specification for BufferedRandomAccessFile.java.
\* It covers the core fields as well as the seek, read, write, flush, and
\* setLength operations.
\*
\* There are three major correctess conditions:
\*
\*   (1) the internal invariants V1-V5 should hold
\*   (2) the behavior should refine a general RandomAccessFile
\*   (3) each operation should refine its RandomAccessFile counterpart
\*
\* Readers will probably want to start with the general RandomAccessFile spec
\* before reading this one.

EXTENDS Naturals, Sequences, TLC, Common

CONSTANT BuffSz

\* Seek's `pos \div BuffSz` needs a nonzero divisor, and Inv2 is unsatisfiable
\* when BuffSz = 0.
ASSUME BuffSzIsPositive == BuffSz \in Nat \ {0}

VARIABLES
    \* in-memory variables (BufferedRandomAccessFile class fields)
    dirty,
    length,
    curr,
    lo,
    buff,
    diskPos,

    \* the underlying file
    file_content,
    file_pointer

vars == <<
    dirty, length, curr, lo, buff, diskPos,
    file_content, file_pointer>>

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

-------------------------------------------------------------------------------
\* Internal invariants (copied from comment in BufferedRandomAccessFile.java)

RelevantBufferContent ==
    ArraySlice(buff, 0, Min(BuffSz, length - lo))

LogicalFileContent == \* denoted c(f) in .java file
    IF ArrayLen(RelevantBufferContent) > 0
    THEN WriteToFile(file_content, lo, RelevantBufferContent)
    ELSE file_content

DiskF(i) == \* denoted disk(f)[i] in .java file
    IF i >= 0 /\ i < ArrayLen(file_content)
    THEN ArrayGet(file_content, i)
    ELSE ArbitrarySymbol

BufferedIndexes == lo .. (Min(lo + BuffSz, length) - 1)

Inv1 ==
    \* /\ f.closed == closed(f) \* close() not described in this spec
    \* /\ f.curr == curr(f)     \* by definition; see `file_pointer <- curr` in refinement mapping below
    /\ length = ArrayLen(LogicalFileContent)
    /\ diskPos = file_pointer

\* Inv2 is a bit special.  Most methods restore it just before they return.  It
\* is generally restored by calling `restoreInvariantsAfterIncreasingCurr()`.
\* But, that behavior is difficult to model in straight TLA+ because each
\* method may modify variables multiple times.  So instead, this spec treats
\* Inv2 as a precondition for the methods and verifies that it is always
\* restored by calling `restoreInvariantsAfterIncreasingCurr()`.
\* See `Inv2CanAlwaysBeRestored` below.
Inv2 ==
    /\ lo <= curr
    /\ curr < lo + BuffSz

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

-------------------------------------------------------------------------------
\* Behavior

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
           THEN LET diskPosA == lo IN \* super.seek(this.lo)
            /\ file_content' = WriteToFile(file_content, diskPosA, ArraySlice(buff, 0, len))
            /\ file_pointer' = diskPosA + len
            /\ diskPos' = lo + len
           ELSE
            UNCHANGED <<diskPos, file_pointer, file_content>>
        /\ dirty' = FALSE
    /\ UNCHANGED <<length, curr, lo, buff>>

\* Helper for Seek (not a full action):
\*  - reads lo'
\*  - constrains diskPos', file_pointer', and buff'
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
        /\ ~dirty \* call to FlushBuffer
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
    \* In reality the buffer doesn't change---but some of its bytes might no
    \* longer be relevant and have to be marked as arbitrary.
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
    /\ curr + 1 <= MaxOffset \* bound model checking
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

\* The `write()` method is composed of repeated calls to `writeAtMost()`, so
\* verifying that the latter maintains all our invariants should be sufficient.
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

-------------------------------------------------------------------------------
\* Refinement of general RandomAccessFile

RAF == INSTANCE RandomAccessFile WITH
    file_content <- LogicalFileContent,
    file_pointer <- curr

Safety == RAF!Spec

\* Ensure that the various actions behave according to their abstract specifications.
FlushBufferCorrect  == [][FlushBuffer => UNCHANGED RAF!vars]_vars
SeekCorrect         == [][\A offset \in Offset: Seek(offset) => RAF!Seek(offset)]_vars
SetLengthCorrect    == [][\A offset \in Offset: SetLength(offset) => RAF!SetLength(offset)]_vars
SeekEstablishesInv2 == [][\A offset \in Offset: Seek(offset) => Inv2']_vars
Write1Correct       == [][\A symbol \in SymbolOrArbitrary: Write1(symbol) => RAF!Write(SeqToArray(<<symbol>>))]_vars
Read1Correct        == [][\A symbol \in SymbolOrArbitrary: Read1(symbol) => RAF!Read(SeqToArray(<<symbol>>))]_vars
WriteAtMostCorrect  == [][\A len \in 1..MaxOffset: \A data \in Array(SymbolOrArbitrary, len): WriteAtMost(data) => \E written \in 1..len: RAF!Write(ArraySlice(data, 0, written))]_vars
ReadCorrect         == [][\A len \in 1..MaxOffset: \A data \in Array(SymbolOrArbitrary, len): Read(data) => RAF!Read(data)]_vars

\* Inv2 is a precondition for many actions; it should always be possible to
\* restore Inv2 by execuing `restoreInvariantsAfterIncreasingCurr()`.  That
\* method calls `seeek(curr)`, which is composed of a FlushBuffer followed by a
\* Seek, or just a Seek.
\*
\* To ensure that `restoreInvariantsAfterIncreasingCurr()` works as expected
\* (without using the \cdot action composition operator), we'll verify a few
\* things:
\*  - dirty => ENABLED FlushBuffer
\*  - FlushBuffer => ~dirty'
\*  - ~dirty => ENABLED Seek(curr)
\*  - Seek(curr) => Inv2'
\* Together, those properties ensure that it is always possible to restore Inv2
\* by taking a FlushBuffer action (if necessary) followed by a Seek(curr)
\* action.
FlushBufferPossibleWhenDirty == dirty => ENABLED FlushBuffer
FlushBufferMakesProgress == [][FlushBuffer => ~dirty']_vars
SeekCurrPossibleWhenNotDirty == ~dirty => ENABLED Seek(curr)
SeekCurrRestoresInv2 == [][Seek(curr) => Inv2']_vars
Inv2CanAlwaysBeRestored ==
    /\ []FlushBufferPossibleWhenDirty
    /\ FlushBufferMakesProgress
    /\ []SeekCurrPossibleWhenNotDirty
    /\ SeekCurrRestoresInv2

-------------------------------------------------------------------------------
\* Model checking helper definitions

Symmetry == Permutations(Symbols)

Alias == [
    \* constants
    BuffSz            |-> BuffSz,
    MaxOffset         |-> MaxOffset,

    \* regular vars
    dirty             |-> dirty,
    length            |-> length,
    curr              |-> curr,
    lo                |-> lo,
    buff              |-> buff,
    diskPos           |-> diskPos,
    file_content      |-> file_content,
    file_pointer      |-> file_pointer,

    \* abstract vars
    abstract_contents |-> LogicalFileContent]

(***************************************************************************)
(* Proof obligations added for tlaps-bench. Each goal is an invariant or   *)
(* property the upstream TLC configuration checks; the upstream module     *)
(* states no theorems.                                                    *)
(***************************************************************************)
THEOREM Thm_TypeOK == Spec => []TypeOK
PROOF OMITTED

THEOREM Thm_Inv1 == Spec => []Inv1
PROOF OMITTED

THEOREM Thm_Inv3 == Spec => []Inv3
PROOF OMITTED

THEOREM Thm_Inv4 == Spec => []Inv4
PROOF OMITTED

THEOREM Thm_Inv5 == Spec => []Inv5
PROOF OMITTED

THEOREM Thm_Safety == Spec => Safety
PROOF OMITTED

THEOREM Thm_FlushBufferCorrect == Spec => FlushBufferCorrect
PROOF OMITTED

THEOREM Thm_SeekCorrect == Spec => SeekCorrect
PROOF OMITTED

THEOREM Thm_SeekEstablishesInv2 == Spec => SeekEstablishesInv2
PROOF OMITTED

THEOREM Thm_Write1Correct == Spec => Write1Correct
PROOF OMITTED

THEOREM Thm_Read1Correct == Spec => Read1Correct
PROOF OMITTED

THEOREM Thm_WriteAtMostCorrect == Spec => WriteAtMostCorrect
PROOF OMITTED

THEOREM Thm_ReadCorrect == Spec => ReadCorrect
PROOF OMITTED

THEOREM Thm_Inv2CanAlwaysBeRestored == Spec => Inv2CanAlwaysBeRestored
PROOF OMITTED

===============================================================================

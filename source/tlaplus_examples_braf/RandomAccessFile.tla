\* Copyright (c) 2024, Oracle and/or its affiliates.

--------------------------- MODULE RandomAccessFile ---------------------------
\* Specification of Java's RandomAccessFile class.
\*
\* A RandomAccessFile offers single-threaded access to some on-disk data
\* (`file_content`) and has an internal "pointer" or "cursor" (`file_pointer`).
\* Clients can move the pointer to an arbitrary position, or the client can
\* read or write data linearly from its current position, which simultaneously
\* advances the pointer.
\*
\* The core operations are:
\*   - seek (to move the pointer)
\*   - setLength (to resize the data)
\*   - read (to copy bytes from disk to memory)
\*   - write (to copy bytes from memory to disk)
\*
\* There are some cases where the general RandomAccessFile contract does not
\* define the data contents, for instance when extending the file using
\* setLength.  In this spec, undefined bytes in the file are explicitly marked
\* with `ArbitrarySymbol`.  While not entirely accurate, that choice simplifies
\* many definitions, since there is no need to nondeterministically choose
\* contents for the file.  It also (incidentally) reduces state space explosion
\* during model checking.

EXTENDS Naturals, Sequences, Common

VARIABLES
    file_content,
    file_pointer

vars == <<file_content, file_pointer>>

TypeOK ==
    /\ file_content \in ArrayOfAnyLength(SymbolOrArbitrary)
    /\ ArrayLen(file_content) <= MaxOffset
    /\ file_pointer \in Offset

Init ==
    /\ file_content = EmptyArray
    /\ file_pointer = 0

Seek(new_offset) ==
    /\ new_offset \in Offset
    /\ file_pointer' = new_offset
    /\ UNCHANGED <<file_content>>

SetLength(new_length) ==
    /\ file_content' = TruncateOrExtendFile(file_content, new_length)

    \* The pointer's behavior is very strange.  Per RandomAccessFile docs [1]:
    \*  > If the present length of the file as returned by the length method is
    \*  > greater than the newLength argument then the file will be truncated.
    \*  > In this case, if the file offset as returned by the getFilePointer
    \*  > method is greater than newLength then after this method returns the
    \*  > offset will be equal to newLength.
    \*
    \* The docs say NOTHING else about the file pointer.  So, we can assume
    \* that there are no other formal restrictions on its behavior.
    \*
    \* [1]: https://docs.oracle.com/en/java/javase/11/docs/api/java.base/java/io/RandomAccessFile.html#setLength(long)
    /\ IF ArrayLen(file_content) > new_length /\ file_pointer > new_length
       THEN file_pointer' = new_length
       ELSE file_pointer' \in Offset

Read(output) ==
    /\ output = ArraySlice(file_content, file_pointer, Min(file_pointer + ArrayLen(output), ArrayLen(file_content)))
    /\ file_pointer' = file_pointer + ArrayLen(output)
    /\ UNCHANGED <<file_content>>

Write(data) ==
    /\ file_pointer + ArrayLen(data) <= MaxOffset
    /\ file_content' = WriteToFile(file_content, file_pointer, data)
    /\ file_pointer' = file_pointer + ArrayLen(data)

Next ==
    \/ \E offset \in Offset:
        \/ Seek(offset)
        \/ SetLength(offset)
    \/ \E len \in 1..MaxOffset: \E data \in Array(SymbolOrArbitrary, len):
        \/ Write(data)
        \/ Read(data)

Spec == Init /\ [][Next]_vars

===============================================================================

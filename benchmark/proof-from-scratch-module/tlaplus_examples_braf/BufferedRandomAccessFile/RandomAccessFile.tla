

--------------------------- MODULE RandomAccessFile ---------------------------

EXTENDS Naturals, Sequences, Common

VARIABLES
    file_content,
    file_pointer

vars == <<file_content, file_pointer>>

Init ==
    /\ file_content = EmptyArray
    /\ file_pointer = 0

Seek(new_offset) ==
    /\ new_offset \in Offset
    /\ file_pointer' = new_offset
    /\ UNCHANGED <<file_content>>

SetLength(new_length) ==
    /\ file_content' = TruncateOrExtendFile(file_content, new_length)

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

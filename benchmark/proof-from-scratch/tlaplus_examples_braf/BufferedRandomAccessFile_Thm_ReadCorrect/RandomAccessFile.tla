

--------------------------- MODULE RandomAccessFile ---------------------------

EXTENDS Naturals, Sequences, Common

VARIABLES
    file_content,
    file_pointer

Read(output) ==
    /\ output = ArraySlice(file_content, file_pointer, Min(file_pointer + ArrayLen(output), ArrayLen(file_content)))
    /\ file_pointer' = file_pointer + ArrayLen(output)
    /\ UNCHANGED <<file_content>>

===============================================================================



--------------------------- MODULE RandomAccessFile ---------------------------

EXTENDS Naturals, Sequences, Common

VARIABLES
    file_content,
    file_pointer

Write(data) ==
    /\ file_pointer + ArrayLen(data) <= MaxOffset
    /\ file_content' = WriteToFile(file_content, file_pointer, data)
    /\ file_pointer' = file_pointer + ArrayLen(data)

===============================================================================

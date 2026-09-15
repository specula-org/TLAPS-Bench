

--------------------------- MODULE RandomAccessFile ---------------------------

EXTENDS Naturals, Sequences, Common

VARIABLES
    file_content,
    file_pointer

Seek(new_offset) ==
    /\ new_offset \in Offset
    /\ file_pointer' = new_offset
    /\ UNCHANGED <<file_content>>

===============================================================================

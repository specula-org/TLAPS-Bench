

----------------------- MODULE BufferedRandomAccessFile_Thm_SeekEstablishesInv2Defs -----------------------

EXTENDS BufferedRandomAccessFileModel

SeekEstablishesInv2 == [][\A offset \in Offset: Seek(offset) => Inv2']_vars

===============================================================================



----------------------- MODULE BufferedRandomAccessFile_Thm_Inv2CanAlwaysBeRestoredDefs -----------------------

EXTENDS BufferedRandomAccessFileModel

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

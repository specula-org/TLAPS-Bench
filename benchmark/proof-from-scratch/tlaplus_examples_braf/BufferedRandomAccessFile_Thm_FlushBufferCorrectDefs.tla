

----------------------- MODULE BufferedRandomAccessFile_Thm_FlushBufferCorrectDefs -----------------------

EXTENDS BufferedRandomAccessFileModel

RelevantBufferContent ==
    ArraySlice(buff, 0, Min(BuffSz, length - lo))

LogicalFileContent == 
    IF ArrayLen(RelevantBufferContent) > 0
    THEN WriteToFile(file_content, lo, RelevantBufferContent)
    ELSE file_content

RAF == INSTANCE RandomAccessFile WITH
    file_content <- LogicalFileContent,
    file_pointer <- curr

FlushBufferCorrect  == [][FlushBuffer => UNCHANGED RAF!vars]_vars

===============================================================================

-------------------------- MODULE MemoryInterface ---------------------------
VARIABLE memInt
CONSTANTS  Send(_, _, _, _),
           Reply(_, _, _, _),
           InitMemInt, 
           Proc,  
           Adr,  
           Val

-----------------------------------------------------------------------------
MReq == [op : {"Rd"}, adr: Adr] 
          \cup [op : {"Wr"}, adr: Adr, val : Val]

NoVal == CHOOSE v : v \notin Val
=============================================================================

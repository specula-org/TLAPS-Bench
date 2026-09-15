------------------------------ MODULE FlashWithMutexModel ------------------------------

EXTENDS Naturals, FiniteSets

CONSTANTS
    NODE,        
    DATA,        
    Undefined    

ASSUME UndefNotInNODE   == Undefined \notin NODE
ASSUME UndefNotInDATA   == Undefined \notin DATA
ASSUME NODEDATADisjoint == NODE \cap DATA = {}
ASSUME NODENonEmpty     == NODE # {}
ASSUME DATANonEmpty     == DATA # {}
ASSUME NODEFinite       == IsFiniteSet(NODE)

ReqCmd      == {"Get", "GetX"}   

VARIABLES
    Home, Proc, Dir, MemData, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
    CurrData, PrevData, PendReqSrc, PendReqCmd, Collecting, FwdCmd, FwdSrc

vars == <<Home, Proc, Dir, MemData, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
          CurrData, PrevData, PendReqSrc, PendReqCmd, Collecting, FwdCmd, FwdSrc>>

pendVars == <<PendReqSrc, PendReqCmd, Collecting>>

fwdVars == <<FwdCmd, FwdSrc>>

Init ==
    \E h \in NODE, d \in DATA :
        /\ Home = h
        /\ Proc = [i \in NODE |-> [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                   CacheState |-> "CACHE_I", CacheData |-> Undefined]]
        /\ Dir  = [Pending |-> FALSE, Local |-> FALSE, Dirty |-> FALSE,
                   HeadVld |-> FALSE, HeadPtr |-> Undefined, ShrVld |-> FALSE,
                   ShrSet |-> {}, InvSet |-> {}]
        /\ MemData = d
        /\ UniMsg  = [i \in NODE |-> [Cmd |-> "UNI_None", Proc |-> Undefined, Data |-> Undefined]]
        /\ InvMsg  = [i \in NODE |-> [Cmd |-> "INV_None"]]
        /\ RpMsg   = [i \in NODE |-> [Cmd |-> "RP_None"]]
        /\ WbMsg   = [Cmd |-> "WB_None", Proc |-> Undefined, Data |-> Undefined]
        /\ ShWbMsg = [Cmd |-> "SHWB_None", Proc |-> Undefined, Data |-> Undefined]
        /\ NakcMsg = [Cmd |-> "NAKC_None"]
        /\ CurrData = d
        /\ PrevData = d
        /\ PendReqSrc = Undefined
        /\ PendReqCmd = Undefined
        /\ Collecting = FALSE
        /\ FwdCmd = "UNI_None"
        /\ FwdSrc = Undefined

InvNodes(exclude) ==
    {p \in NODE \ exclude : \/ (Dir.ShrVld /\ p \in Dir.ShrSet)
                            \/ (Dir.HeadVld /\ Dir.HeadPtr = p)}

NoOtherSharers(req) ==
    Dir.HeadVld => (Dir.HeadPtr = req /\ Dir.ShrSet \subseteq {req})

ProcHomeInvalid ==
    [Proc EXCEPT ![Home].CacheState = "CACHE_I", ![Home].CacheData = Undefined]

ProcHomeInvalidMarked ==
    [Proc EXCEPT ![Home].CacheState = "CACHE_I", ![Home].CacheData = Undefined,
                 ![Home].InvMarked = IF Proc[Home].ProcCmd = "NODE_Get"
                                     THEN TRUE ELSE Proc[Home].InvMarked]

Store(src, data) ==
    /\ Proc[src].CacheState = "CACHE_E"
    /\ Proc' = [Proc EXCEPT ![src].CacheData = data]
    /\ CurrData' = data
    /\ UNCHANGED <<Home, Dir, MemData, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   PrevData, pendVars, fwdVars>>

PI_Remote(src, c) ==
    /\ src # Home
    /\ Proc[src].ProcCmd = "NODE_None"
    /\ Proc[src].CacheState = "CACHE_I"
    /\ Proc' = [Proc EXCEPT ![src].ProcCmd = IF c = "Get" THEN "NODE_Get" ELSE "NODE_GetX"]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> IF c = "Get" THEN "UNI_Get" ELSE "UNI_GetX",
                                          Proc |-> Home, Data |-> Undefined]]
    /\ UNCHANGED <<Home, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

PI_Local_Get_Get ==
    /\ Proc[Home].ProcCmd = "NODE_None"
    /\ Proc[Home].CacheState = "CACHE_I"
    /\ ~Dir.Pending /\ Dir.Dirty
    /\ Proc' = [Proc EXCEPT ![Home].ProcCmd = "NODE_Get"]
    /\ Dir' = [Dir EXCEPT !.Pending = TRUE]
    /\ UniMsg' = [UniMsg EXCEPT ![Home] = [Cmd |-> "UNI_Get", Proc |-> Dir.HeadPtr,
                                           Data |-> Undefined]]
    /\ FwdCmd' = IF Dir.HeadPtr # Home THEN "UNI_Get" ELSE FwdCmd
    /\ PendReqSrc' = Home
    /\ PendReqCmd' = "UNI_Get"
    /\ Collecting' = FALSE
    /\ UNCHANGED <<Home, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData,
                   PrevData, FwdSrc>>

PI_Local_Get_Put ==
    /\ Proc[Home].ProcCmd = "NODE_None"
    /\ Proc[Home].CacheState = "CACHE_I"
    /\ ~Dir.Pending /\ ~Dir.Dirty
    /\ Dir' = [Dir EXCEPT !.Local = TRUE]
    /\ Proc' = [Proc EXCEPT ![Home] = [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                       CacheState |-> IF Proc[Home].InvMarked THEN "CACHE_I" ELSE "CACHE_S",
                                       CacheData |-> IF Proc[Home].InvMarked THEN Undefined ELSE MemData]]
    /\ UNCHANGED <<Home, MemData, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

PI_Local_GetX_GetX ==
    /\ Proc[Home].ProcCmd = "NODE_None"
    /\ Proc[Home].CacheState \in {"CACHE_I", "CACHE_S"}
    /\ ~Dir.Pending /\ Dir.Dirty
    /\ Proc' = [Proc EXCEPT ![Home].ProcCmd = "NODE_GetX"]
    /\ Dir' = [Dir EXCEPT !.Pending = TRUE]
    /\ UniMsg' = [UniMsg EXCEPT ![Home] = [Cmd |-> "UNI_GetX", Proc |-> Dir.HeadPtr,
                                           Data |-> Undefined]]
    /\ FwdCmd' = IF Dir.HeadPtr # Home THEN "UNI_GetX" ELSE FwdCmd
    /\ PendReqSrc' = Home
    /\ PendReqCmd' = "UNI_GetX"
    /\ Collecting' = FALSE
    /\ UNCHANGED <<Home, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData,
                   PrevData, FwdSrc>>

PI_Local_GetX_PutX_Inv ==
    /\ Dir.HeadVld
    /\ Dir' = [Pending |-> TRUE, Local |-> TRUE, Dirty |-> TRUE, HeadVld |-> FALSE,
               HeadPtr |-> Undefined, ShrVld |-> FALSE, ShrSet |-> {}, InvSet |-> InvNodes({Home})]
    /\ InvMsg' = [p \in NODE |-> [Cmd |-> IF p \in InvNodes({Home})
                                          THEN "INV_Inv" ELSE "INV_None"]]
    /\ PendReqSrc' = Home
    /\ Collecting' = TRUE
    /\ PrevData' = CurrData

PI_Local_GetX_PutX_Grant ==
    /\ ~Dir.HeadVld
    /\ Dir' = [Dir EXCEPT !.Local = TRUE, !.Dirty = TRUE]
    /\ UNCHANGED <<InvMsg, PrevData, PendReqSrc, Collecting>>

PI_Local_GetX_PutX ==
    /\ Proc[Home].ProcCmd = "NODE_None"
    /\ Proc[Home].CacheState \in {"CACHE_I", "CACHE_S"}
    /\ ~Dir.Pending /\ ~Dir.Dirty
    /\ Proc' = [Proc EXCEPT ![Home] = [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                       CacheState |-> "CACHE_E", CacheData |-> MemData]]
    /\ \/ PI_Local_GetX_PutX_Inv
       \/ PI_Local_GetX_PutX_Grant
    /\ UNCHANGED <<Home, MemData, UniMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData,
                   PendReqCmd, fwdVars>>

PI_Remote_PutX(dst) ==
    /\ dst # Home
    /\ Proc[dst].ProcCmd = "NODE_None"
    /\ Proc[dst].CacheState = "CACHE_E"
    /\ Proc' = [Proc EXCEPT ![dst].CacheState = "CACHE_I", ![dst].CacheData = Undefined]
    /\ WbMsg' = [Cmd |-> "WB_Wb", Proc |-> dst, Data |-> Proc[dst].CacheData]
    /\ UNCHANGED <<Home, Dir, MemData, UniMsg, InvMsg, RpMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

PI_Local_PutX ==
    /\ Proc[Home].ProcCmd = "NODE_None"
    /\ Proc[Home].CacheState = "CACHE_E"
    /\ Proc' = [Proc EXCEPT ![Home].CacheState = "CACHE_I", ![Home].CacheData = Undefined]
    /\ Dir' = [Dir EXCEPT !.Dirty = FALSE, !.Local = IF Dir.Pending THEN Dir.Local ELSE FALSE]
    /\ MemData' = Proc[Home].CacheData
    /\ UNCHANGED <<Home, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData,
                   PrevData, pendVars, fwdVars>>

PI_Remote_Replace(src) ==
    /\ src # Home
    /\ Proc[src].ProcCmd = "NODE_None"
    /\ Proc[src].CacheState = "CACHE_S"
    /\ Proc' = [Proc EXCEPT ![src].CacheState = "CACHE_I", ![src].CacheData = Undefined]
    /\ RpMsg' = [RpMsg EXCEPT ![src] = [Cmd |-> "RP_Replace"]]
    /\ UNCHANGED <<Home, Dir, MemData, UniMsg, InvMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

PI_Local_Replace ==
    /\ Proc[Home].ProcCmd = "NODE_None"
    /\ Proc[Home].CacheState = "CACHE_S"
    /\ Dir' = [Dir EXCEPT !.Local = FALSE]
    /\ Proc' = [Proc EXCEPT ![Home].CacheState = "CACHE_I", ![Home].CacheData = Undefined]
    /\ UNCHANGED <<Home, MemData, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Nak(dst) ==
    /\ UniMsg[dst].Cmd = "UNI_Nak"
    /\ UniMsg' = [UniMsg EXCEPT ![dst] = [Cmd |-> "UNI_None", Proc |-> Undefined,
                                          Data |-> Undefined]]
    /\ Proc' = [Proc EXCEPT ![dst].ProcCmd = "NODE_None", ![dst].InvMarked = FALSE]
    /\ UNCHANGED <<Home, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Nak_Clear ==
    /\ NakcMsg.Cmd = "NAKC_Nakc"
    /\ NakcMsg' = [Cmd |-> "NAKC_None"]
    /\ Dir' = [Dir EXCEPT !.Pending = FALSE]
    /\ UNCHANGED <<Home, Proc, MemData, UniMsg, InvMsg, RpMsg, WbMsg, ShWbMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Local_Get_Nak(src) ==
    /\ src # Home
    /\ UniMsg[src].Cmd = "UNI_Get"
    /\ UniMsg[src].Proc = Home
    /\ RpMsg[src].Cmd # "RP_Replace"
    /\ \/ Dir.Pending
       \/ (Dir.Dirty /\ Dir.Local /\ Proc[Home].CacheState # "CACHE_E")
       \/ (Dir.Dirty /\ ~Dir.Local /\ Dir.HeadPtr = src)
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Nak", Proc |-> Home, Data |-> Undefined]]
    /\ UNCHANGED <<Home, Proc, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Local_Get_Get(src) ==
    /\ src # Home
    /\ UniMsg[src].Cmd = "UNI_Get"
    /\ UniMsg[src].Proc = Home
    /\ RpMsg[src].Cmd # "RP_Replace"
    /\ ~Dir.Pending /\ Dir.Dirty /\ ~Dir.Local /\ Dir.HeadPtr # src
    /\ Dir' = [Dir EXCEPT !.Pending = TRUE]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Get", Proc |-> Dir.HeadPtr,
                                          Data |-> Undefined]]
    /\ FwdCmd' = IF Dir.HeadPtr # Home THEN "UNI_Get" ELSE FwdCmd
    /\ PendReqSrc' = src
    /\ PendReqCmd' = "UNI_Get"
    /\ Collecting' = FALSE
    /\ UNCHANGED <<Home, Proc, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, FwdSrc>>

NI_Local_Get_Put(src) ==
    /\ src # Home
    /\ UniMsg[src].Cmd = "UNI_Get"
    /\ UniMsg[src].Proc = Home
    /\ RpMsg[src].Cmd # "RP_Replace"
    /\ ~Dir.Pending
    /\ (Dir.Dirty => (Dir.Local /\ Proc[Home].CacheState = "CACHE_E"))
    /\ Dir' = IF Dir.Dirty
              THEN [Dir EXCEPT !.Dirty = FALSE, !.HeadVld = TRUE, !.HeadPtr = src]
              ELSE IF Dir.HeadVld
                   THEN [Dir EXCEPT !.ShrVld = TRUE, !.ShrSet = Dir.ShrSet \cup {src},
                                    !.InvSet = Dir.ShrSet \cup {src}]
                   ELSE [Dir EXCEPT !.HeadVld = TRUE, !.HeadPtr = src]
    /\ MemData' = IF Dir.Dirty THEN Proc[Home].CacheData ELSE MemData
    /\ Proc' = IF Dir.Dirty THEN [Proc EXCEPT ![Home].CacheState = "CACHE_S"] ELSE Proc
    /\ UniMsg' = IF Dir.Dirty
                 THEN [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Put", Proc |-> Home,
                                               Data |-> Proc[Home].CacheData]]
                 ELSE [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Put", Proc |-> Home, Data |-> MemData]]
    /\ UNCHANGED <<Home, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData, PrevData,
                   pendVars, fwdVars>>

NI_Remote_Nak(src, dst) ==
    /\ src # dst /\ dst # Home
    /\ UniMsg[src].Cmd \in {"UNI_Get", "UNI_GetX"}
    /\ UniMsg[src].Proc = dst
    /\ Proc[dst].CacheState # "CACHE_E"
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Nak", Proc |-> dst, Data |-> Undefined]]
    /\ NakcMsg' = [Cmd |-> "NAKC_Nakc"]
    /\ FwdCmd' = "UNI_None"
    /\ FwdSrc' = src
    /\ UNCHANGED <<Home, Proc, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, CurrData,
                   PrevData, pendVars>>

NI_Remote_Get_Put(src, dst) ==
    /\ src # dst /\ dst # Home
    /\ UniMsg[src].Cmd = "UNI_Get"
    /\ UniMsg[src].Proc = dst
    /\ Proc[dst].CacheState = "CACHE_E"
    /\ Proc' = [Proc EXCEPT ![dst].CacheState = "CACHE_S"]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Put", Proc |-> dst,
                                          Data |-> Proc[dst].CacheData]]
    /\ FwdCmd' = "UNI_None"
    /\ FwdSrc' = src
    /\ ShWbMsg' = IF src # Home
                  THEN [Cmd |-> "SHWB_ShWb", Proc |-> src, Data |-> Proc[dst].CacheData]
                  ELSE ShWbMsg
    /\ UNCHANGED <<Home, Dir, MemData, InvMsg, RpMsg, WbMsg, NakcMsg, CurrData,
                   PrevData, pendVars>>

NI_Local_GetX_Nak(src) ==
    /\ src # Home
    /\ UniMsg[src].Cmd = "UNI_GetX"
    /\ UniMsg[src].Proc = Home
    /\ \/ Dir.Pending
       \/ (Dir.Dirty /\ Dir.Local /\ Proc[Home].CacheState # "CACHE_E")
       \/ (Dir.Dirty /\ ~Dir.Local /\ Dir.HeadPtr = src)
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_Nak", Proc |-> Home, Data |-> Undefined]]
    /\ UNCHANGED <<Home, Proc, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Local_GetX_GetX(src) ==
    /\ src # Home
    /\ UniMsg[src].Cmd = "UNI_GetX"
    /\ UniMsg[src].Proc = Home
    /\ ~Dir.Pending /\ Dir.Dirty /\ ~Dir.Local /\ Dir.HeadPtr # src
    /\ Dir' = [Dir EXCEPT !.Pending = TRUE]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_GetX", Proc |-> Dir.HeadPtr,
                                          Data |-> Undefined]]
    /\ FwdCmd' = IF Dir.HeadPtr # Home THEN "UNI_GetX" ELSE FwdCmd
    /\ PendReqSrc' = src
    /\ PendReqCmd' = "UNI_GetX"
    /\ Collecting' = FALSE
    /\ UNCHANGED <<Home, Proc, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, FwdSrc>>

NI_Local_GetX_PutX_Dirty(src) ==
    /\ Dir.Dirty
    /\ Dir' = [Dir EXCEPT !.Local = FALSE, !.Dirty = TRUE, !.HeadVld = TRUE,
                          !.HeadPtr = src, !.ShrVld = FALSE, !.ShrSet = {}, !.InvSet = {}]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_PutX", Proc |-> Home,
                                          Data |-> Proc[Home].CacheData]]
    /\ Proc' = ProcHomeInvalid
    /\ UNCHANGED <<InvMsg, PrevData, pendVars>>

NI_Local_GetX_PutX_Grant(src) ==
    /\ ~Dir.Dirty
    /\ NoOtherSharers(src)
    /\ Dir' = [Dir EXCEPT !.Local = FALSE, !.Dirty = TRUE, !.HeadVld = TRUE,
                          !.HeadPtr = src, !.ShrVld = FALSE, !.ShrSet = {}, !.InvSet = {}]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_PutX", Proc |-> Home, Data |-> MemData]]
    /\ Proc' = IF Dir.Local THEN ProcHomeInvalidMarked ELSE ProcHomeInvalid
    /\ UNCHANGED <<InvMsg, PrevData, pendVars>>

NI_Local_GetX_PutX_Inv(src) ==
    /\ ~Dir.Dirty
    /\ ~NoOtherSharers(src)
    /\ Dir' = [Pending |-> TRUE, Local |-> FALSE, Dirty |-> TRUE, HeadVld |-> TRUE, HeadPtr |-> src,
               ShrVld |-> FALSE, ShrSet |-> {}, InvSet |-> InvNodes({Home, src})]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_PutX", Proc |-> Home, Data |-> MemData]]
    /\ Proc' = IF Dir.Local THEN ProcHomeInvalidMarked ELSE Proc
    /\ InvMsg' = [p \in NODE |-> [Cmd |-> IF p \in InvNodes({Home, src})
                                          THEN "INV_Inv" ELSE "INV_None"]]
    /\ PendReqSrc' = src
    /\ PendReqCmd' = "UNI_GetX"
    /\ Collecting' = TRUE
    /\ PrevData' = CurrData

NI_Local_GetX_PutX(src) ==
    /\ src # Home
    /\ UniMsg[src].Cmd = "UNI_GetX"
    /\ UniMsg[src].Proc = Home
    /\ ~Dir.Pending
    /\ (Dir.Dirty => (Dir.Local /\ Proc[Home].CacheState = "CACHE_E"))
    /\ \/ NI_Local_GetX_PutX_Dirty(src)
       \/ NI_Local_GetX_PutX_Grant(src)
       \/ NI_Local_GetX_PutX_Inv(src)
    /\ UNCHANGED <<Home, MemData, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData, fwdVars>>

NI_Remote_GetX_PutX(src, dst) ==
    /\ src # dst /\ dst # Home
    /\ UniMsg[src].Cmd = "UNI_GetX"
    /\ UniMsg[src].Proc = dst
    /\ Proc[dst].CacheState = "CACHE_E"
    /\ Proc' = [Proc EXCEPT ![dst].CacheState = "CACHE_I", ![dst].CacheData = Undefined]
    /\ UniMsg' = [UniMsg EXCEPT ![src] = [Cmd |-> "UNI_PutX", Proc |-> dst,
                                          Data |-> Proc[dst].CacheData]]
    /\ FwdCmd' = "UNI_None"
    /\ FwdSrc' = src
    /\ ShWbMsg' = IF src # Home
                  THEN [Cmd |-> "SHWB_FAck", Proc |-> src, Data |-> Undefined]
                  ELSE ShWbMsg
    /\ UNCHANGED <<Home, Dir, MemData, InvMsg, RpMsg, WbMsg, NakcMsg, CurrData,
                   PrevData, pendVars>>

NI_Local_Put ==
    /\ UniMsg[Home].Cmd = "UNI_Put"
    /\ UniMsg' = [UniMsg EXCEPT ![Home] = [Cmd |-> "UNI_None", Proc |-> Undefined,
                                           Data |-> Undefined]]
    /\ Dir' = [Dir EXCEPT !.Pending = FALSE, !.Dirty = FALSE, !.Local = TRUE]
    /\ MemData' = UniMsg[Home].Data
    /\ Proc' = [Proc EXCEPT ![Home] = [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                       CacheState |-> IF Proc[Home].InvMarked THEN "CACHE_I" ELSE "CACHE_S",
                                       CacheData |-> IF Proc[Home].InvMarked THEN Undefined ELSE UniMsg[Home].Data]]
    /\ UNCHANGED <<Home, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData, PrevData,
                   pendVars, fwdVars>>

NI_Remote_Put(dst) ==
    /\ dst # Home
    /\ UniMsg[dst].Cmd = "UNI_Put"
    /\ UniMsg' = [UniMsg EXCEPT ![dst] = [Cmd |-> "UNI_None", Proc |-> Undefined,
                                          Data |-> Undefined]]
    /\ Proc' = [Proc EXCEPT ![dst] = [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                      CacheState |-> IF Proc[dst].InvMarked THEN "CACHE_I" ELSE "CACHE_S",
                                      CacheData |-> IF Proc[dst].InvMarked THEN Undefined ELSE UniMsg[dst].Data]]
    /\ UNCHANGED <<Home, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Local_PutXAcksDone ==
    /\ UniMsg[Home].Cmd = "UNI_PutX"
    /\ UniMsg' = [UniMsg EXCEPT ![Home] = [Cmd |-> "UNI_None", Proc |-> Undefined,
                                           Data |-> Undefined]]
    /\ Dir' = [Dir EXCEPT !.Pending = FALSE, !.Local = TRUE, !.HeadVld = FALSE, !.HeadPtr = Undefined]
    /\ Proc' = [Proc EXCEPT ![Home] = [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                       CacheState |-> "CACHE_E", CacheData |-> UniMsg[Home].Data]]
    /\ UNCHANGED <<Home, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg, CurrData,
                   PrevData, pendVars, fwdVars>>

NI_Remote_PutX(dst) ==
    /\ dst # Home
    /\ UniMsg[dst].Cmd = "UNI_PutX"
    /\ Proc[dst].ProcCmd = "NODE_GetX"
    /\ UniMsg' = [UniMsg EXCEPT ![dst] = [Cmd |-> "UNI_None", Proc |-> Undefined,
                                          Data |-> Undefined]]
    /\ Proc' = [Proc EXCEPT ![dst] = [ProcCmd |-> "NODE_None", InvMarked |-> FALSE,
                                      CacheState |-> "CACHE_E", CacheData |-> UniMsg[dst].Data]]
    /\ UNCHANGED <<Home, Dir, MemData, InvMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_Inv(dst) ==
    /\ dst # Home
    /\ InvMsg[dst].Cmd = "INV_Inv"
    /\ InvMsg' = [InvMsg EXCEPT ![dst] = [Cmd |-> "INV_InvAck"]]
    /\ Proc' = [Proc EXCEPT ![dst].CacheState = "CACHE_I",
                            ![dst].CacheData = Undefined,
                            ![dst].InvMarked = IF Proc[dst].ProcCmd = "NODE_Get" THEN TRUE
                                               ELSE Proc[dst].InvMarked]
    /\ UNCHANGED <<Home, Dir, MemData, UniMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_InvAck_More(src) ==
    /\ Dir.InvSet \ {src} # {}
    /\ Dir' = [Dir EXCEPT !.InvSet = Dir.InvSet \ {src}]
    /\ UNCHANGED Collecting

NI_InvAck_Last(src) ==
    /\ Dir.InvSet \ {src} = {}
    /\ Dir' = [Dir EXCEPT !.InvSet = Dir.InvSet \ {src}, !.Pending = FALSE,
                          !.Local = IF Dir.Local /\ ~Dir.Dirty THEN FALSE ELSE Dir.Local]
    /\ Collecting' = FALSE

NI_InvAck(src) ==
    /\ src # Home
    /\ InvMsg[src].Cmd = "INV_InvAck"
    /\ Dir.Pending /\ src \in Dir.InvSet
    /\ InvMsg' = [InvMsg EXCEPT ![src] = [Cmd |-> "INV_None"]]
    /\ \/ NI_InvAck_More(src)
       \/ NI_InvAck_Last(src)
    /\ UNCHANGED <<Home, Proc, MemData, UniMsg, RpMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, PendReqSrc, PendReqCmd, fwdVars>>

NI_Wb ==
    /\ WbMsg.Cmd = "WB_Wb"
    /\ WbMsg' = [Cmd |-> "WB_None", Proc |-> Undefined, Data |-> Undefined]
    /\ Dir' = [Dir EXCEPT !.Dirty = FALSE, !.HeadVld = FALSE, !.HeadPtr = Undefined]
    /\ MemData' = WbMsg.Data
    /\ UNCHANGED <<Home, Proc, UniMsg, InvMsg, RpMsg, ShWbMsg, NakcMsg, CurrData,
                   PrevData, pendVars, fwdVars>>

NI_FAck ==
    /\ ShWbMsg.Cmd = "SHWB_FAck"
    /\ ShWbMsg' = [Cmd |-> "SHWB_None", Proc |-> Undefined, Data |-> Undefined]
    /\ Dir' = [Dir EXCEPT !.Pending = FALSE, !.HeadPtr = IF Dir.Dirty THEN ShWbMsg.Proc ELSE Dir.HeadPtr]
    /\ UNCHANGED <<Home, Proc, MemData, UniMsg, InvMsg, RpMsg, WbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

NI_ShWb ==
    /\ ShWbMsg.Cmd = "SHWB_ShWb"
    /\ ShWbMsg' = [Cmd |-> "SHWB_None", Proc |-> Undefined, Data |-> Undefined]
    /\ Dir' = [Dir EXCEPT !.Pending = FALSE, !.Dirty = FALSE, !.ShrVld = TRUE,
                          !.ShrSet = Dir.ShrSet \cup {ShWbMsg.Proc},
                          !.InvSet = Dir.ShrSet \cup {ShWbMsg.Proc}]
    /\ MemData' = ShWbMsg.Data
    /\ UNCHANGED <<Home, Proc, UniMsg, InvMsg, RpMsg, WbMsg, NakcMsg, CurrData,
                   PrevData, pendVars, fwdVars>>

NI_Replace(src) ==
    /\ RpMsg[src].Cmd = "RP_Replace"
    /\ RpMsg' = [RpMsg EXCEPT ![src] = [Cmd |-> "RP_None"]]
    /\ Dir' = [Dir EXCEPT !.ShrSet = IF Dir.ShrVld THEN Dir.ShrSet \ {src} ELSE Dir.ShrSet,
                          !.InvSet = IF Dir.ShrVld THEN Dir.InvSet \ {src} ELSE Dir.InvSet]
    /\ UNCHANGED <<Home, Proc, MemData, UniMsg, InvMsg, WbMsg, ShWbMsg, NakcMsg,
                   CurrData, PrevData, pendVars, fwdVars>>

Next ==
    \/ \E src \in NODE, data \in DATA : Store(src, data)
    \/ \E src \in NODE :
         \/ \E c \in ReqCmd : PI_Remote(src, c)
         \/ PI_Remote_Replace(src)
         \/ NI_Local_Get_Nak(src) \/ NI_Local_Get_Get(src) \/ NI_Local_Get_Put(src)
         \/ NI_Local_GetX_Nak(src) \/ NI_Local_GetX_GetX(src) \/ NI_Local_GetX_PutX(src)
         \/ NI_InvAck(src) \/ NI_Replace(src)
    \/ \E dst \in NODE :
         \/ PI_Remote_PutX(dst)
         \/ NI_Nak(dst) \/ NI_Remote_Put(dst) \/ NI_Remote_PutX(dst) \/ NI_Inv(dst)
    \/ \E src \in NODE, dst \in NODE :
         \/ NI_Remote_Nak(src, dst) \/ NI_Remote_Get_Put(src, dst)
         \/ NI_Remote_GetX_PutX(src, dst)
    \/ PI_Local_Get_Get \/ PI_Local_Get_Put
    \/ PI_Local_GetX_GetX \/ PI_Local_GetX_PutX
    \/ PI_Local_PutX \/ PI_Local_Replace
    \/ NI_Nak_Clear \/ NI_Local_Put \/ NI_Local_PutXAcksDone
    \/ NI_Wb \/ NI_FAck \/ NI_ShWb

=============================================================================

------------------------------ MODULE FlashWithMutexDefs ------------------------------

EXTENDS FlashWithMutexModel

CACHE_STATE == {"CACHE_I", "CACHE_S", "CACHE_E"}
NODE_CMD    == {"NODE_None", "NODE_Get", "NODE_GetX"}
UNI_CMD     == {"UNI_None", "UNI_Get", "UNI_GetX", "UNI_Put", "UNI_PutX", "UNI_Nak"}
INV_CMD     == {"INV_None", "INV_Inv", "INV_InvAck"}
RP_CMD      == {"RP_None", "RP_Replace"}
WB_CMD      == {"WB_None", "WB_Wb"}
SHWB_CMD    == {"SHWB_None", "SHWB_ShWb", "SHWB_FAck"}
NAKC_CMD    == {"NAKC_None", "NAKC_Nakc"}

DataU  == DATA \cup {Undefined}
NodeU  == NODE \cup {Undefined}
UniU   == UNI_CMD \cup {Undefined}

TypeOK ==
    /\ Home \in NODE
    /\ Proc \in [NODE -> [ProcCmd : NODE_CMD, InvMarked : BOOLEAN,
                          CacheState : CACHE_STATE, CacheData : DataU]]
    /\ Dir \in [Pending : BOOLEAN, Local : BOOLEAN, Dirty : BOOLEAN,
                HeadVld : BOOLEAN, HeadPtr : NodeU, ShrVld : BOOLEAN,
                ShrSet : SUBSET NODE, InvSet : SUBSET NODE]
    /\ MemData \in DATA
    /\ UniMsg \in [NODE -> [Cmd : UNI_CMD, Proc : NodeU, Data : DataU]]
    /\ InvMsg \in [NODE -> [Cmd : INV_CMD]]
    /\ RpMsg  \in [NODE -> [Cmd : RP_CMD]]
    /\ WbMsg   \in [Cmd : WB_CMD, Proc : NodeU, Data : DataU]
    /\ ShWbMsg \in [Cmd : SHWB_CMD, Proc : NodeU, Data : DataU]
    /\ NakcMsg \in [Cmd : NAKC_CMD]
    /\ CurrData \in DATA
    /\ PrevData \in DATA
    /\ PendReqSrc \in NodeU
    /\ PendReqCmd \in UniU
    /\ Collecting \in BOOLEAN
    /\ FwdCmd \in UNI_CMD
    /\ FwdSrc \in NodeU

Spec == Init /\ [][Next]_vars

HandleUni(n) ==
    \/ NI_Nak(n)
    \/ NI_Local_Get_Nak(n)  \/ NI_Local_Get_Get(n)   \/ NI_Local_Get_Put(n)
    \/ NI_Local_GetX_Nak(n) \/ NI_Local_GetX_GetX(n) \/ NI_Local_GetX_PutX(n)
    \/ NI_Remote_Put(n) \/ NI_Remote_PutX(n)
    \/ (n = Home /\ (NI_Local_Put \/ NI_Local_PutXAcksDone))
    \/ \E d \in NODE : \/ NI_Remote_Nak(n, d)
                       \/ NI_Remote_Get_Put(n, d)
                       \/ NI_Remote_GetX_PutX(n, d)

HandleInv(n) == NI_Inv(n) \/ NI_InvAck(n)

HandleShWb == NI_FAck \/ NI_ShWb

Fairness ==
    /\ \A n \in NODE : /\ WF_vars(HandleUni(n))
                       /\ WF_vars(HandleInv(n))
                       /\ WF_vars(NI_Replace(n))
    /\ WF_vars(NI_Nak_Clear)
    /\ WF_vars(NI_Wb)
    /\ WF_vars(HandleShWb)

FairSpec == Init /\ [][Next]_vars /\ Fairness

ReqProgress ==
    \A n \in NODE : (Proc[n].ProcCmd # "NODE_None") ~> (Proc[n].ProcCmd = "NODE_None")

DirProgress == Dir.Pending ~> ~Dir.Pending

UniProgress ==
    \A n \in NODE : (UniMsg[n].Cmd # "UNI_None") ~> (UniMsg[n].Cmd = "UNI_None")

InvProgress ==
    \A n \in NODE : (InvMsg[n].Cmd # "INV_None") ~> (InvMsg[n].Cmd = "INV_None")

RpProgress ==
    \A n \in NODE : (RpMsg[n].Cmd = "RP_Replace") ~> (RpMsg[n].Cmd = "RP_None")

WbProgress   == (WbMsg.Cmd = "WB_Wb") ~> (WbMsg.Cmd = "WB_None")

ShWbProgress == (ShWbMsg.Cmd # "SHWB_None") ~> (ShWbMsg.Cmd = "SHWB_None")

NakcProgress == (NakcMsg.Cmd = "NAKC_Nakc") ~> (NakcMsg.Cmd = "NAKC_None")

CacheStateProp ==
    \A p, q \in NODE :
        p # q => ~(Proc[p].CacheState = "CACHE_E" /\ Proc[q].CacheState = "CACHE_E")

CacheDataProp ==
    \A p \in NODE :
        /\ (Proc[p].CacheState = "CACHE_E" => Proc[p].CacheData = CurrData)
        /\ (Proc[p].CacheState = "CACHE_S" =>
              /\ (Collecting => Proc[p].CacheData = PrevData)
              /\ (~Collecting => Proc[p].CacheData = CurrData))

MemDataProp ==
    ~Dir.Dirty => MemData = CurrData

Lemma_1 ==
    \A dst \in NODE :
        Proc[dst].CacheState = "CACHE_E" =>
            /\ Dir.Dirty
            /\ WbMsg.Cmd # "WB_Wb"
            /\ ShWbMsg.Cmd # "SHWB_ShWb"
            /\ \A p \in NODE : p # dst => Proc[p].CacheState # "CACHE_E"
            /\ UniMsg[Home].Cmd # "UNI_Put"
            /\ \A q \in NODE : UniMsg[q].Cmd # "UNI_PutX"

Lemma_2 ==
    \A src, dst \in NODE :
        (/\ src # dst /\ dst # Home
         /\ UniMsg[src].Cmd = "UNI_Get" /\ UniMsg[src].Proc = dst)
            => /\ Dir.Pending /\ ~Dir.Local
               /\ PendReqSrc = src /\ FwdCmd = "UNI_Get"

Lemma_3 ==
    \A src, dst \in NODE :
        (/\ src # dst /\ dst # Home
         /\ UniMsg[src].Cmd = "UNI_GetX" /\ UniMsg[src].Proc = dst)
            => /\ Dir.Pending /\ ~Dir.Local
               /\ PendReqSrc = src /\ FwdCmd = "UNI_GetX"

Lemma_4 ==
    \A p \in NODE :
        (p # Home /\ InvMsg[p].Cmd = "INV_InvAck") =>
            /\ Dir.Pending /\ Collecting
            /\ NakcMsg.Cmd = "NAKC_None" /\ ShWbMsg.Cmd = "SHWB_None"
            /\ \A q \in NODE :
                 /\ (UniMsg[q].Cmd \in {"UNI_Get", "UNI_GetX"} => UniMsg[q].Proc = Home)
                 /\ (UniMsg[q].Cmd = "UNI_PutX" => (UniMsg[q].Proc = Home /\ PendReqSrc = q))

Lemma_5 ==
    \A p \in NODE : Proc[p].CacheState = "CACHE_E" => Proc[p].CacheData = CurrData
=============================================================================

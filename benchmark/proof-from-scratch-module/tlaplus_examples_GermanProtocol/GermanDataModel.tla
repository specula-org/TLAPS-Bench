------------------------------ MODULE GermanDataModel ------------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS
    NODE,
    DATA,
    NoData,
    NoNode

ASSUME NoDataNotInDATA == NoData \notin DATA
ASSUME NoNodeNotInNODE == NoNode \notin NODE

VARIABLES
    cache,
    chan1,
    chan2,
    chan3,
    invSet,
    shrSet,
    exGntd,
    curCmd,
    curPtr,
    memData,
    auxData

vars == <<cache, chan1, chan2, chan3, invSet, shrSet,
          exGntd, curCmd, curPtr, memData, auxData>>

Init ==
    \E d \in DATA :
        /\ cache  = [i \in NODE |-> [state |-> "I", data |-> NoData]]
        /\ chan1  = [i \in NODE |-> [cmd |-> "Empty", data |-> NoData]]
        /\ chan2  = [i \in NODE |-> [cmd |-> "Empty", data |-> NoData]]
        /\ chan3  = [i \in NODE |-> [cmd |-> "Empty", data |-> NoData]]
        /\ invSet = {}
        /\ shrSet = {}
        /\ exGntd = FALSE
        /\ curCmd = "Empty"
        /\ curPtr = NoNode
        /\ memData = d
        /\ auxData = d

Store(i, d) ==
    /\ cache[i].state = "E"
    /\ cache' = [cache EXCEPT ![i].data = d]
    /\ auxData' = d
    /\ UNCHANGED <<chan1, chan2, chan3, invSet, shrSet,
                   exGntd, curCmd, curPtr, memData>>

SendReq(i) ==
    /\ chan1[i].cmd = "Empty"
    /\ \E c \in {"ReqS", "ReqE"} :
         /\ cache[i].state \in (IF c = "ReqS" THEN {"I"} ELSE {"I", "S"})
         /\ chan1' = [chan1 EXCEPT ![i].cmd = c]
    /\ UNCHANGED <<cache, chan2, chan3, invSet, shrSet,
                   exGntd, curCmd, curPtr, memData, auxData>>

RecvGnt(i) ==
    /\ chan2[i].cmd \in {"GntS", "GntE"}
    /\ cache' = [cache EXCEPT ![i].state = IF chan2[i].cmd = "GntS" THEN "S" ELSE "E",
                              ![i].data  = chan2[i].data]
    /\ chan2' = [chan2 EXCEPT ![i].cmd = "Empty", ![i].data = NoData]
    /\ UNCHANGED <<chan1, chan3, invSet, shrSet,
                   exGntd, curCmd, curPtr, memData, auxData>>

SendInvAck(i) ==
    /\ chan2[i].cmd = "Inv"
    /\ chan3[i].cmd = "Empty"
    /\ chan2' = [chan2 EXCEPT ![i].cmd = "Empty", ![i].data = NoData]
    /\ chan3' = [chan3 EXCEPT ![i].cmd = "InvAck",
                              ![i].data = IF cache[i].state = "E"
                                          THEN cache[i].data
                                          ELSE NoData]
    /\ cache' = [cache EXCEPT ![i].state = "I", ![i].data = NoData]
    /\ UNCHANGED <<chan1, invSet, shrSet,
                   exGntd, curCmd, curPtr, memData, auxData>>

RecvReq(i) ==
    /\ curCmd = "Empty"
    /\ chan1[i].cmd \in {"ReqS", "ReqE"}
    /\ curCmd' = chan1[i].cmd
    /\ curPtr' = i
    /\ chan1' = [chan1 EXCEPT ![i].cmd = "Empty"]
    /\ invSet' = shrSet
    /\ UNCHANGED <<cache, chan2, chan3, shrSet,
                   exGntd, memData, auxData>>

SendInv(i) ==
    /\ chan2[i].cmd = "Empty"
    /\ i \in invSet
    /\ (curCmd = "ReqE" \/ (curCmd = "ReqS" /\ exGntd = TRUE))
    /\ chan2' = [chan2 EXCEPT ![i].cmd = "Inv"]
    /\ invSet' = invSet \ {i}
    /\ UNCHANGED <<cache, chan1, chan3, shrSet,
                   exGntd, curCmd, curPtr, memData, auxData>>

RecvInvAck(i) ==
    /\ chan3[i].cmd = "InvAck"
    /\ curCmd # "Empty"
    /\ shrSet' = shrSet \ {i}
    /\ IF exGntd = TRUE
         THEN /\ exGntd'  = FALSE
              /\ memData' = chan3[i].data
              /\ chan3'   = [chan3 EXCEPT ![i].cmd = "Empty", ![i].data = NoData]
         ELSE /\ chan3'   = [chan3 EXCEPT ![i].cmd = "Empty"]
              /\ UNCHANGED <<exGntd, memData>>
    /\ UNCHANGED <<cache, chan1, chan2, invSet, curCmd, curPtr, auxData>>

SendGnt(i) ==
    /\ curCmd \in {"ReqS", "ReqE"}
    /\ curPtr = i
    /\ chan2[i].cmd = "Empty"
    /\ exGntd = FALSE
    /\ curCmd = "ReqE" => shrSet = {}
    /\ chan2' = [chan2 EXCEPT ![i].cmd  = IF curCmd = "ReqS" THEN "GntS" ELSE "GntE",
                              ![i].data = memData]
    /\ shrSet' = shrSet \cup {i}
    /\ exGntd' = (curCmd = "ReqE")
    /\ curCmd' = "Empty"
    /\ curPtr' = NoNode
    /\ UNCHANGED <<cache, chan1, chan3, invSet, memData, auxData>>

Next ==
    \/ \E i \in NODE, d \in DATA : Store(i, d)
    \/ \E i \in NODE :
         \/ SendReq(i)
         \/ RecvReq(i)
         \/ SendInv(i)     \/ SendInvAck(i)   \/ RecvInvAck(i)
         \/ SendGnt(i)
         \/ RecvGnt(i)

Spec == Init /\ [][Next]_vars

=============================================================================

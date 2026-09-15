------------------------------ MODULE GermanDataDefs ------------------------------
EXTENDS GermanDataModel

Abstract == INSTANCE GermanControl WITH
    cache <- [i \in NODE |-> cache[i].state],
    chan1 <- [i \in NODE |-> chan1[i].cmd],
    chan2 <- [i \in NODE |-> chan2[i].cmd],
    chan3 <- [i \in NODE |-> chan3[i].cmd]

Refinement == Abstract!Spec

DataProp ==
    /\ (exGntd = FALSE => memData = auxData)
    /\ \A i \in NODE : cache[i].state # "I" => cache[i].data = auxData

TransactionConsistency ==
    (curCmd = "Empty") <=> (curPtr = NoNode)

DirectoryAccurate ==
    \A i \in NODE : cache[i].state \in {"S", "E"} => i \in shrSet

ExclusiveIsolation ==
    \A i \in NODE :
        cache[i].state = "E" =>
            /\ exGntd = TRUE
            /\ \A j \in NODE \ {i} :
                /\ cache[j].state = "I"
                /\ chan2[j].cmd \notin {"GntS", "GntE"}
                /\ chan3[j].cmd # "InvAck"

WritebackCarriesLatest ==
    \A i \in NODE :
        (chan3[i].cmd = "InvAck" /\ curCmd # "Empty" /\ exGntd = TRUE) =>
            /\ chan3[i].data = auxData
            /\ \A j \in NODE \ {i} :
                /\ cache[j].state # "E"
                /\ chan2[j].cmd # "GntE"
                /\ chan3[j].cmd # "InvAck"

=============================================================================

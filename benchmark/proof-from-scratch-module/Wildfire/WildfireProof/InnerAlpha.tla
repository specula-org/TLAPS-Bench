
---------------------------- MODULE InnerAlpha ------------------------------

EXTENDS Naturals, Sequences, AlphaInterface, AlphaConstants

CONSTANTS
  InitMem

ASSUME InitialMemory ==

  InitMem \in [Adr -> Data]

VARIABLES
  reqSeq,

  beforeOrder

aVars == <<reqSeq, beforeOrder, aInt>>

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

reqId ==

  UNION { [proc : {p}, idx : DOMAIN reqSeq[p]] : p \in Proc}

reqIdSeq ==

  [rid \in reqId |-> reqSeq[rid.proc][rid.idx] ]

BeforeOrderOK ==

  LET IsBefore(r1, r2) == <<r1, r2>> \in beforeOrder

      SourceOrder(r1, r2) == /\ reqIdSeq[r2].req.type # "MB"
                             /\ reqIdSeq[r2].source = r1

      RequestOrder(r1, r2) ==

        LET ReqTypes == {reqIdSeq[r1].req.type, reqIdSeq[r2].req.type}

        IN  /\ r1.proc = r2.proc 
            /\ r1.idx < r2.idx   
            /\ \/ "MB" \in ReqTypes
               \/ reqIdSeq[r1].req.adr = reqIdSeq[r2].req.adr

      LLSCPair(r1, r2) ==

        /\ r1.proc = r2.proc
        /\ r1.idx < r2.idx
        /\ reqIdSeq[r1].req.type = "LL"
        /\ reqIdSeq[r2].req.type = "SC"
        /\ reqIdSeq[r1].req.adr = reqIdSeq[r2].req.adr
        /\ \A r \in reqId :
                  /\ r.proc = r1.proc
                  /\ (r1.idx < r.idx) /\ (r.idx < r2.idx)
                  => reqIdSeq[r].req.type \notin {"LL", "SC"}

  IN /\ 

        /\ beforeOrder \subseteq reqId \X reqId
        /\ \A r1, r2 \in reqId : IsBefore(r1, r2) => ~IsBefore(r2, r1)
        /\ \A r1, r2, r3 \in reqId :
             IsBefore(r1, r2) /\ IsBefore(r2, r3) => IsBefore(r1, r3)

     /\ 

        \A r1, r2 \in reqId : SourceOrder(r1, r2) => IsBefore(r1, r2)

     /\ 

        \A r1, r2 \in reqId : RequestOrder(r1, r2) => IsBefore(r1, r2)

     /\ 

        \A r1, r2 \in reqId :
           /\ r1 # r2
           /\ reqIdSeq[r1].req.type \in {"Wr", "SC"}
           /\ reqIdSeq[r1].newData # Failed
           /\ reqIdSeq[r1].responded
           /\ reqIdSeq[r2].req.type \in {"Wr", "SC"}
           /\ reqIdSeq[r2].newData # Failed
           /\ reqIdSeq[r2].responded
           /\ reqIdSeq[r1].req.adr = reqIdSeq[r2].req.adr
           => IsBefore(r1, r2) \/ IsBefore(r2, r1)

     /\ 

        \A r2 \in reqId :
           /\ reqIdSeq[r2].req.type = "SC"
           /\ reqIdSeq[r2].newData \notin {Failed, NotChosen}
           => \E r1 \in reqId :
                /\ LLSCPair(r1, r2)
                /\ \A r \in reqId :
                     /\ \/ reqIdSeq[r].req.type = "Wr"
                        \/ /\ reqIdSeq[r].req.type = "SC"
                           /\ reqIdSeq[r].newData \notin {NotChosen, Failed}
                     /\ r.proc # r2.proc
                     /\ reqIdSeq[r2].req.adr = reqIdSeq[r].req.adr
                     => ~IsBefore(r1, r) \/ ~IsBefore(r, r2)

     /\ 

        \A r1, r2 \in reqId :
           /\ reqIdSeq[r2].req.type # "MB"
           /\ reqIdSeq[r2].source # NoSource
           /\ \/ reqIdSeq[r1].req.type = "Wr"
              \/ /\ reqIdSeq[r1].req.type = "SC"
                 /\ reqIdSeq[r1].newData \in Data
           /\ reqIdSeq[r1].req.adr = reqIdSeq[r2].req.adr
           => IF reqIdSeq[r2].source = FromInitMem
                THEN ~IsBefore(r1, r2)
                ELSE \/ ~IsBefore(reqIdSeq[r2].source, r1)
                     \/ ~IsBefore(r1, r2)
-----------------------------------------------------------------------------

Init ==

  /\ reqSeq = [proc \in Proc |-> << >>]
  /\ beforeOrder = {}

-----------------------------------------------------------------------------

ReceiveRequest(proc, req) ==

  LET newMMRequest ==

        IF req.type \in {"Rd", "Wr", "LL", "SC"}
          THEN [req       |-> req ,
                newData   |-> NotChosen ,
                source    |-> NoSource,
                responded |-> FALSE]
          ELSE [req |-> req]
  IN /\ RequestFromEnv(aInt, aInt', proc, req)
     /\ reqSeq' = [reqSeq EXCEPT ![proc] = Append(@, newMMRequest)]

     /\ beforeOrder \subseteq beforeOrder'
     /\ BeforeOrderOK'

ChooseNewData(proc, idx) ==

  LET mreq == reqSeq[proc][idx]  
      req  == mreq.req           
      NewData(oldData) ==

        IF req.type \in {"Rd", "LL"}
          THEN oldData
          ELSE MaskVal(oldData, req.mask, req.data)
  IN  /\ idx \in DOMAIN reqSeq[proc]

      /\ req.type \in {"Rd", "LL", "Wr", "SC"}

      /\ mreq.newData = NotChosen

      /\ \E source \in {NoSource, FromInitMem} \cup reqId,
             newData \in Data \cup {NotChosen, Failed} :

         /\ \/ 

               IF /\ req.type \in {"Wr", "SC"}
                  /\ req.mask = AllOnes
                 THEN 

                      /\ source = NoSource
                      /\ newData = req.data
                 ELSE 

                      \/ 

                         /\ source \in reqId
                         /\ reqIdSeq[source].req.type \in {"Wr", "SC"}
                         /\ reqIdSeq[source].req.adr = req.adr
                         /\ reqIdSeq[source].newData \in Data
                         /\ newData = NewData(reqIdSeq[source].newData)
                      \/ 

                         /\ source = FromInitMem
                         /\ newData = NewData(InitMem[req.adr])
            \/ 

               /\ source = NoSource
               /\ req.type = "SC"
               /\ newData = Failed
         /\ reqSeq' = [reqSeq EXCEPT ![proc][idx].source  = source,
                                     ![proc][idx].newData = newData]
      /\ beforeOrder \subseteq beforeOrder'
      /\ BeforeOrderOK'
      /\ UNCHANGED <<aInt>>

SendResponse(proc, idx) ==

  LET mreq == reqSeq[proc][idx]
      req  == mreq.req
      resp ==

        CASE req.type \in {"Rd", "LL"} ->
               [type |-> req.type, adr |-> req.adr, data |-> mreq.newData]
          [] req.type = "Wr" ->
               [type |-> req.type, adr |-> req.adr]
          [] req.type = "SC" ->
               [type |-> IF mreq.newData # Failed THEN "SC"
                                                  ELSE "FailedSC",
                adr |-> req.adr]
  IN /\ idx \in DOMAIN reqSeq[proc]
     /\ req.type # "MB"

     /\ ~mreq.responded

     /\ mreq.newData # NotChosen

     /\ \A n \in 1..(idx-1) :
          /\ reqSeq[proc][n].req.type \in {"Wr", "Rd", "LL", "SC"}
          /\ reqSeq[proc][n].req.adr = req.adr
          => reqSeq[proc][n].responded

     /\ reqSeq' = [reqSeq EXCEPT ![proc][idx].responded = TRUE]
     /\ ResponseToEnv(aInt, aInt', proc, resp)
     /\ beforeOrder \subseteq beforeOrder'
     /\ BeforeOrderOK'

ExtendBefore ==

  /\ UNCHANGED <<reqSeq, aInt>>
  /\ beforeOrder \subseteq beforeOrder'
  /\ BeforeOrderOK'
-----------------------------------------------------------------------------

Next ==

  \/ \E proc \in Proc :
       \/ \E req \in Request : ReceiveRequest(proc, req)
       \/ \E idx \in DOMAIN reqSeq[proc] :
                   \/ ChooseNewData(proc, idx)
                   \/ SendResponse(proc, idx)
  \/ ExtendBefore

Liveness ==

  [] \A proc \in Proc : \A idx : ( /\ idx \in DOMAIN reqSeq[proc]
                                   /\ reqSeq[proc][idx].req.type # "MB" )
                                  => <>reqSeq[proc][idx].responded

InnerSpec == Init /\ [][Next]_aVars /\ Liveness

-----------------------------------------------------------------------------

=============================================================================

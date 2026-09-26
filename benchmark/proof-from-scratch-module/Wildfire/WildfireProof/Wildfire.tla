
----------------------------- MODULE Wildfire -------------------------------

EXTENDS AlphaInterface, AlphaConstants, Naturals, Sequences, FiniteSets

-----------------------------------------------------------------------------

SeqMinusItem(q, idx) ==

  SubSeq(q, 1, idx-1) \o SubSeq(q, idx+1, Len(q))

-----------------------------------------------------------------------------

CONSTANTS
  LS,

  ProcLS(_),

  AdrLS(_),

  InitMem

ASSUME DisjointNodes == Proc \cap LS = { }

ASSUME NaturalDataLen == DataLen \in Nat

ASSUME InitialMemory == InitMem \in [Adr -> Data]

ASSUME ProcessorHomes == \A p \in Proc : ProcLS(p) \in LS
ASSUME AddressHomes == \A a \in Adr : AdrLS(a) \in LS

InMemory == CHOOSE m : m \notin Proc

Unlocked == CHOOSE u : u \notin Adr

InvalidData == CHOOSE d : d \notin Data

-----------------------------------------------------------------------------

GetShared ==
  [type : {"GetShared"},
   cmdr : Proc,
   adr  : Adr]

GetExclusive ==
  [type : {"GetExclusive"},
   cmdr : Proc,
   adr  : Adr]

ChangeToExclusive ==
  [type : {"ChangeToExclusive"},
   cmdr  : Proc,
   adr   : Adr]

Victim ==

  [type : {"Victim"},
   cmdr  : Proc,
   adr   : Adr,
   data  : Data]

ForwardedGet ==

  [type  : {"ForwardedGet"},
   state : {"Shared", "Exclusive"},
   cmdr  : Proc,
   dest  : Proc,
   adr   : Adr]

ChangeToExclusiveAck ==

  [type : {"ChangeToExclusiveAck"},
   cmdr : Proc,
   adr  : Adr,
   success : BOOLEAN ]

Inval ==

  [type : {"Inval"},
   cmdr  : Proc,
   dest  : Proc,
   adr   : Adr]

VictimAck ==

  [type : {"VictimAck"},
   cmdr  : Proc,
   adr   : Adr]

FillMarker ==

  [type : {"FillMarker"},
   cmdr  : Proc,
   adr   : Adr]

ShadowClear ==

  [type : {"ShadowClear"},
   cmdr  : Proc,
   adr   : Adr]

ComsigClear ==

  [type : {"ComsigClear"},
   cmdr  : Proc,
   adr   : Adr]

Comsig ==

  [type : {"Comsig"},
   cmdr  : Proc]

Q0Message == GetShared \cup GetExclusive \cup
             ChangeToExclusive \cup Victim

Q1Message == ForwardedGet \cup ChangeToExclusiveAck \cup Inval \cup
             VictimAck \cup FillMarker \cup ShadowClear \cup
             ComsigClear \cup Comsig

MsgDestination(m) ==

  IF m \in Q0Message \cup ShadowClear \cup ComsigClear
    THEN AdrLS(m.adr)
    ELSE  IF "dest" \in DOMAIN m  THEN m.dest
                                  ELSE m.cmdr

MustFollow(q, m1, m2) ==

  \/ 

     /\ m1 \in Comsig
     /\ m2 \in Inval \cup ForwardedGet

  \/ 

     /\ m1 \in Q0Message
     /\ m2 \in Q0Message
     /\ m1.adr = m2.adr

  \/ 

     /\ m1 \in Q1Message \ Comsig
     /\ m2 \in Q1Message \ Comsig
     /\ (q = "LSToGS") => (m1.adr = m2.adr)

  \/ 
     /\ q = "GSToLS"
     /\ m1 \in Q0Message
     /\ m2 \in Inval \cup ForwardedGet

-----------------------------------------------------------------------------

Fill ==
  [adr   : Adr,
   data  : Data,
   state : {"Shared", "Exclusive"} ]

-----------------------------------------------------------------------------

VARIABLES
  cache,

  memDir,

  Q,

  fillQ,

  reqQ,
  respQ,

  locked

procVars == <<cache, reqQ, respQ, locked>>
wVars    == <<cache, reqQ, respQ, locked, memDir, Q, fillQ, aInt>>

-----------------------------------------------------------------------------

allQLocations ==

  UNION { UNION { {<<q, pl, idx>> : idx \in DOMAIN Q[q][pl]}
                   : pl \in DOMAIN Q[q]} :
            q \in DOMAIN Q }

msgsInTransit ==

  UNION {Q[loc[1]][loc[2]][loc[3]] : loc \in allQLocations}

msgsInQueue(q) ==

  UNION {q[i] : i \in DOMAIN q}

msgsInLoop(adr, type) ==

  LET ls == AdrLS(adr)
  IN  {m \in msgsInQueue(Q.LSToGS[ls]) \cup msgsInQueue(Q.GSToLS[ls]) :
          (m.type = type) /\  (m.adr = adr)}

InShadowMode(adr) ==

  msgsInLoop(adr, "ShadowClear") # {}

CanDequeueMsgSet(q, pl, idx) ==

  ~ \E i \in 1..(idx-1) :
      \E m1 \in Q[q][pl][idx], m2 \in Q[q][pl][i]  : MustFollow(q, m1, m2)

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

Init ==

   /\ cache = [p \in Proc |->
                 [a \in Adr |-> [state |-> "Invalid",
                                 fillOrCTEAckPending  |-> FALSE,
                                 version |-> << >> ]]]
   /\ memDir = [a \in Adr |-> [writer  |-> InMemory,
                               readers |-> { },
                               data    |-> InitMem[a]]]
   /\ Q = [ProcToLS |-> [p \in Proc |-> << >>],
           LSToProc |-> [p \in Proc |-> << >>],
           LSToGS   |-> [ls \in LS  |-> << >>],
           GSToLS   |-> [ls \in LS  |-> << >>]]
   /\ fillQ = [p \in Proc |-> { }]
   /\ reqQ  = [p \in Proc |-> << >>]
   /\ respQ = [p \in Proc |-> << >>]
   /\ locked = [p \in Proc |-> Unlocked]

-----------------------------------------------------------------------------

DirOpInProgress(proc, adr) ==

  \/ \E m \in msgsInTransit :
          /\ m \in GetShared \cup GetExclusive \cup
                   ChangeToExclusive \cup ForwardedGet \cup
                   ChangeToExclusiveAck
          /\ m.cmdr = proc
          /\ m.adr  = adr
  \/ \E m \in fillQ[proc] : m.adr = adr

CanIssueOrExecuteRdOrWr(p, idx) ==

  LET req == reqQ[p][idx]
  IN  /\ ~cache[p][req.adr].fillOrCTEAckPending

      /\ \A i \in 1..(idx-1) : /\ reqQ[p][i].type # "MB"
                               /\ reqQ[p][i].adr # req.adr
                               /\ (req.type \in {"LL", "SC"}) =>
                                     reqQ[p][i].type \notin {"LL", "SC"}

CanExecuteFromCache(p, idx) ==

  LET adr  == reqQ[p][idx].adr
      type == reqQ[p][idx].type
  IN  /\ \/  /\ type \in {"Wr", "SC"}
             /\ cache[p][adr].state = "Exclusive"

         \/  /\ type = "SC"
             /\ locked[p] # adr

         \/  /\ type \in {"Rd", "LL"}
             /\ cache[p][adr].state # "Invalid"
      /\ CanIssueOrExecuteRdOrWr(p, idx)

AdrToReqIdx(p, adr) ==

  CHOOSE idx \in DOMAIN reqQ[p] :
    /\ reqQ[p][idx].type # "MB"
    /\ reqQ[p][idx].adr = adr
    /\ \A i \in 1..(idx-1) : /\ reqQ[p][i].type # "MB"
                             /\ reqQ[p][i].adr # adr

OldestIdx(version) == 1
NewestIdx(version) == Len(version)
Oldest(version) == version[OldestIdx(version)]
Newest(version) == version[NewestIdx(version)]

ReducedCacheEntry(entry) ==

  IF /\ \/ Len(entry.version) > 1
        \/ /\ Len(entry.version) = 1
           /\ ~entry.fillOrCTEAckPending
           /\ entry.state = "Invalid"
     /\ ~Oldest(entry.version).fillMarkerPending
     /\ ~Oldest(entry.version).victimAckPending
  THEN [ entry EXCEPT !.version = Tail(entry.version) ]
  ELSE entry
-----------------------------------------------------------------------------

ProcReceiveRequest(p, req) ==

    /\ RequestFromEnv(aInt, aInt', p, req)
    /\ reqQ' = [reqQ EXCEPT ![p] = Append(@, req)]
    /\ UNCHANGED <<memDir, Q, fillQ, cache, respQ, locked>>

ProcSendResponse(p, idx) ==

  /\ \A i \in 1..(idx-1) : respQ[p][i].adr # respQ[p][idx].adr
  /\ ResponseToEnv(aInt, aInt', p, respQ[p][idx])
  /\ respQ' = [respQ EXCEPT ![p] = SeqMinusItem(@, idx)]
  /\ UNCHANGED <<memDir, Q, fillQ, cache, reqQ, locked>>

ProcEvictCacheLine(p, adr) ==

  /\ cache[p][adr].state # "Invalid"
  /\ cache[p][adr].version # << >>
  /\ ~cache[p][adr].fillOrCTEAckPending

  /\ cache' =

       [cache EXCEPT
          ![p][adr].state = "Invalid",
          ![p][adr].version =
             IF cache[p][adr].state # "SharedClean"
             THEN [@ EXCEPT ![NewestIdx(@)].victimAckPending=TRUE]
             ELSE 

                  IF /\ Len(@) = 1
                     /\ ~Newest(@).fillMarkerPending
                  THEN << >>
                  ELSE [@ EXCEPT ![NewestIdx(@)].data = InvalidData] ]

  /\ locked' =

       IF locked[p] = adr
       THEN [ locked EXCEPT ![p] = Unlocked ]
       ELSE locked

  /\ Q' =

       IF cache[p][adr].state = "SharedClean"
          THEN Q
          ELSE [Q EXCEPT
                   !.ProcToLS[p] = Append(@,
                       {[type |-> "Victim",
                         cmdr |-> p,
                         adr  |-> adr,
                         data |-> Newest(cache[p][adr].version).data]})]

  /\ UNCHANGED <<memDir, aInt, reqQ, respQ, fillQ>>

ProcRetireRdOrWr(p, idx, cch) ==

  LET req == reqQ[p][idx]
  IN  

      /\ reqQ' = [reqQ EXCEPT ![p] = SeqMinusItem(@, idx)]

      /\ IF \/ req.type = "Wr"
            \/ /\ req.type  = "SC"
               /\ locked[p] = req.adr
           THEN 

                /\ cache' = [cch EXCEPT ![p][req.adr].version =
                                 [@ EXCEPT ![NewestIdx(@)].data =
                                    MaskVal(@, req.mask, req.data)]]
                /\ respQ' =
                     [respQ EXCEPT ![p] =
                        Append(@, [type |-> req.type,
                                   adr  |-> req.adr])]
           ELSE 

                /\ cache' = cch
                /\ respQ' =
                     [respQ EXCEPT ![p] =
                        Append(@,
                          (IF req.type = "SC"
                           THEN 
                             [type |-> "FailedSC",
                              adr  |-> req.adr]
                           ELSE 
                             [type |-> req.type,
                              adr  |-> req.adr,
                              data |->
                                Newest(cch[p][req.adr].version).data]) )]

      /\ locked' =

           [locked EXCEPT ![p] =
              CASE req.type = "LL" -> req.adr

                [] req.type = "SC" -> Unlocked

                [] OTHER -> @]

ProcReceiveMsg(p, idx) ==

  /\ CanDequeueMsgSet("LSToProc", p, idx)

  /\ LET
       msgset == Q.LSToProc[p][idx]

       msg == CHOOSE m \in msgset : m.type # "Comsig"

       entry == cache[p][msg.adr]

     IN
       CASE \E m \in msgset : m \in ForwardedGet ->

               /\ \/ Len(entry.version) > 1
                  \/ ~entry.fillOrCTEAckPending
                  \/ entry.state # "Invalid"

               /\ cache' =

                  LET
                    newstate == IF Len(entry.version) > 1
                                THEN entry.state
                                ELSE IF /\ msg.state = "Shared"
                                        /\ entry.state # "Invalid"
                                     THEN "SharedDirty"
                                     ELSE "Invalid"
                    newentry == [entry EXCEPT !.state = newstate]
                  IN
                    [cache EXCEPT ![p][msg.adr] =
                           IF Len(entry.version) = 1
                           THEN ReducedCacheEntry(newentry)
                           ELSE newentry ]

               /\ fillQ' =

                  LET
                    version == entry.version
                  IN
                    [fillQ EXCEPT ![msg.cmdr] = @ \cup
                                {[adr   |-> msg.adr,
                                  data  |-> Oldest(version).data,
                                  state |-> msg.state]}]
               /\ locked' =

                   IF /\ locked[p] = msg.adr
                      /\ Len(entry.version) = 1

                      /\ msg.state = "Exclusive"
                   THEN [locked EXCEPT ![p] = Unlocked]
                   ELSE locked

               /\ UNCHANGED <<reqQ, respQ>>

       []   \E m \in msgset : m \in Inval ->

               LET forOldVersion ==

                     IF Len(entry.version) = 0

                     THEN TRUE
                     ELSE Newest(entry.version).fillMarkerPending

               IN  /\  \/ forOldVersion

                       \/ ~entry.fillOrCTEAckPending

                       \/ entry.state # "Invalid"

                   /\ cache' =

                        IF forOldVersion
                        THEN
                          cache
                        ELSE
                          [cache EXCEPT
                            ![p][msg.adr] =
                              ReducedCacheEntry([@ EXCEPT
                                                    !.state = "Invalid" ])]

                   /\ locked' =

                      IF /\ locked[p] = msg.adr
                         /\ ~forOldVersion
                      THEN
                        [locked EXCEPT ![p] = Unlocked]
                      ELSE
                        locked

                   /\ UNCHANGED <<reqQ, respQ, fillQ>>

         [] \E m \in msgset : /\ m.type = "ChangeToExclusiveAck"
                              /\ m.success ->

              LET
                ridx ==

                  AdrToReqIdx(p, msg.adr)
                cch ==

                  [cache EXCEPT ![p][msg.adr].state = "Exclusive",
                                ![p][msg.adr].fillOrCTEAckPending = FALSE ]
              IN
                /\ ProcRetireRdOrWr(p, ridx, cch)
                /\ UNCHANGED fillQ

         [] \E m \in msgset : /\ m.type = "ChangeToExclusiveAck"
                              /\ ~m.success ->

              /\ cache' = [ cache EXCEPT
                                    ![p][msg.adr].version = <<>>,
                                    ![p][msg.adr].fillOrCTEAckPending = FALSE ]

              /\ UNCHANGED << fillQ, reqQ, respQ, locked>>

         [] \E m \in msgset : m.type = "VictimAck" ->

              LET
                newentry == [ entry EXCEPT

                   !.version[OldestIdx(entry.version)].victimAckPending =
                                                                      FALSE ]
              IN

                /\ cache' = [cache EXCEPT ![p][msg.adr] =
                                          ReducedCacheEntry(newentry) ]
                /\ UNCHANGED << fillQ, reqQ, respQ, locked>>

         [] \E m \in msgset : m.type = "FillMarker" ->

              LET
                newentry == [ entry EXCEPT

                   !.version[OldestIdx(entry.version)].fillMarkerPending =
                                                                      FALSE ]
              IN

                /\ cache' = [cache EXCEPT ![p][msg.adr] =
                                          ReducedCacheEntry(newentry) ]
                /\ UNCHANGED << fillQ, reqQ, respQ, locked>>

         [] OTHER ->

               UNCHANGED <<fillQ, reqQ, respQ, cache, locked>>

  /\ Q' = [Q EXCEPT !.LSToProc[p] = SeqMinusItem(@, idx)]
  /\ UNCHANGED <<memDir, aInt>>

ProcReceiveFill(p, m) ==

  LET idx == AdrToReqIdx(p, m.adr)

      cch ==

        [cache EXCEPT
           ![p][m.adr].version = [@ EXCEPT ![NewestIdx(@)].data = m.data],
           ![p][m.adr].fillOrCTEAckPending = FALSE,
           ![p][m.adr].state = IF m.state = "Shared"
                               THEN "SharedClean"
                               ELSE "Exclusive"]

  IN

    /\ ProcRetireRdOrWr(p, idx, cch)
    /\ fillQ' = [fillQ EXCEPT ![p] = @ \ {m}]
    /\ UNCHANGED <<memDir, Q, aInt>>

ProcExecuteFromCache(p, idx) ==

  LET req == reqQ[p][idx]
  IN  /\ \/ /\ req.type = "MB"

            /\ \A i \in 1..(idx-1) :
                 /\ reqQ[p][i].type # "MB"

                 /\ DirOpInProgress(p, reqQ[p][i].adr)
                 /\ \A j \in 1..(i-1) : reqQ[p][j].adr # reqQ[p][i].adr

            /\ ~\E m \in msgsInTransit :
                    /\ m.type \in {"Comsig", "GetShared", "GetExclusive",
                                   "ChangeToExclusive"}
                    /\ m.cmdr = p

            /\ reqQ' = [reqQ EXCEPT ![p] = SeqMinusItem(@, idx)]
            /\ UNCHANGED <<respQ, cache, locked>>

         \/ /\ req.type # "MB"

            /\ CanExecuteFromCache(p, idx)

            /\ ProcRetireRdOrWr(p, idx, cache)

      /\ UNCHANGED <<memDir, Q, fillQ, aInt>>

ProcIssueDirReq(p, idx) ==

  LET req == reqQ[p][idx]
      adr == req.adr
      type == req.type
  IN
      /\ \/  /\ type = "Wr"
             /\ cache[p][adr].state # "Exclusive"
         \/  /\ type = "SC"
             /\ cache[p][adr].state \in {"SharedClean", "SharedDirty"}
             /\ locked[p] = adr
         \/  /\ type \in {"Rd", "LL"}
             /\ cache[p][adr].state = "Invalid"

      /\ CanIssueOrExecuteRdOrWr(p, idx)

      /\ ~CanExecuteFromCache(p, idx)

      /\ cache' =
           [ cache EXCEPT ![p][adr].fillOrCTEAckPending = TRUE,
                          ![p][adr].version =
                             IF cache[p][adr].state = "Invalid"
                             THEN Append(@,
                                     [ data              |-> InvalidData,
                                       fillMarkerPending |-> TRUE,
                                       victimAckPending  |-> FALSE ] )
                             ELSE @ ]

      /\ Q' =
           [ Q EXCEPT !.ProcToLS[p] =
               Append(@,
                {[ type |-> IF type \in {"Rd", "LL"}
                            THEN "GetShared"
                            ELSE IF cache[p][adr].state = "Invalid"
                                 THEN "GetExclusive"
                                 ELSE "ChangeToExclusive",
                   cmdr |-> p,
                   adr |-> adr ]} ) ]

      /\ UNCHANGED <<memDir, fillQ, aInt, reqQ, respQ, locked>>

-----------------------------------------------------------------------------

DirectoryProcessRequest(msg, queues) ==

  LET
    adr == msg.adr
    ls  == AdrLS(adr)
    readers == memDir[adr].readers
    writer  == memDir[adr].writer

    comsigMsg ==

      [type  |-> "Comsig", cmdr  |-> msg.cmdr]

    writing ==

      \/ msg.type = "GetExclusive"
      \/ /\ msg.type = "ChangeToExclusive"
         /\ msg.cmdr \in readers \cup {writer}

    invalSet ==

      IF writing
        THEN { [type  |-> "Inval",
                cmdr  |-> msg.cmdr,
                dest  |-> q,
                adr   |-> msg.adr] :
              q \in IF \/ msg.type = "GetExclusive"
                       \/ writer = InMemory
                    THEN readers \ {msg.cmdr}
                    ELSE (readers \cup {writer}) \ {msg.cmdr} }
         ELSE {}

    responseMsg ==

      IF msg.type = "ChangeToExclusive"
      THEN
        [ type |-> "ChangeToExclusiveAck",
          cmdr |-> msg.cmdr,
          adr  |-> msg.adr,
          success |-> writing ]
      ELSE
        [ type |-> "FillMarker",
          cmdr |-> msg.cmdr,
          adr  |-> msg.adr ]

    fgetSet ==

      IF \/ msg.type = "ChangeToExclusive"
         \/ writer = InMemory
      THEN {}
      ELSE
        { [ type |-> "ForwardedGet",
            state |-> IF msg.type = "GetShared"
                      THEN "Shared"
                      ELSE "Exclusive",
            cmdr |-> msg.cmdr,
            dest |-> writer,
            adr  |-> msg.adr ] }

    shadowClearMsg ==

      [type |-> "ShadowClear",
       cmdr  |-> msg.cmdr,
       adr   |-> msg.adr]

    comsigClearMsg ==

      [type |-> "ComsigClear",
       cmdr  |-> msg.cmdr,
       adr   |-> msg.adr]

    EnteringShadowMode ==

      /\ ProcLS(msg.cmdr) = ls
      /\ \E m \in fgetSet \cup invalSet : ProcLS(m.dest) # ls

    ShadowClearRequired ==

        /\ InShadowMode(adr) \/ EnteringShadowMode
        /\ \/ ProcLS(msg.cmdr) = ls
           \/ \E m \in fgetSet \cup invalSet : ProcLS(m.dest) = ls

    ComsigClearRequired ==

      \/  \E m \in fgetSet \cup invalSet : ProcLS(m.dest) # ls

      \/ IF ProcLS(msg.cmdr) = ls
           THEN msgsInLoop(adr, "ComsigClear") # {}

           ELSE \E m \in fgetSet \cup invalSet : ProcLS(m.dest) = ls

    Messages == {comsigMsg} \cup invalSet \cup {responseMsg} \cup fgetSet

    GlobalMessages ==

      IF ShadowClearRequired
      THEN Messages \cup {shadowClearMsg, comsigClearMsg}
      ELSE {m \in Messages : ProcLS(MsgDestination(m)) # ls}
           \cup ( IF ComsigClearRequired
                  THEN {comsigMsg, comsigClearMsg}
                  ELSE {} )

    LocalMessages == Messages \ GlobalMessages

  IN
    /\ Q' = [queues EXCEPT
               !.LSToGS[ls] = IF GlobalMessages = {}
                              THEN @
                              ELSE Append(@,GlobalMessages),
               !.LSToProc =
                   [p \in Proc |->
                      LET msgs ==
                               {m \in LocalMessages : MsgDestination(m) = p }
                      IN  IF msgs = {}
                          THEN @[p]
                          ELSE Append(@[p],msgs) ] ]

    /\ memDir' =
         CASE msg.type = "GetShared" ->
                [ memDir EXCEPT ![adr].readers = @ \cup {msg.cmdr} ]
         []   writing ->
                [ memDir EXCEPT ![adr].readers = {},
                                ![adr].writer = msg.cmdr ]
         []   OTHER ->
                memDir

    /\ fillQ' =
         IF /\ msg \in GetShared \cup GetExclusive
            /\ writer = InMemory
         THEN
           [fillQ EXCEPT ![msg.cmdr]
                  = @ \cup { [ adr |-> adr,
                               data |-> memDir[adr].data,
                               state |-> IF msg \in GetShared
                                         THEN "Shared"
                                         ELSE "Exclusive"]}]
         ELSE
           fillQ

    /\ UNCHANGED <<aInt, cache, reqQ, respQ, locked>>

LSReceiveRequestFromProc(p,idx) ==

  LET req == CHOOSE m \in Q.ProcToLS[p][idx] : TRUE

  IN
    /\ CanDequeueMsgSet("ProcToLS", p, idx)
    /\ req \in Q0Message \ Victim
    /\ AdrLS(req.adr) = ProcLS(p)
    /\ DirectoryProcessRequest(req,
                               [Q EXCEPT !.ProcToLS[p] = SeqMinusItem(@,idx)])

LSReceiveRequestFromGS(ls,idx) ==

  LET req == CHOOSE m \in Q.GSToLS[ls][idx] : TRUE

  IN
    /\ CanDequeueMsgSet("GSToLS", ls, idx)
    /\ req \in Q0Message \ Victim
    /\ DirectoryProcessRequest(req,
                               [Q EXCEPT !.GSToLS[ls] = SeqMinusItem(@,idx)])

DirectoryProcessVictim(m, ls, queues) ==

  LET
    victimAck == [ type |-> "VictimAck",
                   cmdr  |-> m.cmdr,
                   adr   |-> m.adr ]

    shadowClear == [ type |-> "ShadowClear",
                     cmdr  |-> m.cmdr,
                     adr   |-> m.adr ]

  IN
    /\ memDir' = IF memDir[m.adr].writer = m.cmdr
                 THEN [memDir EXCEPT
                        ![m.adr].writer = InMemory,
                        ![m.adr].data   = m.data]
                 ELSE memDir
    /\ Q' = IF InShadowMode(m.adr)
            THEN [queues EXCEPT !.LSToGS[ls] =
                                            Append(@,{victimAck,shadowClear})]
            ELSE IF ProcLS(m.cmdr) # ls
                 THEN [queues EXCEPT !.LSToGS[ls] = Append(@,{victimAck})]
                 ELSE [queues EXCEPT !.LSToProc[m.cmdr] = Append(@,{victimAck})]
    /\ UNCHANGED <<procVars, fillQ, aInt>>

LSReceiveVictimFromProc(p, idx) ==

  LET
    req == CHOOSE m \in Q.ProcToLS[p][idx] : TRUE

  IN
    /\ CanDequeueMsgSet("ProcToLS", p, idx)
    /\ req \in Victim
    /\ AdrLS(req.adr) = ProcLS(p)
    /\ DirectoryProcessVictim(req,
                              ProcLS(req.cmdr),
                              [Q EXCEPT !.ProcToLS[p] = SeqMinusItem(@,idx)])

LSReceiveVictimFromGS(ls, idx) ==

  LET
    req == CHOOSE m \in Q.GSToLS[ls][idx] : TRUE

  IN
    /\ CanDequeueMsgSet("GSToLS", ls, idx)
    /\ req \in Victim
    /\ DirectoryProcessVictim(req, ls,
                               [Q EXCEPT !.GSToLS[ls] = SeqMinusItem(@,idx)])

LSForwardMsgsToProcs(ls, idx) ==

  /\ \E m \in Q.GSToLS[ls][idx] : m \notin Q0Message
  /\ CanDequeueMsgSet("GSToLS", ls, idx)
  /\ Q' = [Q EXCEPT
            !.GSToLS[ls] = SeqMinusItem(@, idx),
            !.LSToProc = [p \in Proc |->
                           LET
                             msgsToP ==
                              {m \in Q.GSToLS[ls][idx] : MsgDestination(m) = p}
                           IN
                             IF msgsToP # {}
                             THEN Append(@[p], msgsToP)
                             ELSE @[p]]]
  /\ UNCHANGED << memDir, fillQ, aInt, procVars>>

LSForwardMsgsToGS(p, idx) ==

  /\ \E m \in Q.ProcToLS[p][idx] : MsgDestination(m) # ProcLS(p)
  /\ CanDequeueMsgSet("ProcToLS", p, idx)
  /\ Q' = [Q EXCEPT !.ProcToLS[p]       = SeqMinusItem(@, idx),
                    !.LSToGS[ProcLS(p)] = Append(@, Q.ProcToLS[p][idx])]
  /\ UNCHANGED << memDir, fillQ, aInt, procVars>>

-----------------------------------------------------------------------------

GSForwardMsgsToLS(ls, idx) ==

  /\ CanDequeueMsgSet("LSToGS", ls, idx)
  /\ Q' = [Q EXCEPT
             !.LSToGS[ls] = SeqMinusItem(@, idx),
             !.GSToLS = [t \in LS |->
                          LET ms == {m \in Q.LSToGS[ls][idx] :
                                       \/ MsgDestination(m) = t
                                       \/ /\ MsgDestination(m) \in Proc
                                          /\ ProcLS(MsgDestination(m)) = t}
                          IN  IF ms = { } THEN Q.GSToLS[t]
                                          ELSE Append(Q.GSToLS[t], ms)] ]
  /\ UNCHANGED <<memDir, fillQ, procVars, aInt>>

-----------------------------------------------------------------------------

Next ==
  \/ \E p \in Proc :
       \/ \E req \in Request : ProcReceiveRequest(p, req)
       \/ \E idx \in DOMAIN respQ[p] : ProcSendResponse(p, idx)
       \/ \E adr \in Adr : ProcEvictCacheLine(p, adr)
       \/ \E idx \in DOMAIN Q.LSToProc[p] : ProcReceiveMsg(p, idx)
       \/ \E m \in fillQ[p] : ProcReceiveFill(p, m)
       \/ \E idx \in DOMAIN reqQ[p] : \/ ProcIssueDirReq(p, idx)
                                      \/ ProcExecuteFromCache(p, idx)
       \/ \E idx \in DOMAIN Q.ProcToLS[p] :
            \/ LSForwardMsgsToGS(p, idx)
            \/ LSReceiveRequestFromProc(p, idx)
            \/ LSReceiveVictimFromProc(p, idx)

  \/ \E ls \in LS :
       \/ \E idx \in DOMAIN Q.GSToLS[ls] : LSReceiveRequestFromGS(ls, idx)
       \/ \E idx \in DOMAIN Q.GSToLS[ls] : LSReceiveVictimFromGS(ls, idx)
       \/ \E idx \in DOMAIN Q.GSToLS[ls] : LSForwardMsgsToProcs(ls, idx)
       \/ \E idx \in DOMAIN Q.LSToGS[ls] : GSForwardMsgsToLS(ls, idx)

-----------------------------------------------------------------------------

Liveness ==

   /\ \A p \in Proc :
      /\ WF_wVars((respQ[p] # <<>>) /\ ProcSendResponse(p, 1))
      /\ WF_wVars((Q.LSToProc[p] # <<>>) /\ ProcReceiveMsg(p, 1))
      /\ \A m \in Fill :  WF_wVars( /\ m \in fillQ[p]
                                    /\ ProcReceiveFill(p, m) )
      /\ WF_wVars((reqQ[p] # <<>>) /\ ProcIssueDirReq(p, 1))
      /\ WF_wVars((reqQ[p] # <<>>) /\ ProcExecuteFromCache(p, 1))
      /\ WF_wVars((Q.ProcToLS[p] # <<>>) /\ LSForwardMsgsToGS(p, 1))
      /\ WF_wVars((Q.ProcToLS[p] # <<>>) /\ LSReceiveRequestFromProc(p, 1))
      /\ WF_wVars((Q.ProcToLS[p] # <<>>) /\ LSReceiveVictimFromProc(p, 1))

   /\ \A ls \in LS :
      /\ WF_wVars((Q.GSToLS[ls] # <<>>) /\ LSReceiveRequestFromGS(ls, 1))
      /\ WF_wVars((Q.GSToLS[ls] # <<>>) /\ LSReceiveVictimFromGS(ls, 1))
      /\ WF_wVars((Q.GSToLS[ls] # <<>>) /\ LSForwardMsgsToProcs(ls, 1))
      /\ WF_wVars((Q.LSToGS[ls] # <<>>) /\ GSForwardMsgsToLS(ls, 1))

Spec == /\ Init
        /\ [][Next]_wVars
        /\ Liveness
-----------------------------------------------------------------------------

=============================================================================

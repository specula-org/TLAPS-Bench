
---------------------------- MODULE InnerAlpha ------------------------------
(***************************************************************************)
(* This module defines the formula InnerSpec to be the "internal"          *)
(* specification of the Alpha memory model--that is, the specification     *)
(* with internal variables visible.                                        *)
(***************************************************************************)
EXTENDS Naturals, Sequences, AlphaInterface, AlphaConstants

CONSTANTS
  InitMem
    (***********************************************************************)
    (* The initial contents of memory.                                     *)
    (***********************************************************************)

ASSUME InitialMemory ==
  (*************************************************************************)
  (* We assume that InitMem has the right "type"--that is, it is a         *)
  (* function from memory addresses to data values.                        *)
  (*************************************************************************)
  InitMem \in [Adr -> Data]

VARIABLES
  reqSeq,
    (***********************************************************************)
    (* For each processor proc, reqSeq[proc] is the sequence of all        *)
    (* requests that have been received from the environment, together     *)
    (* with their execution status.                                        *)
    (*                                                                     *)
    (* Note: TLA+ is untyped, so a variable like reqSeq may assume any     *)
    (* value.  When we say that reqSeq[proc] is a sequence of requests,    *)
    (* we mean that in every state of any behavior satisfying the          *)
    (* specification, the value of reqSeq[proc] will be a sequence of      *)
    (* requests.                                                           *)
    (***********************************************************************)

  beforeOrder
    (***********************************************************************)
    (* The Alpha memory model asserts the existence of a partial order on  *)
    (* requests that describes the order in which they are executed.  The  *)
    (* variable beforeOrder describes that partial order.  Its value is a  *)
    (* partial order on the set reqId of request identifiers, which is     *)
    (* defined below.  More precisely, beforeOrder will be a subset of     *)
    (* reqId \X reqId (the set of all pairs of elements in reqId), where   *)
    (* <<rid1, rid2>> \in beforeOrder means that the request identified by *)
    (* rid1 precedes the request identified by rid2.                       *)
    (***********************************************************************)

aVars == <<reqSeq, beforeOrder, aInt>>
  (*************************************************************************)
  (* For later use, we define aVars to be the tuple of all variables of    *)
  (* the specification.                                                    *)
  (*************************************************************************)
-----------------------------------------------------------------------------
(***************************************************************************)
(*                   Some Constants and Data Types                         *)
(***************************************************************************)

ReqSeqEntry ==
  (*************************************************************************)
  (* The "type" of an element in a processor's request queue.  That is,    *)
  (* for each processor proc, and each element idx in the domain of        *)
  (* reqSeq[proc], the value reqSeq[proc][idx] will be an element of the   *)
  (* set ReqSeqEntry.                                                      *)
  (*                                                                       *)
  (* ReqSeqEntry is the union of two sets of records, the first describing *)
  (* Rd, Wr, LL, and SC requests, and the second describing MB requests.   *)
  (*************************************************************************)
  [req : {r \in Request : r.type \in {"Rd", "LL", "Wr", "SC"}},
     (**********************************************************************)
     (* The request sent over the interface.                               *)
     (* In TLA+, {e(x) : x \in S} is the set of all elements of the form   *)
     (* e(x).                                                              *)
     (**********************************************************************)
   newData : Data \cup {NotChosen, Failed},
     (**********************************************************************)
     (* The value of the memory location after executing the request, or   *)
     (* NotChosen if that value has not yet been determined, or Failed for *)
     (* a failed SC.                                                       *)
     (**********************************************************************)
   source : [proc : Proc, idx : Nat] \cup {NoSource, FromInitMem},
     (**********************************************************************)
     (* For a read or partial-block write, the source of the non-written   *)
     (* part of newData.  The source either (i) is the newData field of a  *)
     (* Wr request, identified by a request identifier, (ii) comes from    *)
     (* the initial value InitMem of memory, or (iii) is NoSource, meaning *)
     (* that the operation either has not been performed, is a failed SC,  *)
     (* or is a Wr that wrote the entire data value (its mask field equals *)
     (* AllOnes).                                                          *)
     (**********************************************************************)
   responded : BOOLEAN]
     (**********************************************************************)
     (* True iff a response for this request has been generated to the     *)
     (* environment.  If true, then the newData field will not equal       *)
     (* NotChosen.                                                         *)
     (**********************************************************************)
 \cup
  [req : {r \in Request : r.type = "MB"}]
     (**********************************************************************)
     (* MB requests generate no response and are not performed to memory   *)
     (**********************************************************************)
-----------------------------------------------------------------------------
(***************************************************************************)
(*                   Some State Functions and Predicates                   *)
(*                                                                         *)
(* A state function is an expression whose value depends on the values of  *)
(* the state variables.  A state predicate is a Boolean-valued state       *)
(* function.                                                               *)
(***************************************************************************)
reqId ==
  (*************************************************************************)
  (* An element of reqId is a record [proc |-> p, idx -> i] that           *)
  (* identifies the idx-th element of processor proc's request queue       *)
  (* reqSeq[proc].                                                         *)
  (*                                                                       *)
  (* In TLA+,                                                              *)
  (* - UNION {S1, ... , Sn} equals S1 \cup ... \cup Sn                     *)
  (* - DOMAIN f is the domain of a function f.  If f is a sequence, it     *)
  (*   therefore equals the set 1 .. Len(f).                               *)
  (*************************************************************************)
  UNION { [proc : {p}, idx : DOMAIN reqSeq[p]] : p \in Proc}


reqIdSeq ==
  (*************************************************************************)
  (* The function such that reqIdSeq[rid] is the ReqSeqEntry for the       *)
  (* request with identifier rid.  In other words, if rid =                *)
  (* [proc |-> p, idx |-> i], then reqIdSeq[rid] = reqSeq[p][i].           *)
  (*************************************************************************)
  [rid \in reqId |-> reqSeq[rid.proc][rid.idx] ]


BeforeOrderOK ==
  (*************************************************************************)
  (* This state predicate is the heart of the specification.  It           *)
  (* encapsulates the requirements of the Alpha memory in a condition that *)
  (* relates beforeOrder and reqSeq.  It is true iff the following         *)
  (* properties hold.                                                      *)
  (*                                                                       *)
  (* - beforeOrder is an irreflexive partial order on reqId                *)
  (*                                                                       *)
  (* - beforeOrder extends the following two orderings:                    *)
  (*                                                                       *)
  (*    - Source Order: r1 precedes r2 if r1 is the source for r2.         *)
  (*                                                                       *)
  (*    - Request Order: r1 precedes r2 if r1 and r2 are requests from     *)
  (*      the same processor, r1 precedes r2 in the request queue, and     *)
  (*      either:                                                          *)
  (*       (a) At least one of them is an MB.                              *)
  (*       (b) They are requests to the same address.                      *)
  (*                                                                       *)
  (* - Writes and successful SCs to the same location that have issued     *)
  (*   responses are totally ordered.                                      *)
  (*                                                                       *)
  (* - The source request of a request is the most recent write.           *)
  (*                                                                       *)
  (* - LL's and successful SC's are properly paired, without intervening   *)
  (*    writes by another processor to the same address.                   *)
  (*************************************************************************)
  LET IsBefore(r1, r2) == <<r1, r2>> \in beforeOrder
        (*******************************************************************)
        (* The Boolean operator version of the beforeOrder relation.  We   *)
        (* define this because it's more convenient to write               *)
        (* IsBefore(r1, r2) than <<r1, r2>> \in beforeOrder.               *)
        (*                                                                 *)
        (* In TLA+, the expression `LET defs IN exp' equals the expression *)
        (* `exp' in the context of the local definitions `defs'.  The      *)
        (* symbol `#' means `not equal to'.                                *)
        (*******************************************************************)

      SourceOrder(r1, r2) == /\ reqIdSeq[r2].req.type # "MB"
                             /\ reqIdSeq[r2].source = r1
        (*******************************************************************)
        (* True iff r1 precedes r2 in the Source Order.                    *)
        (*******************************************************************)

      RequestOrder(r1, r2) ==
        (*******************************************************************)
        (* True iff r1 precedes r2 in the Request Order.                   *)
        (*******************************************************************)
        LET ReqTypes == {reqIdSeq[r1].req.type, reqIdSeq[r2].req.type}
              (*************************************************************)
              (* The set of types of the two requests.                     *)
              (*************************************************************)
        IN  /\ r1.proc = r2.proc (* r1 and r2 come from the same processor *)
            /\ r1.idx < r2.idx   (* r1 precedes r2 in reqSeq[processor]    *)
            /\ \/ "MB" \in ReqTypes
               \/ reqIdSeq[r1].req.adr = reqIdSeq[r2].req.adr

      LLSCPair(r1, r2) ==
        (*******************************************************************)
        (* True iff r1 and r2 are a properly matching LL and SC            *)
        (* request--that is, from the same processor to the same address   *)
        (* with no intervening LL or SC request.                           *)
        (*                                                                 *)
        (* In TLA+, \A is ASCII for \forall (the upside-down A of          *)
        (* predicate logic).                                               *)
        (*******************************************************************)
        /\ r1.proc = r2.proc
        /\ r1.idx < r2.idx
        /\ reqIdSeq[r1].req.type = "LL"
        /\ reqIdSeq[r2].req.type = "SC"
        /\ reqIdSeq[r1].req.adr = reqIdSeq[r2].req.adr
        /\ \A r \in reqId :
                  /\ r.proc = r1.proc
                  /\ (r1.idx < r.idx) /\ (r.idx < r2.idx)
                  => reqIdSeq[r].req.type \notin {"LL", "SC"}

  IN /\ (*******************************************************************)
        (* beforeOrder is an irreflexive, transitively closed relation on  *)
        (* reqId.                                                          *)
        (*******************************************************************)
        /\ beforeOrder \subseteq reqId \X reqId
        /\ \A r1, r2 \in reqId : IsBefore(r1, r2) => ~IsBefore(r2, r1)
        /\ \A r1, r2, r3 \in reqId :
             IsBefore(r1, r2) /\ IsBefore(r2, r3) => IsBefore(r1, r3)

     /\ (*******************************************************************)
        (* SourceOrder implies the beforeOrder order.                      *)
        (*******************************************************************)
        \A r1, r2 \in reqId : SourceOrder(r1, r2) => IsBefore(r1, r2)

     /\ (*******************************************************************)
        (* RequestOrder implies the beforeOrder order.                     *)
        (*******************************************************************)
        \A r1, r2 \in reqId : RequestOrder(r1, r2) => IsBefore(r1, r2)

     /\ (*******************************************************************)
        (* Writes and successful SCs to the same location that have issued *)
        (* a response are totally ordered.                                 *)
        (*******************************************************************)
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

     /\ (*******************************************************************)
        (* LL/SC Axiom: For each successful SC, there is a matching LL,    *)
        (* and there is no write to the same address from a different      *)
        (* processor that comes between the LL and SC in the beforeOrder   *)
        (* order.                                                          *)
        (*                                                                 *)
        (* In TLA+, \E is ASCII for \exists (the upside-down E of          *)
        (* predicate logic).                                               *)
        (*******************************************************************)
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

     /\ (*******************************************************************)
        (* Value Axiom: There is no write or successful SC to the same     *)
        (* address that comes, in the beforeOrder order, between the       *)
        (* request and its source.                                         *)
        (*******************************************************************)
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
(***************************************************************************)
(*                             STATE PREDICATES                            *)
(*                                                                         *)
(***************************************************************************)

Init ==
  (*************************************************************************)
  (* The state predicate that describes the initial state.  Initially,     *)
  (* reqSeq[proc] is the empty sequence << >>, for every processor proc,   *)
  (* and beforeOrder is the empty set {}.  We assume that the initial      *)
  (* state of the interface variable aInt doesn't matter.                  *)
  (*************************************************************************)
  /\ reqSeq = [proc \in Proc |-> << >>]
  /\ beforeOrder = {}

TypeInvariant ==
  (*************************************************************************)
  (* Recall that TLA+ is untyped.  When we say that a variable n has type  *)
  (* Nat, we mean that, in every state of any behavior satisfying some     *)
  (* specification Spec, the value of n is an element of Nat.  This is     *)
  (* asserted by the TLA formula Spec => [](n \in Nat).                    *)
  (*                                                                       *)
  (* TypeInvariant is a state predicate that asserts that reqSeq and       *)
  (* beforeOrder have the right types.                                     *)
  (*************************************************************************)
  /\ reqSeq \in [Proc -> Seq(ReqSeqEntry)]
  /\ beforeOrder \subseteq reqId \X reqId

-----------------------------------------------------------------------------
(***************************************************************************)
(*                                ACTIONS                                  *)
(*                                                                         *)
(* The specification InnerSpec equals                                      *)
(*                                                                         *)
(*    Init /\ [][Next]_aVars /\ Liveness                                   *)
(*                                                                         *)
(* where                                                                   *)
(*                                                                         *)
(* - Init is a state predicate describing the initial state.               *)
(* - Next is an action that describes all allowed steps (state             *)
(*   transitions).                                                         *)
(* - Liveness is a liveness condition, specifying what must eventually     *)
(*   happens.                                                              *)
(*                                                                         *)
(* The conjunct [][Next]_aVars asserts that every step either satisfies    *)
(* Next or else leaves unchanged aVars (and hence all the variables of the *)
(* specification).                                                         *)
(*                                                                         *)
(* The next-state action Next allows four different types of actions:      *)
(*   ReceiveRequest(proc, req) : The system receives a request req from    *)
(*                               processor proc.                           *)
(*   ChooseNewData(proc, idx)  : Choose the newData field of the idx-th    *)
(*                               entry in proc's request queue.            *)
(*   SendResponse(proc, idx)   : Issue a response to the environment for   *)
(*                               proc's idx-th request.                    *)
(*   ExtendBefore              : Expand the beforeOrder relation.          *)
(*                                                                         *)
(* These actions all specify the new value of beforeOrder with             *)
(* the following conjuncts.                                                *)
(*                                                                         *)
(*   /\ beforeOrder \subseteq beforeOrder'                                 *)
(*      \* The beforeOrder relation can only grow.                         *)
(*                                                                         *)
(*   /\ BeforeOrderOK'                                                     *)
(*      \* The new value of beforeOrder satisfies BeforeOrderOK            *)
(*                                                                         *)
(* Since BeforeOrderOK depends on both beforeOrder and reqSeq, the last    *)
(* conjunct asserts a relation between the new values of those variables.  *)
(* However, other conjuncts in the actions describe the new value of       *)
(* reqSeq, so this conjunct just constrains the new value of beforeOrder.  *)
(***************************************************************************)

ReceiveRequest(proc, req) ==
  (*************************************************************************)
  (* The action in which a request req is issued by the environment for    *)
  (* processor proc.                                                       *)
  (*************************************************************************)
  LET newMMRequest ==
        (*******************************************************************)
        (* The ReqSeqEntry added to reqSeq.                                *)
        (*******************************************************************)
        IF req.type \in {"Rd", "Wr", "LL", "SC"}
          THEN [req       |-> req ,
                newData   |-> NotChosen ,
                source    |-> NoSource,
                responded |-> FALSE]
          ELSE [req |-> req]
  IN /\ RequestFromEnv(aInt, aInt', proc, req)
     /\ reqSeq' = [reqSeq EXCEPT ![proc] = Append(@, newMMRequest)]
        (*******************************************************************)
        (* In TLA+, [f EXCEPT ![v] = e] is the function ff that is the     *)
        (* same as f except ff[v] = e.  In the expression e, the symbol @  *)
        (* stands for f[v].                                                *)
        (*******************************************************************)
     /\ beforeOrder \subseteq beforeOrder'
     /\ BeforeOrderOK'

ChooseNewData(proc, idx) ==
  (*************************************************************************)
  (* The action in which the newData field and perhaps the source field    *)
  (* are set for the idx-th request in proc's request queue.               *)
  (*************************************************************************)
  LET mreq == reqSeq[proc][idx]  \* The request's ReqSeqEntry.
      req  == mreq.req           \* The request.
      NewData(oldData) ==
        (*******************************************************************)
        (* The value of the newData field for the request's entry, if the  *)
        (* data value of the source is oldData.                            *)
        (*******************************************************************)
        IF req.type \in {"Rd", "LL"}
          THEN oldData
          ELSE MaskVal(oldData, req.mask, req.data)
  IN  /\ idx \in DOMAIN reqSeq[proc]
         (******************************************************************)
         (* Processor proc has received its idx-th request.                *)
         (******************************************************************)
      /\ req.type \in {"Rd", "LL", "Wr", "SC"}
         (******************************************************************)
         (* The request is not an MB.                                      *)
         (******************************************************************)
      /\ mreq.newData = NotChosen
         (******************************************************************)
         (* The newData field has not yet been chosen.  Note that a failed *)
         (* SC has its newData field equal to Failed.                      *)
         (******************************************************************)
      /\ \E source \in {NoSource, FromInitMem} \cup reqId,
             newData \in Data \cup {NotChosen, Failed} :
              (*************************************************************)
              (* The new source and newData fields.                        *)
              (*************************************************************)
         /\ \/ (************************************************************)
               (* For a read, write, and successful SC.                    *)
               (************************************************************)
               IF /\ req.type \in {"Wr", "SC"}
                  /\ req.mask = AllOnes
                 THEN (*****************************************************)
                      (* This is an unmasked write (mask all 1s), so no    *)
                      (* source is needed.                                 *)
                      (*****************************************************)
                      /\ source = NoSource
                      /\ newData = req.data
                 ELSE (*****************************************************)
                      (* This is a masked write (mask not all 1s), so we   *)
                      (* need to choose a source.                          *)
                      (*****************************************************)
                      \/ (**************************************************)
                         (* The source is a write to the same address.     *)
                         (**************************************************)
                         /\ source \in reqId
                         /\ reqIdSeq[source].req.type \in {"Wr", "SC"}
                         /\ reqIdSeq[source].req.adr = req.adr
                         /\ reqIdSeq[source].newData \in Data
                         /\ newData = NewData(reqIdSeq[source].newData)
                      \/ (**************************************************)
                         (* The source is the initial memory.              *)
                         (**************************************************)
                         /\ source = FromInitMem
                         /\ newData = NewData(InitMem[req.adr])
            \/ (************************************************************)
               (* For a failing SC, choose NoSource as source and Failed   *)
               (* as newData.                                              *)
               (************************************************************)
               /\ source = NoSource
               /\ req.type = "SC"
               /\ newData = Failed
         /\ reqSeq' = [reqSeq EXCEPT ![proc][idx].source  = source,
                                     ![proc][idx].newData = newData]
      /\ beforeOrder \subseteq beforeOrder'
      /\ BeforeOrderOK'
      /\ UNCHANGED <<aInt>>

SendResponse(proc, idx) ==
  (*************************************************************************)
  (* The action in which processor proc issues a response to its idx-th    *)
  (* request to the environment.                                           *)
  (*************************************************************************)
  LET mreq == reqSeq[proc][idx]
      req  == mreq.req
      resp ==
        (*******************************************************************)
        (* The response sent to the environment.                           *)
        (*******************************************************************)
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
          (*****************************************************************)
          (* There is no response to an MB.                                *)
          (*****************************************************************)
     /\ ~mreq.responded
        (*******************************************************************)
        (* This request hasn't been responded to.                          *)
        (*******************************************************************)
     /\ mreq.newData # NotChosen
          (*****************************************************************)
          (* The new data has been chosen.  It can equal Failed for a      *)
          (* failed SC.                                                    *)
          (*****************************************************************)
     /\ \A n \in 1..(idx-1) :
          /\ reqSeq[proc][n].req.type \in {"Wr", "Rd", "LL", "SC"}
          /\ reqSeq[proc][n].req.adr = req.adr
          => reqSeq[proc][n].responded
          (*****************************************************************)
          (* Requests to the same processor for the same address are       *)
          (* responded to in order.                                        *)
          (*****************************************************************)
     /\ reqSeq' = [reqSeq EXCEPT ![proc][idx].responded = TRUE]
     /\ ResponseToEnv(aInt, aInt', proc, resp)
     /\ beforeOrder \subseteq beforeOrder'
     /\ BeforeOrderOK'


ExtendBefore ==
  (*************************************************************************)
  (* Spontaneously extend the beforeOrder relation, leaving reqSeq and     *)
  (* aInt unchanged.  This action represents implementation actions that   *)
  (* constrain the final execution order, but make no other changes        *)
  (* reflected in the memory specification.                                *)
  (*************************************************************************)
  /\ UNCHANGED <<reqSeq, aInt>>
  /\ beforeOrder \subseteq beforeOrder'
  /\ BeforeOrderOK'
-----------------------------------------------------------------------------
(***************************************************************************)
(*                       The Complete TLA Spec                             *)
(***************************************************************************)

Next ==
  (*************************************************************************)
  (* The next-state relation.  A Next step is either                       *)
  (*                                                                       *)
  (* - A ReceiveRequest(proc, req) step for some processor proc and        *)
  (*   request req.                                                        *)
  (*                                                                       *)
  (* - A ChooseNewData(proc, idx) or SendResponse(proc, idx) step for      *)
  (*   some processor proc and idx in 1..Len(reqSeq[proc]).                *)
  (*                                                                       *)
  (* - An ExtendBefore step.                                               *)
  (*************************************************************************)
  \/ \E proc \in Proc :
       \/ \E req \in Request : ReceiveRequest(proc, req)
       \/ \E idx \in DOMAIN reqSeq[proc] :
                   \/ ChooseNewData(proc, idx)
                   \/ SendResponse(proc, idx)
  \/ ExtendBefore


Liveness ==
  (*************************************************************************)
  (* The liveness condition: every non-MB request must eventually receive a *)
  (* response.                                                             *)
  (*                                                                       *)
  (* This liveness condition actually introduces an additional safety      *)
  (* property to the specification.  The next-state relation Next allows   *)
  (* the system to generate a finite sequence of states that cannot be     *)
  (* continued to an infinite behavior that satisfies the liveness         *)
  (* condition.  (It can "paint itself into a corner".)  Conjoining the    *)
  (* liveness condition to the specification therefore effectively         *)
  (* strengthens the next-state relation by disallowing any step that      *)
  (* would lead to a state from which the liveness condition can no longer *)
  (* be satisfied.  In the terminlogy of Abadi and Lamport, this spec is   *)
  (* said not to be machine-closed.  In the terminlogy of Apt, Francez,    *)
  (* and Katz, it is said to be non-feasible.                              *)
  (*                                                                       *)
  (* [] and <> are the usual operators "always" and "eventually" of        *)
  (* linear-time temporal logic.                                           *)
  (*************************************************************************)
  [] \A proc \in Proc : \A idx : ( /\ idx \in DOMAIN reqSeq[proc]
                                   /\ reqSeq[proc][idx].req.type # "MB" )
                                  => <>reqSeq[proc][idx].responded

InnerSpec == Init /\ [][Next]_aVars /\ Liveness
  (*************************************************************************)
  (* The complete inner specification.                                     *)
  (*************************************************************************)
-----------------------------------------------------------------------------
\* The benchmark does not import an unproved type-invariance theorem.
=============================================================================
Last modified on Tue Jun 13 08:56:38 PDT 2000 by lamport

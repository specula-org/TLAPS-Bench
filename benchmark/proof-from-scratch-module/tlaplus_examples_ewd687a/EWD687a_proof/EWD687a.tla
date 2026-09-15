------------------------------ MODULE EWD687a ------------------------------

EXTENDS Integers, Graphs

CONSTANTS Procs, Leader, Edges

InEdges(p)  == {e \in Edges : e[2] = p}

OutEdges(p) == {e \in Edges : e[1] = p}

ASSUME EdgeFacts ==
        /\ 
           \A e \in Edges :
             /\ (e \in Procs \X Procs)
             /\ (e[1] # e[2])
        /\ 
           Leader \in Procs        
        /\ 
           
           InEdges(Leader) = {}

NotAnEdge  == << >>

VARIABLES 

    active,

    sentUnacked,

    rcvdUnacked,

    upEdge,

    msgs,

    acks

vars == <<active, msgs, acks, sentUnacked, rcvdUnacked, upEdge>>

TypeOK == /\ active \in [Procs -> BOOLEAN]
          /\ msgs \in [Edges -> Nat]
          /\ acks \in [Edges -> Nat]
          /\ sentUnacked \in [Edges -> Nat]
          /\ rcvdUnacked \in [Edges -> Nat]
          /\ upEdge \in [Procs \ {Leader} -> Edges \cup {NotAnEdge}]
          /\ \A p \in Procs \ {Leader} :
                upEdge[p] # NotAnEdge => upEdge[p][2] = p

neutral(p) == /\ ~ active[p]
              /\ \A e \in InEdges(p) : rcvdUnacked[e] = 0
              /\ \A e \in OutEdges(p) : sentUnacked[e] = 0 

Init == /\ active = [p \in Procs |-> p = Leader]
        /\ msgs = [e \in Edges |-> 0]
        /\ acks = [e \in Edges |-> 0]
        /\ sentUnacked = [e \in Edges |-> 0]
        /\ rcvdUnacked = [e \in Edges |-> 0]
        /\ upEdge = [p \in Procs \ {Leader} |-> NotAnEdge]
 
----------------------------------------------------------------------------

SendMsg(p) == /\ active[p]
              /\ \E e \in OutEdges(p) : 
                     /\ sentUnacked' = [sentUnacked EXCEPT ![e] = @ + 1] 
                     /\ msgs' = [msgs EXCEPT ![e] = @ + 1]
              /\ UNCHANGED <<active, acks, rcvdUnacked, upEdge>>

RcvAck(p) == \E e \in OutEdges(p) :
                  /\ acks[e] > 0
                  /\ acks' = [acks EXCEPT ![e] = @ - 1]
                  /\ sentUnacked' = [sentUnacked EXCEPT ![e] = @ - 1]
                  /\ UNCHANGED <<active, msgs, rcvdUnacked, upEdge>>

----------------------------------------------------------------------------

SendAck(p) == /\ \E e \in InEdges(p) :
                     /\ rcvdUnacked[e] > 0
                     
                     /\ (e = upEdge[p]) =>
                        
                        \/ rcvdUnacked[e] > 1

                        \/ /\ ~ active[p]
                           /\ \A d \in InEdges(p) \ {e} : rcvdUnacked[d] = 0
                           /\ \A d \in OutEdges(p) : sentUnacked[d] = 0
                           
                     /\ rcvdUnacked' = [rcvdUnacked EXCEPT ![e] = @ - 1] 
                     /\ acks' = [acks EXCEPT ![e] = @ + 1]
              /\ UNCHANGED <<active, msgs, sentUnacked>>

              /\ UP:: upEdge' = IF neutral(p)' THEN [upEdge EXCEPT ![p] = NotAnEdge]
                                               ELSE upEdge

RcvMsg(p) == \E e \in InEdges(p) : 
                  /\ msgs[e] > 0  
                  /\ msgs' = [msgs EXCEPT ![e] = @ - 1]  
                  /\ rcvdUnacked' = [rcvdUnacked EXCEPT ![e] = @ + 1]
                  /\ active' = [active EXCEPT ![p] = TRUE]

                  /\ upEdge' = IF neutral(p) THEN [upEdge EXCEPT ![p] = e]
                                             ELSE upEdge
                  /\ UNCHANGED <<acks, sentUnacked>>

Idle(p) == /\ active[p]
           /\ active' = [active EXCEPT ![p] = FALSE]
           /\ UNCHANGED <<msgs, acks, sentUnacked, rcvdUnacked, upEdge>>

----------------------------------------------------------------------------

Next == \E p \in Procs : SendMsg(p) \/ SendAck(p) \/ RcvMsg(p) \/ RcvAck(p)
                             \/ Idle(p)

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

----------------------------------------------------------------------------

CountersConsistent ==
    \A e \in Edges: sentUnacked[e] = rcvdUnacked[e] + acks[e] + msgs[e]

---------------------------------------------------------------------------

DT1Inv == neutral(Leader) => \A p \in Procs \ {Leader} : neutral(p)

-----------------------------------------------------------------------------

=============================================================================


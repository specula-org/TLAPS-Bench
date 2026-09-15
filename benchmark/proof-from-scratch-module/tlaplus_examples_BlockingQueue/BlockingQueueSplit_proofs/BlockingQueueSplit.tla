------------------------- MODULE BlockingQueueSplit -------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Producers,   
          Consumers,   
          BufCapacity  

ASSUME Assumption ==
       /\ Producers # {}                      
       /\ Consumers # {}                      
       /\ Producers \intersect Consumers = {} 
       /\ BufCapacity \in (Nat \ {0})         
       
-----------------------------------------------------------------------------

VARIABLES buffer, waitSetC, waitSetP
vars == <<buffer, waitSetC, waitSetP>>

NotifyOther(ws) == 
         \/ /\ ws = {}
            /\ UNCHANGED ws
         \/ /\ ws # {}
            /\ \E x \in ws: ws' = ws \ {x}

Wait(ws, t) == /\ ws' = ws \cup {t}
               /\ UNCHANGED <<buffer>>
           
-----------------------------------------------------------------------------

Put(t, d) ==
/\ t \notin waitSetP
/\ \/ /\ Len(buffer) < BufCapacity
      /\ buffer' = Append(buffer, d)
      /\ NotifyOther(waitSetC)
      /\ UNCHANGED waitSetP
   \/ /\ Len(buffer) = BufCapacity
      /\ Wait(waitSetP, t)
      /\ UNCHANGED waitSetC
      
Get(t) ==
/\ t \notin waitSetC
/\ \/ /\ buffer # <<>>
      /\ buffer' = Tail(buffer)
      /\ NotifyOther(waitSetP)
      /\ UNCHANGED waitSetC
   \/ /\ buffer = <<>>
      /\ Wait(waitSetC, t)
      /\ UNCHANGED waitSetP

-----------------------------------------------------------------------------

Init == /\ buffer = <<>>
        /\ waitSetC = {}
        /\ waitSetP = {}

Next == \/ \E p \in Producers: Put(p, p) 
        \/ \E c \in Consumers: Get(c)

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------

A == INSTANCE BlockingQueue WITH waitSet <- (waitSetC \cup waitSetP)

=============================================================================

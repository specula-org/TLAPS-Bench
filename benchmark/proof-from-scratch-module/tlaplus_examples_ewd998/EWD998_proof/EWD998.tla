------------------------------- MODULE EWD998 -------------------------------

EXTENDS Integers, FiniteSets, Functions

CONSTANT
    
    N
ASSUME NAssumption == N \in Nat \ {0} 

Node == 0 .. N-1
Color == {"white", "black"}

VARIABLES 
 
 active,     
 
 color,      
 
 counter,    
 
 pending,    
 
 token       
  
vars == <<active, color, counter, pending, token>>

------------------------------------------------------------------------------
 
Init ==
   
  /\ active \in [Node -> BOOLEAN]
  /\ color \in [Node -> Color]
  
  /\ counter = [i \in Node |-> 0] 
  /\ pending = [i \in Node |-> 0]
  /\ token \in [ pos: Node, q: {0}, color: {"black"} ]

InitiateProbe ==
  
  /\ token.pos = 0
  /\ 
     \/ token.color = "black"
     \/ color[0] = "black"
     \/ counter[0] + token.q > 0
  /\ token' = [pos |-> N-1, q |-> 0, color |-> "white"]
  /\ color' = [ color EXCEPT ![0] = "white" ]
  
  /\ UNCHANGED <<active, counter, pending>>                            
  
PassToken(i) ==
  
  /\ ~ active[i] 
  /\ token.pos = i
  /\ token' = [pos |-> token.pos - 1,
               q |-> token.q + counter[i],
               color |-> IF color[i] = "black" THEN "black" ELSE token.color]
            
  /\ color' = [ color EXCEPT ![i] = "white" ]
  
  /\ UNCHANGED <<active, counter, pending>>

System == \/ InitiateProbe
          \/ \E i \in Node \ {0} : PassToken(i)

-----------------------------------------------------------------------------

SendMsg(i) ==
  
  /\ active[i]
  
  /\ counter' = [counter EXCEPT ![i] = @ + 1]
  
  /\ \E j \in Node \ {i} : pending' = [pending EXCEPT ![j] = @ + 1]

  /\ UNCHANGED <<active, color, token>>

RecvMsg(i) ==
  /\ pending[i] > 0
  /\ pending' = [pending EXCEPT ![i] = @ - 1]
  
  /\ counter' = [counter EXCEPT ![i] = @ - 1]
  
  /\ color' = [ color EXCEPT ![i] = "black" ]
  
  /\ active' = [ active EXCEPT ![i] = TRUE ]
  /\ UNCHANGED <<token>>                           

Deactivate(i) ==
  /\ active[i]
  /\ active' = [active EXCEPT ![i] = FALSE]
  /\ UNCHANGED <<color, counter, pending, token>>

Environment == \E i \in Node : SendMsg(i) \/ RecvMsg(i) \/ Deactivate(i)

-----------------------------------------------------------------------------

Next ==
  System \/ Environment

Spec == Init /\ [][Next]_vars /\ WF_vars(System)

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

terminationDetected ==
  /\ token.pos = 0
  /\ token.color = "white"
  /\ token.q + counter[0] = 0
  /\ color[0] = "white"
  /\ ~ active[0]

Sum(f, S) == FoldFunctionOnSet(+, 0, f, S)

B == Sum(pending, Node)

Termination == 
  /\ \A i \in Node : ~ active[i]
  /\ B = 0

TerminationDetection ==
  terminationDetected => Termination

TD == INSTANCE AsyncTerminationDetection

=============================================================================

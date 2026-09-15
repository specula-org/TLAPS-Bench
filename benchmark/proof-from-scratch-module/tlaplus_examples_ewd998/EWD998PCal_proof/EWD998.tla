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

------------------------------------------------------------------------------
 
Init ==
   
  /\ active \in [Node -> BOOLEAN]
  /\ color \in [Node -> Color]
  
  /\ counter = [i \in Node |-> 0] 
  /\ pending = [i \in Node |-> 0]
  /\ token \in [ pos: Node, q: {0}, color: {"black"} ]

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

-----------------------------------------------------------------------------

terminationDetected ==
  /\ token.pos = 0
  /\ token.color = "white"
  /\ token.q + counter[0] = 0
  /\ color[0] = "white"
  /\ ~ active[0]

TD == INSTANCE AsyncTerminationDetection

=============================================================================

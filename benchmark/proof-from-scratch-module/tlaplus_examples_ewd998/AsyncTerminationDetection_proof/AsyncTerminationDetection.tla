---------------------- MODULE AsyncTerminationDetection ---------------------

EXTENDS Naturals
CONSTANT
  
  N
ASSUME NAssumption == N \in Nat \ {0}

Node == 0 .. N-1

VARIABLES 
  
  active,               
  
  pending,              
  
  terminationDetected   

terminated == \A n \in Node : ~ active[n] /\ pending[n] = 0

Init ==
  /\ active \in [Node -> BOOLEAN]
  /\ pending = [n \in Node |-> 0]
  /\ terminationDetected \in {FALSE, terminated}

Terminate(i) ==  
  /\ active[i]
  /\ active' = [active EXCEPT ![i] = FALSE]
  /\ pending' = pending
     
  /\ terminationDetected' \in {terminationDetected, terminated'}

SendMsg(i,j) ==  
  /\ active[i]
  /\ pending' = [pending EXCEPT ![j] = @ + 1]
  /\ UNCHANGED <<active, terminationDetected>>

RcvMsg(i) == 
  /\ pending[i] > 0
  /\ active' = [active EXCEPT ![i] = TRUE]
  /\ pending' = [pending EXCEPT ![i] = @ - 1]
  /\ UNCHANGED terminationDetected

DetectTermination ==
  /\ terminated
  /\ terminationDetected' = TRUE
  /\ UNCHANGED <<active, pending>>

Next ==
  \/ \E i \in Node : RcvMsg(i) \/ Terminate(i)
  \/ \E i,j \in Node : SendMsg(i,j)
  \/ DetectTermination

vars == <<active, pending, terminationDetected>>
Spec == /\ Init /\ [][Next]_vars
        /\ WF_vars(DetectTermination)

Safe == terminationDetected => terminated

Quiescence == [](terminated => []terminated)

Live == terminated ~> terminationDetected

=============================================================================


---------------------- MODULE AsyncTerminationDetection ---------------------

EXTENDS Naturals
CONSTANT
  
  N
ASSUME NAssumption == N \in Nat \ {0}

VARIABLES 
  
  active,               
  
  pending,              
  
  terminationDetected   

=============================================================================


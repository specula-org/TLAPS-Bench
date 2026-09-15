---------------------------- MODULE Reachability ----------------------------

EXTENDS Integers, Sequences, FiniteSets

CONSTANTS Nodes,  Succ
ASSUME SuccAssump == Succ \in [Nodes -> SUBSET Nodes]

IsPathFromTo(p, m, n) == 
       /\ Len(p) > 0
       /\ (p[1] = m) /\ (p[Len(p)] = n)  
       /\ \A i \in 1..(Len(p)-1) : p[i+1] \in Succ[p[i]]   

ExistsPath(m, n) == 
   \E p \in Seq(Nodes) : IsPathFromTo(p, m, n)
                      
ReachableFrom(S) == 
   {n \in Nodes : \E m \in S : ExistsPath(m, n)}
-----------------------------------------------------------------------------

=============================================================================


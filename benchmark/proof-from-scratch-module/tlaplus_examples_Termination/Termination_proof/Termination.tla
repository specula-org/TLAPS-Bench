------------------------ MODULE Termination ------------------------

EXTENDS Integers

CONSTANT P

VARIABLES
    
    s,
    
    r,
    
    ds,
    
    dr,
    
    visited,
    
    terminated

NumPending(p, q) ==
    s[<<p,q>>] - r[<<p,q>>]

Safety == terminated => \A p,q \in P : NumPending(p,q) = 0

Init ==
    /\ s \in [P\times P -> Int]
    /\ \E pq \in P\times P :
        /\ s[pq] = 1
        /\ \A rs \in P\times P : rs # pq => s[rs] = 0
    /\ r = [pq \in P\times P |-> 0] 
    
    /\ ds = [pq \in P\times P |-> 0]
    /\ dr = [pq \in P\times P |-> 0]
    /\ visited = {}
    /\ terminated = FALSE

process(self) ==
  /\ \E p \in P \ {self} : 
      /\ NumPending(p,self) > 0
      /\ r' = [r EXCEPT ![<<p,self>>] =  @ + 1]
  /\ \E Q \in SUBSET (P \ {self}): 
     /\ s' = [t \in P\times P |->
          IF t[1] = self /\ t[2] \in Q THEN s[t]+1 ELSE s[t]]
  /\ UNCHANGED << ds, dr, visited, terminated >>

Consistent(Q) ==
  \A p,q \in Q : ds[<<p,q>>] = dr[<<p,q>>]
daemon ==
        /\ IF visited # P \/ \neg Consistent(P)
              THEN /\ \E p \in P: 
                        /\ ds' = [t \in P\times P |-> IF t[1] = p THEN s[t] ELSE ds[t]]
                        /\ dr' = [t \in P\times P |-> IF t[2] = p THEN r[t] ELSE dr[t]]
                        /\ visited' = (visited \union {p})
                        /\ UNCHANGED terminated
              ELSE /\ terminated' = TRUE 
                   /\ UNCHANGED << ds, dr, visited >>
        /\ UNCHANGED << s, r >>

Next == daemon \/ (\E p \in P : process(p))

vars == << s, r, ds, dr, visited, terminated >>
Spec == Init /\ [][Next]_vars

=============================================================================

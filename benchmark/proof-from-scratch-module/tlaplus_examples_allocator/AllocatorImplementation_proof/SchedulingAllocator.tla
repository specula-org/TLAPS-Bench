------------------------ MODULE SchedulingAllocator ---------------------

EXTENDS FiniteSets, Sequences, Naturals, TLC

CONSTANTS
  Clients,     
  Resources    

ASSUME SchedulingAllocatorAssumptions ==
  IsFiniteSet(Resources)

VARIABLES
  unsat,       
  alloc,       
  sched        

TypeInvariant ==
  /\ unsat \in [Clients -> SUBSET Resources]
  /\ alloc \in [Clients -> SUBSET Resources]
  /\ sched \in Seq(Clients)

-------------------------------------------------------------------------

PermSeqs(S) ==
  LET perms[ss \in SUBSET S] ==
       IF ss = {} THEN { << >> }
       ELSE LET ps == [ x \in ss |-> 
                        { Append(sq,x) : sq \in perms[ss \ {x}] } ]
            IN  UNION { ps[x] : x \in ss }
  IN  perms[S]

Drop(seq,i) == SubSeq(seq, 1, i-1) \circ SubSeq(seq, i+1, Len(seq))

available == Resources \ (UNION {alloc[c] : c \in Clients})

Range(f) == { f[x] : x \in DOMAIN f }

toSchedule == { c \in Clients : unsat[c] # {} /\ c \notin Range(sched) }

Init == 
  /\ unsat = [c \in Clients |-> {}]
  /\ alloc = [c \in Clients |-> {}]
  /\ sched = << >>

Allocate(c,S) ==
  /\ S # {} /\ S \subseteq available \cap unsat[c]
  /\ \E i \in DOMAIN sched :
        /\ sched[i] = c
        /\ \A j \in 1..i-1 : unsat[sched[j]] \cap S = {}
        /\ sched' = IF S = unsat[c] THEN Drop(sched,i) ELSE sched
  /\ alloc' = [alloc EXCEPT ![c] = @ \cup S]
  /\ unsat' = [unsat EXCEPT ![c] = @ \ S]

Schedule == 
  /\ toSchedule # {}
  /\ \E sq \in PermSeqs(toSchedule) : sched' = sched \circ sq
  /\ UNCHANGED <<unsat,alloc>>

-------------------------------------------------------------------------

-------------------------------------------------------------------------

-------------------------------------------------------------------------

=========================================================================

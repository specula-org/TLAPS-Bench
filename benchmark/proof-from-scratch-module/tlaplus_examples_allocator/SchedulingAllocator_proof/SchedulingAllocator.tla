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

Request(c,S) ==
  /\ unsat[c] = {} /\ alloc[c] = {}
  /\ S # {} /\ unsat' = [unsat EXCEPT ![c] = S]
  /\ UNCHANGED <<alloc,sched>>

Allocate(c,S) ==
  /\ S # {} /\ S \subseteq available \cap unsat[c]
  /\ \E i \in DOMAIN sched :
        /\ sched[i] = c
        /\ \A j \in 1..i-1 : unsat[sched[j]] \cap S = {}
        /\ sched' = IF S = unsat[c] THEN Drop(sched,i) ELSE sched
  /\ alloc' = [alloc EXCEPT ![c] = @ \cup S]
  /\ unsat' = [unsat EXCEPT ![c] = @ \ S]

Return(c,S) ==
  /\ S # {} /\ S \subseteq alloc[c]
  /\ alloc' = [alloc EXCEPT ![c] = @ \ S]
  /\ UNCHANGED <<unsat,sched>>

Schedule == 
  /\ toSchedule # {}
  /\ \E sq \in PermSeqs(toSchedule) : sched' = sched \circ sq
  /\ UNCHANGED <<unsat,alloc>>

Next ==
  \/ \E c \in Clients, S \in SUBSET Resources :
        Request(c,S) \/ Allocate(c,S) \/ Return(c,S)
  \/ Schedule

vars == <<unsat,alloc,sched>>

-------------------------------------------------------------------------

Liveness ==
  /\ \A c \in Clients : WF_vars(unsat[c]={} /\ Return(c,alloc[c]))
  /\ \A c \in Clients : WF_vars(\E S \in SUBSET Resources : Allocate(c, S))
  /\ WF_vars(Schedule)

Allocator == Init /\ [][Next]_vars /\ Liveness

-------------------------------------------------------------------------

ResourceMutex ==   
  \A c1,c2 \in Clients : c1 # c2 => alloc[c1] \cap alloc[c2] = {}

-------------------------------------------------------------------------

=========================================================================

----------------------------- MODULE Disruptor_SPMCModel ------------------------

EXTENDS Integers, FiniteSets, Sequences

CONSTANTS
  Writers,      
  Readers,      
  Size,         
  NULL

ASSUME ExactlyOneWriter       == IsFiniteSet(Writers) /\ Cardinality(Writers) = 1
ASSUME AtLeastOneReader       == Readers /= {}
ASSUME SizeIsPositive         == Size \in Nat \ {0}

ASSUME WritersReadersDisjoint == Writers \cap Readers = {}

VARIABLES
  ringbuffer,
  published,    
  read,         
  pc,           
  consumed      

vars == <<
  ringbuffer,
  published,
  read,
  consumed,
  pc
>>

Access  == "Access"
Advance == "Advance"

Transition(t, from, to) ==
  /\ pc[t] = from
  /\ pc'   = [ pc EXCEPT ![t] = to ]

Buffer == INSTANCE RingBuffer WITH Values <- Int

Range(f) ==
  { f[x] : x \in DOMAIN(f) }

MinReadSequence ==
  CHOOSE min \in Range(read) : \A r \in Readers : min <= read[r]

BeginWrite(writer) ==
  LET
    next     == published + 1
    index    == Buffer!IndexOf(next)
    min_read == MinReadSequence
  IN
    
    /\ min_read >= next - Size
    /\ Transition(writer, Advance, Access)
    /\ Buffer!Write(index, writer, next)
    /\ UNCHANGED << consumed, published, read >>

EndWrite(writer) ==
  LET
    next  == published + 1
    index == Buffer!IndexOf(next)
  IN
    /\ Transition(writer, Access, Advance)
    /\ Buffer!EndWrite(index, writer)
    /\ published' = next
    /\ UNCHANGED << consumed, read >>

BeginRead(reader) ==
  LET
    next  == read[reader] + 1
    index == Buffer!IndexOf(next)
  IN
    /\ published >= next
    /\ Transition(reader, Advance, Access)
    /\ Buffer!BeginRead(index, reader)
    
    /\ consumed' = [ consumed EXCEPT ![reader] = Append(@, Buffer!Read(index)) ]
    /\ UNCHANGED << published, read >>

EndRead(reader) ==
  LET
    next  == read[reader] + 1
    index == Buffer!IndexOf(next)
  IN
    /\ Transition(reader, Access, Advance)
    /\ Buffer!EndRead(index, reader)
    /\ read' = [ read EXCEPT ![reader] = next ]
    /\ UNCHANGED << consumed, published >>

Init ==
  /\ Buffer!Init
  /\ published = -1
  /\ read      = [ r \in Readers                |-> -1      ]
  /\ consumed  = [ r \in Readers                |-> << >>   ]
  /\ pc        = [ a \in Writers \union Readers |-> Advance ]

Next ==
  \/ \E w \in Writers : BeginWrite(w)
  \/ \E w \in Writers : EndWrite(w)
  \/ \E r \in Readers : BeginRead(r)
  \/ \E r \in Readers : EndRead(r)

Fairness ==
  /\ \A r \in Readers : WF_vars(BeginRead(r))
  /\ \A r \in Readers : WF_vars(EndRead(r))

Spec ==
  Init /\ [][Next]_vars /\ Fairness

=============================================================================

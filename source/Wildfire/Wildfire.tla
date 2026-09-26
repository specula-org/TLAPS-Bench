
----------------------------- MODULE Wildfire -------------------------------

(***************************************************************************)
(*                                                                         *)
(* Repaired benchmark version. See README.md and repairs.patch for changes. *)
(*                                                                         *)
(* FOR DETAILS, SEE                                                        *)
(*   http://www.research.digital.com/SRC/tla/wildfire-challenge.html       *)
(*                                                                         *)
(***************************************************************************)

(***************************************************************************)
(* This module describes the Wildfire cached-coherence algorithm.          *)
(* Wildfire is a NUMA (Non-Uniform Memory Access) multiprocessor.  It      *)
(* consists of a network of processors and memories connected to local     *)
(* switches, which are in turn connected to a single global switch as      *)
(* follows:                                                                *)
(*                                                                         *)
(*         -----------          --------                                   *)
(*        | Processor |--.     | Memory |                                  *)
(*         -----------    \     --------                                   *)
(*                         |       |                                       *)
(*              .          |    --------                                   *)
(*                          `--| Local  |                                  *)
(*              .              |        |--.                               *)
(*                          .--| Switch |   \                              *)
(*              .          |    --------     |                             *)
(*                         |                 |                             *)
(*         -----------    /                  |                             *)
(*        | Processor |--'                   |                             *)
(*         -----------                       |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*                                 .         |       --------              *)
(*                                            `-----| Global |             *)
(*                                 .                |        |             *)
(*                                            .-----| Switch |             *)
(*                                 .         |       --------              *)
(*                                           |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*                                           |                             *)
(*         -----------                       |                             *)
(*        | Processor |--.                   |                             *)
(*         -----------    \                  |                             *)
(*                         |                 |                             *)
(*              .          |    --------     |                             *)
(*                          `--| Local  |   /                              *)
(*              .              |        |--'                               *)
(*                          .--| Switch |                                  *)
(*              .          |    --------                                   *)
(*                         |       |                                       *)
(*         -----------    /     --------                                   *)
(*        | Processor |--'     | Memory |                                  *)
(*         -----------          --------                                   *)
(*                                                                         *)
(*                                                                         *)
(*                                                                         *)
(* There is a single space of memory addresses partitioned among the local *)
(* switches.  That is, each memory address belongs to the memory attached  *)
(* to a single local switch.  Each processor has a local cache that        *)
(* contains copies of some memory addresses.  The cache-coherence          *)
(* algorithm is directory based.  A local switch maintains a directory     *)
(* entry for each address belonging to it.  That entry contains            *)
(* information about which processors currently have a copy of the address *)
(* in their local caches.                                                  *)
(*                                                                         *)
(* To load an address into its cache, or to upgrade the status of an       *)
(* address in its cache from read-only to writable, the processor must     *)
(* send a message to the local switch to which the address belongs.        *)
(* Thus, if a processor attached to one local switch wants to access a     *)
(* word in the memory attached to a different local switch, it must send   *)
(* a message to its local switch, which relays the message to the global   *)
(* switch, which in turn relays it to the other local switch, which can    *)
(* then access the memory.                                                 *)
(*                                                                         *)
(* The complexity of the algorithm results from two design choices:        *)
(*                                                                         *)
(*  - If a memory address is accessed only by processors on the same       *)
(*    local switch, then no messages should be sent to the global switch.  *)
(*                                                                         *)
(*  - To minimize processor delays, data is sent directly to               *)
(*    the requesting processor, and the processor should wait              *)
(*    only when absolutely necessary.                                      *)
(*                                                                         *)
(* Each line in the picture connecting a processor and a local switch, and *)
(* connecting a local switch with the global switch, represents a pair of  *)
(* message queues (one for messages in each direction).  These queues are  *)
(* not FIFO; messages in the queues are subject to ordering relations      *)
(* described in the specification.                                         *)
(*                                                                         *)
(* All request and control messages travel in these message queues.        *)
(* There is also a special class of messages called Fills that carry the   *)
(* actual data values read by a processor.  Fills travel on a logically    *)
(* separate network.  When we use the term "message", we exclude Fills.    *)
(*                                                                         *)
(* Here is a brief sketch of how the algorithm works.  An entry            *)
(* in a processor's cache can be in one of the following states:           *)
(*                                                                         *)
(* Exclusive   : This is the primary copy of the data.  The processor      *)
(*               can read or write it.                                     *)
(*                                                                         *)
(* SharedClean : The copy is a secondary, read-only copy.  The primary     *)
(*               copy is elsewhere--either in memory or in another         *)
(*               processor's cache.                                        *)
(*                                                                         *)
(* SharedDirty : This is the primary copy of the data, but it is           *)
(*               read-only.  (The state was previously Exclusive, and      *)
(*               then some other processor requested a read-only copy.)    *)
(*                                                                         *)
(* Invalid : The cache does not contain any copy of the data.              *)
(*                                                                         *)
(* Suppose processor p wants to write an address a that is not in its      *)
(* cache.  It sends a request to the "directory"--that is, to the local    *)
(* switch that contains memory address a and a's directory entry.          *)
(* Suppose no other processor has a copy.  The directory sends a           *)
(* FillMarker control message back to the processor and changes a's        *)
(* directory entry to indicate that p is the owner.  It also sends p a     *)
(* Fill (by a logically separate route) with the data.  The write can be   *)
(* completed as soon as the Fill arrives (which might be before the        *)
(* FillMarker arrives).                                                    *)
(*                                                                         *)
(* Now suppose another processor q wants a read-only copy of a.            *)
(* Processor q sends a request to the directory.  The local switch         *)
(* records in a's directory entry that q has a read-only copy.  It sends   *)
(* a FillMarker back to q, and it sends a ForwardedGet message to p.       *)
(* When p receives the ForwardedGet, it changes its copy to SharedDirty    *)
(* and sends a Fill to q containing the data.  Processor q can perform     *)
(* its read operation as soon as it receives the Fill.                     *)
(*                                                                         *)
(* Now suppose that a third processor r wants an exclusive copy of a.  It  *)
(* sends its request to the local switch containing address a, which       *)
(* changes a's directory entry to indicate that r is the current writer,   *)
(* and sends the following messages:                                       *)
(*   - A FillMarker to r.                                                  *)
(*   - A ForwardedGet to p.  When p receives the ForwardedGet, it          *)
(*     sends a Fill to r with the data and invalidates its cache entry.    *)
(*     (A field in the message distinguishes it from a ForwardedGet        *)
(*     for a read-only  copy.)                                             *)
(*   - An Inval (invalidate) message to q, causing q to invalidate         *)
(*     its cache entry.                                                    *)
(*                                                                         *)
(* Note that a processor need not wait for the FillMarker message when     *)
(* performing the operation.  The precise role of the FillMarker can be    *)
(* understood only by studying the algorithm in detail.                    *)
(*                                                                         *)
(* Suppose a processor p that has a shared copy of an address a in its     *)
(* cache wants to write to a.  It tries to upgrade its copy to executable  *)
(* by sending a ChangeToExclusive request to the directory.  The request   *)
(* will fail if the copy in p's cache is obsolete.  The directory          *)
(* responds to the request with a ChangeToExclusiveAck message that        *)
(* indicates whether the request succeeded.  If it didn't, then p will     *)
(* have received an Inval before the ChangeToExclusiveAck message          *)
(* arrives.  When the ChangeToExclusiveAck does arrive, p will issue a     *)
(* request for an exclusive copy, just as if it never had a copy in its    *)
(* cache.                                                                  *)
(*                                                                         *)
(* A processor may, at any time, evict an address from its cache--that     *)
(* is, make the cache line invalid.  If it has the primary copy in its     *)
(* cache, then it sends that copy back to the memory with a Victim         *)
(* message.  It receives a VictimAck message in response when the data     *)
(* have been written back to memory.  (It must keep a copy of the data     *)
(* until it receives that VictimAck, since it could receive a              *)
(* ForwardedGet requesting the data.)                                      *)
(*                                                                         *)
(* When a request from a processor p is received at the directory, a       *)
(* Comsig message is sent back to p.  That message is usually bundled      *)
(* together with the FillMarker or ChangeToExclusiveAck.  An MB (Memory    *)
(* Barrier) instruction can be retired, and subsequent instructions        *)
(* issued, when there are no outstanding Comsigs for any instructions      *)
(* that preceded the MB.                                                   *)
(*                                                                         *)
(* ---------                                                               *)
(*                                                                         *)
(* This short sketch will give you enough of an idea of what the algorithm *)
(* does to enable you to understand the specification.  There are many     *)
(* subtle details that will become apparent only by reading the            *)
(* specification.  One of the more subtle of these has to do with a        *)
(* procedure called "shadowing".  Suppose processor p accesses a local     *)
(* address a--that is an address a that belongs to the same local switch   *)
(* as the processor.  One would expect that messages would simply go       *)
(* directly between p and its local switch.  That's the case if all        *)
(* accesses to a are local, from processors attached to the same local     *)
(* switch.  However, if a processor attached to a different local switch   *)
(* has a copy of a, then the message that the local switch sends to p may  *)
(* be sent to the global switch, from which it bounces back to the local   *)
(* switch and then goes to p.  This process of looping a message from a    *)
(* local switch to one of its attached processors via the global switch is *)
(* called shadowing.  The specification describes precisely when this is   *)
(* done.                                                                   *)
(*                                                                         *)
(* ---------                                                               *)
(*                                                                         *)
(* This specification describes a high-level algorithm that is much more   *)
(* abstract than the algorithm actually used in Wildfire.  A number of     *)
(* simplifications have been made.  Here is a list of the most important.  *)
(* You may want to skip over this list until you have read the complete    *)
(* specification.                                                          *)
(*                                                                         *)
(* - In our specification, the directory records which processors have     *)
(* read-only copies.  In Wildfire, the directory indicates only which      *)
(* local switch has processors with read-only copies.  The local switch    *)
(* maintains a data structure called the DTag table that records the state *)
(* of the caches of each of its processors.  It uses this table to route   *)
(* Inval messages to the appropriate processors.  However, Wildfire uses a *)
(* direct-mapped cache, meaning that each memory address corresponds to a  *)
(* particular physical cache line.  The DTag table records the state of    *)
(* the physical cache line, but not what address is actually in the cache  *)
(* line.  Moreover, message delays mean that the information in the table  *)
(* may not be current.  All this makes deciding what processors are to     *)
(* receive an Inval for a particular address quite subtle.  Eliminating    *)
(* this aspect of the system probably cuts the length of the specification *)
(* in half.                                                                *)
(*                                                                         *)
(* - Our specification allows a single processor to have outstanding       *)
(* FillMarker messages for an unbounded number of requests to the same     *)
(* address.  The implementation constrains the processing of requests to   *)
(* make it impossible for there to be more than two such outstanding       *)
(* messages.                                                               *)
(*                                                                         *)
(* - In our specification, when a processor evicts the primary copy of an  *)
(* address from the cache, it sends a Victim to the directory and keeps a  *)
(* copy of the data until receiving the VictimAck message.  In the         *)
(* implementation, remote victims (ones whose directory is on a different  *)
(* local switch than the processor) are relayed from the processor to its  *)
(* local switch and then to the directory, with appropriate                *)
(* acknowledgments.                                                        *)
(*                                                                         *)
(* - Various data structures used to keep track of outstanding messages    *)
(* have been eliminated.  Instead, we make certain actions taken by the    *)
(* local switch and by the processor depend on parts of the state          *)
(* external those components--namely, on what messages are in transit.     *)
(* In all these cases, adding the data structures to make those decisions  *)
(* local is straightforward.                                               *)
(***************************************************************************)


EXTENDS AlphaInterface, AlphaConstants, Naturals, Sequences, FiniteSets

-----------------------------------------------------------------------------

(***************************************************************************)
(*                            MISCELLANY                                   *)
(*                                                                         *)
(* We now define an operator sequences that we need for the specification. *)
(***************************************************************************)

SeqMinusItem(q, idx) ==
  (*************************************************************************)
  (* If q is a sequence of elements and idx is a natural number, then this *)
  (* is the sequence obtained by removing the idx-th element of q.  (If q  *)
  (* has no idx-th element, then SeqMinusItem(q, idx) equals q, but we     *)
  (* don't really care about that.)                                        *)
  (*                                                                       *)
  (* The operator SubSeq is defined in the Sequences module so that, if    *)
  (* seq is a sequence, then SubsSeq(seq, i, j) is the subsequence of seq  *)
  (* consisting of its i-th through j-th elements.  If j < i, then it      *)
  (* equals the empty sequence.                                            *)
  (*************************************************************************)
  SubSeq(q, 1, idx-1) \o SubSeq(q, idx+1, Len(q))

-----------------------------------------------------------------------------

(***************************************************************************)
(*                CONSTANT DECLARATIONS AND CONSTANT OPERATORS             *)
(***************************************************************************)

CONSTANTS
  LS,
    (***********************************************************************)
    (* This is the set of local switches.  (More precisely, it is a set of *)
    (* arbitrary identifiers that represent the local switches.)           *)
    (***********************************************************************)

  ProcLS(_),
    (***********************************************************************)
    (* ProcLS(p) is processor p's local switch--that is, the local switch  *)
    (* to which p is connected.                                            *)
    (***********************************************************************)

  AdrLS(_),
    (***********************************************************************)
    (* AdrLS(a) is the local switch whose attached memory contains memory  *)
    (* address a.                                                          *)
    (***********************************************************************)

  InitMem
    (***********************************************************************)
    (* The initial contents of memory.                                     *)
    (***********************************************************************)

ASSUME DisjointNodes == Proc \cap LS = { }
  (*************************************************************************)
  (* We assume that the sets Proc and LS are disjoint.  This allows us to  *)
  (* define the destination of a message to be a Proc or an LS, and to     *)
  (* know that if the destination of the message is a Proc, then its       *)
  (* destination is not an LS.                                             *)
  (*************************************************************************)

ASSUME NaturalDataLen == DataLen \in Nat

ASSUME InitialMemory == InitMem \in [Adr -> Data]

ASSUME ProcessorHomes == \A p \in Proc : ProcLS(p) \in LS
ASSUME AddressHomes == \A a \in Adr : AdrLS(a) \in LS

InMemory == CHOOSE m : m \notin Proc
  (*************************************************************************)
  (* A value that is not a processor.  We use it as the value of the       *)
  (* `writer' field of an address's directory entry, to indicate that      *)
  (* there is no `writer' processor and the memory has the current value.  *)
  (*************************************************************************)

Unlocked == CHOOSE u : u \notin Adr
  (*************************************************************************)
  (* A value that is not an address.  See the description of the variable  *)
  (* `locked' below to see how this value is used.                         *)
  (*************************************************************************)

InvalidData == CHOOSE d : d \notin Data
  (*************************************************************************)
  (* A value that is not in Data.  It is used when creating a new          *)
  (* cache-line version with invalid data.                                 *)
  (*************************************************************************)

CacheVersionEntry ==
  (*************************************************************************)
  (* A cache entry can record multiple versions of a data value for an     *)
  (* address.  Recall that, after evicting a primary copy from the cache,  *)
  (* the processor must keep the data around to respond to a possible      *)
  (* ForwardedGet message.  It could, in the meantime, have requested and  *)
  (* even received another copy of the data.  Moreover, even when the      *)
  (* processor evicts a clean copy, it may need to keep that version       *)
  (* around (although not with the actual data) so it can respond properly *)
  (* to Inval messages.                                                    *)
  (*                                                                       *)
  (* A CacheVersionEntry is a record that defines the cache state          *)
  (* information associated with a specific version of an address (and not *)
  (* with the address itself).                                             *)
  (*************************************************************************)
  [ data : Data \cup {InvalidData},
    fillMarkerPending : BOOLEAN,
      (*********************************************************************)
      (* True iff the FillMarker for this version has not yet arrived.     *)
      (*********************************************************************)
    victimAckPending  : BOOLEAN  ]
      (*********************************************************************)
      (* True iff the version was evicted and a Victim message was sent to *)
      (* the directory, but the VictimAck has not returned.                *)
      (*********************************************************************)

CacheEntry ==
  (*************************************************************************)
  (* The set of possible cache entries for a particular address in a       *)
  (* processor's cache.  The versions field is a sequence of versions      *)
  (* listed from oldest to newest.                                         *)
  (*************************************************************************)
  [ state : {"Exclusive", "SharedClean", "SharedDirty", "Invalid"},
    fillOrCTEAckPending : BOOLEAN,
      (*********************************************************************)
      (* True iff a request was issued for this address and its Fill or    *)
      (* ChangeToExclusiveAck message has not arrived.                     *)
      (*********************************************************************)
    version : Seq(CacheVersionEntry) ]

MemDirEntry ==
  (*************************************************************************)
  (* The set of values that can represent the memory and directory entries *)
  (* for an address.                                                       *)
  (*************************************************************************)
  [ data    : Data,
      (*********************************************************************)
      (* The value for this address in the memory.                         *)
      (*********************************************************************)
    writer  : Proc \cup {InMemory},
      (*********************************************************************)
      (* The processor currently granted exclusive access to this address, *)
      (* or InMemory, in which case the current value for this address is  *)
      (* in memory.                                                        *)
      (*                                                                   *)
      (* If the writer is a processor p, then the current value for this   *)
      (* address is in one of the following places, possibly in transit in *)
      (* one of the messages defined in the next section:                  *)
      (*    - p's cache.                                                   *)
      (*    - in a Fill message in fillQ[p],                               *)
      (*    - in a Victim message in transit from p to the address's       *)
      (*      home LS.                                                     *)
      (*    - in the cache of a processor q with a ForwardedGet message in *)
      (*      transit to q asking q to send an exclusive copy to p.        *)
      (*********************************************************************)
    readers : SUBSET Proc]
      (*********************************************************************)
      (* The set of processors that have been granted shared access to     *)
      (* this address.                                                     *)
      (*                                                                   *)
      (* For each processor p in this set, either p has a copy of the data *)
      (* in its cache, or there is a ForwardedGet in transit to the writer *)
      (* asking the writer to send a copy of the data to p, or there is a  *)
      (* Fill in transit to p with a copy of the data, or p has evicted    *)
      (* the copy.                                                         *)
      (*********************************************************************)

-----------------------------------------------------------------------------

(***************************************************************************)
(*                             MESSAGES                                    *)
(*                                                                         *)
(* We now define sets of messages, and some operators on messages.  These  *)
(* are all constants and constant operators.                               *)
(*                                                                         *)
(* Here are the meanings of the various fields of a message.  (Not all     *)
(* messages have all of these fields.)                                     *)
(*                                                                         *)
(* type  : The type of the message (a string).                             *)
(*                                                                         *)
(* cmdr  : A processor.  If the message was sent by a processor then       *)
(*         this is the processor.  Otherwise, it is the processor that     *)
(*         issued the command that produced the message.                   *)
(*                                                                         *)
(* state : A message with this field is the result of a read or write      *)
(*         request.  The value of this field is "Shared" if it is was a    *)
(*         read and "Exclusive" if it was a write.  (This is the state     *)
(*         that the cmdr's cache will have when the operation              *)
(*         is executed.)                                                   *)
(*                                                                         *)
(* adr   : The relevant memory address.                                    *)
(*                                                                         *)
(* dest  : A processor.  It is the destination of the message, when that   *)
(*         destination is not the cmdr.                                    *)
(*                                                                         *)
(* Messages are classified as either Q0 or Q1 messages.                    *)
(***************************************************************************)

(***************************************************************************)
(* Q0 Messages                                                             *)
(* -----------                                                             *)
(* Q0 messages are ones sent from the processor to the directory.  They    *)
(* are the request messages and Victim messages.                           *)
(***************************************************************************)

GetShared ==
  [type : {"GetShared"},
   cmdr : Proc,
   adr  : Adr]

GetExclusive ==
  [type : {"GetExclusive"},
   cmdr : Proc,
   adr  : Adr]

ChangeToExclusive ==
  [type : {"ChangeToExclusive"},
   cmdr  : Proc,
   adr   : Adr]

Victim ==
  (*************************************************************************)
  (* When a processor cmdr evicts a primary copy from its cache, it sends  *)
  (* a Victim message to the directory with the data value for this        *)
  (* address.                                                              *)
  (*************************************************************************)
  [type : {"Victim"},
   cmdr  : Proc,
   adr   : Adr,
   data  : Data]

(***************************************************************************)
(* Q1 Messages                                                             *)
(* -----------                                                             *)
(* Q1 messages are ones sent by a local switch--most of them to a          *)
(* processor, but some of them to itself via the global switch.            *)
(***************************************************************************)

ForwardedGet ==
  (*************************************************************************)
  (* When a processor cmdr issues a command to the directory for an        *)
  (* address adr whose current value is not in memory, the directory sends *)
  (* a ForwardedGet to the current writer instructing the writer to send a *)
  (* copy to cmdr.  The dest field names the current writer.               *)
  (*************************************************************************)
  [type  : {"ForwardedGet"},
   state : {"Shared", "Exclusive"},
   cmdr  : Proc,
   dest  : Proc,
   adr   : Adr]

ChangeToExclusiveAck ==
  (*************************************************************************)
  (* When a processor cmdr wants to write to an address adr that is        *)
  (* currently in its cache in "Shared" state, it issues a command to the  *)
  (* directory and receives a ChangeToExclusiveAck message in reply.       *)
  (*************************************************************************)
  [type : {"ChangeToExclusiveAck"},
   cmdr : Proc,
   adr  : Adr,
   success : BOOLEAN ]

Inval ==
  (*************************************************************************)
  (* When a processor cmdr issues a command to the directory for an        *)
  (* address adr requiring the directory to invalidate a copy of this      *)
  (* address in another processor dest's cache, the directory sends an     *)
  (* Inval message to processor dest to tell it that the data in its cache *)
  (* are stale and its cache entry should be made invalid.                 *)
  (*************************************************************************)
  [type : {"Inval"},
   cmdr  : Proc,
   dest  : Proc,
   adr   : Adr]

VictimAck ==
  (*************************************************************************)
  (* This is the response to a Victim message from processor cmdr for      *)
  (* address adr.  It is sent from the directory when the Victim message   *)
  (* is received.                                                          *)
  (*************************************************************************)
  [type : {"VictimAck"},
   cmdr  : Proc,
   adr   : Adr]

FillMarker ==
  (*************************************************************************)
  (* This message is sent in response to a GetShared or GetExclusive       *)
  (* request.                                                              *)
  (*************************************************************************)
  [type : {"FillMarker"},
   cmdr  : Proc,
   adr   : Adr]

ShadowClear ==
  (*************************************************************************)
  (* This message is sent from the local switch to itself via the global   *)
  (* switch.  It usually accompanies a message sent via the global switch  *)
  (* to a processor on another local switch.  A memory address adr that    *)
  (* resides at a local switch is in SHADOW MODE while there is a          *)
  (* ShadowClear message for that address in transit.                      *)
  (*************************************************************************)
  [type : {"ShadowClear"},
   cmdr  : Proc,
   adr   : Adr]

ComsigClear ==
  (*************************************************************************)
  (* This is another class of message that is sent from the local switch   *)
  (* to itself via the global switch.  It always accompanies a Comsig      *)
  (* message.                                                              *)
  (*************************************************************************)
  [type : {"ComsigClear"},
   cmdr  : Proc,
   adr   : Adr]

Comsig ==
  (*************************************************************************)
  (* When a processor issues a directory command, the directory sends a    *)
  (* Comsig message back to the processor.  An MB request can be retired   *)
  (* when every request ahead of it has had its Comsig returned.  Since a  *)
  (* Comsig can return before the Fill, this means that an MB can be       *)
  (* retired before all operations ahead of it have actually completed.    *)
  (*************************************************************************)
  [type : {"Comsig"},
   cmdr  : Proc]


(***************************************************************************)
(* We now define Q0Message, Q1Message, and Message to be the sets of all   *)
(* possible Q0 messages, Q1 messages, and all messages, respectively.      *)
(*                                                                         *)
(* There is another class of messages that we talk about in the            *)
(* comments--namely, probes.  A probe is a ForwardedGet or an Inval        *)
(* message.                                                                *)
(***************************************************************************)
Q0Message == GetShared \cup GetExclusive \cup
             ChangeToExclusive \cup Victim

Q1Message == ForwardedGet \cup ChangeToExclusiveAck \cup Inval \cup
             VictimAck \cup FillMarker \cup ShadowClear \cup
             ComsigClear \cup Comsig

Message == Q0Message \cup Q1Message

MsgDestination(m) ==
  (*************************************************************************)
  (* Where message m is heading.  It is an LS for a Clear or Victim        *)
  (* message.  For any other message, if the message has a dest field,     *)
  (* then it is the dest processor, otherwise, it is the cmdr.             *)
  (*************************************************************************)
  IF m \in Q0Message \cup ShadowClear \cup ComsigClear
    THEN AdrLS(m.adr)
    ELSE  IF "dest" \in DOMAIN m  THEN m.dest
                                  ELSE m.cmdr

MustFollow(q, m1, m2) ==
  (*************************************************************************)
  (* This constant predicate defines the rules for when messages can move  *)
  (* ahead of other messages in the various queues.  MustFollow(q, m1, m2) *)
  (* is true iff, when message m1 follows m2 in queue type q, message m2   *)
  (* must be removed from the queue before m1--in other words, m1 must     *)
  (* follow m2 in the queue and may not jump ahead of m2.  The queue type  *)
  (* q must be one of the strings "ProcToLS", "LSToProc", "LSToGS", or     *)
  (* "GSToLS".  (See the declaration of the variable Q below.)             *)
  (*************************************************************************)

  \/ (**********************************************************************)
     (* A Comsig may not jump ahead of any probe.                          *)
     (*                                                                    *)
     (* Note: we could allow Comsigs to jump ahead of probes in the LS     *)
     (* to GS queue, but they will never actually jump because they will   *)
     (* be bundled with things like FillMarkers or Invals that must stay   *)
     (* in order.                                                          *)
     (**********************************************************************)
     /\ m1 \in Comsig
     /\ m2 \in Inval \cup ForwardedGet

  \/ (**********************************************************************)
     (* Q0 messages for the same address are ordered from processor to     *)
     (* directory                                                          *)
     (**********************************************************************)
     /\ m1 \in Q0Message
     /\ m2 \in Q0Message
     /\ m1.adr = m2.adr

  \/ (**********************************************************************)
     (* All Q1 messages are strictly ordered from GS to LS and from LS to  *)
     (* the processor.  Q1 messages for the same address are ordered       *)
     (* elsewhere (in LS to GS).                                           *)
     (*                                                                    *)
     (* Note: This only makes sense for non-comsigs, since comsigs don't   *)
     (* carry addresses.                                                   *)
     (**********************************************************************)
     /\ m1 \in Q1Message \ Comsig
     /\ m2 \in Q1Message \ Comsig
     /\ (q = "LSToGS") => (m1.adr = m2.adr)

  \/ (* A directory request cannot overtake an older probe from the GS. *)
     /\ q = "GSToLS"
     /\ m1 \in Q0Message
     /\ m2 \in Inval \cup ForwardedGet

-----------------------------------------------------------------------------

(***************************************************************************)
(*                                 FILLS                                   *)
(*                                                                         *)
(* A Fill is packet to a processor that carries data for the processor's   *)
(* cache, indicating the address, the value to insert into the processor's *)
(* cache for this address, and the state of this cache entry.  We          *)
(* distinguish between messages and Fills simply because they are          *)
(* delivered by different mechanisms.                                      *)
(***************************************************************************)
Fill ==
  [adr   : Adr,
   data  : Data,
   state : {"Shared", "Exclusive"} ]

-----------------------------------------------------------------------------

(***************************************************************************)
(*                              VARIABLES                                  *)
(*                                                                         *)
(* We now declare all variables--except for the interface variable aInt,   *)
(* whose declaration is imported from the AlphaInterface module.           *)
(***************************************************************************)
VARIABLES
  cache,
    (***********************************************************************)
    (* cache[p][a] is processor p's cache entry for address a.             *)
    (***********************************************************************)

  memDir,
    (***********************************************************************)
    (* memDir[a] is the state of the memory and directory entry for        *)
    (* address a.                                                          *)
    (***********************************************************************)

  Q,
    (***********************************************************************)
    (* Q is a record with four fields, where each field of the record is a *)
    (* function describing the queues going between the GS and the LSs and *)
    (* between the LSs and the Procs.  More precisely:                     *)
    (*                                                                     *)
    (*    Q.ProcToLS[p], Q.LSToProc[p] : the message queues joining        *)
    (*       processor p to its local switch.                              *)
    (*                                                                     *)
    (*    Q.LSToGS[ls], Q.GSToLS[ls] : the message queues joining local    *)
    (*       switch ls and the global switch.                              *)
    (*                                                                     *)
    (* Each of these queues is a sequence of SETS OF messages.  For        *)
    (* example, in response to a request from processor p, a local switch  *)
    (* may generate a Comsig message and a FillMarker message to p.  Those *)
    (* messages will travel together as part of the same message set,      *)
    (* possibly traveling across the global switch, and will reach p at    *)
    (* the same time.  Thus, what we call messages are really message      *)
    (* components that are combined into bundles--the message sets--and it *)
    (* is the message sets that travel in the queues.                      *)
    (*                                                                     *)
    (* Messages to different processors can also be combined into          *)
    (* messages sets.  For example, the request by p may also generate a   *)
    (* ForwardedGet message to the processor q that has the primary copy   *)
    (* and an Inval message to another processor r that has a read-only    *)
    (* copy.  All four messages--the two to p and the ones to q and        *)
    (* r--might be sent to the global switch.  In that case, they would    *)
    (* all be bundled together into a single message set and put into      *)
    (* Q.LSToGS[ls0] by local switch ls0.  Suppose p is on local switch    *)
    (* ls1 and q and r are on a different local switch ls2.  When that     *)
    (* message set reaches the global switch, it will be broken into two   *)
    (* different message sets--one to ls1 and the other to ls2.  When the  *)
    (* message set with the ForwadedGet and the Inval reaches ls2, it      *)
    (* will be split into two singleton message sets, which are sent to q  *)
    (* and to r.  The Comsig and the FillMarker will arrive at processor   *)
    (* p as a single message set.                                          *)
    (*                                                                     *)
    (* There are some messages that always travel alone, in singleton      *)
    (* sets--for example, Q0 messages and VictimAck messages.              *)
    (*                                                                     *)
    (* Although these queues are sequences of message sets, they are not   *)
    (* FIFO queues.  Message sets are appended to the end of the queue,    *)
    (* but they can be removed from anywhere in the queue--subject to      *)
    (* constraints described below.                                        *)
    (*                                                                     *)
    (* In TLA+, a record is a function whose domain is a set of strings.   *)
    (* Saying that r is a record with component foo means that it is a     *)
    (* function whose domain contains the string "foo"; r.foo is just an   *)
    (* abbreviation for r["foo"].  Thus Q is both a record with fields     *)
    (* ProcToLS, LSToProc, LSToGS and GSToLS components and a function     *)
    (* with domain {"ProcToLS", "LSToProc", "LSToGS", "GSToLS"}.           *)
    (***********************************************************************)

  fillQ,
    (***********************************************************************)
    (* For each processor p, fillQ[p] is the set of Fills in transit to p. *)
    (***********************************************************************)

  reqQ,
  respQ,
    (***********************************************************************)
    (* For each processor p, reqQ[p] is the queue of requests that have    *)
    (* come from the environment but have not been retired, and respQ[p]   *)
    (* is the queue of requests that have been retired but for which       *)
    (* responses to the environment have not yet been issued.  (A read or  *)
    (* write is retired when it is performed to the processor's cache.)    *)
    (***********************************************************************)

  locked
    (***********************************************************************)
    (* When an LL request is retired by processor p, locked[p] is set to   *)
    (* its address.  The value of locked[p] is reset to Unlocked when an   *)
    (* SC is retired, or when the cache entry is invalidated.  When        *)
    (* processor p retires an SC, the SC fails if its address is not equal *)
    (* to the value of locked[p].                                          *)
    (***********************************************************************)

(***************************************************************************)
(* We define two tuples of variables that will be handy.                   *)
(***************************************************************************)
procVars == <<cache, reqQ, respQ, locked>>
wVars    == <<cache, reqQ, respQ, locked, memDir, Q, fillQ, aInt>>

-----------------------------------------------------------------------------
(***************************************************************************)
(*                STATE FUNCTIONS AND STATE PREDICATES                     *)
(*                                                                         *)
(* We now define some useful state functions and state predicates.         *)
(***************************************************************************)

allQLocations ==
  (*************************************************************************)
  (* The set of all triples <<"qname", pl, idx>> such that idx is in       *)
  (* DOMAIN Q.qname[pl].  In other words, it is the set of all triples     *)
  (* <<q, pl, idx>> such that Q[q][pl][idx] is a message set.              *)
  (*************************************************************************)
  UNION { UNION { {<<q, pl, idx>> : idx \in DOMAIN Q[q][pl]}
                   : pl \in DOMAIN Q[q]} :
            q \in DOMAIN Q }

msgsInTransit ==
  (*************************************************************************)
  (* The set of all messages in transit.  In other words, the union of all *)
  (* message sets in transit.                                              *)
  (*************************************************************************)
  UNION {Q[loc[1]][loc[2]][loc[3]] : loc \in allQLocations}

msgsInQueue(q) ==
  (*************************************************************************)
  (* If q is a sequence of message sets, then this is the set of all       *)
  (* messages in that sequence.                                            *)
  (*************************************************************************)
  UNION {q[i] : i \in DOMAIN q}

msgsInLoop(adr, type) ==
  (*************************************************************************)
  (* The set of messages of the indicated type for address adr that are    *)
  (* going between the LS containing the directory entry for address adr   *)
  (* and the GS (in either direction).                                     *)
  (*************************************************************************)
  LET ls == AdrLS(adr)
  IN  {m \in msgsInQueue(Q.LSToGS[ls]) \cup msgsInQueue(Q.GSToLS[ls]) :
          (m.type = type) /\  (m.adr = adr)}

InShadowMode(adr) ==
  (*************************************************************************)
  (* As mentioned above, we say that an address is in shadow mode if there *)
  (* is a ShadowClear message for that address looping between the         *)
  (* address's local switch and the global switch.  When the address is in *)
  (* shadow mode, responses to requests for that address must go via the   *)
  (* global switch, even if their destination is a processor on the same   *)
  (* local switch as the memory address.                                   *)
  (*                                                                       *)
  (* Shadow mode has two functions.  One is to maintain cache              *)
  (* consistency--that is, to implement the Alpha memory specification.    *)
  (* The second is to avoid deadlock.  Without shadow mode, it would be    *)
  (* possible for the following scenario to occur.  Suppose that           *)
  (*                                                                       *)
  (*   - processors p1 and p3 and address a1 are on local switch ls1       *)
  (*   - processors p2 and p4 and address a2 are on local switch ls2       *)
  (*   - p1 has the primary copy of a2 in its cache                        *)
  (*   - p2 has the primary copy of a1 in its cache                        *)
  (*                                                                       *)
  (* so we have the following situation.                                   *)
  (*                                                                       *)
  (*         -----------          --------                                 *)
  (*        |    p1     |--.     |   a1   |                                *)
  (*         -----------    \     --------                                 *)
  (*            |a2|         |       |                                     *)
  (*             --          |    --------                                 *)
  (*                          `--|        |                                *)
  (*                             |  ls1   |--.                             *)
  (*                          .--|        |   \                            *)
  (*                         |    --------     |                           *)
  (*                         |                 |                           *)
  (*         -----------    /                  |                           *)
  (*        |    p3     |--'                   |                           *)
  (*         -----------                       |       --------            *)
  (*                                            `-----| Global |           *)
  (*                                                  |        |           *)
  (*                                            .-----| Switch |           *)
  (*         -----------                       |       -------             *)
  (*        |    p2     |--.                   |                           *)
  (*         -----------    \                  |                           *)
  (*            |a1|         |                 |                           *)
  (*             --          |    --------     |                           *)
  (*                          `--|        |   /                            *)
  (*                             |  ls2   |--'                             *)
  (*                          .--|        |                                *)
  (*                         |    --------                                 *)
  (*                         |       |                                     *)
  (*         -----------    /     --------                                 *)
  (*        |    p4     |--'     |   a2   |                                *)
  (*         -----------          --------                                 *)
  (*                                                                       *)
  (* Now the following actions occur:                                      *)
  (*                                                                       *)
  (*   - p1 issues a request for a copy of a1                              *)
  (*   + p1's request reaches the directory and sends a ForwardedGet       *)
  (*     FG(p1,a1) towards p2.                                             *)
  (*   - p2 issues a request for a copy of a2                              *)
  (*   + p2's request reaches the directory and sends a ForwardedGet       *)
  (*     FG(p2,a2) towards p1.                                             *)
  (*   - p3 issues a request for a copy of a1                              *)
  (*   * p3's request reaches the directory and generate a ForwardedGet    *)
  (*     FG(p3,a1) to p1, which (without shadowing) is put directly into   *)
  (*     Q.LSToProc[p1].                                                   *)
  (*   - p4 issues a request for a copy of a1                              *)
  (*   * p4's request reaches the directory and generate a ForwardedGet    *)
  (*     FG(p4,a2) to p2, which (without shadowing) is put directly into   *)
  (*     Q.LSToProc[p2].                                                   *)
  (*   - Lots of other, unrelated  messages enter LSToProc[p1] and         *)
  (*     LSToProc[p2]                                                      *)
  (*   - FG(p2,a2) reaches ls1 heading for p1                              *)
  (*   - FG(p1,a1) reaches ls2 heading for p2                              *)
  (*                                                                       *)
  (*                                                                       *)
  (* We have now reached the following situation, where the XXX's          *)
  (* denote some sequences of messages.                                     *)
  (*                                                                       *)
  (*         ----------                                                    *)
  (*        |    p1    |<--.FG(p3,a1)                                      *)
  (*         ----------     \                                              *)
  (*            |a2|         |XXX                                          *)
  (*             --          |    -------                                  *)
  (*                          `--|       |                                 *)
  (*                             |  ls1  |<--. FG(p2,a2)                   *)
  (*                             |       |    \                            *)
  (*                              -------                                  *)
  (*                                                                       *)
  (*                                                                       *)
  (*         ----------                                                    *)
  (*        |    p2    |<--. FG(p4,a2)                                     *)
  (*         ----------     \                                              *)
  (*            |a1|         |XXX                                          *)
  (*             --          |    -------                                  *)
  (*                          `--|       |    /                            *)
  (*                             |  ls2  |<--' FG(p1,a1)                   *)
  (*                             |       |                                 *)
  (*                              -------                                  *)
  (*                                                                       *)
  (* LSToProc[p1] now has FG(p3,a1) in LSToProc[p1], but p1 can't handle   *)
  (* it until FG(p2,a1) reaches p2, and p2 sends a copy of a1 back to p1.  *)
  (* Until that happens, FG(p3,a1) must sit in LSToProc[p1].  Similarly,   *)
  (* LSToProc[p2] now has FG(p4,a2) in LSToProc[p2], which p2 can't        *)
  (* handle until FG(p2,a2) reaches p1 and p1 sends back a copy of a2.     *)
  (* In principle, FG(p2,a2) can be moved into LSToProc[p1], "jump ahead   *)
  (* of" FG(p3,a1), and be processed by p1.  Similarly, FG(p1,a1) can be   *)
  (* received by p2 before FG(p4,a2).  However, in practice, with limited  *)
  (* queue sizes, those unrelated messages XXX in LSToProc[p1] and         *)
  (* LSToProc[p2] might prevent FG(p2,a2) and FG(p1,a1) from being moved   *)
  (* into the LSToProc queues.  In particular, those XXX's could be        *)
  (* ForwardedGets for other addresses that are similarly deadlocked.      *)
  (*                                                                       *)
  (* What actually happens is that shadowing saves the day.  The steps     *)
  (* marked `+' put a1 and a2 in shadow mode, causing FG(p3,a1) and        *)
  (* FG(p4,a2), generated in the steps marked `*', to be sent to the       *)
  (* global switch, rather than being put directly into Q.LSToProc.  This  *)
  (* guarantees that either FG(p2,a2) will wind up ahead of FG(p3,a1), or  *)
  (* that FG(p1,a1) will wind up ahead of FG(p4,a2), eliminating the       *)
  (* deadlock.  The proof that this works in general is nontrivial; it     *)
  (* must form part of a proof that the algorithm satisfies the Alpha      *)
  (* memory specification's liveness property.                             *)
  (*************************************************************************)
  msgsInLoop(adr, "ShadowClear") # {}


CanDequeueMsgSet(q, pl, idx) ==
  (*************************************************************************)
  (* True iff the message set in Q.q[pl][idx] can be received dequeued     *)
  (* (and processed) by the receiving processor, local switch, or global   *)
  (* switch, assuming idx is in DOMAIN Q.q[pl].  For example,              *)
  (* CanDequeueMsgSet("LSToGS",l1,7) is true iff the 7th message in the    *)
  (* queue from LS l1 to the GS can be dequeued.  Note that message sets   *)
  (* can be dequeued out of order; the only ordering constraints are the   *)
  (* ones implied by MustFollow.                                           *)
  (*************************************************************************)
  ~ \E i \in 1..(idx-1) :
      \E m1 \in Q[q][pl][idx], m2 \in Q[q][pl][i]  : MustFollow(q, m1, m2)


-----------------------------------------------------------------------------
(***************************************************************************)
(*                              INVARIANTS                                 *)
(*                                                                         *)
(* We now define two invariants--state predicates that are true of every   *)
(* reachable state.  These invariants aren't needed as part of the         *)
(* specification.  However, we state them to help you understand the       *)
(* algorithm.                                                              *)
(***************************************************************************)

TypeInvariant ==
  (*************************************************************************)
  (* This declares the "types" of all the variables (except aInt, whose    *)
  (* type is unspecified).  The type of a variable x is just a simple set  *)
  (* S such that the predicate x \in S is an invariant.                    *)
  (*************************************************************************)
   /\ cache \in [ Proc -> [ Adr -> CacheEntry ] ]
   /\ memDir \in [ Adr -> MemDirEntry ]
   /\ Q      \in [ProcToLS : [ Proc -> Seq(SUBSET Message) ],
                  LSToProc : [ Proc -> Seq(SUBSET Message) ],
                  LSToGS   : [ LS -> Seq(SUBSET Message) ],
                  GSToLS   : [ LS -> Seq(SUBSET Message) ] ]
   /\ fillQ \in [Proc -> SUBSET Fill]
   /\ reqQ \in [Proc -> Seq(Request)]
   /\ respQ \in [Proc -> Seq(Response)]
   /\ locked \in [Proc -> Adr \cup {Unlocked}]

MessageInvariant ==
  (*************************************************************************)
  (* This invariant asserts a number of interesting facts about            *)
  (* messages--including what messages can appear in what queues.          *)
  (*************************************************************************)
   /\ (*********************************************************************)
      (* The ProcToLS queues.                                              *)
      (*********************************************************************)
      \A p \in Proc :
          \A m \in msgsInQueue(Q.ProcToLS[p]) : /\ m \in Q0Message
                                                /\ m.cmdr = p
   /\ (*********************************************************************)
      (* The LSToProc queues.                                              *)
      (*********************************************************************)
      \A p \in Proc :
         /\ \A m \in msgsInQueue(Q.LSToProc[p]) :
              /\ m \in ForwardedGet \cup ChangeToExclusiveAck \cup
                       Inval \cup Comsig \cup VictimAck \cup FillMarker
              /\ MsgDestination(m) = p
         /\ \A idx \in DOMAIN Q.LSToProc[p] :
                  \/ Cardinality(Q.LSToProc[p][idx]) = 1
                  \/ {m.type : m \in Q.LSToProc[p][idx]} =
                        {"Comsig", "ChangeToExclusiveAck"}
                  \/ {m.type : m \in Q.LSToProc[p][idx]} =
                        {"Comsig", "FillMarker"}
            (***************************************************************)
            (* The only time we send two messages at once to the same      *)
            (* processor is we send a Comsig with a ChangeToExclusiveAck   *)
            (* or FillMarker.                                              *)
            (***************************************************************)

   /\ (*********************************************************************)
      (* The LSToGS queues.                                                *)
      (*********************************************************************)
      \A ls \in LS :
           \A m \in msgsInQueue(Q.LSToGS[ls]) :
              /\ (m \in ShadowClear \cup ComsigClear) =>
                              /\ MsgDestination(m) = ls
                              /\ AdrLS(m.adr) = ls
              /\ (m \in Q0Message) => (MsgDestination(m) # ls)
              /\ /\ m \in Q1Message \
                                 (ComsigClear \cup ShadowClear \cup Comsig)
                 /\ ProcLS(MsgDestination(m)) = ls
                 => (AdrLS(m.adr) = ls)

   /\ (*********************************************************************)
      (* The GSToLS queues.                                                *)
      (*********************************************************************)
      \A ls \in LS :
           \A m \in msgsInQueue(Q.GSToLS[ls]) :
              IF m \in Q0Message \cup ShadowClear \cup ComsigClear
                THEN MsgDestination(m) = ls
                ELSE ProcLS(MsgDestination(m)) = ls

   /\ (*********************************************************************)
      (* Victims travel alone; they never belong to the same message set   *)
      (* as another message.                                               *)
      (*********************************************************************)
      \A loc \in allQLocations:
        (\E m \in Q[loc[1]][loc[2]][loc[3]] : m \in Victim) =>
                 (Cardinality(Q[loc[1]][loc[2]][loc[3]]) = 1)

   /\ (*********************************************************************)
      (* There can be at most one Victim from any processor for any single *)
      (* address.                                                          *)
      (*********************************************************************)
       \A p \in Proc, a \in Adr :
         1 \geq Cardinality({loc \in allQLocations :
                               \E m \in Q[loc[1]][loc[2]][loc[3]] : /\ m.type = "Victim"
                                                        /\ m.cmdr = p
                                                        /\ (m.adr = a)})

MiscellaneousInvariant ==
  (*************************************************************************)
  (* This will is another miscellaneous invariant that seems worth noting. *)
  (*************************************************************************)
     (**********************************************************************)
     (* The cache entry of for locked address cannot be invalid.           *)
     (**********************************************************************)
     \A p \in Proc:
        (locked[p] # Unlocked) => (cache[p][locked[p]].state # "Invalid")

-----------------------------------------------------------------------------
(***************************************************************************)
(*                          THE INITIAL PREDICATE                          *)
(***************************************************************************)

Init ==
  (*************************************************************************)
  (* This predicate describes the initial values of variables.             *)
  (*************************************************************************)
   /\ cache = [p \in Proc |->
                 [a \in Adr |-> [state |-> "Invalid",
                                 fillOrCTEAckPending  |-> FALSE,
                                 version |-> << >> ]]]
   /\ memDir = [a \in Adr |-> [writer  |-> InMemory,
                               readers |-> { },
                               data    |-> InitMem[a]]]
   /\ Q = [ProcToLS |-> [p \in Proc |-> << >>],
           LSToProc |-> [p \in Proc |-> << >>],
           LSToGS   |-> [ls \in LS  |-> << >>],
           GSToLS   |-> [ls \in LS  |-> << >>]]
   /\ fillQ = [p \in Proc |-> { }]
   /\ reqQ  = [p \in Proc |-> << >>]
   /\ respQ = [p \in Proc |-> << >>]
   /\ locked = [p \in Proc |-> Unlocked]



-----------------------------------------------------------------------------
(***************************************************************************)
(*                         SOME STATE FUNCTIONS                            *)
(*                                                                         *)
(* We now define some state functions and state predicates that are used   *)
(* below to define the processor actions.                                  *)
(***************************************************************************)

DirOpInProgress(proc, adr) ==
  (*************************************************************************)
  (* This is true iff processor proc has issued a request to obtain a copy *)
  (* of memory address adr in its cache, and that request is still being   *)
  (* processed.  This is true iff there is a Fill or ForwardedGet or       *)
  (* ChangeToExclusiveAck message for this proc and adr.                   *)
  (*************************************************************************)
  \/ \E m \in msgsInTransit :
          /\ m \in GetShared \cup GetExclusive \cup
                   ChangeToExclusive \cup ForwardedGet \cup
                   ChangeToExclusiveAck
          /\ m.cmdr = proc
          /\ m.adr  = adr
  \/ \E m \in fillQ[proc] : m.adr = adr

CanIssueOrExecuteRdOrWr(p, idx) ==
  (*************************************************************************)
  (* True iff p's idx-th pending request, which is assumed not to be an    *)
  (* MB, is ready to be processed--either by executing it from the cache   *)
  (* or by issuing a request to the directory.                             *)
  (*************************************************************************)
  LET req == reqQ[p][idx]
  IN  /\ ~cache[p][req.adr].fillOrCTEAckPending
         (******************************************************************)
         (* The request cannot be processed if there is a Fill or CTEAck   *)
         (* pending for the address.                                       *)
         (******************************************************************)
      /\ \A i \in 1..(idx-1) : /\ reqQ[p][i].type # "MB"
                               /\ reqQ[p][i].adr # req.adr
                               /\ (req.type \in {"LL", "SC"}) =>
                                     reqQ[p][i].type \notin {"LL", "SC"}
         (******************************************************************)
         (* There is no memory barrier or request for the same address in  *)
         (* front of this request.  Also, all LL/SC operations must be     *)
         (* executed in request order.  (This is necessary to maintain the *)
         (* LLSCPair conjunct of the LL/SC axiom in beforeOrderOK of       *)
         (* the Alpha memory spec.)                                        *)
         (******************************************************************)


CanExecuteFromCache(p, idx) ==
  (*************************************************************************)
  (* True iff p's idx-th pending request is not an MB and can be executed  *)
  (* from the cache.                                                       *)
  (*************************************************************************)
  LET adr  == reqQ[p][idx].adr
      type == reqQ[p][idx].type
  IN  /\ \/  /\ type \in {"Wr", "SC"}
             /\ cache[p][adr].state = "Exclusive"
             (**************************************************************)
             (* The Wr or SC can be done if the state is exclusive,        *)
             (* although the SC will be failed if the address is not       *)
             (* locked.                                                    *)
             (**************************************************************)
         \/  /\ type = "SC"
             /\ locked[p] # adr
             (**************************************************************)
             (* The SC must be failed in this case.                        *)
             (**************************************************************)
         \/  /\ type \in {"Rd", "LL"}
             /\ cache[p][adr].state # "Invalid"
      /\ CanIssueOrExecuteRdOrWr(p, idx)

AdrToReqIdx(p, adr) ==
  (*************************************************************************)
  (* If p has issued a directory operation for address adr that is         *)
  (* still outstanding, then that operation is for the request in          *)
  (* reqQ[p][AdrToReqIdx(p,adr)].  Since a processor can have only a       *)
  (* single outstanding directory operation for an address,                *)
  (* AdrToReqIdx(p,adr) is the smallest idx for which reqQ[p][idx] is a    *)
  (* request for address adr.                                              *)
  (*************************************************************************)
  CHOOSE idx \in DOMAIN reqQ[p] :
    /\ reqQ[p][idx].type # "MB"
    /\ reqQ[p][idx].adr = adr
    /\ \A i \in 1..(idx-1) : /\ reqQ[p][i].type # "MB"
                             /\ reqQ[p][i].adr # adr

(***************************************************************************)
(* The next four operators define the oldest and newest versions in the    *)
(* version field of a CacheEntry, and their indices--that is, their        *)
(* positions in the sequence of versions.                                  *)
(***************************************************************************)
OldestIdx(version) == 1
NewestIdx(version) == Len(version)
Oldest(version) == version[OldestIdx(version)]
Newest(version) == version[NewestIdx(version)]


ReducedCacheEntry(entry) ==
  (*************************************************************************)
  (* Several actions remove the oldest version from the sequence of        *)
  (* versions in the version field of a CacheEntry.  This can be done if   *)
  (* there is no FillMarker or VictimAck pending for the version and       *)
  (* either the version has been superseded by a newer one, or the cache   *)
  (* entry is invalid and it has no Fill or CTEAck pending.  If e is the   *)
  (* CacheEntry value after its bits have been set to reflect the current  *)
  (* operation, then ReducedCacheEntry(e) is the new CacheEntry value,     *)
  (* which either equals e or equals e after removing the oldest version.  *)
  (*************************************************************************)
  IF /\ \/ Len(entry.version) > 1
        \/ /\ Len(entry.version) = 1
           /\ ~entry.fillOrCTEAckPending
           /\ entry.state = "Invalid"
     /\ ~Oldest(entry.version).fillMarkerPending
     /\ ~Oldest(entry.version).victimAckPending
  THEN [ entry EXCEPT !.version = Tail(entry.version) ]
  ELSE entry
-----------------------------------------------------------------------------
(***************************************************************************)
(*                             PROCESSOR ACTIONS                           *)
(*                                                                         *)
(* We now define the subactions of the next-state action that represent    *)
(* operations performed by the processor.                                  *)
(***************************************************************************)

(***************************************************************************)
(*                   HANDLING REQUESTS AND RESPONSES                       *)
(***************************************************************************)
ProcReceiveRequest(p, req) ==
  (*************************************************************************)
  (* A request req for processor p arrives from the environment.  It is    *)
  (* simply appended to reqQ[p].                                           *)
  (*************************************************************************)
    /\ RequestFromEnv(aInt, aInt', p, req)
    /\ reqQ' = [reqQ EXCEPT ![p] = Append(@, req)]
    /\ UNCHANGED <<memDir, Q, fillQ, cache, respQ, locked>>

ProcSendResponse(p, idx) ==
  (*************************************************************************)
  (* Processor p issues a response.  It can respond for any element in     *)
  (* respQ[p] that doesn't have another request for the same address ahead *)
  (* of it.                                                                *)
  (*************************************************************************)
  /\ \A i \in 1..(idx-1) : respQ[p][i].adr # respQ[p][idx].adr
  /\ ResponseToEnv(aInt, aInt', p, respQ[p][idx])
  /\ respQ' = [respQ EXCEPT ![p] = SeqMinusItem(@, idx)]
  /\ UNCHANGED <<memDir, Q, fillQ, cache, reqQ, locked>>

(***************************************************************************)
(*                     EVICTING A CACHE LINE                               *)
(***************************************************************************)

ProcEvictCacheLine(p, adr) ==
  (*************************************************************************)
  (* The processor evicts a cache line.  We take this to be a spontaneous  *)
  (* event; in a real implementation, it is occurs because the processor   *)
  (* needs to make room in the cache.                                      *)
  (*************************************************************************)
  /\ cache[p][adr].state # "Invalid"
  /\ cache[p][adr].version # << >>
  /\ ~cache[p][adr].fillOrCTEAckPending

  /\ cache' =
       (********************************************************************)
       (* Invalidate the evicted cache line.  If this is the primary copy  *)
       (* of the address (the state is Exclusive or SharedDirty), then a   *)
       (* victim is sent to the directory, so we set victimAckPending for  *)
       (* the newest version.  If this is not the primary copy, then it is *)
       (* removed by either setting the data field to InvalidData, or      *)
       (* deleting the version--which we can do iff it's the only version  *)
       (* and its FillMarker has arrived.                                  *)
       (********************************************************************)
       [cache EXCEPT
          ![p][adr].state = "Invalid",
          ![p][adr].version =
             IF cache[p][adr].state # "SharedClean"
             THEN [@ EXCEPT ![NewestIdx(@)].victimAckPending=TRUE]
             ELSE (*********************************************************)
                  (* Note that                                             *)
                  (* Newest(cache[p][adr].version).victimAckPending is     *)
                  (* false here.                                           *)
                  (*********************************************************)
                  IF /\ Len(@) = 1
                     /\ ~Newest(@).fillMarkerPending
                  THEN << >>
                  ELSE [@ EXCEPT ![NewestIdx(@)].data = InvalidData] ]

  /\ locked' =
       (********************************************************************)
       (* If the evicted address is locked, then unlock it.                *)
       (********************************************************************)
       IF locked[p] = adr
       THEN [ locked EXCEPT ![p] = Unlocked ]
       ELSE locked

  /\ Q' =
       (********************************************************************)
       (* If the copy is the primary one, then a Victim is sent to the     *)
       (* directory.                                                       *)
       (********************************************************************)
       IF cache[p][adr].state = "SharedClean"
          THEN Q
          ELSE [Q EXCEPT
                   !.ProcToLS[p] = Append(@,
                       {[type |-> "Victim",
                         cmdr |-> p,
                         adr  |-> adr,
                         data |-> Newest(cache[p][adr].version).data]})]

  /\ UNCHANGED <<memDir, aInt, reqQ, respQ, fillQ>>

(***************************************************************************)
(*                  ACTIONS THAT PERFORM OPERATIONS                        *)
(*                                                                         *)
(* We now define actions with which the processor actually performs        *)
(* operations.  The ProcReceiveMsg action also handles ForwardedGets       *)
(* and Invals that are generated by other processors' operations.  But     *)
(* first, we define an auxiliary action used to define other actions.      *)
(***************************************************************************)

ProcRetireRdOrWr(p, idx, cch) ==
  (*************************************************************************)
  (* This action is used to define ProcReceiveFill, ProcExecuteFromCache,  *)
  (* and ProcReceiveMsg.                                                   *)
  (*                                                                       *)
  (* This action defines the values of reqQ, respQ, lock, and cache after  *)
  (* performing the idx-th request in processor p's request queue when the *)
  (* cache is equal to cch.  It assumes that the state and all state bits  *)
  (* such as fillMarkerPending have been set correctly in cch by the       *)
  (* calling action, and updates only the value of the cache entry in      *)
  (* question by writing the value specified by a Wr or SC. In particular, *)
  (* when used in ProcReceiveFill and ProcReceiveMsg, it assumes that the  *)
  (* data carried in these messages have already been written into cch.    *)
  (* It assumes that the request is a Rd, LL, Wr, or SC that can now be    *)
  (* processed.                                                            *)
  (*************************************************************************)
  LET req == reqQ[p][idx]
  IN  (*********************************************************************)
      (* The following should be true when this action is used:            *)
      (*                                                                   *)
      (*    \/ /\ req.type \in {"Rd", "LL"}                                *)
      (*       /\ cch[p][req.adr].state # "Invalid"                        *)
      (*    \/ /\ req.type \in {"Wr", "SC"}                                *)
      (*       /\ cch[p][req.adr].state = "Exclusive"                      *)
      (*    \/ /\ req.type = "SC"                                          *)
      (*       /\ locked[p] # req.adr                                      *)
      (*********************************************************************)

      /\ reqQ' = [reqQ EXCEPT ![p] = SeqMinusItem(@, idx)]
           (****************************************************************)
           (* The idx-th entry is removed from reqQ[p].                    *)
           (****************************************************************)
      /\ IF \/ req.type = "Wr"
            \/ /\ req.type  = "SC"
               /\ locked[p] = req.adr
           THEN (***********************************************************)
                (* A Wr or successful SC request.  The masked write is     *)
                (* performed to cache[p] and the response appended to      *)
                (* respQ[p].                                               *)
                (***********************************************************)
                /\ cache' = [cch EXCEPT ![p][req.adr].version =
                                 [@ EXCEPT ![NewestIdx(@)].data =
                                    MaskVal(@, req.mask, req.data)]]
                /\ respQ' =
                     [respQ EXCEPT ![p] =
                        Append(@, [type |-> req.type,
                                   adr  |-> req.adr])]
           ELSE (***********************************************************)
                (* A Rd or LL request, or a failed SC. The cache is        *)
                (* unchanged and a response is added to respQ[p].          *)
                (***********************************************************)
                /\ cache' = cch
                /\ respQ' =
                     [respQ EXCEPT ![p] =
                        Append(@,
                          (IF req.type = "SC"
                           THEN (* A  failed SC.               *)
                             [type |-> "FailedSC",
                              adr  |-> req.adr]
                           ELSE (* A Rd or LL.                 *)
                             [type |-> req.type,
                              adr  |-> req.adr,
                              data |->
                                Newest(cch[p][req.adr].version).data]) )]

      /\ locked' =
           (****************************************************************)
           (* The address is locked by an LL and is unlocked by an SC.     *)
           (****************************************************************)
           [locked EXCEPT ![p] =
              CASE req.type = "LL" -> req.adr
                   (********************************************************)
                   (* An LL sets lock[p] equal to the request's address,   *)
                   (* making possible the success of a subsequent SC to    *)
                   (* that address.                                        *)
                   (********************************************************)
                [] req.type = "SC" -> Unlocked
                   (********************************************************)
                   (* According to the Alpha memory spec, there can be no  *)
                   (* SC--not even a failed one--between a successful SC   *)
                   (* and its LL. Hence, any SC should resrt lock[p].      *)
                   (********************************************************)
                [] OTHER -> @]
                   (********************************************************)
                   (* A Rd or Wr request by the same processor is allowed  *)
                   (* to come between a successful SC and its LL.          *)
                   (********************************************************)


ProcReceiveMsg(p, idx) ==
  (*************************************************************************)
  (* Processor p receives a message set, the idx-th set in the queue from  *)
  (* the local switch to p, and processes each of the messages in the set. *)
  (*************************************************************************)
  /\ CanDequeueMsgSet("LSToProc", p, idx)
       (********************************************************************)
       (* This is the action's enabling condition, true iff the message    *)
       (* can be received now.                                             *)
       (********************************************************************)

  /\ LET
       msgset == Q.LSToProc[p][idx]
         (******************************************************************)
         (* The message set that processor p is receiving.  It contains    *)
         (* either a single message, or else a ChangeToExclusiveAck        *)
         (* accompanied by a Comsig.                                       *)
         (******************************************************************)
       msg == CHOOSE m \in msgset : m.type # "Comsig"
         (******************************************************************)
         (* The non-Comsig message in the set, if there is one.            *)
         (******************************************************************)

       entry == cache[p][msg.adr]

     IN
       CASE \E m \in msgset : m \in ForwardedGet ->
            (***************************************************************)
            (* Case 1: The message is a ForwardedGet.  In this case        *)
            (* entry.version must be nonempty.  If there are multiple      *)
            (* versions, then the ForwardedGet is for the oldest one.  If  *)
            (* there is a single version, then the message can be          *)
            (* processed now only if the Fill for this version has         *)
            (* arrived.  (In this case, the state must be "Exclusive";     *)
            (* there canot be a CTEAck pending.)                           *)
            (***************************************************************)
               /\ \/ Len(entry.version) > 1
                  \/ ~entry.fillOrCTEAckPending

               /\ cache' =
                  (*********************************************************)
                  (* Invalidate the cache line, unless the message is      *)
                  (* asking for a shared copy.                             *)
                  (*********************************************************)
                  LET
                    newstate == IF Len(entry.version) > 1
                                THEN entry.state
                                ELSE IF /\ msg.state = "Shared"
                                        /\ entry.state # "Invalid"
                                     THEN "SharedDirty"
                                     ELSE "Invalid"
                    newentry == [entry EXCEPT !.state = newstate]
                  IN
                    [cache EXCEPT ![p][msg.adr] =
                           IF Len(entry.version) = 1
                           THEN ReducedCacheEntry(newentry)
                           ELSE newentry ]

               /\ fillQ' =
                  (*********************************************************)
                  (* Send a copy of the data in a Fill if the message is   *)
                  (* asking for one.  We know that the copy being          *)
                  (* requested is the data value of the oldest version.    *)
                  (*********************************************************)
                  LET
                    version == entry.version
                  IN
                    [fillQ EXCEPT ![msg.cmdr] = @ \cup
                                {[adr   |-> msg.adr,
                                  data  |-> Oldest(version).data,
                                  state |-> msg.state]}]
               /\ locked' =
                  (*********************************************************)
                  (* If the address is locked and the version in question  *)
                  (* is the current one (which is true iff there is only   *)
                  (* one version), and the ForwardedGet is "Exclusive",    *)
                  (* then unlock the address.  Note that if there is more  *)
                  (* than one version, then the version being obtained by  *)
                  (* the ForwardedGet must have been evicted, and the      *)
                  (* eviction unlocked the address had it been locked.  In *)
                  (* that case, if the address is locked, it's because the *)
                  (* Fill has already returned for a LL of a later         *)
                  (* version.                                              *)
                  (*********************************************************)
                   IF /\ locked[p] = msg.adr
                      /\ Len(entry.version) = 1
                         (**************************************************)
                         (* Because a ForwardedGet comes only for a        *)
                         (* primary copy, in this case ~forOldVersion is   *)
                         (* equivalent to Len(entry.version) = 1.          *)
                         (**************************************************)
                      /\ msg.state = "Exclusive"
                   THEN [locked EXCEPT ![p] = Unlocked]
                   ELSE locked

               /\ UNCHANGED <<reqQ, respQ>>

       []   \E m \in msgset : m \in Inval ->
            (***************************************************************)
            (* Case 2: The message is an Inval.                            *)
            (***************************************************************)
               LET forOldVersion ==
                     (******************************************************)
                     (* True iff the Inval is for an earlier version of    *)
                     (* the data, and hence should be thrown away.         *)
                     (******************************************************)
                     IF Len(entry.version) = 0
                        (***************************************************)
                        (* There is no current version.                    *)
                        (***************************************************)
                     THEN TRUE
                     ELSE Newest(entry.version).fillMarkerPending
                        (***************************************************)
                        (* An Inval for any version must follow that       *)
                        (* version's FillMarker, so in this case the Inval *)
                        (* isn't for the current version.                  *)
                        (***************************************************)
               IN  /\  \/ forOldVersion
                          (*************************************************)
                          (* Throw the Inval away, since the fillmarker is *)
                          (* for an earlier version.                       *)
                          (*************************************************)

                       \/ ~entry.fillOrCTEAckPending
                           (************************************************)
                           (* Do the invalidation, since we are not        *)
                           (* waiting for a fill.                          *)
                           (************************************************)

                       \/ entry.state # "Invalid"
                           (************************************************)
                           (* If entry.fillOrCTEAckPending is true, then   *)
                           (* we are waiting for either a Fill or a        *)
                           (* CTEAck.  If the state is not Invalid, then   *)
                           (* we must be waiting for a CTEAck.  Hence,     *)
                           (* this Inval was generated by an operation     *)
                           (* that invalidated the current copy before the *)
                           (* ChangeToExclusive reached the directory.     *)
                           (* So, we receive the Inval now and wait for    *)
                           (* the failed CTEAck that must be coming.       *)
                           (************************************************)

                   /\ cache' =
                        (***************************************************)
                        (* Invalidate the cache line, unless the Inval is  *)
                        (* for an earlier version.                         *)
                        (***************************************************)
                        IF forOldVersion
                        THEN
                          cache
                        ELSE
                          [cache EXCEPT
                            ![p][msg.adr] =
                              ReducedCacheEntry([@ EXCEPT
                                                    !.state = "Invalid" ])]

                   /\ locked' =
                        (***************************************************)
                        (* Unlock the invalidated cache line, unless the   *)
                        (* Inval is for an earlier version.                *)
                        (***************************************************)
                      IF /\ locked[p] = msg.adr
                         /\ ~forOldVersion
                      THEN
                        [locked EXCEPT ![p] = Unlocked]
                      ELSE
                        locked

                   /\ UNCHANGED <<reqQ, respQ, fillQ>>

         [] \E m \in msgset : /\ m.type = "ChangeToExclusiveAck"
                              /\ m.success ->
            (***************************************************************)
            (* Case 3: The message is a successful ChangeToExclusiveAck,   *)
            (* and perhaps a Comsig.  In this case, there is a single      *)
            (* version because the ChangeToExclusiveAck is delivered after *)
            (* the VictimAcks for all prior versions have been delivered,  *)
            (* and the state of that version must be either "SharedClean"  *)
            (* or "SharedDirty".                                           *)
            (***************************************************************)
              LET
                ridx ==
                  (*********************************************************)
                  (* The index of the request in the request queue for     *)
                  (* which this ChangeToExclusiveAck is the response.      *)
                  (*********************************************************)
                  AdrToReqIdx(p, msg.adr)
                cch ==
                  (*********************************************************)
                  (* The cache after setting this line to Exclusive.       *)
                  (*********************************************************)
                  [cache EXCEPT ![p][msg.adr].state = "Exclusive",
                                ![p][msg.adr].fillOrCTEAckPending = FALSE ]
              IN
                /\ ProcRetireRdOrWr(p, ridx, cch)
                /\ UNCHANGED fillQ

         [] \E m \in msgset : /\ m.type = "ChangeToExclusiveAck"
                              /\ ~m.success ->
            (***************************************************************)
            (* Case 4: The message is a failed ChangeToExclusiveAck and    *)
            (* perhaps a Comsig.  If the CTE was for an SC, then receipt   *)
            (* of this message will enable ProcExecuteFromCache to fail    *)
            (* the SC. In this case, there is just a single extant version *)
            (* (cache[p][msg.adr].version has length 1), that version has  *)
            (* no pending FillMarker or VictimAck, and the entry's state   *)
            (* is "Invalid".                                               *)
            (***************************************************************)
              /\ cache' = [ cache EXCEPT
                                    ![p][msg.adr].version = <<>>,
                                    ![p][msg.adr].fillOrCTEAckPending = FALSE ]
                 (**********************************************************)
                 (* The cache entry's fillOrCTEAckPending field is set     *)
                 (* false and the sole extant version is removed.  (The    *)
                 (* observations above imply that if e is the cache entry  *)
                 (* obtained by setting the fillOrCTEAckPending field      *)
                 (* false, then ReducedCacheEntry(e) is e with the version *)
                 (* field set to the empty sequence.                       *)
                 (**********************************************************)
              /\ UNCHANGED << fillQ, reqQ, respQ, locked>>

         [] \E m \in msgset : m.type = "VictimAck" ->
            (***************************************************************)
            (* Case 5: The message is a VictimAck.  The VictimAck must be  *)
            (* for the oldest version, because there can't be either a     *)
            (* VictimAck or a FillMarker outstanding for any older         *)
            (* version.  Hence, there must be an oldest version            *)
            (* (entry.version not the empty sequence) and its              *)
            (* victimAckPending field must equal TRUE.                     *)
            (***************************************************************)
              LET
                newentry == [ entry EXCEPT
                (***********************************************************)
                (* Reset the victimAckPending bit for the oldest version.  *)
                (***********************************************************)
                   !.version[OldestIdx(entry.version)].victimAckPending =
                                                                      FALSE ]
              IN
                (***********************************************************)
                (* The VictimAck must be for the oldest version,           *)
                (* because there can't be either a VictimAck or a          *)
                (* FillMarker outstanding for any older version.           *)
                (***********************************************************)
                /\ cache' = [cache EXCEPT ![p][msg.adr] =
                                          ReducedCacheEntry(newentry) ]
                /\ UNCHANGED << fillQ, reqQ, respQ, locked>>

         [] \E m \in msgset : m.type = "FillMarker" ->
            (***************************************************************)
            (* Case 6: The message is a FillMarker, perhaps with a Comsig. *)
            (* The FillMarker must be for the oldest version, because      *)
            (* there can't be either a VictimAck or a FillMarker           *)
            (* outstanding for any older version.  Hence, there must be an *)
            (* oldest version (entry.version is not the empty sequence)    *)
            (* and its fillMarkerPending field must equal TRUE.            *)
            (***************************************************************)
              LET
                newentry == [ entry EXCEPT
                (***********************************************************)
                (* Reset the fillMarkerPending bit for the oldest version. *)
                (***********************************************************)
                   !.version[OldestIdx(entry.version)].fillMarkerPending =
                                                                      FALSE ]
              IN
                (***********************************************************)
                (* The FillMarker must be for the oldest version,          *)
                (* because there can't be either a VictimAck or a          *)
                (* FillMarker outstanding for any older version.           *)
                (***********************************************************)
                /\ cache' = [cache EXCEPT ![p][msg.adr] =
                                          ReducedCacheEntry(newentry) ]
                /\ UNCHANGED << fillQ, reqQ, respQ, locked>>

         [] OTHER ->
            (***************************************************************)
            (* Case 7: The message is a Comsig by itself.                  *)
            (***************************************************************)
               UNCHANGED <<fillQ, reqQ, respQ, cache, locked>>
               (************************************************************)
               (* The actual Wildfire implementation keeps track of how    *)
               (* many Comsigs are outstanding by keeping a counter that   *)
               (* is incremented when a request is sent to the directory,  *)
               (* and is decremented when the Comsig returns.  An MB       *)
               (* cannot be retired unless that counter is zero.  In this  *)
               (* specification, we have abstracted away that counter, and *)
               (* simply enable the retiring of the MB on how many Comsigs *)
               (* are actually in Q.                                       *)
               (************************************************************)

  /\ Q' = [Q EXCEPT !.LSToProc[p] = SeqMinusItem(@, idx)]
  /\ UNCHANGED <<memDir, aInt>>


ProcReceiveFill(p, m) ==
  (*************************************************************************)
  (* Processor p receives the Fill m appearing in fillQ[p].  Processor p   *)
  (* inserts the new data into the cache and retires the Rd or Wr          *)
  (* instruction that generated the directory command this Fill is         *)
  (* responding to.                                                        *)
  (*************************************************************************)
  LET idx == AdrToReqIdx(p, m.adr)
        (*******************************************************************)
        (* The index of the request in the request queue that generated    *)
        (* the directory command for which this Fill is the response.      *)
        (*******************************************************************)
      cch ==
        (*******************************************************************)
        (* The cache after inserting this Fill into the cache.  The data   *)
        (* in this Fill are used to update the newest version of the       *)
        (* address.                                                        *)
        (*******************************************************************)
        [cache EXCEPT
           ![p][m.adr].version = [@ EXCEPT ![NewestIdx(@)].data = m.data],
           ![p][m.adr].fillOrCTEAckPending = FALSE,
           ![p][m.adr].state = IF m.state = "Shared"
                               THEN "SharedClean"
                               ELSE "Exclusive"]

  IN
    (***********************************************************************)
    (* The request cannot be an SC (or a failed SC) because an SC can      *)
    (* never generate a Fill.  An SC can go to the directory only for a    *)
    (* SharedToExclusive request.                                          *)
    (***********************************************************************)
    /\ ProcRetireRdOrWr(p, idx, cch)
    /\ fillQ' = [fillQ EXCEPT ![p] = @ \ {m}]
    /\ UNCHANGED <<memDir, Q, aInt>>


ProcExecuteFromCache(p, idx) ==
  (*************************************************************************)
  (* Processor p executes the idx-th request in its request queue directly *)
  (* from the cache--that is, without having to issue a directory          *)
  (* operation.  For a read or write, this means that the data are already *)
  (* in its cache.                                                         *)
  (*************************************************************************)
  LET req == reqQ[p][idx]
  IN  /\ \/ /\ req.type = "MB"
               (************************************************************)
               (* Case 1: the request is a MB.                             *)
               (************************************************************)
            /\ \A i \in 1..(idx-1) :
                 /\ reqQ[p][i].type # "MB"
                    (*******************************************************)
                    (* This is the first MB in the request queue.          *)
                    (*******************************************************)
                 /\ DirOpInProgress(p, reqQ[p][i].adr)
                 /\ \A j \in 1..(i-1) : reqQ[p][j].adr # reqQ[p][i].adr
                    (*******************************************************)
                    (* All requests r ahead of the MB in the request queue *)
                    (* have generated directory commands.  This means that *)
                    (* there is a directory command in progress for r's    *)
                    (* address, and there is no other request to the same  *)
                    (* address ahead of r in the queue.  (It follows that  *)
                    (* r is the ONLY request to this address ahead of the  *)
                    (* MB.)                                                *)
                    (*******************************************************)
            /\ ~\E m \in msgsInTransit :
                    /\ m.type \in {"Comsig", "GetShared", "GetExclusive",
                                   "ChangeToExclusive"}
                    /\ m.cmdr = p
                    (*******************************************************)
                    (* p is not waiting for a Comsig, meaning there is no  *)
                    (* Comsig in transit to p, and no Q0 message from p    *)
                    (* that will generate a Comsig.                        *)
                    (*******************************************************)
            /\ reqQ' = [reqQ EXCEPT ![p] = SeqMinusItem(@, idx)]
            /\ UNCHANGED <<respQ, cache, locked>>

         \/ /\ req.type # "MB"
               (************************************************************)
               (* Case 2: the request is a Rd or Wr or LL or SC.           *)
               (************************************************************)
            /\ CanExecuteFromCache(p, idx)
               (************************************************************)
               (* The request can be fulfilled from the p's cache.         *)
               (************************************************************)
            /\ ProcRetireRdOrWr(p, idx, cache)

      /\ UNCHANGED <<memDir, Q, fillQ, aInt>>


ProcIssueDirReq(p, idx) ==
  (*************************************************************************)
  (* Processor p initiates execution of the idx-th request in its request  *)
  (* queue by generating a request to the directory.                       *)
  (*************************************************************************)
  LET req == reqQ[p][idx]
      adr == req.adr
      type == req.type
  IN
      /\ \/  /\ type = "Wr"
             /\ cache[p][adr].state # "Exclusive"
         \/  /\ type = "SC"
             /\ cache[p][adr].state \in {"SharedClean", "SharedDirty"}
             /\ locked[p] = adr
         \/  /\ type \in {"Rd", "LL"}
             /\ cache[p][adr].state = "Invalid"

      /\ CanIssueOrExecuteRdOrWr(p, idx)

      /\ ~CanExecuteFromCache(p, idx)

      /\ cache' =
           [ cache EXCEPT ![p][adr].fillOrCTEAckPending = TRUE,
                          ![p][adr].version =
                             IF cache[p][adr].state = "Invalid"
                             THEN Append(@,
                                     [ data              |-> InvalidData,
                                       fillMarkerPending |-> TRUE,
                                       victimAckPending  |-> FALSE ] )
                             ELSE @ ]

      /\ Q' =
           [ Q EXCEPT !.ProcToLS[p] =
               Append(@,
                {[ type |-> IF type \in {"Rd", "LL"}
                            THEN "GetShared"
                            ELSE IF cache[p][adr].state = "Invalid"
                                 THEN "GetExclusive"
                                 ELSE "ChangeToExclusive",
                   cmdr |-> p,
                   adr |-> adr ]} ) ]

      /\ UNCHANGED <<memDir, fillQ, aInt, reqQ, respQ, locked>>

-----------------------------------------------------------------------------

(***************************************************************************)
(*                          LOCAL SWITCH ACTIONS                           *)
(*                                                                         *)
(* The following actions represent operations that are performed by a      *)
(* local switch                                                            *)
(***************************************************************************)

DirectoryProcessRequest(msg, queues) ==
  (*************************************************************************)
  (* This action is not itself a subaction of the next-state action, but   *)
  (* is used in defining the actions LSReceiveRequestFromProc and          *)
  (* LSReceiveRequestFromGS, which are subactions of the next-state        *)
  (* action.  It defines the new state after the directory (that is, the   *)
  (* LS maintaining the directory entry) processes a request message msg,  *)
  (* where queues is the state of the queues in the old state after        *)
  (* removing the message.  A request message is a GetShared,              *)
  (* GetExclusive, or ChangeToExclusive.                                   *)
  (*************************************************************************)
  LET
    adr == msg.adr
    ls  == AdrLS(adr)
    readers == memDir[adr].readers
    writer  == memDir[adr].writer

    comsigMsg ==
      (*********************************************************************)
      (* The Comsig message that is sent to msg.cmdr, the processor that   *)
      (* sent the request message.                                         *)
      (*********************************************************************)
      [type  |-> "Comsig", cmdr  |-> msg.cmdr]

    writing ==
      (*********************************************************************)
      (* True iff this request is a GetExclusive or a successful           *)
      (* ChangeToExclusive.                                                *)
      (*********************************************************************)
      \/ msg.type = "GetExclusive"
      \/ /\ msg.type = "ChangeToExclusive"
         /\ msg.cmdr \in readers \cup {writer}

    invalSet ==
      (*********************************************************************)
      (* The set of Inval messages that are generated.                     *)
      (*********************************************************************)
      IF writing
        THEN { [type  |-> "Inval",
                cmdr  |-> msg.cmdr,
                dest  |-> q,
                adr   |-> msg.adr] :
              q \in IF \/ msg.type = "GetExclusive"
                       \/ writer = InMemory
                    THEN readers \ {msg.cmdr}
                    ELSE (readers \cup {writer}) \ {msg.cmdr} }
         ELSE {}

    responseMsg ==
      (*********************************************************************)
      (* The Q1 message sent in response to the request--either a          *)
      (* FillMarker or a ChangeToExclusiveAck.                             *)
      (*********************************************************************)
      IF msg.type = "ChangeToExclusive"
      THEN
        [ type |-> "ChangeToExclusiveAck",
          cmdr |-> msg.cmdr,
          adr  |-> msg.adr,
          success |-> writing ]
      ELSE
        [ type |-> "FillMarker",
          cmdr |-> msg.cmdr,
          adr  |-> msg.adr ]

    fgetSet ==
      (*********************************************************************)
      (* The set of ForwardedGet messages sent.  It is either the empty    *)
      (* set (no ForwardedGet sent) or contains the single ForwardedGet    *)
      (* message sent to the writer (the processor that has the primary    *)
      (* copy of the address).                                             *)
      (*********************************************************************)
      IF \/ msg.type = "ChangeToExclusive"
         \/ writer = InMemory
      THEN {}
      ELSE
        { [ type |-> "ForwardedGet",
            state |-> IF msg.type = "GetShared"
                      THEN "Shared"
                      ELSE "Exclusive",
            cmdr |-> msg.cmdr,
            dest |-> writer,
            adr  |-> msg.adr ] }

    shadowClearMsg ==
      (*********************************************************************)
      (* If a ShadowClear message is sent to the GS, then this is that     *)
      (* message.                                                          *)
      (*********************************************************************)
      [type |-> "ShadowClear",
       cmdr  |-> msg.cmdr,
       adr   |-> msg.adr]

    comsigClearMsg ==
      (*********************************************************************)
      (* If a ComsigClear message is sent to the GS, then this is that     *)
      (* message.                                                          *)
      (*********************************************************************)
      [type |-> "ComsigClear",
       cmdr  |-> msg.cmdr,
       adr   |-> msg.adr]

    EnteringShadowMode ==
      (*********************************************************************)
      (* The address enters shadow mode if the commander is local          *)
      (* (attached to this local switch) and the command generates a Q1    *)
      (* probe (a ForwardedGet or Inval) to a nonlocal processor.          *)
      (*********************************************************************)
      /\ ProcLS(msg.cmdr) = ls
      /\ \E m \in fgetSet \cup invalSet : ProcLS(m.dest) # ls

    ShadowClearRequired ==
       (********************************************************************)
       (* True iff a ShadowClear message should be looped to the GS.  The  *)
       (* ShadowClear is sent iff (i) the address either is already in or  *)
       (* is now entering shadow mode and (ii) the requester or the owner  *)
       (* is local.  (If the requester is not the owner--so this is not a  *)
       (* ChangeToExclusive request--then a ForwardedGet is sent to the    *)
       (* owner.)                                                          *)
       (********************************************************************)
        /\ InShadowMode(adr) \/ EnteringShadowMode
        /\ \/ ProcLS(msg.cmdr) = ls
           \/ \E m \in fgetSet \cup invalSet : ProcLS(m.dest) = ls

    ComsigClearRequired ==
      (*********************************************************************)
      (* A ComsigClear is always required if a ShadowClear is required.    *)
      (* The predicate ComsigClearRequired is true if (but not only if) a  *)
      (* ComsigClear is required and a ShadowClear is not required.  That  *)
      (* is, a ComsigClear is required iff ComsigClearRequired \/          *)
      (* ShadowClearRequired is true.                                      *)
      (*********************************************************************)

      \/  \E m \in fgetSet \cup invalSet : ProcLS(m.dest) # ls
            (***************************************************************)
            (* A ForwardedGet or an Inval is being sent to a nonlocal      *)
            (* processor.                                                  *)
            (***************************************************************)

      \/ IF ProcLS(msg.cmdr) = ls
           THEN msgsInLoop(adr, "ComsigClear") # {}
                (***********************************************************)
                (* For a local requester, a ComsigClear is required if     *)
                (* there is already a ComsigClear looping between the LS   *)
                (* and GS (or if a ShadowClear is required).               *)
                (***********************************************************)

           ELSE \E m \in fgetSet \cup invalSet : ProcLS(m.dest) = ls
                (***********************************************************)
                (* For a nonlocal requester, a ComsigClear is needed if a  *)
                (* ForwardedGet or Inval is being sent to a local          *)
                (* processor.                                              *)
                (***********************************************************)

    Messages == {comsigMsg} \cup invalSet \cup {responseMsg} \cup fgetSet
      (*********************************************************************)
      (* The set of all messages being sent other than the ShadowClear and *)
      (* ComsigClear messages.                                             *)
      (*********************************************************************)

    GlobalMessages ==
      (*********************************************************************)
      (* The set of all messages that are being sent to the global switch. *)
      (*********************************************************************)
      IF ShadowClearRequired
      THEN Messages \cup {shadowClearMsg, comsigClearMsg}
      ELSE {m \in Messages : ProcLS(MsgDestination(m)) # ls}
           \cup ( IF ComsigClearRequired
                  THEN {comsigMsg, comsigClearMsg}
                  ELSE {} )

    LocalMessages == Messages \ GlobalMessages
      (*********************************************************************)
      (* The set of messages being sent directly to (local) processors.    *)
      (*********************************************************************)

  IN
    /\ Q' = [queues EXCEPT
               !.LSToGS[ls] = IF GlobalMessages = {}
                              THEN @
                              ELSE Append(@,GlobalMessages),
               !.LSToProc =
                   [p \in Proc |->
                      LET msgs ==
                               {m \in LocalMessages : MsgDestination(m) = p }
                      IN  IF msgs = {}
                          THEN @[p]
                          ELSE Append(@[p],msgs) ] ]

    /\ memDir' =
         CASE msg.type = "GetShared" ->
                [ memDir EXCEPT ![adr].readers = @ \cup {msg.cmdr} ]
         []   writing ->
                [ memDir EXCEPT ![adr].readers = {},
                                ![adr].writer = msg.cmdr ]
         []   OTHER ->
                memDir

    /\ fillQ' =
         IF /\ msg \in GetShared \cup GetExclusive
            /\ writer = InMemory
         THEN
           [fillQ EXCEPT ![msg.cmdr]
                  = @ \cup { [ adr |-> adr,
                               data |-> memDir[adr].data,
                               state |-> IF msg \in GetShared
                                         THEN "Shared"
                                         ELSE "Exclusive"]}]
         ELSE
           fillQ

    /\ UNCHANGED <<aInt, cache, reqQ, respQ, locked>>


LSReceiveRequestFromProc(p,idx) ==
  (*************************************************************************)
  (* The action of processor p's local switch processing a request from p, *)
  (* which is in the idx-th element of Q.ProcToLS[p].                      *)
  (*************************************************************************)
  LET req == CHOOSE m \in Q.ProcToLS[p][idx] : TRUE
      (*********************************************************************)
      (* This is an arbitrary message in the idx-th element of the queue   *)
      (* from p to its local switch.  The action is enabled only if req is *)
      (* a processor request message, in which case it is the only element *)
      (* in the message set.                                               *)
      (*********************************************************************)
  IN
    /\ CanDequeueMsgSet("ProcToLS", p, idx)
    /\ req \in Q0Message \ Victim
    /\ AdrLS(req.adr) = ProcLS(p)
    /\ DirectoryProcessRequest(req,
                               [Q EXCEPT !.ProcToLS[p] = SeqMinusItem(@,idx)])

LSReceiveRequestFromGS(ls,idx) ==
  (*************************************************************************)
  (* The action of local switch ls processing a request it receives from   *)
  (* the global switch, which is in idx-th element of Q.GSToLS[ls].        *)
  (*************************************************************************)
  LET req == CHOOSE m \in Q.GSToLS[ls][idx] : TRUE
      (*********************************************************************)
      (* This is an arbitrary message in the idx-th element of the queue   *)
      (* from p to its local switch.  The action is enabled only if req is *)
      (* a processor request message, in which case it is the only element *)
      (* in the message set.                                               *)
      (*********************************************************************)
  IN
    /\ CanDequeueMsgSet("GSToLS", ls, idx)
    /\ req \in Q0Message \ Victim
    /\ DirectoryProcessRequest(req,
                               [Q EXCEPT !.GSToLS[ls] = SeqMinusItem(@,idx)])

DirectoryProcessVictim(m, ls, queues) ==
  (*************************************************************************)
  (* This action is used to define LSReceiveVictimFromProc and             *)
  (* LSReceiveVictimFromGS, the two actions that describe the arrival of a *)
  (* Victim at the home directory.                                         *)
  (*                                                                       *)
  (* The action assumes that m is a Victim message such that the local     *)
  (* switch ls the home of of m.adr.  The action describes the new values  *)
  (* of all variables other than Q when s is delivered to ls.              *)
  (*************************************************************************)
  LET
    victimAck == [ type |-> "VictimAck",
                   cmdr  |-> m.cmdr,
                   adr   |-> m.adr ]
      (*********************************************************************)
      (* The VictimAck message sent to m.cmdr, the victim's sender.        *)
      (*********************************************************************)

    shadowClear == [ type |-> "ShadowClear",
                     cmdr  |-> m.cmdr,
                     adr   |-> m.adr ]
      (*********************************************************************)
      (* If the address is in shadow mode, a local or remote victim's ack *)
      (* goes through the GS. The address must stay shadowed until the    *)
      (* VictimAck reaches the GS, so a ShadowClear message is sent to the *)
      (* GS with the VictimAck, from where it bounces back to ls.  In that *)
      (* case, this is the ShadowClear that is sent. Local acks must also *)
      (* follow older probes that are still travelling through the GS.   *)
      (*********************************************************************)

  IN
    /\ memDir' = IF memDir[m.adr].writer = m.cmdr
                 THEN [memDir EXCEPT
                        ![m.adr].writer = InMemory,
                        ![m.adr].data   = m.data]
                 ELSE memDir
    /\ Q' = IF InShadowMode(m.adr)
            THEN [queues EXCEPT !.LSToGS[ls] =
                                            Append(@,{victimAck,shadowClear})]
            ELSE IF ProcLS(m.cmdr) # ls
                 THEN [queues EXCEPT !.LSToGS[ls] = Append(@,{victimAck})]
                 ELSE [queues EXCEPT !.LSToProc[m.cmdr] = Append(@,{victimAck})]
    /\ UNCHANGED <<procVars, fillQ, aInt>>


LSReceiveVictimFromProc(p, idx) ==
  (*************************************************************************)
  (* The action by which processor p's local switch processes a Victim     *)
  (* from p, so that local switch is the home of the memory address.  The  *)
  (* Victim is in the idx-th message set in Q.ProcToLS[p].                 *)
  (*************************************************************************)
  LET
    req == CHOOSE m \in Q.ProcToLS[p][idx] : TRUE
      (*********************************************************************)
      (* This is an arbitrary message in the idx-th element of the queue   *)
      (* from p to its local switch.  The action is enabled only if req is *)
      (* a Victim message, in which case it is the only element in the     *)
      (* message set.                                                      *)
      (*********************************************************************)
  IN
    /\ CanDequeueMsgSet("ProcToLS", p, idx)
    /\ req \in Victim
    /\ AdrLS(req.adr) = ProcLS(p)
    /\ DirectoryProcessVictim(req,
                              ProcLS(req.cmdr),
                              [Q EXCEPT !.ProcToLS[p] = SeqMinusItem(@,idx)])

LSReceiveVictimFromGS(ls, idx) ==
  (*************************************************************************)
  (* The action by which local switch ls processes a Victim in the idx-th  *)
  (* element of its GSToLS message queue.  Since the Victim is coming from *)
  (* the GS, ls must be the home switch for the address.                   *)
  (*************************************************************************)
  LET
    req == CHOOSE m \in Q.GSToLS[ls][idx] : TRUE
      (*********************************************************************)
      (* This is an arbitrary message in the idx-th element of the queue   *)
      (* from p to its local switch.  The action is enabled only if req is *)
      (* a Victim message, in which case it is the only element in the     *)
      (* message set.                                                      *)
      (*********************************************************************)
  IN
    /\ CanDequeueMsgSet("GSToLS", ls, idx)
    /\ req \in Victim
    /\ DirectoryProcessVictim(req, ls,
                               [Q EXCEPT !.GSToLS[ls] = SeqMinusItem(@,idx)])


(***************************************************************************)
(*                       MESSAGE SWITCHING ACTIONS                         *)
(*                                                                         *)
(* The following actions are ones in which the LS just moves messages from *)
(* queue to queue.                                                         *)
(***************************************************************************)

LSForwardMsgsToProcs(ls, idx) ==
  (*************************************************************************)
  (* The action with which local Switch ls forwards the messages from      *)
  (* idx-th message set in Q.GSToLS[ls] to their destination processors    *)
  (* (and throws the Clears away).                                         *)
  (*************************************************************************)
  /\ \E m \in Q.GSToLS[ls][idx] : m \notin Q0Message
  /\ CanDequeueMsgSet("GSToLS", ls, idx)
  /\ Q' = [Q EXCEPT
            !.GSToLS[ls] = SeqMinusItem(@, idx),
            !.LSToProc = [p \in Proc |->
                           LET
                             msgsToP ==
                              {m \in Q.GSToLS[ls][idx] : MsgDestination(m) = p}
                           IN
                             IF msgsToP # {}
                             THEN Append(@[p], msgsToP)
                             ELSE @[p]]]
  /\ UNCHANGED << memDir, fillQ, aInt, procVars>>

LSForwardMsgsToGS(p, idx) ==
  (*************************************************************************)
  (* The action by which processor p's local switch forwards a message in  *)
  (* Q.ProcToLS[p], destined for another local switch, to the GS. The      *)
  (* message must be a Q0 message, since that's the only kind of messages  *)
  (* that originate at a processor.                                        *)
  (*************************************************************************)
  /\ \E m \in Q.ProcToLS[p][idx] : MsgDestination(m) # ProcLS(p)
  /\ CanDequeueMsgSet("ProcToLS", p, idx)
  /\ Q' = [Q EXCEPT !.ProcToLS[p]       = SeqMinusItem(@, idx),
                    !.LSToGS[ProcLS(p)] = Append(@, Q.ProcToLS[p][idx])]
  /\ UNCHANGED << memDir, fillQ, aInt, procVars>>

-----------------------------------------------------------------------------
(***************************************************************************)
(*                                THE GS ACTION                            *)
(*                                                                         *)
(* The GS is just a message switch.                                        *)
(***************************************************************************)

GSForwardMsgsToLS(ls, idx) ==
  (*************************************************************************)
  (* The GS removes the idx-th message set from Q.LSToGS[ls] and transfers *)
  (* its contents to the appropriate GSToLS queues.                        *)
  (*************************************************************************)
  /\ CanDequeueMsgSet("LSToGS", ls, idx)
  /\ Q' = [Q EXCEPT
             !.LSToGS[ls] = SeqMinusItem(@, idx),
             !.GSToLS = [t \in LS |->
                          LET ms == {m \in Q.LSToGS[ls][idx] :
                                       \/ MsgDestination(m) = t
                                       \/ /\ MsgDestination(m) \in Proc
                                          /\ ProcLS(MsgDestination(m)) = t}
                          IN  IF ms = { } THEN Q.GSToLS[t]
                                          ELSE Append(Q.GSToLS[t], ms)] ]
  /\ UNCHANGED <<memDir, fillQ, procVars, aInt>>

-----------------------------------------------------------------------------
(***************************************************************************)
(*                          THE NEXT-STATE ACTION                          *)
(***************************************************************************)

Next ==
  \/ \E p \in Proc :
       \/ \E req \in Request : ProcReceiveRequest(p, req)
       \/ \E idx \in DOMAIN respQ[p] : ProcSendResponse(p, idx)
       \/ \E adr \in Adr : ProcEvictCacheLine(p, adr)
       \/ \E idx \in DOMAIN Q.LSToProc[p] : ProcReceiveMsg(p, idx)
       \/ \E m \in fillQ[p] : ProcReceiveFill(p, m)
       \/ \E idx \in DOMAIN reqQ[p] : \/ ProcIssueDirReq(p, idx)
                                      \/ ProcExecuteFromCache(p, idx)
       \/ \E idx \in DOMAIN Q.ProcToLS[p] :
            \/ LSForwardMsgsToGS(p, idx)
            \/ LSReceiveRequestFromProc(p, idx)
            \/ LSReceiveVictimFromProc(p, idx)

  \/ \E ls \in LS :
       \/ \E idx \in DOMAIN Q.GSToLS[ls] : LSReceiveRequestFromGS(ls, idx)
       \/ \E idx \in DOMAIN Q.GSToLS[ls] : LSReceiveVictimFromGS(ls, idx)
       \/ \E idx \in DOMAIN Q.GSToLS[ls] : LSForwardMsgsToProcs(ls, idx)
       \/ \E idx \in DOMAIN Q.LSToGS[ls] : GSForwardMsgsToLS(ls, idx)

-----------------------------------------------------------------------------
(***************************************************************************)
(*                   THE COMPLETE TEMPORAL-LOGIC SPECIFICATION             *)
(***************************************************************************)

Liveness ==
  (*************************************************************************)
  (* This is the specification's liveness condition.  We want it to        *)
  (* guarantee that every request eventually generates a response.  This   *)
  (* requires the processing of things sitting in queues--namely, requests *)
  (* in the request queue, response in the response queue, and messages in *)
  (* the various message queues.  We don't require that queues be FIFO.    *)
  (* That is, we allow requests to be processed out of order, responses to *)
  (* be delivered out of order, and messages to be delivered from a queue  *)
  (* out of order (subject to constraints, of course).  However, we don't  *)
  (* require that things be processed out of order.  For example, if the   *)
  (* message at the head of Q.LSToProc[p] is a ForwardedGet that p cannot  *)
  (* process because it doesn't yet have a copy of the data, we don't      *)
  (* require that other messages be processed before the ForwardedGet is.  *)
  (* We allow p to process no messages until it can process that           *)
  (* ForwardedGet.  (See the discussion of shadowing in the comment for    *)
  (* the definition of InShadowMode.)  Hence, we put a fairness condition  *)
  (* only on the processing of the first element of a queue.               *)
  (*                                                                       *)
  (* Remember that fillQ[p] is a set of Fills, not a queue.  Hence, there  *)
  (* is no "first element".  We require that any Fill in fillQ[p] must     *)
  (* eventually be received by processor p.                                *)
  (*                                                                       *)
  (* In TLA, the formula WF_v(A) asserts that if action A /\ (v'#v) is     *)
  (* ever continuously enabled, then an A /\ (v'#v) step must eventually   *)
  (* occur.                                                                *)
  (*************************************************************************)
   /\ \A p \in Proc :
      /\ WF_wVars((respQ[p] # <<>>) /\ ProcSendResponse(p, 1))
      /\ WF_wVars((Q.LSToProc[p] # <<>>) /\ ProcReceiveMsg(p, 1))
      /\ \A m \in Fill :  WF_wVars( /\ m \in fillQ[p]
                                    /\ ProcReceiveFill(p, m) )
      /\ WF_wVars((reqQ[p] # <<>>) /\ ProcIssueDirReq(p, 1))
      /\ WF_wVars((reqQ[p] # <<>>) /\ ProcExecuteFromCache(p, 1))
      /\ WF_wVars((Q.ProcToLS[p] # <<>>) /\ LSForwardMsgsToGS(p, 1))
      /\ WF_wVars((Q.ProcToLS[p] # <<>>) /\ LSReceiveRequestFromProc(p, 1))
      /\ WF_wVars((Q.ProcToLS[p] # <<>>) /\ LSReceiveVictimFromProc(p, 1))

   /\ \A ls \in LS :
      /\ WF_wVars((Q.GSToLS[ls] # <<>>) /\ LSReceiveRequestFromGS(ls, 1))
      /\ WF_wVars((Q.GSToLS[ls] # <<>>) /\ LSReceiveVictimFromGS(ls, 1))
      /\ WF_wVars((Q.GSToLS[ls] # <<>>) /\ LSForwardMsgsToProcs(ls, 1))
      /\ WF_wVars((Q.LSToGS[ls] # <<>>) /\ GSForwardMsgsToLS(ls, 1))

Spec == /\ Init
        /\ [][Next]_wVars
        /\ Liveness
-----------------------------------------------------------------------------
\* The benchmark goal is stated in WildfireProof; no invariant is assumed here.
=============================================================================

Last modified on Sun Jun 18 09:38:33 PDT 2000 by lamport

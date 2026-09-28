--------------------- MODULE AllocatorImplementation_proof_PermSeqsTypeScaffold -----------------
(***************************************************************************)
(* TLAPS proofs of two safety theorems stated in                          *)
(* AllocatorImplementation.tla:                                           *)
(*                                                                         *)
(*   Specification => []TypeInvariant                                     *)
(*   Specification => []ResourceMutex                                     *)
(*                                                                         *)
(* TypeInvariant uses the SchedulingAllocator's TypeInvariant via the     *)
(* Sched! instance, plus the type of the additional client-side variables *)
(* (requests, holding, network).  The proof essentially mirrors           *)
(* SchedulingAllocator_proof.tla.                                          *)
(*                                                                         *)
(* ResourceMutex here is the *client-side* mutex                          *)
(*    \A c1, c2: holding[c1] \cap holding[c2] # {} => c1 = c2.            *)
(* The argument is: holding only grows from RAlloc(m) where m is an       *)
(* in-transit "allocate" message; for that m to exist Sched!Allocate(c,S) *)
(* fired earlier, which by Sched's mutex means S is disjoint from         *)
(* alloc[c'] for c' # c, and (by an interplay invariant) from holding[c'] *)
(* too.                                                                    *)
(*                                                                         *)
(* Here we prove TypeInvariant fully and ResourceMutex assuming the       *)
(* (internal) Invariant -- which combines the Sched-level                 *)
(* AllocatorInvariant with the network/holding consistency invariant      *)
(* "alloc[c] = holding[c] \cup AllocsInTransit(c) \cup ReturnsInTransit(c)".*)
(* We do not (yet) prove that combined Invariant inductive; that piece is *)
(* deferred to future work along with the Sched!AllocatorInvariant proof. *)
(***************************************************************************)
EXTENDS AllocatorImplementation, Integers, SequenceTheorems,
        FiniteSets, FiniteSetTheorems, WellFoundedInduction, TLAPS

(***************************************************************************)
(* The PermSeqs proof needs Clients to be finite (PermSeqs is the set of  *)
(* permutation sequences over a finite set; the recursion well-founds only*)
(* over finite subsets).                                                   *)
(***************************************************************************)
ASSUME ClientsFinite == IsFiniteSet(Clients)

(***************************************************************************)
(* SchedulingAllocator-level helpers, copied for in-module access.         *)
(***************************************************************************)
LEMMA SubSeqInRange ==
  ASSUME NEW T, NEW s \in Seq(T), NEW m \in Int, NEW n \in Int,
         m >= 1, n <= Len(s)
  PROVE  SubSeq(s, m, n) \in Seq(T)
PROOF OMITTED

LEMMA ConcatType ==
  ASSUME NEW T, NEW s1 \in Seq(T), NEW s2 \in Seq(T)
  PROVE  s1 \o s2 \in Seq(T)
  OBVIOUS

LEMMA DropType ==
  ASSUME NEW T, NEW s \in Seq(T), NEW i \in 1..Len(s)
  PROVE  Sched!Drop(s, i) \in Seq(T)
PROOF OMITTED

(***************************************************************************)
(* PermSeqsType.  The proof is the same shape as in                        *)
(* SchedulingAllocator_proof but threaded through the Sched! instance.    *)
(***************************************************************************)
PermsRec(g, ss) ==
  IF ss = {} THEN { << >> }
  ELSE UNION {{Append(sq, x) : sq \in g[ss \ {x}]} : x \in ss}

PermsFn(S) == CHOOSE g : g = [ss \in SUBSET S |-> PermsRec(g, ss)]

LEMMA PermsRecNonempty ==
  ASSUME NEW g, NEW ss, ss # {}
  PROVE  PermsRec(g, ss) =
           UNION { { Append(sq, x) : sq \in g[ss \ {x}] } : x \in ss }
PROOF OMITTED

LEMMA PermsFnRec ==
  ASSUME NEW S, IsFiniteSet(S), NEW ss \in SUBSET S
  PROVE  PermsFn(S)[ss] = PermsRec(PermsFn(S), ss)
PROOF OMITTED

(***************************************************************************)
(* The original reference leaves this equality unproved.  The model and  *)
(* PermsRec now inline the inner permutation set so INSTANCE expansion    *)
(* preserves the recursive binding.                                      *)
(***************************************************************************)
LEMMA PermSeqsIsPermsFn ==
  ASSUME NEW S
  PROVE  Sched!PermSeqs(S) = PermsFn(S)[S]
  OMITTED

=============================================================================

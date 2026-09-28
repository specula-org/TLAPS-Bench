--------------------- MODULE SchedulingAllocator_proof_PermSeqsTypeScaffold ---------------------
(***************************************************************************)
(* TLAPS proofs of the safety theorems stated in SchedulingAllocator.tla:  *)
(*                                                                         *)
(*   Allocator => []TypeInvariant                                          *)
(*   Allocator => []ResourceMutex                                          *)
(*                                                                         *)
(* TypeInvariant is directly inductive (the only subtlety is that         *)
(* Drop(sched, i) and sched \circ sq stay in Seq(Clients)).  ResourceMutex *)
(* uses the same argument as in SimpleAllocator: an Allocate(c, S) action *)
(* takes S from `available`, so S is disjoint from every alloc[c'].       *)
(*                                                                         *)
(* AllocatorInvariant is left as future work; its preservation across the *)
(* Schedule action requires careful reasoning about Range(sched \circ sq) *)
(* and the way toSchedule changes.                                       *)
(***************************************************************************)
EXTENDS SchedulingAllocator, Integers, SequenceTheorems,
        FiniteSets, FiniteSetTheorems, WellFoundedInduction, TLAPS

(***************************************************************************)
(* The PermSeqs proof needs Clients to be finite (PermSeqs is the set of   *)
(* permutation sequences over a finite set; the recursion well-founds only *)
(* over finite subsets).  Resources is already finite by the spec's        *)
(* SchedulingAllocatorAssumptions; we add Clients here.                    *)
(***************************************************************************)
ASSUME ClientsFinite == IsFiniteSet(Clients)

(***************************************************************************)
(*                          Allocator => []TypeInvariant                   *)
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
  PROVE  Drop(s, i) \in Seq(T)
PROOF OMITTED

(***************************************************************************)
(* Permutations of a finite set, packaged as sequences, are sequences over *)
(* (a superset of) the set.  The recursion in PermSeqs builds each output *)
(* by Append-ing elements of S, so the result is a sequence whose elements *)
(* are all from S \subseteq T.                                             *)
(*                                                                         *)
(* The proof has the same shape as MaximumProp in PaxosCommit_proof:       *)
(*   - PermsRec / PermsFn give the inner CHOOSE-defined recursive function;*)
(*   - PermsFnRec is the recursion equation (via WFInductiveDef);          *)
(*   - PermSeqsIsPermsFn ties PermSeqs(S) to PermsFn(S)[S];                *)
(*   - PermSeqsType then proves the property by FS_WFInduction.            *)
(***************************************************************************)
PermsRec(g, ss) ==
  IF ss = {} THEN { << >> }
  ELSE UNION {{Append(sq, x) : sq \in g[ss \ {x}]} : x \in ss}

PermsFn(S) == CHOOSE g : g = [ss \in SUBSET S |-> PermsRec(g, ss)]

(***************************************************************************)
(* Equivalent unfold-form for non-empty ss; the LET binding can be         *)
(* eliminated by substituting ps[x] inline.                                 *)
(***************************************************************************)
LEMMA PermsRecNonempty ==
  ASSUME NEW g, NEW ss, ss # {}
  PROVE  PermsRec(g, ss) =
           UNION { { Append(sq, x) : sq \in g[ss \ {x}] } : x \in ss }
PROOF OMITTED

LEMMA PermsFnRec ==
  ASSUME NEW S, IsFiniteSet(S), NEW ss \in SUBSET S
  PROVE  PermsFn(S)[ss] = PermsRec(PermsFn(S), ss)
PROOF OMITTED

LEMMA PermSeqsIsPermsFn ==
  ASSUME NEW S
  PROVE  PermSeqs(S) = PermsFn(S)[S]
PROOF OMITTED

=============================================================================

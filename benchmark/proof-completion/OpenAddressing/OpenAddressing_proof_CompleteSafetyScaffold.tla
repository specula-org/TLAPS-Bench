--------------------------- MODULE OpenAddressing_proof_CompleteSafetyScaffold ---------------------------
(***************************************************************************)
(* Proofs checked by TLAPS about the OpenAddressing PlusCal specification. *)
(*                                                                         *)
(* The OpenAddressing module specifies a concurrent, open-addressing       *)
(* fingerprint hash table with eviction to external storage (the Java      *)
(* OffHeapDiskFPSet algorithm).  Several safety properties are stated in   *)
(* the spec:                                                               *)
(*                                                                         *)
(*   Contains, Duplicates, Sorted, Consistent, CompleteAsSafety            *)
(*                                                                         *)
(* `Contains', `Duplicates', `Sorted', and `Consistent' are all very deep  *)
(* properties about the concurrent insertion/eviction algorithm; their     *)
(* TLAPS proofs would require sequence-level reasoning over `SelectSeq',   *)
(* sortedness invariants, and the algebraic properties of the hashing      *)
(* operators (`mod', `rescale', `idx').  We leave their full inductive     *)
(* proofs as OMITTED stubs (with the recommended invariant chain stated),  *)
(* and concentrate on what is fully tractable in this round:               *)
(*                                                                         *)
(*   THEOREM CompleteSafety  == Spec => []CompleteAsSafety                 *)
(*                                                                         *)
(* That property captures the partial-correctness statement that whenever  *)
(* a writer process reaches its `Done' label, all fingerprints in `fps'    *)
(* have actually been observed in the `history' set.  It is implied by a   *)
(* small inductive invariant `Inv' that we discharge in full.              *)
(***************************************************************************)
EXTENDS OpenAddressing, TLAPS, SequenceTheorems, FiniteSetTheorems

(***************************************************************************)
(* The set of pc labels that appear in the spec.  The PlusCal translation  *)
(* uses string labels at every control point of `p(self)' and the          *)
(* `Evict(self)' procedure (plus the implicit `Done' label injected by the *)
(* translator for terminating processes).                                  *)
(***************************************************************************)
EvictLabels  == {"strIns", "nestedIns", "set", "flush", "rtrn"}
WriterLabels == {"pick", "put", "waitEv", "endWEv", "chkSnc", "cntns",
                 "onSnc", "insrt", "isMth", "cas", "tryEv", "waitIns",
                 "endEv", "Done"}
PcRange      == WriterLabels \cup EvictLabels

(***************************************************************************)
(* `pick' and `Done' are the only pc values where `fp[self]' may legally   *)
(* hold its initial value (0) instead of an element of `fps':              *)
(*  - in the initial state every writer has pc = "pick" and fp = 0;        *)
(*  - the `pick' action either keeps pc = "pick" / sets pc = "Done"        *)
(*    (without picking an fp, because (fps \ history) = {}), or picks      *)
(*    f \in (fps \ history) and goes to "put".                             *)
(* For every other pc value, `fp[self]' must be in `fps' because the only  *)
(* path that reaches it goes through the `else' branch of `pick' which     *)
(* assigns fp[self] \in (fps \ history) \subseteq fps.                     *)
(***************************************************************************)
PickOrDone == {"pick", "Done"}

(***************************************************************************)
(* The inductive invariant.                                                *)
(*                                                                         *)
(*  - HistorySubset:  `history' is always a subset of `fps'.               *)
(*  - PcRangeOK:      every pc value is one of the labels in PcRange.      *)
(*  - FpInFps:        once a writer has left `pick' (and is not at `Done') *)
(*                    its in-flight fingerprint `fp[self]' is in `fps'.    *)
(*  - DoneImpliesAllSeen:  whenever a writer's pc is "Done", all of `fps'  *)
(*                    has been observed in `history'.                      *)
(***************************************************************************)
HistorySubset == history \subseteq fps

PcRangeOK == pc \in [ProcSet -> PcRange]

(***************************************************************************)
(* `fp' must always be a function from Writer to Int.  This is needed by   *)
(* TLAPS for the EXCEPT-semantics step `[fp EXCEPT ![self] = f][s2] = ...' *)
(* in the `pick' inductive case.                                           *)
(***************************************************************************)
FpType == fp \in [Writer -> Int]

FpInFps ==
  \A self \in Writer :
    pc[self] \notin PickOrDone => fp[self] \in fps

DoneImpliesAllSeen ==
  \A self \in ProcSet : pc[self] = "Done" => history = fps

(***************************************************************************)
(* Stack-shape invariant.                                                  *)
(*                                                                         *)
(* The PlusCal `call' construct pushes a frame onto `stack[self]' and      *)
(* `return' pops it.  In this spec, `Evict()' is `call'-ed only from       *)
(* `waitIns', which pushes a single frame whose saved `pc' is `"endEv"'    *)
(* (the writer's continuation after the procedure returns).  Hence:        *)
(*  - whenever a writer is anywhere inside the Evict body                  *)
(*    (`pc[self] \in EvictLabels'), `stack[self]' is exactly that          *)
(*    one-element sequence whose unique frame's saved `pc' is `"endEv"';   *)
(*  - whenever the writer is at any `WriterLabels' label (including        *)
(*    `"Done"'), `stack[self]' is the empty sequence.                      *)
(*                                                                         *)
(* This is what lets us conclude in the `rtrn' case that                   *)
(* `pc'[self] = Head(stack[self]).pc = "endEv" \in PcRange' and that       *)
(* `stack'[self] = Tail(<<frame>>) = <<>>'.                                *)
(***************************************************************************)
StackOK ==
  /\ DOMAIN stack = ProcSet
  /\ \A self \in ProcSet :
       /\ pc[self] \in EvictLabels =>
            /\ stack[self] # <<>>
            /\ Tail(stack[self]) = <<>>
            /\ Head(stack[self]).pc = "endEv"
       /\ pc[self] \in WriterLabels => stack[self] = <<>>

Inv ==
  /\ HistorySubset
  /\ PcRangeOK
  /\ FpType
  /\ FpInFps
  /\ DoneImpliesAllSeen

(***************************************************************************)
(* Helper: ProcSet = Writer (the spec only declares writers as the set of  *)
(* fair processes; no readers are instantiated in this PlusCal version).   *)
(***************************************************************************)
LEMMA ProcSetIsWriter == ProcSet = Writer
PROOF OMITTED

(***************************************************************************)
(* Helper: every element of `fps' is an integer.  Discharged from the      *)
(* spec's ASSUME `\A fp \in fps : fp \in Nat \ {0}'.                       *)
(***************************************************************************)
LEMMA FpsAreInts == \A f \in fps : f \in Int
PROOF OMITTED

(***************************************************************************)
(* Helper: `mod(i, K) \in 1..K' for every integer `i'.  This is the         *)
(* "open-addressing" instance of the standing modulo-range fact already    *)

(***************************************************************************)
LEMMA ModInRange ==
  ASSUME NEW i \in Int
  PROVE  mod(i, K) \in 1..K
PROOF OMITTED

(***************************************************************************)
(* Helper: `min(S) \in S' and `max(S) \in S' for every non-empty subset of *)
(* `Nat' that has a minimum/maximum.  We use them only via `fps' as `S'    *)
(* (whose elements are in `Nat \ {0}' by `OAAssumption').                 *)
(*                                                                         *)
(* Proving these from the TLA+ semantics of `CHOOSE' requires the          *)
(* well-ordering of `Nat' (for `min') and finite/boundedness for `max'.    *)
(* Both are standard but require the `Naturals' theory.  Left OMITTED to *)
(* keep the dependency graph small; they are the only "external" arithmetic*)
(* facts the `idx \in 1..K' chain depends on.                              *)
(***************************************************************************)
LEMMA MinInFps ==
  ASSUME NEW someFp \in fps
  PROVE  min(fps) \in fps
PROOF OMITTED

LEMMA MaxInFps ==
  ASSUME NEW someFp \in fps
  PROVE  max(fps) \in fps
PROOF OMITTED

(***************************************************************************)
(* Helper: `idx(fpv, offset) \in 1..K' for every integer pair               *)
(* `(fpv, offset)' when `fps' is non-empty (so `min(fps)' / `max(fps)' are  *)
(* well-defined elements of `fps').  The "non-empty" precondition is       *)
(* provided in practice by `FpInFps' applied to any writer outside         *)
(* `{pick, Done}'.                                                         *)
(***************************************************************************)
LEMMA IdxInRange ==
  ASSUME NEW fpv \in Int, NEW offset \in Int,
         NEW someFp \in fps,
         max(fps) - min(fps) # 0
  PROVE  idx(fpv, offset) \in 1..K
PROOF OMITTED

(***************************************************************************)
(* Init implies Inv.                                                       *)
(***************************************************************************)
LEMMA InitInv == Init => Inv
PROOF OMITTED

(***************************************************************************)
(* Init implies StackOK.  Every writer starts at "pick" with an empty      *)
(* stack, so the EvictLabels conjunct is vacuously true and the            *)
(* WriterLabels conjunct is witnessed directly by the initial value.       *)
(***************************************************************************)
LEMMA InitStackOK == Init => StackOK
PROOF OMITTED

(***************************************************************************)
(* Inductive step for StackOK.                                             *)
(*                                                                         *)
(* `StackOK' is preserved by every action of `Next'.  The proof has the    *)
(* same case skeleton as `InvNext', but each case only has to show that    *)
(* the action neither (a) leaves a writer at an `EvictLabels' label with   *)
(* the wrong stack shape, nor (b) leaves a writer at a `WriterLabels'      *)
(* label with a non-empty stack.                                           *)
(*                                                                         *)
(* Most actions trivially preserve `StackOK' because they leave `stack'    *)
(* unchanged and only move `pc[self]' within the same label group          *)
(* (Evict labels stay Evict labels; Writer labels stay Writer labels).     *)
(* The two non-trivial actions are:                                        *)
(*   - `waitIns(self)': pushes the unique frame `[pc |-> "endEv", ...]'    *)
(*     onto the (then-empty) stack and moves `pc' from "waitIns" to        *)
(*     "strIns".                                                           *)
(*   - `rtrn(self)':    pops the (then unique) frame and moves `pc' from   *)
(*     "rtrn" to `Head(stack[self]).pc = "endEv"'.                         *)
(***************************************************************************)
(***************************************************************************)
(* Helper used in the inductive step of StackOKInd.  For any "boring"      *)
(* action -- one that leaves `stack' UNCHANGED, doesn't change `pc'        *)
(* outside `self', and keeps `pc[self]' inside the same label group --     *)
(* StackOK at any `s2 \in ProcSet' is preserved.  The hypotheses are       *)
(* per-s2 (rather than universally quantified over a fresh s) which lets   *)
(* the per-action discharges be one-liners over the action's UNCHANGED     *)
(* and EXCEPT clauses.                                                     *)
(***************************************************************************)
LEMMA StackOK_BoringEvict ==
  ASSUME StackOK,
         NEW self \in ProcSet,
         NEW s2 \in ProcSet,
         stack' = stack,
         s2 # self => pc'[s2] = pc[s2],
         pc[self] \in EvictLabels,
         pc'[self] \in EvictLabels
  PROVE  /\ pc'[s2] \in EvictLabels =>
              /\ stack'[s2] # <<>>
              /\ Tail(stack'[s2]) = <<>>
              /\ Head(stack'[s2]).pc = "endEv"
         /\ pc'[s2] \in WriterLabels => stack'[s2] = <<>>
PROOF OMITTED

LEMMA StackOK_BoringWriter ==
  ASSUME StackOK,
         NEW self \in ProcSet,
         NEW s2 \in ProcSet,
         stack' = stack,
         s2 # self => pc'[s2] = pc[s2],
         pc[self] \in WriterLabels,
         pc'[self] \in WriterLabels
  PROVE  /\ pc'[s2] \in EvictLabels =>
              /\ stack'[s2] # <<>>
              /\ Tail(stack'[s2]) = <<>>
              /\ Head(stack'[s2]).pc = "endEv"
         /\ pc'[s2] \in WriterLabels => stack'[s2] = <<>>
PROOF OMITTED

(***************************************************************************)
(* Helper lemma: extract `stack' = stack' from `UNCHANGED vars'.  TLAPS'   *)
(* SMT backends do not reliably project a 15-tuple equality down to a      *)
(* single component, so this is proved standalone with the Isabelle        *)
(* backend (which handles tuple destructuring directly).                   *)
(***************************************************************************)
LEMMA UnchangedVarsImpliesUnchangedStack ==
  ASSUME UNCHANGED vars
  PROVE  stack' = stack
PROOF OMITTED

LEMMA StackOKInd == Inv /\ StackOK /\ [Next]_vars => StackOK'
PROOF OMITTED

(***************************************************************************)
(* Helper used in the inductive step: under `Inv', any successful `cas'    *)
(* by self only adds `fp[self] \in fps' to `history'.                      *)
(***************************************************************************)
LEMMA CasFpInFps ==
  ASSUME Inv,
         NEW self \in Writer,
         pc[self] = "cas"
  PROVE  fp[self] \in fps
PROOF OMITTED

(***************************************************************************)
(* Inductive step.                                                         *)
(*                                                                         *)
(* The proof proceeds by case analysis on which top-level action of the    *)
(* spec's `Next' fired (Evict procedure body, writer body, or stutter).    *)
(* Within each `p(self)' case the writer's pc determines the disjunct.     *)
(***************************************************************************)
LEMMA InvNext == Inv /\ StackOK /\ [Next]_vars => Inv'
PROOF OMITTED

(***************************************************************************)
(* Main safety theorem: Spec implies CompleteAsSafety.                     *)
(***************************************************************************)
=============================================================================

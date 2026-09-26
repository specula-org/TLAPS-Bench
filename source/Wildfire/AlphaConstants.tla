
-------------------------- MODULE AlphaConstants ----------------------------
(***************************************************************************)
(* This module declares the constant parameters of the specification and   *)
(* defines some useful constants and constant operators.                   *)
(***************************************************************************)

EXTENDS AlphaInterface, Sequences
  (*************************************************************************)
  (* Imports the declarations and definitions from module AlphaInterface   *)
  (* (and hence the ones from modules Naturals and FiniteSets) and module  *)
  (* Sequences.  The Sequences module defines:                             *)
  (*                                                                       *)
  (*    Seq(S)       : The set of all finite sequences whose elements are  *)
  (*                   in S.                                               *)
  (*    Len(s)       : The length of the sequence s.                       *)
  (*    Head(s)      : The first element of sequence s.                    *)
  (*    Tail(s)      : The tail of sequence s.                             *)
  (*    Append(s, e) : The sequence obtained by appending the element e    *)
  (*                   to the end of sequence s.                           *)
  (*    s \o t       : The sequence obtained by concatenating sequences    *)
  (*                   s and t.                                            *)
  (*                                                                       *)
  (* Sequences are functions, so s[i] is the i-th element of a sequence s. *)
  (* Hence, Head(s) = s[1].  In TLA+, tuples are also sequences, so << >>  *)
  (* is the empty sequence, <<a, b, c>>[2] = b, and Append(s, e) equals    *)
  (* s \o <<e>>.                                                           *)
  (*************************************************************************)
-----------------------------------------------------------------------------
AllOnes == [n \in 0..(DataLen - 1) |-> 1]
  (*************************************************************************)
  (* A Data value consisting of all ones.  (It is used as a mask for a     *)
  (* full block write.)  In TLA+, [x \in S |-> ...] is the function f with *)
  (* domain S such that f[x] = ...  for all x in S.                        *)
  (*************************************************************************)

NotChosen == CHOOSE nc : nc \notin Data
Failed    == CHOOSE f  : f  \notin Data \cup {NotChosen}
  (*************************************************************************)
  (* Two distinct, arbitrary values that are not elements of Data.         *)
  (* NotChosen represents a value not yet chosen, and Failed is a value    *)
  (* assigned to a Failed SC.                                              *)
  (*                                                                       *)
  (* In TLA+, CHOOSE x : P(x) equals some unique, arbitrary value v such   *)
  (* that P(v) is true (if there is such a value).  The CHOOSE operator is *)
  (* known in logic as Hilbert's epsilon.                                  *)
  (*************************************************************************)

NoSource    == CHOOSE ns : ns \notin [proc : Proc, idx : Nat]
FromInitMem == CHOOSE fm : fm \notin [proc : Proc, idx : Nat] \cup {NoSource}
  (*************************************************************************)
  (* An element of the set [proc : Proc, idx : Nat] of records will be     *)
  (* used to identify a request, where [proc |-> p, idx |-> i], the record *)
  (* r with r.proc = p and r.idx = i, identifies the i-th request from     *)
  (* processor p.  NoSource and FromInitMem are two arbitrary, distinct    *)
  (* values that are not elements of this set of request identifiers.      *)
  (*************************************************************************)

MaskVal(old, mask, new) ==
  (*************************************************************************)
  (* The result of storing the Data value new through the mask to an       *)
  (* address that contains the value old.                                  *)
  (*************************************************************************)
  [i \in 0..(DataLen-1) |-> IF mask[i]=1 THEN new[i] ELSE old[i]]

=============================================================================
Last modified on Mon Jun 12 17:24:12 PDT 2000 by lamport

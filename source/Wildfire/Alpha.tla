------------------------------ MODULE Alpha ---------------------------------

(***************************************************************************)
(* This is the complete specification of the Alpha memory module.          *)
(***************************************************************************)
EXTENDS AlphaInterface

Inner(InitMem, reqSeq, beforeOrder) == INSTANCE InnerAlpha
  (*************************************************************************)
  (* For any defined formula F of InnerAlpha, this defines                 *)
  (* Inner(im, rs, bo)!F to be F with the substitutions InitMem <- im,     *)
  (* reqSeq <- rs, and beforeOrder <- bo.                                  *)
  (*************************************************************************)

Spec ==
  (*************************************************************************)
  (* This is the TLA formula that describes the legal behaviors of an      *)
  (* Alpha memory.  It is a temporal formula whose only free variable is   *)
  (* aInt.  It has the free constant parameters RequestFromEnv,            *)
  (* ResponseToEnv, Proc, Adr, and DataLen.  Specifying values for these   *)
  (* constant parameters yields a temporal formula whose value on a        *)
  (* behavior depends only on the values of aInt.  This formula is         *)
  (* satisfied by a behavior iff the sequence of values the behavior       *)
  (* assigns to aInt describes a correct execution of the Alpha memory     *)
  (* system--that is, of both the memory and the processors.               *)
  (*                                                                       *)
  (* The formula Spec is obtained by hiding (existentially quantifying     *)
  (* over) the constant InitMem and the variables reqSeq and beforeOrder.  *)
  (* The TLA+ operator \EE is temporal existential quantification over     *)
  (* (flexible) variables.                                                 *)
  (*************************************************************************)
  \E InitMem \in [Adr -> Data] :
    \EE reqSeq, beforeOrder : Inner(InitMem, reqSeq, beforeOrder)!InnerSpec
=============================================================================
Last modified on Mon Jun 12 18:02:08 PDT 2000 by lamport


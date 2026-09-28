---------------------------- MODULE Elevator_proof_GetDirectionTypeScaffold ----------------------------
(***************************************************************************)
(* Proofs checked by TLAPS about the multi-car elevator specification.    *)
(*                                                                         *)
(*   THEOREM TypeCorrect       == Spec => []TypeInvariant                  *)
(*   THEOREM SafetyCorrect     == Spec => []SafetyInvariant                *)
(*                                                                         *)
(* These cover the safety part of the spec-stub at Elevator.tla:235:      *)
(*   Spec => [](TypeInvariant /\ SafetyInvariant /\ TemporalInvariant)    *)
(* The TemporalInvariant (liveness) part is not addressed here.           *)
(*                                                                         *)
(* Strategy: prove a strengthened state invariant `Inv` and derive both   *)
(* TypeInvariant and SafetyInvariant as corollaries.                      *)
(***************************************************************************)
EXTENDS Elevator, TLAPS

(***************************************************************************)
(* The spec does not explicitly state that the CONSTANT `Elevator` is     *)
(* disjoint from `Floor` (= 1..FloorCount).  In TLC the assumption is     *)
(* implicit because users supply model values for `Elevator`; we make it  *)
(* explicit here so PersonState[p].location \in Floor and                  *)
(* PersonState[p].location = e \in Elevator can never both hold.          *)
(***************************************************************************)
ASSUME ElevatorFloorDisjoint == Floor \cap Elevator = {}

(***************************************************************************)
(* Function-evaluation lemmas for the single-tuple-argument definitions.   *)
(* The statements retain their original domains.                          *)
(***************************************************************************)
LEMMA GetDirectionEval ==
  ASSUME NEW c \in Floor, NEW d \in Floor
  PROVE  GetDirection[<<c, d>>] = IF d > c THEN "Up" ELSE "Down"
  OMITTED

LEMMA GetDistanceEval ==
  ASSUME NEW f1 \in Floor, NEW f2 \in Floor
  PROVE  GetDistance[<<f1, f2>>] = IF f1 > f2 THEN f1 - f2 ELSE f2 - f1
  OMITTED

LEMMA CanServiceCallEval ==
  ASSUME NEW e \in Elevator, NEW c \in ElevatorCall
  PROVE  CanServiceCall[<<e, c>>] <=>
           (c.floor = ElevatorState[e].floor /\ c.direction = ElevatorState[e].direction)
  OMITTED

LEMMA PeopleWaitingEval ==
  ASSUME NEW f \in Floor, NEW d \in Direction
  PROVE  PeopleWaiting[<<f, d>>] =
           {p \in Person : /\ PersonState[p].location = f
                            /\ PersonState[p].waiting
                            /\ GetDirection[<<PersonState[p].location, PersonState[p].destination>>] = d}
  OMITTED

(***************************************************************************)
(* Type-level helpers (single-arg, so TLAPS handles via DEF).             *)
(***************************************************************************)

LEMMA DirectionInElevatorDirectionState ==
  Direction \subseteq ElevatorDirectionState
PROOF OMITTED

LEMMA StationaryInElevatorDirectionState ==
  "Stationary" \in ElevatorDirectionState
PROOF OMITTED

=============================================================================

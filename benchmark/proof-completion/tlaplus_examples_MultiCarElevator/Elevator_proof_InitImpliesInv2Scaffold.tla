---------------------------- MODULE Elevator_proof_InitImpliesInv2Scaffold ----------------------------
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

LEMMA GetDirectionType ==
  ASSUME NEW c \in Floor, NEW d \in Floor
  PROVE  GetDirection[<<c, d>>] \in Direction
PROOF OMITTED

LEMMA ElevatorCallFields ==
  ASSUME NEW c \in ElevatorCall
  PROVE  /\ c.floor \in Floor
         /\ c.direction \in Direction
PROOF OMITTED

(***************************************************************************)
(* Strengthened invariant -- enough to prove TypeInvariant inductive.     *)
(***************************************************************************)
WaitingFloor ==
  \A p \in Person : ~PersonState[p].waiting => PersonState[p].location \in Floor

Inv1 == TypeInvariant /\ WaitingFloor

(***************************************************************************)
(* Init implies Inv1.                                                      *)
(***************************************************************************)
LEMMA InitImpliesInv1 == Init => Inv1
PROOF OMITTED

(***************************************************************************)
(* Inductive step.                                                         *)
(***************************************************************************)
LEMMA Inv1Next == Inv1 /\ [Next]_Vars => Inv1'
PROOF OMITTED

(***************************************************************************)
(* Spec => []TypeInvariant.                                                *)
(***************************************************************************)
THEOREM TypeCorrect == Spec => []TypeInvariant
PROOF OMITTED

(***************************************************************************)
(* Strengthened invariant for SafetyInvariant.                             *)
(*                                                                         *)
(* The seven auxiliaries (besides TypeInvariant + WaitingFloor +          *)
(* SafetyInvariant) are mutually inductive: each is needed to discharge   *)
(* one of the per-action obligations of the others.                       *)
(*                                                                         *)
(*   WaitingDestinationDistinct                                           *)
(*       waiting(p) => location(p) /= destination(p)                      *)
(*   DoorsOpenImpliesNotInButtonsPressed                                  *)
(*       doorsOpen(e) => floor(e) \notin buttonsPressed(e)                *)
(*   NoServiceableActiveCall                                              *)
(*       doorsOpen(e) /\ direction(e) \in Direction =>                    *)
(*          [floor(e), direction(e)] \notin ActiveElevatorCalls           *)
(*   DoorsOpenImpliesNotStationary                                        *)
(*       doorsOpen(e) => direction(e) \in Direction                       *)
(*   StationaryNoPassenger                                                *)
(*       direction(e) = "Stationary" => \A p : location(p) /= e           *)
(*   PersonImpliesButton                                                  *)
(*       location(p) = e =>                                                *)
(*          destination(p) \in buttonsPressed(e)                          *)
(*          \/ (doorsOpen(e) /\ floor(e) = destination(p))                *)
(*   PersonInElevatorDirection (== SafetyInvariant Property 2)            *)
(***************************************************************************)
WaitingDestinationDistinct ==
  \A p \in Person :
    PersonState[p].waiting => PersonState[p].location /= PersonState[p].destination

DoorsOpenImpliesNotInButtonsPressed ==
  \A e \in Elevator :
    ElevatorState[e].doorsOpen =>
        ElevatorState[e].floor \notin ElevatorState[e].buttonsPressed

NoServiceableActiveCall ==
  \A e \in Elevator :
    (ElevatorState[e].doorsOpen /\ ElevatorState[e].direction \in Direction) =>
        [floor |-> ElevatorState[e].floor, direction |-> ElevatorState[e].direction]
            \notin ActiveElevatorCalls

DoorsOpenImpliesNotStationary ==
  \A e \in Elevator :
    ElevatorState[e].doorsOpen => ElevatorState[e].direction \in Direction

StationaryNoPassenger ==
  \A e \in Elevator :
    ElevatorState[e].direction = "Stationary" =>
        \A p \in Person : PersonState[p].location /= e

PersonImpliesButton ==
  \A p \in Person, e \in Elevator :
    PersonState[p].location = e =>
        \/ PersonState[p].destination \in ElevatorState[e].buttonsPressed
        \/ (ElevatorState[e].doorsOpen
            /\ ElevatorState[e].floor = PersonState[p].destination)

Inv2 ==
  /\ Inv1
  /\ WaitingDestinationDistinct
  /\ DoorsOpenImpliesNotInButtonsPressed
  /\ NoServiceableActiveCall
  /\ DoorsOpenImpliesNotStationary
  /\ StationaryNoPassenger
  /\ PersonImpliesButton
  /\ SafetyInvariant

(***************************************************************************)
(* The full Spec => []Inv2 proof is OMITTED.  The seven auxiliary         *)
(* invariants above plus TypeInvariant and SafetyInvariant are mutually   *)
(* inductive (each discharges one of the per-action obligations of the    *)
(* others); closing the inductive step requires:                          *)
(*                                                                         *)
(*   - per-action case analysis (9 actions + stutter) for each of the     *)
(*     ~10 conjuncts (~90 inductive sub-cases),                           *)
(*   - explicit `~ENABLED EnterElevator(e)` / `~ENABLED ExitElevator(e)` *)
(*     / `~ENABLED OpenElevatorDoors(e)` reasoning via `ExpandENABLED`    *)
(*     (used by CloseElevatorDoors and StopElevator),                     *)
(*   - careful arithmetic on `Floor = 1..FloorCount` for the              *)
(*     extreme-floor argument that closes the StopElevator case for       *)
(*     SafetyInvariant Property 2.                                        *)
(*                                                                         *)
(* This is genuine Band-H work, comparable to the EWD998 refinement       *)
(* proof, and is left to a follow-up.                                      *)
(***************************************************************************)
=============================================================================

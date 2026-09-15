---------------------------- MODULE Elevator_proofDefs ----------------------------

EXTENDS Elevator, TLAPS

ASSUME ElevatorFloorDisjoint == Floor \cap Elevator = {}

=============================================================================

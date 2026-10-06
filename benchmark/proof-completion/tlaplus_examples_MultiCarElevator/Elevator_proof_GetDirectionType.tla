---- MODULE Elevator_proof_GetDirectionType ----
EXTENDS Elevator_proof_GetDirectionTypeScaffold
LEMMA GetDirectionType ==
  ASSUME NEW c \in Floor, NEW d \in Floor
  PROVE  GetDirection[<<c, d>>] \in Direction
\* BEGIN AGENT PROOF
PROOF OBVIOUS
\* END AGENT PROOF
====

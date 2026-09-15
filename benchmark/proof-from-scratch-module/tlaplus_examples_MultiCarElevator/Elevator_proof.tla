---- MODULE Elevator_proof ----
EXTENDS Elevator_proofDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeInvariant
\* BEGIN AGENT PROOF tlaplus_examples_MultiCarElevator/Elevator_proof_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_MultiCarElevator/Elevator_proof_TypeCorrect.tla

THEOREM SafetyCorrect == Spec => []SafetyInvariant
\* BEGIN AGENT PROOF tlaplus_examples_MultiCarElevator/Elevator_proof_SafetyCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_MultiCarElevator/Elevator_proof_SafetyCorrect.tla
====

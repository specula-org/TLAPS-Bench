---- MODULE ivy_examples_alternating_bit_protocol ----
EXTENDS ivy_examples_alternating_bit_protocolDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM Safety == SafetySpec => []ReceiverValuesFromSender
\* BEGIN AGENT PROOF ivy_examples_alternating_bit_protocol/ivy_examples_alternating_bit_protocol_Safety.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_alternating_bit_protocol/ivy_examples_alternating_bit_protocol_Safety.tla

THEOREM Liveness == Spec => DataDelivery
\* BEGIN AGENT PROOF ivy_examples_alternating_bit_protocol/ivy_examples_alternating_bit_protocol_Liveness.tla
PROOF OMITTED
\* END AGENT PROOF ivy_examples_alternating_bit_protocol/ivy_examples_alternating_bit_protocol_Liveness.tla
====

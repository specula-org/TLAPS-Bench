-------------------------- MODULE WildfireProof_RefinementDefs ---------------------------
EXTENDS Wildfire

RecordRequest(old, new, p, r) ==
    new = Append(old, [kind |-> "request", proc |-> p, value |-> r])

RecordResponse(old, new, p, r) ==
    new = Append(old, [kind |-> "response", proc |-> p, value |-> r])

Protocol == INSTANCE Wildfire
    WITH RequestFromEnv <- RecordRequest, ResponseToEnv <- RecordResponse

AlphaModel == INSTANCE Alpha
    WITH RequestFromEnv <- RecordRequest, ResponseToEnv <- RecordResponse

TraceSpec == Protocol!Spec /\ aInt = <<>>

=============================================================================

---- MODULE CCFProofDefs ----
EXTENDS ccfraft

ASSUME DistinctProtocolLabels ==
    /\ Cardinality({Follower, PreVoteCandidate, Candidate, Leader, None}) = 5
    /\ Cardinality({Active, RetirementOrdered, RetirementSigned,
                    RetirementCompleted, RetiredCommitted}) = 5
    /\ Cardinality({RequestVoteRequest, RequestVoteResponse,
                    AppendEntriesRequest, AppendEntriesResponse, ProposeVoteRequest}) = 5
    /\ Cardinality({TypeEntry, TypeSignature, TypeReconfiguration, TypeRetired}) = 4
    /\ Cardinality({PreVoteDisabled, PreVoteCapable, PreVoteEnabled}) = 3
    /\ Cardinality({OrderedNoDup, Ordered, ReorderedNoDup, Reordered}) = 4

ASSUME OrderedNetwork == Guarantee = OrderedNoDup

====

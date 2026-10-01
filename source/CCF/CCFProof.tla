---- MODULE CCFProof ----
EXTENDS ccfraft

\* Protocol enum values are distinct, as in upstream MCccfraft.cfg.
ASSUME DistinctProtocolLabels ==
    /\ Cardinality({Follower, PreVoteCandidate, Candidate, Leader, None}) = 5
    /\ Cardinality({Active, RetirementOrdered, RetirementSigned,
                    RetirementCompleted, RetiredCommitted}) = 5
    /\ Cardinality({RequestVoteRequest, RequestVoteResponse,
                    AppendEntriesRequest, AppendEntriesResponse, ProposeVoteRequest}) = 5
    /\ Cardinality({TypeEntry, TypeSignature, TypeReconfiguration, TypeRetired}) = 4
    /\ Cardinality({PreVoteDisabled, PreVoteCapable, PreVoteEnabled}) = 3
    /\ Cardinality({OrderedNoDup, Ordered, ReorderedNoDup, Reordered}) = 4

\* CCF's authenticated node channels preserve order and suppress duplicates.
\* INSTANCE Network does not import that module's assumptions.
ASSUME OrderedNetwork == Guarantee = OrderedNoDup

THEOREM CommittedLogsAgree == Spec => []LogInv
PROOF OMITTED

THEOREM CommittedLogsAppendOnly == Spec => CommittedLogAppendOnlyProp
PROOF OMITTED

====

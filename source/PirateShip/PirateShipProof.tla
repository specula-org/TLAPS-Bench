---- MODULE PirateShipProof ----
EXTENDS PirateShip

THEOREM TypeOKCorrect == Spec => []TypeOK
PROOF OMITTED

THEOREM IndexBoundsInvCorrect == Spec => []IndexBoundsInv
PROOF OMITTED

THEOREM BranchInvCorrect == Spec => []BranchInv
PROOF OMITTED

THEOREM AuditBranchInvCorrect == Spec => []AuditBranchInv
PROOF OMITTED

THEOREM OneLeaderPerViewInvCorrect == Spec => []OneLeaderPerViewInv
PROOF OMITTED

THEOREM WellFormedBranchInvCorrect == Spec => []WellFormedBranchInv
PROOF OMITTED

THEOREM ViewMonotonicInvCorrect == Spec => []ViewMonotonicInv
PROOF OMITTED

THEOREM ViewStabilizationInvCorrect == Spec => []ViewStabilizationInv
PROOF OMITTED

THEOREM CommittedBranchAppendOnlyPropCorrect == Spec => CommittedBranchAppendOnlyProp
PROOF OMITTED

THEOREM AuditedBranchAppendOnlyPropCorrect == Spec => AuditedBranchAppendOnlyProp
PROOF OMITTED

THEOREM MonotonicAuditedIndexPropCorrect == Spec => MonotonicAuditedIndexProp
PROOF OMITTED

====

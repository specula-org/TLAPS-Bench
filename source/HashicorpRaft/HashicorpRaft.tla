---- MODULE HashicorpRaft ----
EXTENDS HashicorpRaftRuntime

THEOREM LeaderCompletenessCorrect == Spec => []LeaderCompleteness
PROOF OMITTED

THEOREM StateMachineSafetyCorrect == Spec => []StateMachineSafety
PROOF OMITTED

THEOREM CommittedEntriesPreservedCorrect == Spec => []CommittedEntriesPreserved
PROOF OMITTED

THEOREM LogMatchingCorrect == Spec => []LogMatching
PROOF OMITTED

THEOREM ElectionSafetyCorrect == Spec => []ElectionSafety
PROOF OMITTED

THEOREM ConfigurationSafetyCorrect == Spec => []ConfigurationSafety
PROOF OMITTED

====

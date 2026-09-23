---- MODULE HashicorpRaft ----
EXTENDS HashicorpRaftDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM LeaderCompletenessCorrect == Spec => []LeaderCompleteness
\* BEGIN AGENT PROOF HashicorpRaft/HashicorpRaft_LeaderCompletenessCorrect.tla
PROOF OMITTED
\* END AGENT PROOF HashicorpRaft/HashicorpRaft_LeaderCompletenessCorrect.tla

THEOREM StateMachineSafetyCorrect == Spec => []StateMachineSafety
\* BEGIN AGENT PROOF HashicorpRaft/HashicorpRaft_StateMachineSafetyCorrect.tla
PROOF OMITTED
\* END AGENT PROOF HashicorpRaft/HashicorpRaft_StateMachineSafetyCorrect.tla

THEOREM CommittedEntriesPreservedCorrect == Spec => []CommittedEntriesPreserved
\* BEGIN AGENT PROOF HashicorpRaft/HashicorpRaft_CommittedEntriesPreservedCorrect.tla
PROOF OMITTED
\* END AGENT PROOF HashicorpRaft/HashicorpRaft_CommittedEntriesPreservedCorrect.tla

THEOREM LogMatchingCorrect == Spec => []LogMatching
\* BEGIN AGENT PROOF HashicorpRaft/HashicorpRaft_LogMatchingCorrect.tla
PROOF OMITTED
\* END AGENT PROOF HashicorpRaft/HashicorpRaft_LogMatchingCorrect.tla

THEOREM ElectionSafetyCorrect == Spec => []ElectionSafety
\* BEGIN AGENT PROOF HashicorpRaft/HashicorpRaft_ElectionSafetyCorrect.tla
PROOF OMITTED
\* END AGENT PROOF HashicorpRaft/HashicorpRaft_ElectionSafetyCorrect.tla

THEOREM ConfigurationSafetyCorrect == Spec => []ConfigurationSafety
\* BEGIN AGENT PROOF HashicorpRaft/HashicorpRaft_ConfigurationSafetyCorrect.tla
PROOF OMITTED
\* END AGENT PROOF HashicorpRaft/HashicorpRaft_ConfigurationSafetyCorrect.tla
====

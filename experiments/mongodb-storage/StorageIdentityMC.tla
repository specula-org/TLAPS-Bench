--------------------------- MODULE StorageIdentityMC ---------------------------
EXTENDS StorageCallerHistory

\* Enforce the existing theorem premise only in the single-write checking mode.
MCNext == CallerHistoryEpochNext /\ SingleWritePerKey'
MCSpec == HistoryInit /\ [][MCNext]_historyVars

\* The ordered identity-aware predicate also supports repeated writes/removes.
RepeatedWriteSpec == CallerHistoryEpochSpec
=============================================================================

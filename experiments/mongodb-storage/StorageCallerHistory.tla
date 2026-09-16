------------------------ MODULE StorageCallerHistory ------------------------
EXTENDS StorageHistory, StorageCaller, StorageHistoryProjection

CallerHistoryEpochNext == HistoryEpochNext /\ FreshPrepareCall
CallerHistoryEpochSpec == HistoryInit /\ [][CallerHistoryEpochNext]_historyVars

\* Candidate only: no theorem/proof is asserted here.
CallerEpochSITarget ==
  (CallerHistoryEpochSpec /\ []SingleWritePerKey) => []FullSI

\* The historical candidate lost transaction identities and is refuted.
LegacyCallerEpochSITarget ==
  (CallerHistoryEpochSpec /\ []SingleWritePerKey) => []LegacyFullSI

THEOREM HistoryEpochActionProjection == HistoryEpochNext => EpochNext
BY SMT DEF HistoryEpochNext, ObservedOperations, QuietEpochNext, EpochNext,
           ObserveRead, ObserveWrite, ObserveRemove

THEOREM HistoryEpochStutteringProjection == [HistoryEpochNext]_historyVars => [EpochNext]_vars
BY SMT, HistoryEpochActionProjection DEF historyVars

THEOREM HistoryEpochBehaviorProjection == HistoryEpochSpec => EpochSpec
BY HistoryInitialProjection, HistoryEpochStutteringProjection,
   PTL DEF HistoryEpochSpec, EpochSpec

THEOREM CallerHistoryStutteringProjection == [CallerHistoryEpochNext]_historyVars => [CallerEpochNext]_vars
BY SMT, HistoryEpochActionProjection DEF CallerHistoryEpochNext, CallerEpochNext, historyVars

THEOREM CallerHistoryProjection == CallerHistoryEpochSpec => CallerEpochSpec
BY HistoryInitialProjection, CallerHistoryStutteringProjection,
   PTL DEF CallerHistoryEpochSpec, CallerEpochSpec
=============================================================================

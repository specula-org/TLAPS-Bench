---------------------- MODULE StorageHistoryProjection ----------------------
EXTENDS StorageHistory, TLAPS

THEOREM HistoryInitialProjection == HistoryInit => Init
BY SMT DEF HistoryInit

THEOREM HistoryActionProjection == HistoryNext => Next
BY SMT DEF HistoryNext, HistoryEpochNext, ObservedOperations, QuietEpochNext,
           ObserveRead, ObserveWrite, ObserveRemove, Next

THEOREM HistoryStutteringProjection == [HistoryNext]_historyVars => [Next]_vars
BY SMT, HistoryActionProjection DEF historyVars

THEOREM HistoryBehaviorProjection == HistorySpec => (Init /\ [][Next]_vars)
BY HistoryInitialProjection, HistoryStutteringProjection, PTL DEF HistorySpec
=============================================================================

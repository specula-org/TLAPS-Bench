---- MODULE FlashWithMutex ----
EXTENDS FlashWithMutexDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM TypeCorrect == Spec => []TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_TypeCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_TypeCorrect.tla

THEOREM ReqProgressCorrect == FairSpec => ReqProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_ReqProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_ReqProgressCorrect.tla

THEOREM DirProgressCorrect == FairSpec => DirProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_DirProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_DirProgressCorrect.tla

THEOREM UniProgressCorrect == FairSpec => UniProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_UniProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_UniProgressCorrect.tla

THEOREM InvProgressCorrect == FairSpec => InvProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_InvProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_InvProgressCorrect.tla

THEOREM RpProgressCorrect == FairSpec => RpProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_RpProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_RpProgressCorrect.tla

THEOREM WbProgressCorrect == FairSpec => WbProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_WbProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_WbProgressCorrect.tla

THEOREM ShWbProgressCorrect == FairSpec => ShWbProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_ShWbProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_ShWbProgressCorrect.tla

THEOREM NakcProgressCorrect == FairSpec => NakcProgress
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_NakcProgressCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_NakcProgressCorrect.tla

THEOREM CacheStateCorrect == Spec => []CacheStateProp
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_CacheStateCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_CacheStateCorrect.tla

THEOREM CacheDataCorrect == Spec => []CacheDataProp
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_CacheDataCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_CacheDataCorrect.tla

THEOREM MemDataCorrect == Spec => []MemDataProp
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_MemDataCorrect.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_MemDataCorrect.tla

THEOREM Lemma_1_Correct == Spec => []Lemma_1
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_1_Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_1_Correct.tla

THEOREM Lemma_2_Correct == Spec => []Lemma_2
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_2_Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_2_Correct.tla

THEOREM Lemma_3_Correct == Spec => []Lemma_3
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_3_Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_3_Correct.tla

THEOREM Lemma_4_Correct == Spec => []Lemma_4
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_4_Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_4_Correct.tla

THEOREM Lemma_5_Correct == Spec => []Lemma_5
\* BEGIN AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_5_Correct.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_FlashProtocol/FlashWithMutex_Lemma_5_Correct.tla
====

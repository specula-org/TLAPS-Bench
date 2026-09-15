---- MODULE bcastByz ----
EXTENDS bcastByzDefs

\* BEGIN AGENT HELPERS
\* END AGENT HELPERS

THEOREM FCConstraints_TypeOK_Init == 
  Init => FCConstraints /\ TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_Init.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_Init.tla

THEOREM FCConstraints_TypeOK_IndInv_Unforg_NoBcast ==  
  IndInv_Unforg_NoBcast => FCConstraints /\ TypeOK
\* BEGIN AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_IndInv_Unforg_NoBcast.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_IndInv_Unforg_NoBcast.tla

THEOREM FCConstraints_TypeOK_IndInv_Unforg_NoBcast_TLC ==  
  IndInv_Unforg_NoBcast_TLC => FCConstraints
\* BEGIN AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_IndInv_Unforg_NoBcast_TLC.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_IndInv_Unforg_NoBcast_TLC.tla

THEOREM FCConstraints_TypeOK_SpecNoBcast == SpecNoBcast => [](FCConstraints /\ TypeOK)
\* BEGIN AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_SpecNoBcast.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_bcastByz/bcastByz_FCConstraints_TypeOK_SpecNoBcast.tla

THEOREM Unforg_Step4 == SpecNoBcast => []Unforg
\* BEGIN AGENT PROOF tlaplus_examples_bcastByz/bcastByz_Unforg_Step4.tla
PROOF OMITTED
\* END AGENT PROOF tlaplus_examples_bcastByz/bcastByz_Unforg_Step4.tla
====

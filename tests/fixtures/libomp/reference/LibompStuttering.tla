---- MODULE LibompStuttering ----
EXTENDS LibompCounting
LEMMA StutterPreserves ==
 ASSUME Inductive, UNCHANGED allVars
 PROVE Inductive'
<1>T. TypeOK BY DEF Inductive
<1>S. SerialInv BY DEF Inductive
<1>P. PhaseInv BY DEF Inductive
<1>W. WorkInv BY DEF Inductive
<1>C. CountInv BY DEF Inductive

<1>1. TypeOK'
  BY <1>T, <1>T, SMTT("r10") DEF allVars, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, PcStates, TaskPhases, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, LiveTask, AllGathered, TypeOK, TypeOK
<1>2. SerialInv'
  BY <1>S, <1>T, SMTT("r10") DEF allVars, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, PcStates, TaskPhases, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, LiveTask, AllGathered, SerialInv, TypeOK
<1>3. PhaseInv'
  BY <1>P, <1>T, SMTT("r10") DEF allVars, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, PcStates, TaskPhases, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, LiveTask, AllGathered, PhaseInv, TypeOK
<1>4. WorkInv'
  BY <1>W, <1>T, SMTT("r10") DEF allVars, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, PcStates, TaskPhases, Slots, Before, After, Effective, Toggled, RoundSlot, Drained, UnfinishedSet, LiveTask, AllGathered, WorkInv, TypeOK
<1>U. UNCHANGED <<RoundSlot, unfinished, UnfinishedSet>>
  BY SMTT("r10") DEF allVars, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, RoundSlot, Effective, Toggled, UnfinishedSet
<1>A. Counting' => Counting
  BY SMTT("r10") DEF allVars, barrierVars, parityVars, lifecycleVars, taskVars, taskCountVars, serialVars, workVars, Counting
<1>5. CountInv'
  BY <1>C, <1>U, <1>A, PreserveCount
<1> QED BY <1>1, <1>2, <1>3, <1>4, <1>5 DEF Inductive
====

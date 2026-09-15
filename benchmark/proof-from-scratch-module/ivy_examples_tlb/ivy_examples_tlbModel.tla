--------------------------- MODULE ivy_examples_tlbModel ---------------------------
EXTENDS TLAPS

CONSTANTS Processor, PMap, PageEntry

ASSUME NonemptySets ==
  /\ Processor # {}
  /\ PMap # {}
  /\ PageEntry # {}

VARIABLES
  pc, userpmap, writepmap, actionlock, actionneeded, active, interrupt,
  currentcpu, plock, tlb, pentry, todo, error

vars ==
  << pc, userpmap, writepmap, actionlock, actionneeded, active, interrupt,
     currentcpu, plock, tlb, pentry, todo, error >>

Boot == "Boot"
MainCheck == "MainCheck"
MainChoose == "MainChoose"
MainHandleInterrupt == "MainHandleInterrupt"

InitiatorDeactivate == "InitiatorDeactivate"
InitiatorLockPmap == "InitiatorLockPmap"
InitiatorForSend == "InitiatorForSend"
InitiatorCheckCpuPmap == "InitiatorCheckCpuPmap"
InitiatorLockAction == "InitiatorLockAction"
InitiatorSetActionNeeded == "InitiatorSetActionNeeded"
InitiatorUnlockAction == "InitiatorUnlockAction"
InitiatorInterrupt == "InitiatorInterrupt"
InitiatorWaitForQuiescence == "InitiatorWaitForQuiescence"
InitiatorUpdateEntry == "InitiatorUpdateEntry"
InitiatorMaybeRefreshOwnTlb == "InitiatorMaybeRefreshOwnTlb"
InitiatorUnlockPmap == "InitiatorUnlockPmap"
InitiatorReactivate == "InitiatorReactivate"

ResponderCheck == "ResponderCheck"
ResponderDeactivate == "ResponderDeactivate"
ResponderLockAction == "ResponderLockAction"
ResponderRefreshTlb == "ResponderRefreshTlb"
ResponderClearActionNeeded == "ResponderClearActionNeeded"
ResponderUnlockAction == "ResponderUnlockAction"
ResponderReactivate == "ResponderReactivate"

Init ==
  /\ pc = [p \in Processor |-> Boot]
  /\ userpmap \in [Processor -> PMap]
  /\ writepmap \in [Processor -> PMap]
  /\ actionlock = [p \in Processor |-> FALSE]
  /\ actionneeded = [p \in Processor |-> FALSE]
  /\ active = [p \in Processor |-> TRUE]
  /\ interrupt = [p \in Processor |-> FALSE]
  /\ currentcpu \in [Processor -> Processor]
  /\ plock = [m \in PMap |-> FALSE]
  /\ tlb \in [Processor -> PageEntry]
  /\ pentry \in [PMap -> PageEntry]
  /\ todo = [p \in Processor |-> [q \in Processor |-> FALSE]]
  /\ error = FALSE

BootProcessor(p, m) ==
  /\ p \in Processor
  /\ m \in PMap
  /\ pc[p] = Boot
  /\ ~plock[m]
  /\ pc' = [pc EXCEPT ![p] = MainCheck]
  /\ userpmap' = [userpmap EXCEPT ![p] = m]
  /\ tlb' = [tlb EXCEPT ![p] = pentry[m]]
  /\ UNCHANGED << writepmap, actionlock, actionneeded, active, interrupt,
                  currentcpu, plock, pentry, todo, error >>

MainCheckTlb(p) ==
  /\ p \in Processor
  /\ pc[p] = MainCheck
  /\ pc' = [pc EXCEPT ![p] = MainChoose]
  /\ error' = error \/ (tlb[p] # pentry[userpmap[p]])
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, todo >>

ChooseInitiator(p) ==
  /\ p \in Processor
  /\ pc[p] = MainChoose
  /\ pc' = [pc EXCEPT ![p] = InitiatorDeactivate]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, todo, error >>

SkipInitiator(p) ==
  /\ p \in Processor
  /\ pc[p] = MainChoose
  /\ pc' = [pc EXCEPT ![p] = MainHandleInterrupt]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, todo, error >>

HandleInterrupt(p) ==
  /\ p \in Processor
  /\ pc[p] = MainHandleInterrupt
  /\ pc' = [pc EXCEPT ![p] =
       IF interrupt[p] THEN ResponderCheck ELSE MainCheck]
  /\ interrupt' = [interrupt EXCEPT ![p] = FALSE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  currentcpu, plock, tlb, pentry, todo, error >>

BeginShootdown(p, m) ==
  /\ p \in Processor
  /\ m \in PMap
  /\ pc[p] = InitiatorDeactivate
  /\ pc' = [pc EXCEPT ![p] = InitiatorLockPmap]
  /\ active' = [active EXCEPT ![p] = FALSE]
  /\ writepmap' = [writepmap EXCEPT ![p] = m]
  /\ UNCHANGED << userpmap, actionlock, actionneeded, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

AcquirePmapLock(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorLockPmap
  /\ ~plock[writepmap[p]]
  /\ pc' = [pc EXCEPT ![p] = InitiatorForSend]
  /\ plock' = [plock EXCEPT ![writepmap[p]] = TRUE]
  /\ todo' = [todo EXCEPT ![p] =
       [q \in Processor |-> pc[q] # Boot /\ q # p]]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, tlb, pentry, error >>

SelectShootdownCpu(p, cpu) ==
  /\ p \in Processor
  /\ cpu \in Processor
  /\ pc[p] = InitiatorForSend
  /\ todo[p][cpu]
  /\ pc' = [pc EXCEPT ![p] = InitiatorCheckCpuPmap]
  /\ currentcpu' = [currentcpu EXCEPT ![p] = cpu]
  /\ todo' = [todo EXCEPT ![p][cpu] = FALSE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, plock, tlb, pentry, error >>

ExitShootdownCpuLoop(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorForSend
  /\ \A cpu \in Processor : ~todo[p][cpu]
  /\ pc' = [pc EXCEPT ![p] = InitiatorWaitForQuiescence]
  /\ todo' = [todo EXCEPT ![p] =
       [q \in Processor |-> pc[q] # Boot /\ q # p]]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, error >>

CheckCpuPmap(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorCheckCpuPmap
  /\ pc' = [pc EXCEPT ![p] =
       IF userpmap[currentcpu[p]] = writepmap[p]
         THEN InitiatorLockAction
         ELSE InitiatorForSend]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, todo, error >>

AcquireActionLockForCpu(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorLockAction
  /\ ~actionlock[currentcpu[p]]
  /\ pc' = [pc EXCEPT ![p] = InitiatorSetActionNeeded]
  /\ actionlock' = [actionlock EXCEPT ![currentcpu[p]] = TRUE]
  /\ UNCHANGED << userpmap, writepmap, actionneeded, active, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

SetActionNeeded(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorSetActionNeeded
  /\ pc' = [pc EXCEPT ![p] = InitiatorUnlockAction]
  /\ actionneeded' = [actionneeded EXCEPT ![currentcpu[p]] = TRUE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, active, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

UnlockActionForCpu(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorUnlockAction
  /\ pc' = [pc EXCEPT ![p] = InitiatorInterrupt]
  /\ actionlock' = [actionlock EXCEPT ![currentcpu[p]] = FALSE]
  /\ error' = error \/ ~actionlock[currentcpu[p]]
  /\ UNCHANGED << userpmap, writepmap, actionneeded, active, interrupt,
                  currentcpu, plock, tlb, pentry, todo >>

InterruptCpu(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorInterrupt
  /\ pc' = [pc EXCEPT ![p] = InitiatorForSend]
  /\ interrupt' = [interrupt EXCEPT ![currentcpu[p]] = TRUE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  currentcpu, plock, tlb, pentry, todo, error >>

WaitForCpuQuiescence(p, cpu) ==
  /\ p \in Processor
  /\ cpu \in Processor
  /\ pc[p] = InitiatorWaitForQuiescence
  /\ todo[p][cpu]
  /\ (~active[cpu] \/ userpmap[cpu] # writepmap[p])
  /\ todo' = [todo EXCEPT ![p][cpu] = FALSE]
  /\ UNCHANGED << pc, userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, error >>

ExitQuiescenceLoop(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorWaitForQuiescence
  /\ \A cpu \in Processor : ~todo[p][cpu]
  /\ pc' = [pc EXCEPT ![p] = InitiatorUpdateEntry]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, todo, error >>

UpdatePageEntry(p, e) ==
  /\ p \in Processor
  /\ e \in PageEntry
  /\ pc[p] = InitiatorUpdateEntry
  /\ pc' = [pc EXCEPT ![p] = InitiatorMaybeRefreshOwnTlb]
  /\ pentry' = [pentry EXCEPT ![writepmap[p]] = e]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, todo, error >>

MaybeRefreshOwnTlb(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorMaybeRefreshOwnTlb
  /\ pc' = [pc EXCEPT ![p] = InitiatorUnlockPmap]
  /\ tlb' = IF userpmap[p] = writepmap[p]
              THEN [tlb EXCEPT ![p] = pentry[writepmap[p]]]
              ELSE tlb
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, pentry, todo, error >>

UnlockPmap(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorUnlockPmap
  /\ pc' = [pc EXCEPT ![p] = InitiatorReactivate]
  /\ plock' = [plock EXCEPT ![writepmap[p]] = FALSE]
  /\ error' = error \/ ~plock[writepmap[p]]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, tlb, pentry, todo >>

ReactivateInitiator(p) ==
  /\ p \in Processor
  /\ pc[p] = InitiatorReactivate
  /\ pc' = [pc EXCEPT ![p] = MainHandleInterrupt]
  /\ active' = [active EXCEPT ![p] = TRUE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

CheckActionNeeded(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderCheck
  /\ pc' = [pc EXCEPT ![p] =
       IF actionneeded[p] THEN ResponderDeactivate ELSE MainCheck]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, tlb, pentry, todo, error >>

DeactivateResponder(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderDeactivate
  /\ pc' = [pc EXCEPT ![p] = ResponderLockAction]
  /\ active' = [active EXCEPT ![p] = FALSE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

AcquireResponderActionLock(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderLockAction
  /\ ~plock[userpmap[p]]
  /\ pc' = [pc EXCEPT ![p] = ResponderRefreshTlb]
  /\ actionlock' = [actionlock EXCEPT ![p] = TRUE]
  /\ error' = error \/ actionlock[p]
  /\ UNCHANGED << userpmap, writepmap, actionneeded, active, interrupt,
                  currentcpu, plock, tlb, pentry, todo >>

RefreshTlbFromPmap(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderRefreshTlb
  /\ pc' = [pc EXCEPT ![p] = ResponderClearActionNeeded]
  /\ tlb' = [tlb EXCEPT ![p] = pentry[userpmap[p]]]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, active,
                  interrupt, currentcpu, plock, pentry, todo, error >>

ClearActionNeeded(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderClearActionNeeded
  /\ pc' = [pc EXCEPT ![p] = ResponderUnlockAction]
  /\ actionneeded' = [actionneeded EXCEPT ![p] = FALSE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, active, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

UnlockResponderAction(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderUnlockAction
  /\ pc' = [pc EXCEPT ![p] = ResponderReactivate]
  /\ actionlock' = [actionlock EXCEPT ![p] = FALSE]
  /\ error' = error \/ ~actionlock[p]
  /\ UNCHANGED << userpmap, writepmap, actionneeded, active, interrupt,
                  currentcpu, plock, tlb, pentry, todo >>

ReactivateResponder(p) ==
  /\ p \in Processor
  /\ pc[p] = ResponderReactivate
  /\ pc' = [pc EXCEPT ![p] = ResponderCheck]
  /\ active' = [active EXCEPT ![p] = TRUE]
  /\ UNCHANGED << userpmap, writepmap, actionlock, actionneeded, interrupt,
                  currentcpu, plock, tlb, pentry, todo, error >>

BootStep(p) ==
  \E m \in PMap : BootProcessor(p, m)

Step(p) ==
  \/ BootStep(p)
  \/ MainCheckTlb(p)
  \/ ChooseInitiator(p)
  \/ SkipInitiator(p)
  \/ HandleInterrupt(p)
  \/ \E m \in PMap : BeginShootdown(p, m)
  \/ AcquirePmapLock(p)
  \/ \E cpu \in Processor : SelectShootdownCpu(p, cpu)
  \/ ExitShootdownCpuLoop(p)
  \/ CheckCpuPmap(p)
  \/ AcquireActionLockForCpu(p)
  \/ SetActionNeeded(p)
  \/ UnlockActionForCpu(p)
  \/ InterruptCpu(p)
  \/ \E cpu \in Processor : WaitForCpuQuiescence(p, cpu)
  \/ ExitQuiescenceLoop(p)
  \/ \E e \in PageEntry : UpdatePageEntry(p, e)
  \/ MaybeRefreshOwnTlb(p)
  \/ UnlockPmap(p)
  \/ ReactivateInitiator(p)
  \/ CheckActionNeeded(p)
  \/ DeactivateResponder(p)
  \/ AcquireResponderActionLock(p)
  \/ RefreshTlbFromPmap(p)
  \/ ClearActionNeeded(p)
  \/ UnlockResponderAction(p)
  \/ ReactivateResponder(p)

Next ==
  \E p \in Processor : Step(p)

SafetySpec ==
  /\ Init
  /\ [][Next]_vars

=============================================================================

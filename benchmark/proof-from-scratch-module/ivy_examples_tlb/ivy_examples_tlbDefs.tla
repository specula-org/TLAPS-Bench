--------------------------- MODULE ivy_examples_tlbDefs ---------------------------
EXTENDS ivy_examples_tlbModel

Spec ==
  /\ SafetySpec
  /\ \A p \in Processor : WF_vars(Step(p))
  /\ \A p \in Processor : SF_vars(BootStep(p))
  /\ \A p \in Processor : SF_vars(AcquirePmapLock(p))
  /\ \A p \in Processor : SF_vars(AcquireResponderActionLock(p))

NoError ==
  ~error

ProcessorMakesProgress(p) ==
  pc[p] \in {MainCheck, ResponderClearActionNeeded}

NonStarvation ==
  \A p \in Processor : TRUE ~> ProcessorMakesProgress(p)

=============================================================================

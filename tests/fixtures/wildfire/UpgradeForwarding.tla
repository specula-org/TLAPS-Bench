---- MODULE UpgradeForwarding ----
EXTENDS WildfireProofDefs, TLC
CONSTANTS SecondKind, UpgradeSC

MCProcHome(p) == "ls"
MCAdrHome(a) == "ls"
MCZero == [i \in 0..(DataLen-1) |-> 0]
MCInitialMemory == [a \in Adr |-> MCZero]
MCEnvironment(old,new,p,r) == FALSE
MCMemoryOwner == "memory"
MCNoLock == "unlocked"
MCInvalid == "invalidData"

MCWrite == [type |-> "Wr", adr |-> "b", mask |-> AllOnes, data |-> MCZero]
MCRead == [type |-> "Rd", adr |-> "b"]
MCLinkedRead == [type |-> "LL", adr |-> "b"]
MCSecond == IF SecondKind = "Wr" THEN MCWrite
            ELSE [type |-> SecondKind, adr |-> "b"]
MCUpgrade == IF UpgradeSC THEN [MCWrite EXCEPT !.type = "SC"] ELSE MCWrite
MCFill(st) == [adr |-> "b", data |-> MCZero, state |-> st]

VARIABLE phase
MCVariables == <<wVars,phase>>
MCInit == Protocol!Init /\ aInt = <<>> /\ phase = 0

\* Reach the upgrade/probe race, then explore every internal action.
MCScheduledAction ==
  CASE phase = 0  -> Protocol!ProcReceiveRequest("r",MCWrite)
    [] phase = 1  -> Protocol!ProcIssueDirReq("r",1)
    [] phase = 2  -> Protocol!LSReceiveRequestFromProc("r",1)
    [] phase = 3  -> Protocol!ProcReceiveFill("r",MCFill("Exclusive"))
    [] phase = 4  -> Protocol!ProcReceiveMsg("r",1)
    [] phase = 5  -> Protocol!ProcSendResponse("r",1)
    [] phase = 6  -> Protocol!ProcReceiveRequest("q",MCRead)
    [] phase = 7  -> Protocol!ProcIssueDirReq("q",1)
    [] phase = 8  -> Protocol!LSReceiveRequestFromProc("q",1)
    [] phase = 9  -> Protocol!ProcReceiveMsg("r",1)
    [] phase = 10 -> Protocol!ProcReceiveFill("q",MCFill("Shared"))
    [] phase = 11 -> Protocol!ProcReceiveMsg("q",1)
    [] phase = 12 -> Protocol!ProcSendResponse("q",1)
    [] phase = 13 -> IF UpgradeSC THEN Protocol!ProcReceiveRequest("r",MCLinkedRead)
                       ELSE UNCHANGED wVars
    [] phase = 14 -> IF UpgradeSC THEN Protocol!ProcExecuteFromCache("r",1)
                       ELSE UNCHANGED wVars
    [] phase = 15 -> IF UpgradeSC THEN Protocol!ProcSendResponse("r",1)
                       ELSE UNCHANGED wVars
    [] phase = 16 -> Protocol!ProcEvictCacheLine("q","b")
    [] phase = 17 -> Protocol!ProcReceiveRequest("q",MCSecond)
    [] phase = 18 -> Protocol!ProcIssueDirReq("q",1)
    [] phase = 19 -> Protocol!ProcReceiveRequest("r",MCUpgrade)
    [] phase = 20 -> Protocol!ProcIssueDirReq("r",1)
    [] phase = 21 -> Protocol!LSReceiveRequestFromProc("q",1)
    [] phase = 22 -> Protocol!LSReceiveRequestFromProc("r",1)
    [] phase = 23 -> Protocol!ProcReceiveMsg("q",1)


\* All canonical Next disjuncts except input from the environment.
MCInternalNext ==
  \/ \E p \in Proc :
       \/ \E i \in DOMAIN respQ[p] : Protocol!ProcSendResponse(p,i)
       \/ \E a \in Adr : Protocol!ProcEvictCacheLine(p,a)
       \/ \E i \in DOMAIN Q.LSToProc[p] : Protocol!ProcReceiveMsg(p,i)
       \/ \E m \in fillQ[p] : Protocol!ProcReceiveFill(p,m)
       \/ \E i \in DOMAIN reqQ[p] :
            \/ Protocol!ProcIssueDirReq(p,i)
            \/ Protocol!ProcExecuteFromCache(p,i)
       \/ \E i \in DOMAIN Q.ProcToLS[p] :
            \/ Protocol!LSForwardMsgsToGS(p,i)
            \/ Protocol!LSReceiveRequestFromProc(p,i)
            \/ Protocol!LSReceiveVictimFromProc(p,i)
  \/ \E ls \in LS :
       \/ \E i \in DOMAIN Q.GSToLS[ls] : Protocol!LSReceiveRequestFromGS(ls,i)
       \/ \E i \in DOMAIN Q.GSToLS[ls] : Protocol!LSReceiveVictimFromGS(ls,i)
       \/ \E i \in DOMAIN Q.GSToLS[ls] : Protocol!LSForwardMsgsToProcs(ls,i)
       \/ \E i \in DOMAIN Q.LSToGS[ls] : Protocol!GSForwardMsgsToLS(ls,i)

MCNext == \/ /\ phase < 24
              /\ MCScheduledAction
              /\ phase' = phase+1
          \/ /\ phase = 24
              /\ MCInternalNext
              /\ UNCHANGED phase

\* Prefix scheduling is fixture-only; protocol fairness governs the suffix.
MCSpec == MCInit /\ [][MCNext]_MCVariables /\ WF_MCVariables(MCNext) /\ Protocol!Liveness

MCReachesFinal == <> (phase = 24)
MCReceived(p) == Cardinality({i \in DOMAIN aInt : aInt[i].kind="request" /\ aInt[i].proc=p})
MCResponded(p) == Cardinality({i \in DOMAIN aInt : aInt[i].kind="response" /\ aInt[i].proc=p})
MCReadCompletion == [] (MCReceived("q") = 2 => <> (MCResponded("q") = 2))
MCWriterCount == IF UpgradeSC THEN 3 ELSE 2
MCWriteCompletion == [] (MCReceived("r") = MCWriterCount => <> (MCResponded("r") = MCWriterCount))
MCFillData == \A p \in Proc : \A f \in fillQ[p] : f.data = MCZero
MCReadData == \A i \in DOMAIN aInt :
  IF aInt[i].kind = "response" THEN
    IF aInt[i].value.type \in {"Rd", "LL"} THEN aInt[i].value.data = MCZero ELSE TRUE
  ELSE TRUE
MCExclusive == \A p,q \in Proc : p # q =>
  ~(cache[p]["b"].state = "Exclusive" /\ cache[q]["b"].state = "Exclusive")
MCUpgradeOutcome == \A i \in DOMAIN aInt :
  IF aInt[i].kind = "response" /\ aInt[i].proc = "r" THEN
    IF aInt[i].value.type \in {"SC", "FailedSC"} THEN
      aInt[i].value.type = (IF SecondKind = "Wr" THEN "FailedSC" ELSE "SC")
    ELSE TRUE
  ELSE TRUE
MCCompleted == MCResponded("q") = 2 /\ MCResponded("r") = MCWriterCount
MCNeverCompletes == ~MCCompleted
====

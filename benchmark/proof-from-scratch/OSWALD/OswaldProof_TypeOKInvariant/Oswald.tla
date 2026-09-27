----------------------------- MODULE Oswald -----------------------------

EXTENDS Naturals, Integers, FiniteSets, Sequences, SequencesExt, TLC

CONSTANTS Writers,
          GarbageCollectors,
          Values

CONSTANTS SNAPSHOT_RECOVERY, CATCHUP_RECOVERY, 
          VALIDATE, UPDATE_MANIFEST, READY, DELETE

CONSTANTS NIL

WritableLsns == 0..Cardinality(Values)

VARIABLES manifest,         
          chunk,            
          snapshot          

VARIABLES wState,           
          wManifestVersion, 
          wSafeLsn,         
          wNextLsn,         
          wMachineData,     
          wSnapshottedLsns, 
          wPendingApply     

VARIABLES gcState,          
          gcWm              

VARIABLES auxUsedValues,    
          auxObsSnapshots   

storeVars == <<manifest, chunk, snapshot>>
writerVars == <<wState, wManifestVersion, wSafeLsn, wNextLsn, 
                wMachineData, wSnapshottedLsns, wPendingApply>>
gcVars == <<gcState, gcWm>>
auxVars == <<auxUsedValues, auxObsSnapshots>>
vars == <<storeVars, writerVars, gcVars, auxVars>>

SnapshotRecovery(w) ==
    /\ wState[w] = SNAPSHOT_RECOVERY
    /\ wManifestVersion' = [wManifestVersion EXCEPT ![w] = manifest.version]
    /\ wSafeLsn' = [wSafeLsn EXCEPT ![w] = manifest.snapshotLsn]
    /\ wNextLsn' = [wNextLsn EXCEPT ![w] = manifest.snapshotLsn + 1]
    /\ wMachineData' = [wMachineData EXCEPT ![w] = 
                            IF manifest.snapshotLsn = 0 THEN <<>>
                            ELSE snapshot[manifest.snapshotLsn]]
    /\ wPendingApply' = [wPendingApply EXCEPT ![w] = <<>>] 
    /\ wState' = [wState EXCEPT ![w] = CATCHUP_RECOVERY]
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wSnapshottedLsns>>

CatchupRecovery(w) ==
    /\ wState[w] = CATCHUP_RECOVERY
    /\ LET read == IF wNextLsn[w] \in DOMAIN chunk
                   THEN chunk[wNextLsn[w]] ELSE NIL
       IN \/ /\ read /= NIL
             /\ wPendingApply' = [wPendingApply EXCEPT ![w] = Append(@, read)]
             /\ wNextLsn' = [wNextLsn EXCEPT ![w] = @ + 1]
             /\ UNCHANGED <<wState>>
          \/ /\ read = NIL
             /\ wState' = [wState EXCEPT ![w] = VALIDATE]
             /\ UNCHANGED <<wNextLsn, wPendingApply>>
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wMachineData, wSafeLsn, 
                  wSnapshottedLsns, wManifestVersion>>

ObserveSnapshot(w) ==
    LET lsn  == wNextLsn[w] - 1
        snap == wMachineData[w] \o wPendingApply[w]
    IN /\ auxObsSnapshots' = [auxObsSnapshots EXCEPT ![lsn] = @ \union {snap}]
       /\ UNCHANGED auxUsedValues

Validate(w) ==
    /\ wState[w] = VALIDATE
    /\ IF /\ wManifestVersion[w] /= manifest.version
          /\ wSafeLsn[w] <= manifest.gcWatermark
       THEN /\ wState' = [wState EXCEPT ![w] = SNAPSHOT_RECOVERY]
            /\ wPendingApply' = [wPendingApply EXCEPT ![w] = <<>>]
            /\ UNCHANGED <<wSafeLsn, wMachineData, auxVars>>
       ELSE /\ wState' = [wState EXCEPT ![w] = READY]
            /\ wSafeLsn' = [wSafeLsn EXCEPT ![w] = wNextLsn[w]]
            /\ wMachineData' = [wMachineData EXCEPT ![w] = @ \o wPendingApply[w]]
            /\ wPendingApply' = [wPendingApply EXCEPT ![w] = <<>>]
            /\ ObserveSnapshot(w)
    /\ UNCHANGED <<storeVars, gcVars, wNextLsn, wManifestVersion, wSnapshottedLsns>>

AppendChunk(w, v) ==
    /\ wState[w] = READY
    /\ wPendingApply[w] = <<>>
    /\ v \notin auxUsedValues
    /\ \/ /\ wNextLsn[w] \notin DOMAIN chunk
          /\ chunk' = chunk @@ (wNextLsn[w] :> v)
          /\ wNextLsn' = [wNextLsn EXCEPT ![w] = @ + 1]
          /\ wPendingApply' = [wPendingApply EXCEPT ![w] = <<v>>]
          /\ wState' = [wState EXCEPT ![w] = VALIDATE]
          /\ auxUsedValues' = auxUsedValues \union {v}
       \/ /\ wNextLsn[w] \in DOMAIN chunk
          /\ wState' = [wState EXCEPT ![w] = CATCHUP_RECOVERY]
          /\ UNCHANGED <<chunk, wNextLsn, wPendingApply, auxUsedValues>>
    /\ UNCHANGED <<manifest, snapshot, wMachineData, wManifestVersion, 
                   wSafeLsn, wSnapshottedLsns, gcVars, auxObsSnapshots>>

WriteSnapshot(w) ==
    /\ wState[w] = READY
    /\ wPendingApply[w] = <<>>
    /\ wNextLsn[w] > 1 
    /\ LET lsn == wNextLsn[w] - 1 IN
        /\ lsn \notin DOMAIN snapshot
        /\ lsn \notin wSnapshottedLsns[w] 
        /\ snapshot' = snapshot @@ (lsn :> wMachineData[w])
        /\ wState' = [wState EXCEPT ![w] = UPDATE_MANIFEST]
        /\ wSnapshottedLsns' = [wSnapshottedLsns EXCEPT ![w] = @ \union {lsn}]
    /\ UNCHANGED <<chunk, manifest, wManifestVersion, wSafeLsn, 
                   wNextLsn, wMachineData, wPendingApply, gcVars, auxVars>>

UpdateManifest(w) ==
    /\ wState[w] = UPDATE_MANIFEST
    /\ LET currManifest == manifest
           lsn          == wNextLsn[w] - 1
           newVersion   == currManifest.version + 1
       IN
            /\ IF currManifest.snapshotLsn < lsn
               THEN manifest' = [manifest EXCEPT !.snapshotLsn = lsn,
                                                 !.version = newVersion]
               ELSE UNCHANGED manifest
            /\ wState' = [wState EXCEPT ![w] = READY]                
    /\ UNCHANGED <<snapshot, chunk, wSafeLsn, wNextLsn, wManifestVersion,
                   wMachineData, wSnapshottedLsns, wPendingApply, gcVars, auxVars>>

AdvanceGcWatermark(gc) ==
    /\ \/ gcState[gc] = READY
       
       \/ /\ gcState[gc] = DELETE
          /\ ~\E lsn \in DOMAIN chunk : lsn <= gcWm[gc]
          /\ ~\E lsn \in DOMAIN snapshot : lsn <= gcWm[gc]
    /\ manifest.snapshotLsn /= manifest.gcWatermark
    /\ manifest' = [manifest EXCEPT !.gcWatermark = manifest.snapshotLsn,
                                    !.version = @ + 1]
    /\ gcState' = [gcState EXCEPT ![gc] = DELETE]
    /\ gcWm' = [gcWm EXCEPT ![gc] = manifest.snapshotLsn]
    /\ UNCHANGED <<chunk, snapshot, writerVars, auxVars>>

DeleteChunk(gc) ==
    /\ gcState[gc] = DELETE
    /\ \E lsn \in DOMAIN chunk :
        /\ lsn <= gcWm[gc]
        /\ chunk' = [l \in (DOMAIN chunk \ {lsn}) |-> chunk[l]]
        /\ UNCHANGED <<manifest, snapshot, writerVars, gcVars, auxVars>>

DeleteSnapshot(gc) ==
    /\ gcState[gc] = DELETE
    /\ \E lsn \in DOMAIN snapshot :
        /\ lsn < gcWm[gc]
        /\ snapshot' = [l \in (DOMAIN snapshot \ {lsn}) |-> snapshot[l]]
        /\ UNCHANGED <<chunk, manifest, writerVars, gcVars, auxVars>>

TypeOK ==
    /\ manifest \in [snapshotLsn: Nat, gcWatermark: Nat, version: Nat]
    /\ \A lsn \in DOMAIN chunk :
        /\ lsn \in WritableLsns
        /\ chunk[lsn] \in Values
    /\ \A lsn \in DOMAIN snapshot :
        /\ lsn \in WritableLsns
        /\ snapshot[lsn] \in Seq(Values)
    /\ wState \in [Writers -> {SNAPSHOT_RECOVERY, CATCHUP_RECOVERY, VALIDATE,
                               READY, UPDATE_MANIFEST}]
    /\ wManifestVersion \in [Writers -> Nat]
    /\ wSafeLsn \in [Writers -> Nat]
    /\ wNextLsn \in [Writers -> Nat]
    /\ wMachineData \in [Writers -> Seq(Values)]
    /\ wSnapshottedLsns \in [Writers -> SUBSET WritableLsns]
    /\ wPendingApply \in [Writers -> Seq(Values)]
    /\ gcState \in [GarbageCollectors -> {READY, DELETE}]
    /\ gcWm \in [GarbageCollectors -> Nat]
    /\ auxUsedValues \in SUBSET Values
    /\ \A lsn \in WritableLsns :
        \A element \in auxObsSnapshots[lsn] :
            element \in Seq(Values)

Init ==
    /\ manifest = [snapshotLsn |-> 0, gcWatermark |-> 0, version |-> 0]
    /\ chunk = <<>>
    /\ snapshot = <<>>
    /\ wState = [w \in Writers |-> SNAPSHOT_RECOVERY]
    /\ wManifestVersion = [w \in Writers |-> 0]
    /\ wSafeLsn= [w \in Writers |-> 0]
    /\ wNextLsn = [w \in Writers |-> 1]
    /\ wMachineData = [w \in Writers |-> <<>>]
    /\ wSnapshottedLsns = [w \in Writers |-> {}]
    /\ wPendingApply = [w \in Writers |-> <<>>]
    /\ gcState = [gc \in GarbageCollectors |-> READY]
    /\ gcWm = [gc \in GarbageCollectors |-> 0]
    /\ auxUsedValues = {}
    /\ auxObsSnapshots = [lsn \in WritableLsns |-> {}]

Next ==
    \/ \E w \in Writers :
        \/ SnapshotRecovery(w)
        \/ CatchupRecovery(w)
        \/ Validate(w)
        \/ \E v \in Values : AppendChunk(w, v)
        \/ WriteSnapshot(w)
        \/ UpdateManifest(w)
    \/ \E gc \in GarbageCollectors :
        \/ AdvanceGcWatermark(gc)
        \/ DeleteChunk(gc)
        \/ DeleteSnapshot(gc)

Spec == Init /\ [][Next]_vars
=============================================================================

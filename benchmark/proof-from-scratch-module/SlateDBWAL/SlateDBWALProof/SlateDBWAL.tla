----------------------------- MODULE SlateDBWAL -------------------------

EXTENDS Naturals, Integers, FiniteSets, FiniteSetsExt, Sequences, TLC

CONSTANTS Writers,           
          GarbageCollectors, 
          Values             

CONSTANTS IDLE, FIND_NEXT_WAL_ID, CLAIM_EPOCH, CHECK_BOUNDARY, WRITE_FENCE,
          VALIDATE_BEFORE_RETRY, VALIDATE_BEFORE_REPLAY, VALIDATE_BEFORE_NOT_FOUND,
          LOAD_SNAPSHOT, REPLAY_WAL, READY, COMMIT_SNAPSHOT, 
          FENCED, NOT_FOUND

CONSTANTS MANIFEST_GC, WAL_GC

CONSTANTS LOAD_BOUNDARY, COMPUTE_BOUNDARY, 
          ADVANCE_BOUNDARY, FIND_LAST_WAL_ID, DELETE, DONE

CONSTANTS DATA, FENCE

CONSTANTS NIL, ILLEGAL_STATE

VARIABLES manifest,         
          boundary,         
          wal,              
          snapshot,         
          wState,           
          wEpoch,           
          wManifest,        
          wManifestLoad,    
          wNextWalId,       
          wMachineData,     
          wReplayId,        
          gcType,           
          gcState,          
          gcLastWalId,      
          gcBoundary,       
          gcManifest        

VARIABLES auxUsedValues,    
          auxWrittenEntries 

storeVars == <<manifest, boundary, wal, snapshot>>
writerVars == <<wState, wEpoch, wManifest, wManifestLoad, wNextWalId, 
                wMachineData, wReplayId>>
gcVars == <<gcType, gcState, gcLastWalId, gcBoundary, gcManifest>>
auxVars == <<auxUsedValues, auxWrittenEntries>>
vars == <<storeVars, writerVars, gcVars, auxVars>>

LastWalId == IF DOMAIN wal = {} THEN 0 ELSE Max(DOMAIN wal)
ReadWalEntry(id) == IF id \in DOMAIN wal THEN wal[id] ELSE NIL
LastManifestId == Max(DOMAIN manifest)
ReadLastManifest == manifest[LastManifestId]
ReadSnapshot(id) == IF id \in DOMAIN snapshot THEN snapshot[id] ELSE NIL

DoRefresh(w) ==
    \/ /\ wManifestLoad[w].loaded = FALSE
       /\ wManifest[w] /= ReadLastManifest
    \/ wManifestLoad[w].checked = FALSE

RefreshManifest(w) ==
    CASE /\ wManifestLoad[w].loaded = FALSE
         /\ wManifest[w] /= ReadLastManifest ->
            /\ wManifest' = [wManifest EXCEPT ![w] = ReadLastManifest]
            /\ wManifestLoad' = [wManifestLoad EXCEPT ![w] = 
                                            [loaded   |-> TRUE,
                                             checked  |-> FALSE,
                                             valid    |-> FALSE]]
      [] wManifestLoad[w].checked = FALSE -> 
            /\ wManifestLoad' = [wManifestLoad EXCEPT ![w] = 
                                    [loaded  |-> TRUE,
                                     checked |-> TRUE,
                                     valid   |-> wManifest[w].id > boundary.manifestId]]
            /\ UNCHANGED wManifest
                                 
ManifestRefreshed(w) ==
    /\ wManifestLoad' = [wManifestLoad EXCEPT ![w]=
                            [checked |-> FALSE,
                             loaded  |-> FALSE,
                             valid   |-> FALSE]]
    /\ UNCHANGED wManifest

StartWriter(w) ==
    /\ wState[w] = IDLE
    /\ CASE DoRefresh(w) -> 
                /\ RefreshManifest(w)
                /\ UNCHANGED wState
         [] wManifestLoad[w].valid = FALSE ->
                /\ wState' = [wState EXCEPT ![w] = IDLE]
                /\ ManifestRefreshed(w)
         [] OTHER -> 
                /\ wState' = [wState EXCEPT ![w] = FIND_NEXT_WAL_ID]
                /\ ManifestRefreshed(w)
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, wNextWalId, 
                   wMachineData, wNextWalId, wReplayId>>

FindNextWalId(w) ==
    /\ wState[w] = FIND_NEXT_WAL_ID
    /\ wState' = [wState EXCEPT ![w] = CLAIM_EPOCH]
    /\ wNextWalId' = [wNextWalId EXCEPT ![w] = LastWalId + 1]
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, wManifest, 
                   wManifestLoad, wMachineData, wReplayId>>

ClaimEpoch(w) ==
    /\ wState[w] = CLAIM_EPOCH
    /\ LET newManifestId == wManifest[w].id + 1 
           newManifest == [wManifest[w] EXCEPT !.id = newManifestId,
                                               !.writerEpoch = @ + 1]
       IN \/ /\ newManifestId \in DOMAIN manifest
             /\ wState' = [wState EXCEPT ![w] = IDLE]
             /\ UNCHANGED <<manifest, wManifest>>
          \/ /\ newManifestId \notin DOMAIN manifest
             /\ manifest' =  manifest @@ (newManifestId :> newManifest)
             /\ wManifest' = [wManifest EXCEPT ![w] = newManifest]
             /\ wState' = [wState EXCEPT ![w] = CHECK_BOUNDARY]
    /\ UNCHANGED <<gcVars, auxVars, wal, snapshot, boundary, wNextWalId,  
                   wEpoch, wManifestLoad, wMachineData, wNextWalId, wReplayId>>

CheckBoundary(w) ==
    /\ wState[w] = CHECK_BOUNDARY
    /\ LET currBoundary == boundary.manifestId
       IN
            \/ /\ wManifest[w].id <= currBoundary
               /\ wState' = [wState EXCEPT ![w] = IDLE]
               /\ UNCHANGED wEpoch
            \/ /\ wManifest[w].id > currBoundary
               /\ wEpoch' = [wEpoch EXCEPT ![w] = wManifest[w].writerEpoch]
               /\ wState' = [wState EXCEPT ![w] = WRITE_FENCE]
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wManifest, wManifestLoad,
                   wNextWalId, wMachineData, wReplayId>>

WriteFenceWalEntry(w) ==
    /\ wState[w] = WRITE_FENCE
    /\ \/ /\ wNextWalId[w] \in DOMAIN wal
          /\ wState' = [wState EXCEPT ![w] = VALIDATE_BEFORE_RETRY]
          /\ UNCHANGED <<wal, auxWrittenEntries>>
       \/ /\ wNextWalId[w] \notin DOMAIN wal
          /\ LET entry == [kind  |-> FENCE, 
                           epoch |-> wEpoch[w]]
             IN
                /\ wal' = wal @@ (wNextWalId[w] :> entry)
                /\ wState' = [wState EXCEPT ![w] = VALIDATE_BEFORE_REPLAY]
    /\ UNCHANGED <<gcVars, auxVars, manifest, snapshot, boundary, wEpoch, 
                   wManifest, wManifestLoad, wNextWalId, wMachineData, wNextWalId, wReplayId>>

ValidateEpochBeforeWalFenceRetry(w) ==
    /\ wState[w] = VALIDATE_BEFORE_RETRY
    /\ CASE DoRefresh(w) -> 
                /\ RefreshManifest(w)
                /\ UNCHANGED <<wState, wNextWalId>>
         [] wManifestLoad[w].valid = FALSE \/ wEpoch[w] < wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = FENCED]
                /\ ManifestRefreshed(w)
                /\ UNCHANGED wNextWalId
         [] wEpoch[w] > wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = ILLEGAL_STATE]
                /\ ManifestRefreshed(w)
                /\ UNCHANGED wNextWalId
         [] wEpoch[w] = wManifest[w].writerEpoch ->
                /\ wNextWalId' = [wNextWalId EXCEPT ![w] = @ + 1]
                /\ wState' = [wState EXCEPT ![w] = WRITE_FENCE]
                /\ ManifestRefreshed(w)
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, wMachineData, wReplayId>>

ValidateEpochBeforeReplay(w) ==
    /\ wState[w] = VALIDATE_BEFORE_REPLAY
    /\ CASE DoRefresh(w) -> 
                /\ RefreshManifest(w)
                /\ UNCHANGED <<wState, wNextWalId, wReplayId>>
         [] wManifestLoad[w].valid = FALSE \/ wEpoch[w] < wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = FENCED]
                /\ ManifestRefreshed(w)
                /\ UNCHANGED <<wNextWalId, wReplayId>>
         [] wEpoch[w] > wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = ILLEGAL_STATE]
                /\ ManifestRefreshed(w)
                /\ UNCHANGED <<wNextWalId, wReplayId>>
         [] wEpoch[w] = wManifest[w].writerEpoch ->
                 /\ wNextWalId' = [wNextWalId EXCEPT ![w] = @ + 1]
                 /\ wReplayId' = [wReplayId EXCEPT ![w] = wManifest[w].replayAfterWalId]
                 /\ wState' = [wState EXCEPT ![w] = LOAD_SNAPSHOT]
                 /\ ManifestRefreshed(w)
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, wMachineData>>

LoadSnapshot(w) ==
    /\ wState[w] = LOAD_SNAPSHOT
    /\ LET snapshotId == wManifest[w].replayAfterWalId - 1
           readSnapshot == IF snapshotId = 0
                           THEN <<>> 
                           ELSE ReadSnapshot(snapshotId)
       IN
          \/ /\ readSnapshot = NIL
             /\ wState' = [wState EXCEPT ![w] = FENCED]
             /\ UNCHANGED <<wMachineData, wReplayId>>
          \/ /\ readSnapshot /= NIL
             /\ wMachineData' = [wMachineData EXCEPT ![w] = readSnapshot]
             /\ wReplayId' = [wReplayId EXCEPT ![w] = wManifest[w].replayAfterWalId]
             /\ wState' = [wState EXCEPT ![w] = REPLAY_WAL]
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, wManifest, wManifestLoad, wNextWalId>>

ReplayWAL(w) ==
    /\ wState[w] = REPLAY_WAL
    /\ LET id   == wReplayId[w]
           read == ReadWalEntry(id)
       IN    
          CASE id = wNextWalId[w] ->
                    /\ wState' = [wState EXCEPT ![w] = READY]
                    /\ wReplayId' = [wReplayId EXCEPT ![w] = 0]
                    /\ UNCHANGED <<wMachineData>>
            [] read = NIL ->
                    /\ wState' = [wState EXCEPT ![w] = VALIDATE_BEFORE_NOT_FOUND]
                    /\ UNCHANGED <<wReplayId, wMachineData>>
            [] read.kind = DATA ->
                    /\ wMachineData' = [wMachineData EXCEPT ![w] = Append(@, read.value)]
                    /\ wReplayId' = [wReplayId EXCEPT ![w] = @ + 1]
                    /\ UNCHANGED <<wState>>
            [] read.kind = FENCE ->
                    /\ wReplayId' = [wReplayId EXCEPT ![w] = @ + 1]
                    /\ UNCHANGED <<wState, wMachineData>>
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, wNextWalId, wManifest, wManifestLoad>>

ValidateBeforeNotFound(w) ==
    /\ wState[w] = VALIDATE_BEFORE_NOT_FOUND
    /\ CASE DoRefresh(w) -> 
                /\ RefreshManifest(w)
                /\ UNCHANGED wState
         [] wManifestLoad[w].valid = FALSE \/ wEpoch[w] < wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = FENCED]
                /\ ManifestRefreshed(w)
         [] wEpoch[w] > wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = ILLEGAL_STATE]
                /\ ManifestRefreshed(w)
         [] wEpoch[w] = wManifest[w].writerEpoch ->
                /\ wState' = [wState EXCEPT ![w] = NOT_FOUND]
                /\ ManifestRefreshed(w)
    /\ UNCHANGED <<storeVars, gcVars, auxVars, wEpoch, 
                   wNextWalId, wReplayId, wMachineData>>

AppendEntryToWAL(w, v) ==
    /\ wState[w] = READY
    /\ v \notin auxUsedValues
    /\ \/ /\ wNextWalId[w] \in DOMAIN wal
          /\ wState' = [wState EXCEPT ![w] = FENCED]
          /\ UNCHANGED <<wal, wNextWalId, wMachineData, auxUsedValues,
                         auxWrittenEntries>>
       \/ LET entry == [kind  |-> DATA,
                        epoch |-> wEpoch[w],
                        value |-> v]
          IN
            /\ wNextWalId[w] \notin DOMAIN wal
            /\ wal' = wal @@ (wNextWalId[w] :> entry)
            /\ wNextWalId' = [wNextWalId EXCEPT ![w] = @ + 1]
            /\ wMachineData' = [wMachineData EXCEPT ![w] = Append(@, v)]
            /\ auxUsedValues' = auxUsedValues \union {v}
            /\ auxWrittenEntries' = Append(auxWrittenEntries, [walId |-> wNextWalId[w],
                                                               value |-> v])
            /\ UNCHANGED wState
    /\ UNCHANGED <<gcVars, manifest, snapshot, boundary,
                   wEpoch, wManifest, wManifestLoad, wReplayId>>

WriteSnapshot(w) ==
    /\ wState[w] = READY
    /\ wMachineData[w] /= <<>>
    /\ LET lastSnapshotId == wManifest[w].replayAfterWalId - 1
           nextSnapshotId == wNextWalId[w] - 1
       IN
          /\ nextSnapshotId >= lastSnapshotId 
          /\ nextSnapshotId \notin DOMAIN snapshot
          /\ snapshot' = snapshot @@ (nextSnapshotId :> wMachineData[w])
          /\ wState' = [wState EXCEPT ![w] = COMMIT_SNAPSHOT]
    /\ UNCHANGED <<gcVars, auxVars, wal, manifest, boundary, 
                   wEpoch, wManifest, wManifestLoad, wNextWalId, wMachineData, wReplayId>>

CommitSnapshot(w) ==
    /\ wState[w] = COMMIT_SNAPSHOT
    /\ LET snapshotId    == wNextWalId[w] - 1
           newManifestId == wManifest[w].id + 1
           newManifest == [wManifest[w] EXCEPT !.id = newManifestId,
                                               !.replayAfterWalId = snapshotId + 1]
        
       IN
          \/ /\ newManifestId \in DOMAIN manifest
                
             /\ wState' = [wState EXCEPT ![w] = FENCED]
             /\ UNCHANGED <<manifest, wManifest>>
          \/ /\ newManifestId \notin DOMAIN manifest
             /\ manifest' = manifest @@ (newManifestId :> newManifest)
             /\ wManifest' = [wManifest EXCEPT ![w] = newManifest]
             /\ wState' = [wState EXCEPT ![w] = READY]
    /\ UNCHANGED <<gcVars, auxVars, wal, snapshot, boundary, wManifestLoad,
                   wEpoch, wNextWalId, wMachineData, wReplayId>>

StartGC(gc) ==
    /\ gcState[gc] = IDLE
    /\ \E type \in {MANIFEST_GC, WAL_GC} :
        /\ gcType' = [gcType EXCEPT ![gc] = type]
        /\ gcManifest' = [gcManifest EXCEPT ![gc] = ReadLastManifest]
        /\ gcState' = [gcState EXCEPT ![gc] = LOAD_BOUNDARY]
        /\ UNCHANGED <<storeVars, writerVars, auxVars, gcBoundary, gcLastWalId>>

LoadGcBoundary(gc) ==
    /\ gcState[gc] = LOAD_BOUNDARY
    /\ \/ /\ gcManifest[gc].id <= boundary.manifestId
          /\ gcState' = [gcState EXCEPT ![gc] = IDLE]
          /\ UNCHANGED gcBoundary 
       \/ /\ gcManifest[gc].id > boundary.manifestId
          /\ gcBoundary' = [gcBoundary EXCEPT ![gc] = boundary]
          /\ gcState' = [gcState EXCEPT ![gc] = 
                            IF gcType[gc] = MANIFEST_GC
                            THEN COMPUTE_BOUNDARY
                            ELSE FIND_LAST_WAL_ID]
    /\ UNCHANGED <<storeVars, writerVars, auxVars,
                   gcLastWalId, gcManifest, gcType>>

MaxManifestId(gc) ==
    IF ~\E id \in DOMAIN manifest : id < gcManifest[gc].id
    THEN 0
    ELSE CHOOSE id \in DOMAIN manifest : 
                    /\ id < gcManifest[gc].id
                    /\ ~\E id1 \in DOMAIN manifest :
                        /\ id1 < gcManifest[gc].id
                        /\ id1 > id
             
ComputeMaxManifestId(gc) ==
    /\ gcState[gc] = COMPUTE_BOUNDARY
    /\ gcBoundary' = [gcBoundary EXCEPT ![gc].manifestId = MaxManifestId(gc)]
    /\ gcState' = [gcState EXCEPT ![gc] = ADVANCE_BOUNDARY]
    /\ UNCHANGED <<storeVars, writerVars, auxVars, gcManifest, 
                   gcLastWalId, gcType>>

AdvanceGcBoundary(gc) ==
    /\ gcState[gc] = ADVANCE_BOUNDARY
    /\ CASE gcBoundary[gc].version < boundary.version ->
                /\ gcState' = [gcState EXCEPT ![gc] = IDLE]
                /\ UNCHANGED <<boundary, gcBoundary>>
         [] gcBoundary[gc].version > boundary.version ->
                /\ gcState' = [gcState EXCEPT ![gc] = ILLEGAL_STATE]
                /\ UNCHANGED <<boundary, gcBoundary>>
         [] /\ gcBoundary[gc].version = boundary.version
            /\ gcBoundary[gc].manifestId > boundary.manifestId ->
                LET newBoundary == [gcBoundary[gc] EXCEPT !.version  = @ + 1]
                IN /\ boundary' = newBoundary 
                   /\ gcBoundary' = [gcBoundary EXCEPT ![gc] = newBoundary] 
                   /\ gcState' = [gcState EXCEPT ![gc] = DELETE]
         [] OTHER -> 
                /\ gcState' = [gcState EXCEPT ![gc] = DONE]
                /\ UNCHANGED <<boundary, gcBoundary>> 
    /\ UNCHANGED <<writerVars, auxVars, manifest, wal, snapshot, 
                   gcManifest, gcLastWalId, gcType>>

DeleteManifest(gc) ==
    /\ gcType[gc] = MANIFEST_GC
    /\ gcState[gc] = DELETE
    /\ \E id \in DOMAIN manifest :
        /\ id <= gcBoundary[gc].manifestId
        /\ manifest' = [i \in (DOMAIN manifest \ {id}) |-> manifest[i]]
        /\ UNCHANGED <<gcLastWalId, boundary, wal, snapshot, 
                       writerVars, gcVars, auxVars>>

FindLastWalId(gc) ==
    /\ gcState[gc] = FIND_LAST_WAL_ID
    /\ gcLastWalId' = [gcLastWalId EXCEPT ![gc] = LastWalId]
    /\ gcState' = [gcState EXCEPT ![gc] = DELETE]
    /\ UNCHANGED <<storeVars, writerVars, auxVars, gcManifest,
                   gcBoundary, gcType>> 

DeletableWalEntry(gc, id) ==
    /\ id < gcManifest[gc].replayAfterWalId
    /\ id < gcLastWalId[gc]
    /\ wal[id].kind = DATA
    
DeleteWalEntry(gc) ==
    /\ gcType[gc] = WAL_GC
    /\ gcState[gc] = DELETE
    /\ \E id \in DOMAIN wal :
        /\ DeletableWalEntry(gc, id)
        /\ wal' = [i \in (DOMAIN wal \ {id}) |-> wal[i]]
    /\ UNCHANGED <<manifest, boundary, snapshot,
                   writerVars, gcVars, auxVars>>

DeletableSnapshot(gc, id) ==
    id < gcManifest[gc].replayAfterWalId - 1

DeleteSnapshot(gc) ==
    /\ gcType[gc] = WAL_GC
    /\ gcState[gc] = DELETE
    /\ \E id \in DOMAIN snapshot :
        /\ DeletableSnapshot(gc, id)
        /\ snapshot' = [i \in (DOMAIN snapshot \ {id}) |-> snapshot[i]]
        /\ UNCHANGED <<boundary, wal, manifest, writerVars, 
                       gcVars, auxVars>>

DataObjectType == [kind: {DATA}, epoch: Nat, value: Values]
FenceObjectType == [kind: {FENCE}, epoch: Nat]
WALObjectType == DataObjectType \union FenceObjectType

ManifestType ==
    [id: Nat, 
     writerEpoch: Nat, 
     replayAfterWalId: Nat]

BoundaryType == [manifestId: Nat, version: Nat]

MachineDataType == Seq(Values)
HistoryEntryType == [walId: Nat, value: Values]

TypeOK ==
    /\ \A id \in DOMAIN manifest : 
        id \in Nat /\ manifest[id] \in ManifestType
    /\ \A id \in DOMAIN wal : 
        id \in Nat /\ wal[id] \in WALObjectType
    /\ \A id \in DOMAIN snapshot : 
        id \in Nat /\ snapshot[id] \in Seq(Values)
    /\ boundary \in BoundaryType
    /\ wState \in [Writers -> {IDLE, FIND_NEXT_WAL_ID, CLAIM_EPOCH, CHECK_BOUNDARY, WRITE_FENCE,
                               VALIDATE_BEFORE_RETRY, VALIDATE_BEFORE_REPLAY, VALIDATE_BEFORE_NOT_FOUND,
                               LOAD_SNAPSHOT, REPLAY_WAL, READY, COMMIT_SNAPSHOT, FENCED, NOT_FOUND}]
    /\ wEpoch \in [Writers -> Nat]
    /\ wManifest \in [Writers -> ManifestType \union {NIL}]
    /\ wManifestLoad \in [Writers -> [loaded: BOOLEAN, checked: BOOLEAN, valid: BOOLEAN]]
    /\ wNextWalId \in [Writers -> Nat]
    /\ wMachineData \in [Writers -> MachineDataType]
    /\ wReplayId \in [Writers -> Nat]
    /\ gcType \in [GarbageCollectors -> {MANIFEST_GC, WAL_GC, NIL}]
    /\ gcState \in [GarbageCollectors -> {IDLE, LOAD_BOUNDARY, COMPUTE_BOUNDARY, 
                                          ADVANCE_BOUNDARY, FIND_LAST_WAL_ID, 
                                          DELETE, DONE}]
    /\ gcLastWalId \in [GarbageCollectors -> Nat]
    /\ gcBoundary \in [GarbageCollectors -> BoundaryType \union {NIL}] 
    /\ gcManifest \in [GarbageCollectors -> ManifestType \union {NIL}]
    /\ auxUsedValues \in SUBSET Values
    /\ auxWrittenEntries \in Seq(HistoryEntryType)

ValidWriters ==
    
    /\ \A w \in Writers : wState[w] \notin { NOT_FOUND, ILLEGAL_STATE }
    
    /\ \E w \in Writers : wState[w] /= FENCED

PrefixOf(machineData, hist) ==
    /\ Len(machineData) <= Len(hist)
    /\ \A pos \in DOMAIN machineData :
            machineData[pos] = hist[pos].value

ConsistentMachineData ==
    \A w \in Writers :
        wState[w] \in {READY, COMMIT_SNAPSHOT} =>
            /\ PrefixOf(wMachineData[w], auxWrittenEntries)
            /\ IF wManifest[w].id = LastManifestId
               THEN Len(wMachineData[w]) = Len(auxWrittenEntries)
               ELSE TRUE

ManifestRepresentsCommittedLog ==
    LET m          == ReadLastManifest 
        snapshotId == m.replayAfterWalId - 1
        snap       == IF snapshotId = 0 THEN <<>>
                      ELSE snapshot[snapshotId]
        hist       == auxWrittenEntries
    IN
        
        /\ PrefixOf(snap, hist)
        
        /\ \A i \in 1..Len(hist) :
            LET histEntry == hist[i]
                snapEntry == snap[i]
                walEntry  == wal[histEntry.walId] 
            IN

                \/ /\ histEntry.walId < m.replayAfterWalId
                   /\ snapEntry = histEntry.value

                \/ /\ histEntry.walId >= m.replayAfterWalId
                   /\ walEntry.kind = DATA
                   /\ walEntry.value = histEntry.value

Init ==
    /\ manifest = <<>> @@ (0 :> [id               |-> 1, 
                                 writerEpoch      |-> 0, 
                                 replayAfterWalId |-> 1])
    /\ wal = <<>>
    /\ snapshot = <<>>
    /\ boundary = [manifestId |-> 0, version |-> 0]
    /\ wState = [w \in Writers |-> IDLE]
    /\ wEpoch = [w \in Writers |-> 0]
    /\ wManifest = [w \in Writers |-> NIL]
    /\ wManifestLoad = [w \in Writers |-> [loaded  |-> FALSE,
                                           checked |-> FALSE,
                                           valid   |-> FALSE]]
    /\ wNextWalId = [w \in Writers |-> 1]
    /\ wMachineData = [w \in Writers |-> <<>>]
    /\ wReplayId = [w \in Writers |-> 0]
    /\ gcType = [gc \in GarbageCollectors |-> NIL]
    /\ gcState = [gc \in GarbageCollectors |-> IDLE]
    /\ gcLastWalId = [gc \in GarbageCollectors |-> 0]
    /\ gcBoundary = [gc \in GarbageCollectors |-> NIL]
    /\ gcManifest = [gc \in GarbageCollectors |-> NIL]
    /\ auxUsedValues = {}
    /\ auxWrittenEntries = <<>>

Next ==
    \/ \E w \in Writers :
        
        \/ StartWriter(w)
        \/ FindNextWalId(w)
        \/ ClaimEpoch(w)
        \/ CheckBoundary(w)
        \/ WriteFenceWalEntry(w)
        \/ ValidateEpochBeforeWalFenceRetry(w)
        \/ ValidateEpochBeforeReplay(w)
        \/ LoadSnapshot(w)
        \/ ReplayWAL(w)
        \/ ValidateBeforeNotFound(w)
        
        \/ \E v \in Values : AppendEntryToWAL(w, v)
        \/ WriteSnapshot(w)
        \/ CommitSnapshot(w)
    \/ \E gc \in GarbageCollectors :
        \/ StartGC(gc)
        \/ LoadGcBoundary(gc)
        \/ ComputeMaxManifestId(gc)
        \/ AdvanceGcBoundary(gc)
        \/ DeleteManifest(gc)
        \/ FindLastWalId(gc)
        \/ DeleteWalEntry(gc)
        \/ DeleteSnapshot(gc)

Spec == Init /\ [][Next]_vars

========================================================================

----------------------------- MODULE Walgit -------------------------

EXTENDS Naturals, Integers, FiniteSets, FiniteSetsExt, Sequences, 
        SequencesExt, TLC

CONSTANTS Replicas, 
          Values    

CONSTANTS IDLE, GET_MANIFEST, REPLAY_WAL, CLAIM_SLOT, 
          CAS_MANIFEST, CHECK_SLOT, DELETE_OWN_SEGMENT, 
          DELETE_BURNED_SEGMENTS, READY,  
          COMMIT_CHECKPOINT, ILLEGAL_STATE

CONSTANTS REPLICATE, WRITE, CHECKPOINT

CONSTANT None

VARIABLES logSegments,     
          checkpoints,     
          manifest         

VARIABLES rOperation,      
          rState,          
          rManifest,       
          rMachineData,    
          rAppliedSeq,     
          rPendingValue,   
          rPendingSegment, 
          rPendingCp,      
          rCandidateSeq,   
          rBurned          

VARIABLES auxUsedValues,   
          auxAttemptKey,   
          auxCommitted     

storeVars == <<logSegments, manifest, checkpoints>>
replicaVars == <<rOperation, rState, rManifest, rMachineData, 
                 rAppliedSeq, rPendingValue, rPendingSegment,
                 rPendingCp, rCandidateSeq, rBurned>>
auxVars == <<auxUsedValues, auxAttemptKey, auxCommitted>>
vars == <<storeVars, replicaVars, auxVars>>

RemoveKey(f, key) == [x \in (DOMAIN f \ {key}) |-> f[x]]

IsCaughtUp(r, currManifest) ==
    rAppliedSeq[r] = currManifest.headSeq

ReadCheckpoint(id) == IF id \in DOMAIN checkpoints
                      THEN checkpoints[id]
                      ELSE None
ReadLogSegment(id) == IF id \in DOMAIN logSegments
                      THEN logSegments[id]
                      ELSE None

IllegalState(r) ==
    /\ rState' = [rState EXCEPT ![r] = ILLEGAL_STATE]
    /\ UNCHANGED <<rOperation, rPendingValue, rManifest, rMachineData, 
                   rAppliedSeq, rPendingSegment, rBurned, 
                   rCandidateSeq, rPendingCp>>

RefreshManifest(r) ==
    rManifest' = [rManifest EXCEPT ![r] = manifest]

TransitionToReady(r) ==
    /\ rState' = [rState EXCEPT ![r] = READY]
    /\ rOperation' = [rOperation EXCEPT ![r] = READY]

TransitionToReplayWAL(r) ==
    /\ rState' = [rState EXCEPT ![r] = REPLAY_WAL]
    /\ rOperation' = [rOperation EXCEPT ![r] = REPLICATE]

ConcatEntries(sq1, sq2) ==
    IF \/ \E i \in DOMAIN sq1 : i \in DOMAIN sq2
       \/ \E i \in DOMAIN sq2 : i \in DOMAIN sq1
    THEN <<>>
    ELSE sq1 @@ sq2

StartReplica(r) ==
    /\ rState[r] = IDLE
    /\ RefreshManifest(r)
    /\ IF IsCaughtUp(r, manifest)
       THEN TransitionToReady(r)
       ELSE TransitionToReplayWAL(r)
    /\ UNCHANGED <<storeVars, auxVars, rPendingValue, 
                   rPendingSegment, rPendingCp, rMachineData,
                   rAppliedSeq, rBurned, rCandidateSeq>>

ShouldLoadCheckpoint(r) ==
    
    /\ rManifest[r].checkpoint /= None
    
    /\ rAppliedSeq[r] < rManifest[r].checkpoint.seq

LoadCheckpoint(r) ==
    LET cp == ReadCheckpoint(rManifest[r].checkpoint.id) IN
        
        /\ rMachineData' = [rMachineData EXCEPT ![r] = cp.entries]
        
        /\ rAppliedSeq' = [rAppliedSeq EXCEPT ![r] = cp.seq]
        /\ UNCHANGED <<rOperation, rState, rPendingValue, rManifest,
                       rPendingSegment, rPendingCp, rBurned, rCandidateSeq>>

ShouldLoadNextSegment(r) ==
    
    \E segRef \in rManifest[r].logSegments : 
        segRef.lastSeq > rAppliedSeq[r]

NextSegmentRef(r) ==

    CHOOSE segRef \in rManifest[r].logSegments :
                /\ segRef.lastSeq > rAppliedSeq[r]
                /\ ~\E segRef0 \in rManifest[r].logSegments :
                    /\ segRef0.lastSeq > rAppliedSeq[r]
                    /\ segRef0.lastSeq < segRef.lastSeq

ReplayNextSegment(r) ==
    LET segRef  == NextSegmentRef(r) 
        segment == ReadLogSegment(segRef.id)
    IN
        
        /\ rMachineData' = [rMachineData EXCEPT ![r] = 
                                    ConcatEntries(@, segment.entries)] 
        
        /\ rAppliedSeq' = [rAppliedSeq EXCEPT ![r] = segRef.lastSeq]
        /\ UNCHANGED <<rOperation, rState, rPendingValue, rManifest, rPendingCp,
                       rPendingSegment, rBurned, rCandidateSeq>>

ShouldCompleteReplay(r) ==
    rAppliedSeq[r] = rManifest[r].headSeq

StateAfterReplay(r) ==
    CASE 
         rOperation[r] = WRITE -> CLAIM_SLOT
      [] rOperation[r] = REPLICATE -> READY
      [] OTHER -> ILLEGAL_STATE

OpAfterReplay(r, nextState) ==
    IF nextState = READY THEN READY ELSE rOperation[r]

CompleteReplay(r) ==
    LET nextState == StateAfterReplay(r)
        nextOp    == OpAfterReplay(r, nextState)
    IN
        /\ rState' = [rState EXCEPT ![r] = nextState]
        /\ rOperation' = [rOperation EXCEPT ![r] = nextOp]
        /\ UNCHANGED <<rPendingValue, rManifest, rMachineData,  
                       rPendingCp, rAppliedSeq, rPendingSegment, 
                       rBurned, rCandidateSeq>>

ReplayWAL(r) ==
    /\ rState[r] = REPLAY_WAL
    /\ CASE ShouldCompleteReplay(r) -> CompleteReplay(r)
         [] ~ShouldCompleteReplay(r) /\ ShouldLoadCheckpoint(r) -> LoadCheckpoint(r)
         [] ~ShouldCompleteReplay(r) /\ ~ShouldLoadCheckpoint(r)
            /\ ShouldLoadNextSegment(r) -> ReplayNextSegment(r)
         [] OTHER -> IllegalState(r)
    /\ UNCHANGED <<storeVars, auxVars>>

StartReplicate(r) ==
    /\ rState[r] = READY
    /\ rManifest[r].version /= manifest.version
    /\ RefreshManifest(r)
    /\ IF IsCaughtUp(r, manifest)
       THEN UNCHANGED <<rState, rOperation>>
       ELSE TransitionToReplayWAL(r)
    /\ UNCHANGED <<storeVars, auxVars, rPendingValue,
                   rAppliedSeq, rPendingSegment, rMachineData,
                   rPendingCp, rBurned, rCandidateSeq>>

StartPublish(r, values) ==
    /\ rState[r] = READY
    /\ values /= {}
    /\ \A v \in values: v \notin auxUsedValues
    /\ rManifest[r].version = manifest.version
    /\ IsCaughtUp(r, rManifest[r])
    /\ rCandidateSeq' = [rCandidateSeq EXCEPT ![r] = rManifest[r].headSeq + 1]
    /\ rState' = [rState EXCEPT ![r] = CLAIM_SLOT]
    /\ rOperation' = [rOperation EXCEPT ![r] = WRITE]
    /\ rPendingValue' = [rPendingValue EXCEPT ![r] = SetToSeq(values)]
    /\ auxUsedValues' = auxUsedValues \union values
    /\ UNCHANGED <<storeVars, auxAttemptKey, auxCommitted, rManifest,
                   rAppliedSeq, rPendingSegment, rPendingCp, rMachineData, 
                   rBurned>>

Entries(r, first, last) ==
    LET diff == first - 1 IN
        [i \in first..last |-> rPendingValue[r][i-diff]]

ClaimFreeLogSlot(r) ==
    /\ rState[r] = CLAIM_SLOT
    /\ LET firstSeq == rCandidateSeq[r]
           lastSeq  == rCandidateSeq[r] + Len(rPendingValue[r]) - 1
           segRef   == [id       |-> firstSeq, 
                        firstSeq |-> firstSeq,
                        lastSeq  |-> lastSeq]
           segment  == [entries    |-> Entries(r, firstSeq, lastSeq),
                        attemptKey |-> auxAttemptKey]
           pending  == [ref |-> segRef, segment |-> segment]
       IN
          
          \/ /\ firstSeq \in DOMAIN logSegments
             /\ rState' = [rState EXCEPT ![r] = CHECK_SLOT]
             /\ UNCHANGED <<logSegments, rPendingSegment, auxAttemptKey>>
          
          \/ /\ firstSeq \notin DOMAIN logSegments
             /\ logSegments' = logSegments @@ (firstSeq :> segment)
             /\ rPendingSegment' = [rPendingSegment EXCEPT![r] = pending]
             /\ auxAttemptKey' = auxAttemptKey + 1
             /\ rState' = [rState EXCEPT ![r] = CAS_MANIFEST]
    /\ UNCHANGED <<manifest, checkpoints, auxCommitted, auxUsedValues,
                   rOperation, rAppliedSeq, rManifest, rPendingValue,
                   rMachineData, rPendingCp, rBurned, rCandidateSeq>>

CheckSlot(r) ==
    /\ rState[r] = CHECK_SLOT
    /\ RefreshManifest(r)
    /\ CASE 

            rAppliedSeq[r] < manifest.headSeq ->
                  /\ rState' = [rState EXCEPT ![r] = REPLAY_WAL]
                  /\ rBurned' = [rBurned EXCEPT ![r] = <<>>]
                  /\ rCandidateSeq' = [rCandidateSeq EXCEPT ![r] = manifest.headSeq + 1]
                  /\ UNCHANGED <<rOperation, rPendingValue>> 

         [] /\ ~(rAppliedSeq[r] < manifest.headSeq)
            /\ rCandidateSeq[r] > manifest.headSeq
            /\ rCandidateSeq[r] \notin DOMAIN logSegments ->
                  /\ rState' = [rState EXCEPT ![r] = CLAIM_SLOT]
                  /\ UNCHANGED <<rOperation, rPendingValue, rCandidateSeq, rBurned>>

         [] /\ ~(rAppliedSeq[r] < manifest.headSeq)
            /\ rCandidateSeq[r] > manifest.headSeq
            /\ rCandidateSeq[r] \in DOMAIN logSegments ->
                  /\ LET id     == rCandidateSeq[r]
                         burned == [id |-> id, attemptKey |-> logSegments[id].attemptKey]
                     IN /\ rBurned' = [rBurned EXCEPT ![r] = Append(@, burned)]
                        /\ rCandidateSeq' = [rCandidateSeq EXCEPT ![r] = @ + 1]
                        /\ rState' = [rState EXCEPT ![r] = CLAIM_SLOT]
                  /\ UNCHANGED <<rOperation, rPendingValue>>
    /\ UNCHANGED <<storeVars, auxVars, rAppliedSeq, rPendingSegment,
                   rMachineData, rPendingCp>>

CasManifest(r) ==
    /\ rState[r] = CAS_MANIFEST
    /\ LET segRef    == rPendingSegment[r].ref
           successor == [rManifest[r] EXCEPT !.headSeq     = segRef.lastSeq,
                                             !.logSegments = @ \union {segRef},
                                             !.version     = @ + 1]
           committed == rPendingSegment[r].segment.entries
       IN

            \/ /\ rManifest[r].version /= manifest.version
               /\ rAppliedSeq[r] < manifest.headSeq
               /\ RefreshManifest(r)
               /\ rState' = [rState EXCEPT ![r] = DELETE_OWN_SEGMENT]
               /\ UNCHANGED <<manifest, auxCommitted, rOperation, 
                              rMachineData, rAppliedSeq,
                              rPendingValue, rPendingSegment>>

            \/ /\ rManifest[r].version /= manifest.version
               /\ rAppliedSeq[r] = manifest.headSeq
               /\ RefreshManifest(r)
               /\ UNCHANGED <<manifest, auxCommitted, rOperation, 
                              rState, rMachineData, rAppliedSeq,
                              rPendingValue, rPendingSegment>>

            \/ /\ rManifest[r].version = manifest.version
               /\ manifest' = successor
               /\ rManifest'       = [rManifest EXCEPT ![r] = successor]
               /\ rMachineData'   = [rMachineData EXCEPT ![r] = 
                                            ConcatEntries(@, committed)]
               /\ rAppliedSeq'     = [rAppliedSeq EXCEPT ![r] = segRef.lastSeq]
               /\ rPendingValue'   = [rPendingValue EXCEPT ![r] = None]
               /\ rPendingSegment' = [rPendingSegment EXCEPT ![r] = None]
               /\ auxCommitted' = ConcatEntries(auxCommitted, committed)
               /\ IF Len(rBurned[r]) = 0
                  THEN TransitionToReady(r)
                  ELSE /\ rState' = [rState EXCEPT ![r] = DELETE_BURNED_SEGMENTS]
                       /\ UNCHANGED rOperation
    /\ UNCHANGED <<logSegments, checkpoints, auxAttemptKey, auxUsedValues,
                   rBurned, rCandidateSeq, rPendingCp>>          

DeleteOwnLogSegment(r) ==
    /\ rState[r] = DELETE_OWN_SEGMENT
    /\ LET id     == rPendingSegment[r].ref.id
           attemptKey == rPendingSegment[r].segment.attemptKey
       IN
        /\ logSegments' = IF /\ id \in DOMAIN logSegments
                             /\ logSegments[id].attemptKey = attemptKey
                          THEN RemoveKey(logSegments, id)
                          ELSE logSegments
        /\ rPendingSegment' = [rPendingSegment EXCEPT ![r] = None]
        /\ rCandidateSeq' = [rCandidateSeq EXCEPT ![r] = rManifest[r].headSeq + 1]
        /\ rState' = [rState EXCEPT ![r] = REPLAY_WAL]
        /\ rBurned' = [rBurned EXCEPT ![r] = <<>>]
        /\ UNCHANGED <<manifest, checkpoints, auxVars, rOperation, rManifest,
                    rAppliedSeq, rPendingValue, rMachineData, rPendingCp>>

DeleteOneBurnedLogSegment(r) ==
    /\ rState[r] = DELETE_BURNED_SEGMENTS
    /\ LET burned == Head(rBurned[r])
       IN /\ logSegments' =
                  IF /\ burned.id \in DOMAIN logSegments
                     /\ logSegments[burned.id].attemptKey = burned.attemptKey
                  THEN RemoveKey(logSegments, burned.id)
                  ELSE logSegments
          /\ rBurned' = [rBurned EXCEPT ![r] = Tail(@)]
          /\ IF Len(rBurned[r]) = 1
             THEN TransitionToReady(r)
             ELSE UNCHANGED <<rState, rOperation>>
    /\ UNCHANGED <<manifest, checkpoints, auxVars, rAppliedSeq, rManifest, 
                   rPendingValue, rMachineData, rCandidateSeq, 
                   rPendingSegment, rPendingCp>>

ValidCheckpointSeq(r, seq) ==

    /\ \E segRef \in rManifest[r].logSegments :
            segRef.lastSeq = seq
    /\ 
       
       \/ rManifest[r].checkpoint = None /\ seq > 0

       \/ /\ rManifest[r].checkpoint /= None
          /\ seq > rManifest[r].checkpoint.seq

CheckpointEntries(r, upperSeq) ==
    LET cpSeqs == { seq \in DOMAIN rMachineData[r] : seq <= upperSeq }
    IN [seq \in cpSeqs |-> rMachineData[r][seq]]  

WriteCheckpoint(r) ==
    /\ rState[r] = READY
    /\ rManifest[r].version = manifest.version
    /\ \E seq \in DOMAIN rMachineData[r] :
        /\ ValidCheckpointSeq(r, seq)
        /\ LET cpId  == [seq |-> seq, attemptKey |-> auxAttemptKey]
               cpRef == [id |-> cpId, seq |-> seq]   
               cp    == [seq     |-> seq,
                         entries |-> CheckpointEntries(r, seq)]
           IN /\ checkpoints' = checkpoints @@ (cpId :> cp)
              /\ rPendingCp' = [rPendingCp EXCEPT ![r] = cpRef]
              /\ rState' = [rState EXCEPT ![r] = COMMIT_CHECKPOINT]
              /\ rOperation' = [rOperation EXCEPT ![r] = CHECKPOINT]
              /\ auxAttemptKey' = auxAttemptKey + 1
    /\ UNCHANGED <<manifest, logSegments, auxUsedValues, auxCommitted,
                   rAppliedSeq, rBurned, rCandidateSeq, rManifest,
                   rPendingSegment, rPendingValue, rMachineData>>

TrimmedSegments(r) ==
    { segRef \in rManifest[r].logSegments :
            segRef.firstSeq > rPendingCp[r].seq }

CommitCheckpoint(r) ==
    /\ rState[r] = COMMIT_CHECKPOINT
    /\ LET segments == TrimmedSegments(r) 
           successor == [rManifest[r] EXCEPT !.logSegments = segments,
                                             !.checkpoint  = rPendingCp[r],
                                             !.version     = @ + 1]
       IN
           /\ IF rManifest[r].version = manifest.version
              THEN /\ manifest' = successor
                   /\ rManifest' = [rManifest EXCEPT ![r] = successor]
              ELSE UNCHANGED <<manifest, rManifest>>
           /\ TransitionToReady(r)
           /\ rPendingCp' = [rPendingCp EXCEPT ![r] = None]
    /\ UNCHANGED <<checkpoints, logSegments, auxVars, rAppliedSeq, rMachineData,
                   rBurned, rCandidateSeq, rPendingSegment, rPendingValue>>

CheckpointIdType == [seq: Nat, attemptKey: Nat]
CheckpointRefType == [id: CheckpointIdType, seq: Nat]   

ValidReplicas == 
    \A r \in Replicas :
        /\ rState[r] /= ILLEGAL_STATE
        /\ rState[r] = READY => rOperation[r] = READY

Init ==
    /\ logSegments = <<>>
    /\ checkpoints = <<>>
    /\ manifest = [headSeq     |-> 0, 
                   logSegments |-> {},
                   checkpoint  |-> None,
                   version     |-> 1]
    /\ rOperation = [r \in Replicas |-> IDLE]
    /\ rState = [r \in Replicas |-> IDLE]
    /\ rManifest = [r \in Replicas |-> None]
    /\ rMachineData = [r \in Replicas |-> <<>>]
    /\ rAppliedSeq = [r \in Replicas |-> 0]
    /\ rPendingValue = [r \in Replicas |-> None]
    /\ rPendingSegment = [r \in Replicas |-> None]
    /\ rPendingCp = [r \in Replicas |-> None]
    /\ rCandidateSeq = [r \in Replicas |-> 0]
    /\ rBurned = [r \in Replicas |-> <<>>]
    /\ auxUsedValues = {}
    /\ auxAttemptKey = 1
    /\ auxCommitted = <<>>

Next ==
    \E r \in Replicas :
        
        \/ StartReplica(r)
        \/ ReplayWAL(r)
        
        \/ StartReplicate(r)
        
        \/ WriteCheckpoint(r)
        \/ CommitCheckpoint(r)
        
        \/ \E v \in SUBSET Values : StartPublish(r, v)
        \/ ClaimFreeLogSlot(r)
        \/ CheckSlot(r)
        \/ CasManifest(r)
        \/ DeleteOwnLogSegment(r)
        \/ DeleteOneBurnedLogSegment(r)

Spec == Init /\ [][Next]_vars

=============================================================

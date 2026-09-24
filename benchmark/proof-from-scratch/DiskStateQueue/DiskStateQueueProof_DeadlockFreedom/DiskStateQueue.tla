-------------------------- MODULE DiskStateQueue ---------------------------
EXTENDS Integers, FiniteSets

CONSTANT SpuriousWakeups    

CONSTANTS Threads,         
          Workers,         
          Capacity,        
          Writer,          
          Reader,          
          Cleaner,         
          RestoreQueue     

None == "-"
Clients == Threads \ { Writer, Reader, Cleaner }
Monitors == { "q", "w", "r", "mu" }
EmptyQueue == [ enq |-> 0, deq |-> 0, lo |-> 1, hi |-> 0 ]
Size(q) == q.enq + q.deq + Capacity * ( q.hi - q.lo + 1 )

QueueType == [enq:0 .. Capacity, deq:0 .. Capacity, lo:Nat \ { 0 }, hi:Nat ]

ASSUME ThreadAssumption == /\ IsFiniteSet(Threads)
                           /\ Workers \subseteq Clients
                           /\ Cardinality({ Writer, Reader, Cleaner }) = 3
                           /\ None \notin
                                Threads \cup { Writer, Reader, Cleaner }
ASSUME CapacityAssumption == Capacity \in Nat \ { 0 }
ASSUME SwitchAssumption == SpuriousWakeups \in BOOLEAN
ASSUME RestoreAssumption == /\ RestoreQueue \in QueueType
                            /\ RestoreQueue.lo <= RestoreQueue.hi + 1

VARIABLES queue,
          balance,
          disk,
          deleted,
          writer,
          reader,
          cleaner,
          finish,
          stop,
          counted,
          owner,
          waiters,
          pc,
          op,
          kind,
          result,
          snapshot,
          checkpointTo
vars ==
  << queue,
     balance,
     disk,
     deleted,
     writer,
     reader,
     cleaner,
     finish,
     stop,
     counted,
     owner,
     waiters,
     pc,
     op,
     kind,
     result,
     snapshot,
     checkpointTo
  >>

Init ==
  /\ queue = EmptyQueue /\ balance = 0 /\ disk = 0 /\ deleted = 0
  /\ writer = [ file |-> -1, done |-> FALSE ]
  /\ reader = [ file |-> 0, cache |-> -1, canRead |-> FALSE, done |-> FALSE ]
  /\ cleaner = [ done |-> FALSE, limit |-> 0, ready |-> FALSE ]
  /\ finish = FALSE /\ stop = FALSE /\ counted = {}
  /\ owner = [m \in Monitors |-> None]
  /\ waiters = [m \in Monitors |-> {}]
  /\ pc = [p \in Threads |-> IF p \in { Writer, Reader } THEN "new" ELSE "idle"]
  /\ op = [p \in Threads |-> "none"] /\ kind = [p \in Threads |-> "none"]
  /\ result = [p \in Threads |-> FALSE]
  /\ snapshot = EmptyQueue /\ checkpointTo = 0

Free(m) == owner[m] = None
Own(p, m) == owner[m] = p
CanAcquire(p, m) == owner[m] \in { None, p }
CanWake(p, m) == Free(m) /\ p \notin waiters[m]
Signals(m) ==
  IF waiters[m] = {} THEN { {} } ELSE {waiters[m] \ { p }: p \in waiters[m]}
NeedWorkers == Cardinality(counted) < Cardinality(Workers)
CanUse(p) == Own(p, "q") /\ pc[p] \in { "call", "filledReturn" }

Call(p, operation) ==
  /\ p \in Clients /\ pc[p] = "idle" /\ Free("q")
  /\ operation \in { "put", "get", "peek" }
  /\ ( owner' = [owner EXCEPT !["q"] = p] /\ pc' = [pc EXCEPT ![p] = "call"] /\
             op' = [op EXCEPT ![p] = operation] /\
           result' = [result EXCEPT ![p] = FALSE] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            kind,
            snapshot,
            checkpointTo
         >>
     )

Return(p) ==
  /\ CanUse(p) /\ ( op[p] = "put" \/ result[p] )
  /\ ( owner' = [owner EXCEPT !["q"] = None] /\ pc' = [pc EXCEPT ![p] = "idle"] /\
           op' = [op EXCEPT ![p] = "none"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

AppendEntry(p) ==
  /\ queue.enq < Capacity
  /\ \/ /\ CanUse(p) /\ op[p] = "put"
        /\ ( queue' = [queue EXCEPT !.enq = @ + 1] /\ balance' = balance + 1 /\
                 result' = [result EXCEPT ![p] = TRUE] /\
               UNCHANGED << disk,
                  deleted,
                  writer,
                  reader,
                  cleaner,
                  finish,
                  stop,
                  counted,
                  owner,
                  waiters,
                  pc,
                  op,
                  kind,
                  snapshot,
                  checkpointTo
               >>
           )
     \/ /\ p \in Clients \ Workers /\ pc[p] = "idle" /\ Free("q")
        
        /\ ( queue' = [queue EXCEPT !.enq = @ + 1] /\ balance' = balance + 1 /\
                 pc' = [pc EXCEPT ![p] = "unsafeEnd"] /\
               UNCHANGED << disk,
                  deleted,
                  writer,
                  reader,
                  cleaner,
                  finish,
                  stop,
                  counted,
                  owner,
                  waiters,
                  op,
                  kind,
                  result,
                  snapshot,
                  checkpointTo
               >>
           )

Remove(p, peek) ==
  /\ CanUse(p) /\ op[p] = IF peek THEN "peek" ELSE "get"
  /\ ~finish /\ ~stop /\ queue.deq > 0
  /\ ( queue' = [queue EXCEPT !.deq = @ - IF peek THEN 0 ELSE 1] /\
               balance' = balance - ( IF peek THEN 0 ELSE 1 ) /\
             pc' = [pc EXCEPT ![p] = "call"] /\
           result' = [result EXCEPT ![p] = TRUE] /\
         UNCHANGED << disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            snapshot,
            checkpointTo
         >>
     )

EmptyReturn(p, finished) ==
  /\ CanUse(p) /\ op[p] \in { "get", "peek" }
  /\ IF finished
     THEN finish
     ELSE ~finish /\ Size(queue) = 0 /\
         Cardinality(counted) + 1 >= Cardinality(Workers)
  /\ ( result' = [result EXCEPT ![p] = TRUE] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            pc,
            op,
            kind,
            snapshot,
            checkpointTo
         >>
     )

CanCountLast(p) ==
  /\ CanUse(p) /\ p \in Workers /\ op[p] \in { "get", "peek" }
  /\ ~finish /\ stop /\ Size(queue) > 0 /\ p \notin counted
  /\ Cardinality(counted) + 1 = Cardinality(Workers)

CountLast(p) ==
  /\ CanCountLast(p)
  /\ ( counted' = counted \cup { p } /\ pc' = [pc EXCEPT ![p] = "announce"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

AnnounceLast(p) ==
  /\ pc[p] = "announce" /\ Own(p, "q") /\ Free("mu")
  /\ \E remaining \in Signals("mu"):
       ( waiters' = [waiters EXCEPT !["mu"] = remaining] /\
             pc' = [pc EXCEPT ![p] = "announced"] /\
           UNCHANGED << queue,
              balance,
              disk,
              deleted,
              writer,
              reader,
              cleaner,
              finish,
              stop,
              counted,
              owner,
              op,
              kind,
              result,
              snapshot,
              checkpointTo
           >>
       )

WaitWorker(p) ==
  /\ Own(p, "q") /\ p \in Workers
  /\ \/ pc[p] = "announced"
     \/ /\ pc[p] = "call" /\ ~finish /\ ( stop \/ Size(queue) = 0 )
        /\ Cardinality(counted) + 1 < Cardinality(Workers)
  /\ ( owner' = [owner EXCEPT !["q"] = None] /\
               waiters' = [waiters EXCEPT !["q"] = @ \cup { p }] /\
             counted' = counted \cup { p } /\
           pc' = [pc EXCEPT ![p] = "waitQ"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

WakeWorker(p) ==
  /\ pc[p] = "waitQ" /\ CanWake(p, "q")
  /\ ( owner' = [owner EXCEPT !["q"] = p] /\
               waiters' = [waiters EXCEPT !["q"] = @ \ { p }] /\
             counted' = counted \ { p } /\
           pc' = [pc EXCEPT ![p] = "call"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

NotifyWorkers(p) ==
  /\ CanUse(p) /\ op[p] = "put" /\ counted # {} /\ ~stop
  /\ ( waiters' = [waiters EXCEPT !["q"] = {}] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            pc,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

StartOffer(p) ==
  /\ queue.enq = Capacity
  /\ ( ( CanUse(p) /\ op[p] = "put" ) \/
         ( p \in Clients \ Workers /\ pc[p] = "idle" /\ Free("q") )
     )
  /\ ( pc' = [pc EXCEPT ![p] = "offerEnter"] /\
           op' = [op EXCEPT ![p] = IF Own(p, "q") THEN "put" ELSE "unsafePut"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

EnterWriter(p, offer) ==
  /\ pc[p] = IF offer THEN "offerEnter" ELSE "awaitEnter"
  /\ Free("w")
  /\ ( owner' = [owner EXCEPT !["w"] = p] /\
           pc' = [pc EXCEPT ![p] = IF offer THEN "offer" ELSE "await"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FlushOld(p) ==
  /\ Own(p, "w") /\ pc[p] = "offer" /\ writer.file = disk
  /\ ( disk' = disk + 1 /\ pc' = [pc EXCEPT ![p] = "offerFlushed"] /\
         UNCHANGED << queue,
            balance,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Offer(p) ==
  /\ Own(p, "w") /\ pc[p] \in { "offer", "offerFlushed" }
  /\ writer.file = -1 \/ pc[p] = "offerFlushed"
  /\ \E remaining \in Signals("w"):
       ( writer' = [writer EXCEPT !.file = queue.hi] /\
                   queue' = [queue EXCEPT !.hi = @ + 1, !.enq = 0] /\
                 owner' = [owner EXCEPT !["w"] = None] /\
               waiters' = [waiters EXCEPT !["w"] = remaining] /\
             pc' = [pc EXCEPT ![p] = "offered"] /\
           UNCHANGED << balance,
              disk,
              deleted,
              reader,
              cleaner,
              finish,
              stop,
              counted,
              op,
              kind,
              result,
              snapshot,
              checkpointTo
           >>
       )

StartAwait(p) ==
  /\ CanUse(p) /\ op[p] \in { "get", "peek" } /\ queue.deq = 0
  /\ ~finish /\ ~stop /\ Size(queue) > 0 /\ queue.lo + 1 >= queue.hi
  /\ ( pc' = [pc EXCEPT ![p] = "awaitEnter"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

WaitWriter(p) ==
  /\ Own(p, "w") /\ pc[p] = "await" /\ writer.file # -1
  /\ ( owner' = [owner EXCEPT !["w"] = None] /\
             waiters' = [waiters EXCEPT !["w"] = @ \cup { p }] /\
           pc' = [pc EXCEPT ![p] = "waitW"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

WakeWriterCaller(p) ==
  /\ pc[p] = "waitW" /\ CanWake(p, "w")
  /\ ( owner' = [owner EXCEPT !["w"] = p] /\
             waiters' = [waiters EXCEPT !["w"] = @ \ { p }] /\
           pc' = [pc EXCEPT ![p] = "await"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

AwaitDone(p) ==
  /\ Own(p, "w") /\ pc[p] = "await" /\ writer.file = -1
  /\ ( owner' = [owner EXCEPT !["w"] = None] /\
           pc' = [pc EXCEPT ![p] = "fillReady"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

StartTake(p, sourceKind) ==
  /\ Own(p, "q") /\ op[p] \in { "get", "peek" } /\ queue.deq = 0
  /\ ~finish /\ ~stop /\ Size(queue) > 0
  /\ IF sourceKind = "load"
     THEN /\ queue.lo + 1 <= queue.hi
          /\ pc[p] = "fillReady" \/
               ( pc[p] = "call" /\ queue.lo + 1 < queue.hi )
     ELSE pc[p] = "fillReady" /\ queue.lo + 1 > queue.hi
  /\ ( pc' = [pc EXCEPT ![p] = "takeEnter"] /\
           kind' = [kind EXCEPT ![p] = sourceKind] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            result,
            snapshot,
            checkpointTo
         >>
     )

EnterReader(p) ==
  /\ pc[p] = "takeEnter" /\ Free("r")
  /\ ( owner' = [owner EXCEPT !["r"] = p] /\ pc' = [pc EXCEPT ![p] = "take"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Take(p, source) ==
  /\ Own(p, "r") /\ pc[p] = "take"
  /\ CASE source = "cache" -> reader.cache # -1
     [] source = "file" ->
     reader.cache = -1 /\ reader.file # -1 /\
         ( kind[p] = "load" \/ reader.canRead ) /\
       reader.file \in deleted .. ( disk - 1 )
     [] source = "direct" ->
     kind[p] = "load" /\ reader.cache = -1 /\ reader.file = -1 /\
       queue.lo \in deleted .. ( disk - 1 )
     [] source = "empty" ->
     kind[p] = "cache" /\ reader.cache = -1 /\
       ( reader.file = -1 \/ ~reader.canRead )
  /\ LET full == source # "empty"
         exchange == source \in { "cache", "file" }
     IN ( queue' =
                         [queue EXCEPT
                         !.deq =
                         IF full THEN Capacity ELSE queue.enq,
                         !.enq =
                         IF full THEN @ ELSE 0,
                         !.lo =
                         @ + IF full THEN 1 ELSE 0] /\
                       reader' =
                         [reader EXCEPT
                         !.cache =
                         IF exchange THEN -1 ELSE @,
                         !.file =
                         IF exchange THEN queue.lo ELSE @,
                         !.canRead =
                         IF exchange THEN kind[p] = "load" ELSE @] /\
                     waiters' =
                       [waiters EXCEPT
                       !["r"] =
                       IF exchange /\ kind[p] = "load" THEN {} ELSE @] /\
                   owner' = [owner EXCEPT !["r"] = None] /\
                 pc' = [pc EXCEPT ![p] = "filled"] /\
               kind' =
                 [kind EXCEPT
                 ![p] =
                 IF kind[p] = "load"
                 THEN "loadDone"
                 ELSE IF full THEN "cacheHit" ELSE "cacheMiss"] /\
             UNCHANGED << balance,
                disk,
                deleted,
                writer,
                cleaner,
                finish,
                stop,
                counted,
                op,
                result,
                snapshot,
                checkpointTo
             >>
         )

Boot(p, m) ==
  /\ pc[p] = "new" /\ Free(m)
  /\ ( pc' = [pc EXCEPT ![p] = "run"] /\ owner' = [owner EXCEPT ![m] = p] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

BackgroundWait(p, m) ==
  /\ Own(p, m) /\ pc[p] = "run"
  /\ IF p = Writer
     THEN writer.file = -1 /\ ~writer.done
     ELSE reader.file = -1 \/ reader.cache # -1 \/ ~reader.canRead
  /\ ( owner' = [owner EXCEPT ![m] = None] /\
             waiters' = [waiters EXCEPT ![m] = @ \cup { p }] /\
           pc' = [pc EXCEPT ![p] = "wait"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

BackgroundWake(p, m) ==
  /\ pc[p] = "wait" /\ CanWake(p, m)
  /\ ( owner' = [owner EXCEPT ![m] = p] /\
             waiters' = [waiters EXCEPT ![m] = @ \ { p }] /\
           pc' =
             [pc EXCEPT
             ![p] =
             IF p = Reader /\ reader.done THEN "exit" ELSE "run"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Publish ==
  /\ Own(Writer, "w") /\ pc[Writer] = "run" /\ writer.file = disk
  /\ Free("r")

  /\ \E remaining \in Signals("w"):
       ( disk' = disk + 1 /\ writer' = [writer EXCEPT !.file = -1] /\
                 reader' = [reader EXCEPT !.canRead = TRUE] /\
               waiters' = [waiters EXCEPT !["w"] = remaining, !["r"] = {}] /\
             pc' = [pc EXCEPT ![Writer] = "published"] /\
           UNCHANGED << queue,
              balance,
              deleted,
              cleaner,
              finish,
              stop,
              counted,
              owner,
              op,
              kind,
              result,
              snapshot,
              checkpointTo
           >>
       )

Prefetch ==
  /\ Own(Reader, "r") /\ pc[Reader] = "run"
  /\ reader.cache = -1 /\ reader.canRead /\
       reader.file \in deleted .. ( disk - 1 )
  /\ ( reader' = [reader EXCEPT !.cache = reader.file, !.file = -1] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            pc,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

BackgroundExit(p, m) ==
  /\ Own(p, m)
  /\ IF p = Writer
     THEN pc[p] = "run" /\ writer.done /\ writer.file = -1
     ELSE pc[p] = "exit" /\ reader.done
  /\ ( owner' = [owner EXCEPT ![m] = None] /\ pc' = [pc EXCEPT ![p] = "exited"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Clean ==
  /\ ~cleaner.done /\ cleaner.ready
  /\ cleaner.limit <= queue.lo - 1
  /\ ( deleted' = cleaner.limit /\ cleaner' = [cleaner EXCEPT !.ready = FALSE] /\
         UNCHANGED << queue,
            balance,
            disk,
            writer,
            reader,
            finish,
            stop,
            counted,
            owner,
            waiters,
            pc,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

CleanerExit ==
  /\ cleaner.done /\ pc[Cleaner] # "exited"
  /\ ( pc' = [pc EXCEPT ![Cleaner] = "exited"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishBegin(p) ==
  /\ p \in Clients /\ pc[p] = "idle" /\ Free("q")
  /\ ( owner' = [owner EXCEPT !["q"] = p] /\ pc' = [pc EXCEPT ![p] = "finish"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishSignal(p) ==
  /\ pc[p] = "finish" /\ Own(p, "q")
  /\ ( finish' = TRUE /\ waiters' = [waiters EXCEPT !["q"] = {}] /\
           pc' = [pc EXCEPT ![p] = "finishMu"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            stop,
            counted,
            owner,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishNotify(p) ==
  /\ pc[p] = "finishMu" /\ Own(p, "q") /\ Free("mu")
  /\ \E remaining \in Signals("mu"):
       ( waiters' = [waiters EXCEPT !["mu"] = remaining] /\
             pc' = [pc EXCEPT ![p] = "finishEnd"] /\
           UNCHANGED << queue,
              balance,
              disk,
              deleted,
              writer,
              reader,
              cleaner,
              finish,
              stop,
              counted,
              owner,
              op,
              kind,
              result,
              snapshot,
              checkpointTo
           >>
       )

FinishQueue(p) ==
  /\ pc[p] = "finishEnd" /\ Own(p, "q")
  /\ ( owner' = [owner EXCEPT !["q"] = None] /\
           pc' = [pc EXCEPT ![p] = "finishWriter"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishWriter(p) ==
  /\ pc[p] = "finishWriter" /\ Free("w")
  /\ ( writer' = [writer EXCEPT !.done = TRUE] /\
             waiters' = [waiters EXCEPT !["w"] = {}] /\
           pc' = [pc EXCEPT ![p] = "finishReader"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishReaderBegin(p) ==
  /\ pc[p] = "finishReader" /\ Free("r")
  /\ ( reader' = [reader EXCEPT !.done = TRUE] /\
             owner' = [owner EXCEPT !["r"] = p] /\
           pc' = [pc EXCEPT ![p] = "finishReaderEnd"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishReader(p) ==
  /\ pc[p] = "finishReaderEnd" /\ Own(p, "r")
  /\ ( waiters' = [waiters EXCEPT !["r"] = {}] /\
             owner' = [owner EXCEPT !["r"] = None] /\
           pc' = [pc EXCEPT ![p] = "finishCleaner"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

FinishCleaner(p) ==
  /\ pc[p] = "finishCleaner"
  /\ ( cleaner' = [cleaner EXCEPT !.done = TRUE] /\
           pc' = [pc EXCEPT ![p] = "idle"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

SuspendBegin(p) ==
  /\ p \in Clients /\ pc[p] = "idle" /\ Free("q")
  /\ ( owner' = [owner EXCEPT !["q"] = p] /\ pc' = [pc EXCEPT ![p] = "suspend"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

StopWorkers(p) ==
  /\ pc[p] = "suspend" /\ Own(p, "q") /\ ~finish
  /\ ( stop' = TRUE /\ owner' = [owner EXCEPT !["q"] = None] /\
           pc' =
             [pc EXCEPT ![p] = IF NeedWorkers THEN "barrier" ELSE "barrierDone"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

EnterBarrier(p) ==
  /\ pc[p] = "barrier" /\ Free("mu")

  /\ ( owner' = [owner EXCEPT !["mu"] = p] /\
             pc' = [pc EXCEPT ![p] = "barrierMu"] /\
           kind' =
             [kind EXCEPT
             ![p] =
             IF finish
             THEN "finished"
             ELSE IF NeedWorkers THEN "wait" ELSE "done"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            result,
            snapshot,
            checkpointTo
         >>
     )

WaitBarrier(p) ==
  /\ pc[p] = "barrierMu" /\ Own(p, "mu") /\ kind[p] # "finished"

  /\ kind[p] = "wait" \/ NeedWorkers \/
       ( \E w \in Workers: pc[w] = "announce" )
  /\ ( owner' = [owner EXCEPT !["mu"] = None] /\
             waiters' = [waiters EXCEPT !["mu"] = @ \cup { p }] /\
           pc' = [pc EXCEPT ![p] = "waitMu"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

WakeBarrier(p) ==
  /\ pc[p] = "waitMu" /\ CanWake(p, "mu")
  
  /\ ( waiters' = [waiters EXCEPT !["mu"] = @ \ { p }] /\
           pc' = [pc EXCEPT ![p] = "recheck"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Recheck(p) ==
  /\ pc[p] = "recheck" /\ Free("q") /\ ~finish
  /\ ( pc' = [pc EXCEPT ![p] = IF NeedWorkers THEN "barrier" ELSE "barrierDone"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Suspended(p) ==
  /\ pc[p] = "barrierDone" \/
       /\ pc[p] = "barrierMu" /\ Own(p, "mu") /\ kind[p] # "finished"
       /\ kind[p] = "done" \/ ~NeedWorkers \/

            ( \E w \in Workers: CanCountLast(w)
            )
  /\ ( owner' = [owner EXCEPT !["mu"] = IF @ = p THEN None ELSE @] /\
           pc' = [pc EXCEPT ![p] = "idle"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

SuspendFinished(p, at) ==
  /\ finish
  /\ CASE at = "queue" -> pc[p] = "suspend" /\ Own(p, "q")
     [] at = "mu" -> pc[p] = "barrierMu" /\ Own(p, "mu")
     [] at = "recheck" -> pc[p] = "recheck" /\ Free("q")
  /\ ( owner' =
             [owner EXCEPT
             !["q"] =
             IF @ = p THEN None ELSE @,
             !["mu"] =
             IF @ = p THEN None ELSE @] /\
           pc' = [pc EXCEPT ![p] = "idle"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Resume(p) ==
  
  /\ p \in Clients /\ pc[p] \in { "idle", "commit" } /\ Free("q")
  /\ ( stop' = FALSE /\ waiters' = [waiters EXCEPT !["q"] = {}] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            counted,
            owner,
            pc,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

StartCheckpoint(p) ==
  /\ p \in Clients /\ pc[p] = "idle" /\ Free("q")
  /\ stop \/ finish
  
  /\ ( cleaner' = [cleaner EXCEPT !.done = TRUE] /\
           pc' = [pc EXCEPT ![p] = "checkpoint"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Snapshot(p) ==
  /\ pc[p] = "checkpoint"
  /\ ( snapshot' = queue /\ checkpointTo' = queue.lo - 1 /\
           pc' = [pc EXCEPT ![p] = "commit"] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result
         >>
     )

Commit(p) ==
  /\ pc[p] = "commit"
  /\ ( deleted' = checkpointTo /\ pc' = [pc EXCEPT ![p] = "idle"] /\
         UNCHANGED << queue,
            balance,
            disk,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

Advance(p, from, to) ==
  /\ pc[p] = from
  /\ ( pc' = [pc EXCEPT ![p] = to] /\
         UNCHANGED << queue,
            balance,
            disk,
            deleted,
            writer,
            reader,
            cleaner,
            finish,
            stop,
            counted,
            owner,
            waiters,
            op,
            kind,
            result,
            snapshot,
            checkpointTo
         >>
     )

SpuriousWakeup(p) ==
  /\ SpuriousWakeups
  /\ \/ /\ \E m \in Monitors:
             /\ p \in waiters[m]
             /\ waiters' = [waiters EXCEPT ![m] = @ \ { p }]
        /\ UNCHANGED cleaner
     
     \/ /\ p = Cleaner /\ ~cleaner.done /\ ~cleaner.ready
        /\ cleaner' = [cleaner EXCEPT !.ready = TRUE]
        /\ UNCHANGED waiters
  /\ UNCHANGED << queue, balance, disk, deleted, writer, reader, finish, stop,
                  counted, owner, pc, op, kind, result, snapshot, checkpointTo >>

EnqueueStep(p) ==
  \/ AppendEntry(p)
  \/ StartOffer(p)
  \/ EnterWriter(p, TRUE)
  \/ FlushOld(p)
  \/ Offer(p)
  \/ Advance(p, "offered", "call")

DequeueStep(p) ==
  \/ Remove(p, FALSE)
  \/ EmptyReturn(p, FALSE)
  \/ EmptyReturn(p, TRUE)
  \/ CountLast(p)
  \/ AnnounceLast(p)
  \/ WaitWorker(p)
  \/ WakeWorker(p)
  \/ StartAwait(p)
  \/ EnterWriter(p, FALSE)
  \/ WaitWriter(p)
  \/ WakeWriterCaller(p)
  \/ AwaitDone(p)
  \/ \E k \in { "load", "cache" }: StartTake(p, k)
  \/ EnterReader(p)
  \/ \E source \in { "cache", "file", "direct", "empty" }: Take(p, source)
  \/ Advance(p, "filled", "filledReturn")

SuspendStep(p) ==
  \/ StopWorkers(p)
  \/ EnterBarrier(p)
  \/ WaitBarrier(p)
  \/ WakeBarrier(p)
  \/ Recheck(p)
  \/ Suspended(p)
  \/ \E at \in { "queue", "mu", "recheck" }: SuspendFinished(p, at)

FinishStep(p) ==
  \/ FinishBegin(p)
  \/ FinishSignal(p)
  \/ FinishNotify(p)
  \/ FinishQueue(p)
  \/ FinishWriter(p)
  \/ FinishReaderBegin(p)
  \/ FinishReader(p)
  \/ FinishCleaner(p)

WriterStep ==
  \/ Boot(Writer, "w")
  \/ BackgroundWait(Writer, "w")
  \/ BackgroundWake(Writer, "w")
  \/ Publish
  \/ Advance(Writer, "published", "run")
  \/ BackgroundExit(Writer, "w")

ReaderStep ==
  \/ Boot(Reader, "r")
  \/ BackgroundWait(Reader, "r")
  \/ BackgroundWake(Reader, "r")
  \/ Prefetch
  \/ BackgroundExit(Reader, "r")

RequiredMonitor(p, m) ==
  
  \/ /\ m = "q"
     /\ p \in Clients
     /\ pc[p] \in { "idle", "waitQ", "recheck" }
  
  \/ /\ m = "w"
     /\ pc[p] \in { "offerEnter", "awaitEnter", "waitW", "finishWriter" }
  
  \/ /\ m = "r"
     /\ pc[p] \in { "takeEnter", "finishReader" }
  
  \/ /\ m = "mu"
     /\ pc[p] \in { "announce", "finishMu", "barrier", "waitMu" }
  
  \/ /\ m = "w"
     /\ p = Writer
     /\ pc[p] \in { "new", "wait" }
  
  \/ /\ m = "r"
     /\ p = Reader
     /\ pc[p] \in { "new", "wait" }
  
  \/ /\ m = "r"
     /\ p = Writer
     /\ pc[p] = "run"
     /\ writer.file # -1

Blocked ==
  (UNION { waiters[m]: m \in Monitors }) \cup
    { p \in Threads:
      \/ \E m \in Monitors: RequiredMonitor(p, m) /\ ~CanAcquire(p, m)
      \/ p = Cleaner /\ ~cleaner.done /\ ~cleaner.ready }

=============================================================================

-------------------------------- MODULE Network -------------------------------
EXTENDS Naturals, Sequences, SequencesExt, Bags, Functions, TLC

CONSTANT
    OrderedNoDup,
    Ordered,
    ReorderedNoDup,
    Reordered

CONSTANT
    Guarantee
ASSUME NetworkGuaranteeAssumption == Guarantee \in {OrderedNoDup, Ordered, ReorderedNoDup, Reordered}

CONSTANT 
    Servers

VARIABLE 
    messages

----------------------------------------------------------------------------------
\* Reordering and duplication of messages:

ReorderDupInitMessageVar ==
    messages = <<>>
    
ReorderDupWithMessage(m, msgs) == 
    IF m \notin (DOMAIN msgs) THEN
        msgs @@ (m :> 1)
    ELSE
        [ msgs EXCEPT ![m] = @ + 1 ]

ReorderDupWithoutMessage(m, msgs) == 
    IF msgs[m] = 1 THEN
        [ msg \in ((DOMAIN msgs) \ {m}) |-> msgs[msg] ]
    ELSE
        [ msgs EXCEPT ![m] = @ - 1 ]

ReorderDupMessages ==
    DOMAIN messages

ReorderDupMessagesTo(dest, source) ==
    { m \in ReorderDupMessages : m.dest = dest /\ m.source = source}

ReorderDupOneMoreMessage(msg) ==
    \/ msg \notin ReorderDupMessages /\ msg \in ReorderDupMessages'
    \/ msg \in ReorderDupMessages /\ messages'[msg] > messages[msg]

ReorderDupDropMessages ==
    messages' \in SubBag(messages)

----------------------------------------------------------------------------------
\* Reordering and deduplication of messages (iff the spec removes message m from
\* msgs after receiving m, i.e., ReorderNoDupWithoutMessage.)

ReorderNoDupInitMessageVar ==
    messages = {}

ReorderNoDupWithMessage(m, msgs) == 
    msgs \union {m}

ReorderNoDupWithoutMessage(m, msgs) == 
    msgs \ {m}

ReorderNoDupMessages ==
    messages

ReorderNoDupMessagesTo(dest, source) ==
    { m \in messages : m.dest = dest /\ m.source = source }

ReorderNoDupOneMoreMessage(msg) ==
    \/ msg \notin ReorderNoDupMessages /\ msg \in ReorderNoDupMessages'
    \/ msg \in ReorderNoDupMessages /\ messages'[msg] > messages[msg]

ReorderNoDupDropMessages ==
    messages' \in SUBSET messages

----------------------------------------------------------------------------------
\* Point-to-Point Ordering and duplication of messages:

OrderInitMessageVar ==
    messages = [ s \in Servers |-> <<>>]

OrderWithMessage(m, msgs) ==
    [ msgs EXCEPT ![m.dest] = Append(@, m) ]

OrderWithoutMessage(m, msgs) ==
    [ msgs EXCEPT ![m.dest] = RemoveFirst(@, m) ]

OrderMessages ==
    UNION { Range(messages[s]) : s \in Servers }

OrderMessagesTo(dest, source) ==
    FoldLeft(LAMBDA acc, e: IF acc = {} /\ e.source = source THEN acc \cup {e} ELSE acc, {}, messages[dest])

OrderOneMoreMessage(m) ==
    \/ /\ m \notin OrderMessages
       /\ m \in OrderMessages'
    \/ Len(SelectSeq(messages[m.dest], LAMBDA e: m = e)) < Len(SelectSeq(messages'[m.dest], LAMBDA e: m = e))

OrderDropMessages(server) ==
    \E s \in AllSubSeqs(messages[server]):
        messages' = [ messages EXCEPT ![server] = s ]

\* These alternatives of OrderDropMessages may be useful for debugging
OrderDropOlderMessages(server) ==
   (* Always drop older messages first, i.e., an old message has to be handled or dropped before a new message can be handled or dropped. *)
    \E s \in Suffixes(messages[server]):
        messages' = [ messages EXCEPT ![server] = s ]

OrderDropConsecutiveMessages(server) ==
   (* Drop messages regardless of "time", but only ever drop consecutive messages. *)
    \E s \in SubSeqs(messages[server]):
        messages' = [ messages EXCEPT ![server] = s ]

OrderDropMessage(server, Test(_)) ==
    \E i \in { idx \in 1..Len(messages[server]) : Test(messages[server][idx]) }:
        messages' = [ messages EXCEPT ![server] = RemoveAt(@, i) ]

----------------------------------------------------------------------------------
\* Point-to-Point Ordering and no duplication of messages:

OrderNoDupInitMessageVar ==
    OrderInitMessageVar

OrderNoDupWithMessage(m, msgs) ==
    IF \E i \in 1..Len(msgs[m.dest]) : msgs[m.dest][i] = m THEN
        msgs
    ELSE
        OrderWithMessage(m, msgs)

OrderNoDupWithoutMessage(m, msgs) ==
    OrderWithoutMessage(m, msgs)

OrderNoDupMessages ==
    OrderMessages

OrderNoDupMessagesTo(dest, source) ==
    OrderMessagesTo(dest, source)

OrderNoDupOneMoreMessage(m) ==
    \/ /\ m \notin OrderMessages
       /\ m \in OrderMessages'
    \/ /\ m \in OrderMessages
       /\ m \in OrderMessages'

OrderNoDupDropMessages(server) ==
    \E subSeq \in SubSeqs(messages[server]):
        messages' = [ messages EXCEPT ![server] = subSeq ]

----------------------------------------------------------------------------------

InitMessageVar ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupInitMessageVar
      [] Guarantee = Ordered        -> OrderInitMessageVar
      [] Guarantee = ReorderedNoDup -> ReorderNoDupInitMessageVar
      [] Guarantee = Reordered      -> ReorderDupInitMessageVar

Messages ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupMessages
      [] Guarantee = Ordered        -> OrderMessages
      [] Guarantee = ReorderedNoDup -> ReorderNoDupMessages
      [] Guarantee = Reordered      -> ReorderDupMessages

MessagesTo(dest, source) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupMessagesTo(dest, source)
      [] Guarantee = Ordered        -> OrderMessagesTo(dest, source)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupMessagesTo(dest, source)
      [] Guarantee = Reordered      -> ReorderDupMessagesTo(dest, source)

\* Helper for Send and Reply. Given a message m and set of messages, return a
\* new set of messages with one more m in it.
WithMessage(m, msgs) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupWithMessage(m, msgs)
      [] Guarantee = Ordered        -> OrderWithMessage(m, msgs)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupWithMessage(m, msgs)
      [] Guarantee = Reordered      -> ReorderDupWithMessage(m, msgs)

\* Helper for Discard and Reply. Given a message m and bag of messages, return
\* a new bag of messages with one less m in it.
WithoutMessage(m, msgs) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupWithoutMessage(m, msgs)
      [] Guarantee = Ordered        -> OrderWithoutMessage(m, msgs)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupWithoutMessage(m, msgs)
      [] Guarantee = Reordered      -> ReorderDupWithoutMessage(m, msgs)
   
OneMoreMessage(msg) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupOneMoreMessage(msg)
      [] Guarantee = Ordered        -> OrderOneMoreMessage(msg)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupOneMoreMessage(msg) 
      [] Guarantee = Reordered      -> ReorderDupOneMoreMessage(msg)

DropMessages(server) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupDropMessages(server)
      [] Guarantee = Ordered        -> OrderDropMessages(server)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupDropMessages
      [] Guarantee = Reordered      -> ReorderDupDropMessages

DropMessage(sender, Test(_)) ==
    CASE Guarantee = OrderedNoDup   -> FALSE
      [] Guarantee = Ordered        -> OrderDropMessage(sender, Test)
      [] Guarantee = ReorderedNoDup -> FALSE
      [] Guarantee = Reordered      -> FALSE

==================================================================================

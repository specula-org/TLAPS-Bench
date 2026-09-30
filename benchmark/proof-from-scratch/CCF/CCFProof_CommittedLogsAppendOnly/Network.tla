-------------------------------- MODULE Network -------------------------------
EXTENDS Naturals, Sequences, SequencesExt, Bags, Functions, TLC

CONSTANT
    OrderedNoDup,
    Ordered,
    ReorderedNoDup,
    Reordered

CONSTANT
    Guarantee
ASSUME Guarantee \in {OrderedNoDup, Ordered, ReorderedNoDup, Reordered}

CONSTANT 
    Servers

VARIABLE 
    messages

----------------------------------------------------------------------------------

LOCAL ReorderDupInitMessageVar ==
    messages = <<>>
    
LOCAL ReorderDupWithMessage(m, msgs) == 
    IF m \notin (DOMAIN msgs) THEN
        msgs @@ (m :> 1)
    ELSE
        [ msgs EXCEPT ![m] = @ + 1 ]

LOCAL ReorderDupWithoutMessage(m, msgs) == 
    IF msgs[m] = 1 THEN
        [ msg \in ((DOMAIN msgs) \ {m}) |-> msgs[msg] ]
    ELSE
        [ msgs EXCEPT ![m] = @ - 1 ]

LOCAL ReorderDupMessages ==
    DOMAIN messages

LOCAL ReorderDupMessagesTo(dest, source) ==
    { m \in ReorderDupMessages : m.dest = dest /\ m.source = source}

----------------------------------------------------------------------------------

LOCAL ReorderNoDupInitMessageVar ==
    messages = {}

LOCAL ReorderNoDupWithMessage(m, msgs) == 
    msgs \union {m}

LOCAL ReorderNoDupWithoutMessage(m, msgs) == 
    msgs \ {m}

LOCAL ReorderNoDupMessagesTo(dest, source) ==
    { m \in messages : m.dest = dest /\ m.source = source }

----------------------------------------------------------------------------------

LOCAL OrderInitMessageVar ==
    messages = [ s \in Servers |-> <<>>]

LOCAL OrderWithMessage(m, msgs) ==
    [ msgs EXCEPT ![m.dest] = Append(@, m) ]

LOCAL OrderWithoutMessage(m, msgs) ==
    [ msgs EXCEPT ![m.dest] = RemoveFirst(@, m) ]

LOCAL OrderMessagesTo(dest, source) ==
    FoldLeft(LAMBDA acc, e: IF acc = {} /\ e.source = source THEN acc \cup {e} ELSE acc, {}, messages[dest])

----------------------------------------------------------------------------------

LOCAL OrderNoDupInitMessageVar ==
    OrderInitMessageVar

LOCAL OrderNoDupWithMessage(m, msgs) ==
    IF \E i \in 1..Len(msgs[m.dest]) : msgs[m.dest][i] = m THEN
        msgs
    ELSE
        OrderWithMessage(m, msgs)

LOCAL OrderNoDupWithoutMessage(m, msgs) ==
    OrderWithoutMessage(m, msgs)

LOCAL OrderNoDupMessagesTo(dest, source) ==
    OrderMessagesTo(dest, source)

----------------------------------------------------------------------------------

InitMessageVar ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupInitMessageVar
      [] Guarantee = Ordered        -> OrderInitMessageVar
      [] Guarantee = ReorderedNoDup -> ReorderNoDupInitMessageVar
      [] Guarantee = Reordered      -> ReorderDupInitMessageVar

MessagesTo(dest, source) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupMessagesTo(dest, source)
      [] Guarantee = Ordered        -> OrderMessagesTo(dest, source)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupMessagesTo(dest, source)
      [] Guarantee = Reordered      -> ReorderDupMessagesTo(dest, source)

WithMessage(m, msgs) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupWithMessage(m, msgs)
      [] Guarantee = Ordered        -> OrderWithMessage(m, msgs)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupWithMessage(m, msgs)
      [] Guarantee = Reordered      -> ReorderDupWithMessage(m, msgs)

WithoutMessage(m, msgs) ==
    CASE Guarantee = OrderedNoDup   -> OrderNoDupWithoutMessage(m, msgs)
      [] Guarantee = Ordered        -> OrderWithoutMessage(m, msgs)
      [] Guarantee = ReorderedNoDup -> ReorderNoDupWithoutMessage(m, msgs)
      [] Guarantee = Reordered      -> ReorderDupWithoutMessage(m, msgs)

==================================================================================

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

----------------------------------------------------------------------------------

ReorderNoDupInitMessageVar ==
    messages = {}

ReorderNoDupWithMessage(m, msgs) == 
    msgs \union {m}

ReorderNoDupWithoutMessage(m, msgs) == 
    msgs \ {m}

ReorderNoDupMessagesTo(dest, source) ==
    { m \in messages : m.dest = dest /\ m.source = source }

----------------------------------------------------------------------------------

OrderInitMessageVar ==
    messages = [ s \in Servers |-> <<>>]

OrderWithMessage(m, msgs) ==
    [ msgs EXCEPT ![m.dest] = Append(@, m) ]

OrderWithoutMessage(m, msgs) ==
    [ msgs EXCEPT ![m.dest] = RemoveFirst(@, m) ]

OrderMessagesTo(dest, source) ==
    FoldLeft(LAMBDA acc, e: IF acc = {} /\ e.source = source THEN acc \cup {e} ELSE acc, {}, messages[dest])

----------------------------------------------------------------------------------

OrderNoDupInitMessageVar ==
    OrderInitMessageVar

OrderNoDupWithMessage(m, msgs) ==
    IF \E i \in 1..Len(msgs[m.dest]) : msgs[m.dest][i] = m THEN
        msgs
    ELSE
        OrderWithMessage(m, msgs)

OrderNoDupWithoutMessage(m, msgs) ==
    OrderWithoutMessage(m, msgs)

OrderNoDupMessagesTo(dest, source) ==
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

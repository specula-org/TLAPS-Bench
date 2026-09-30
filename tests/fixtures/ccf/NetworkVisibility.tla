---- MODULE NetworkVisibility ----
EXTENDS CCFProofDefs
LOCAL P == INSTANCE TLAPS

Configured == Guarantee = OrderedNoDup /\ OrderedNoDup \notin {Ordered, ReorderedNoDup, Reordered}

THEOREM InitialNetwork ==
    Configured => (Network!InitMessageVar <=> messages = [s \in Servers |-> <<>>])
BY ONLY P!SMT DEF Configured, Network!InitMessageVar,
    Network!OrderNoDupInitMessageVar, Network!OrderInitMessageVar

THEOREM MessageInsertion ==
    \A m, q : Configured =>
      Network!WithMessage(m, q) =
        IF \E k \in 1..Network!Len(q[m.dest]) : q[m.dest][k] = m
        THEN q
        ELSE [q EXCEPT ![m.dest] = Network!Append(@, m)]
BY ONLY P!SMT DEF Configured, Network!WithMessage,
    Network!OrderNoDupWithMessage, Network!OrderWithMessage

THEOREM MessageRemoval ==
    \A m, q : Configured =>
      Network!WithoutMessage(m, q) = [q EXCEPT ![m.dest] = Network!RemoveFirst(@, m)]
BY ONLY P!SMT DEF Configured, Network!WithoutMessage,
    Network!OrderNoDupWithoutMessage, Network!OrderWithoutMessage

THEOREM MessageSelection ==
    \A dest, sender : Configured =>
      Network!MessagesTo(dest, sender) =
        Network!FoldLeft(LAMBDA acc, e :
            IF acc = {} /\ e.source = sender THEN acc \cup {e} ELSE acc,
            {}, messages[dest])
BY ONLY P!Isa DEF Configured, Network!MessagesTo,
    Network!OrderNoDupMessagesTo, Network!OrderMessagesTo
====

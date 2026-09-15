

-------------------------------- MODULE Common --------------------------------

EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Symbols, 
    ArbitrarySymbol, 
    MaxOffset 

ASSUME ArbitrarySymbolIsDistinct == ArbitrarySymbol \notin Symbols

ASSUME SymbolsIsFinite == IsFiniteSet(Symbols)

ASSUME SymbolsIsNonEmpty == Symbols # {}

ASSUME MaxOffsetIsNat == MaxOffset \in Nat

Offset == 0..MaxOffset

SymbolOrArbitrary == Symbols \union {ArbitrarySymbol}

Min(a, b) == IF a <= b THEN a ELSE b
Max(a, b) == IF a <= b THEN b ELSE a

ArrayOfAnyLength(T) == [elems: Seq(T)]
Array(T, len) == [elems: [1..len -> T]]
ConstArray(len, x) == [elems |-> [i \in 1..len |-> x]]
MkArray(len, f) == [elems |-> [i \in 1..len |-> f[i - 1]]]
EmptyArray == [elems |-> <<>>]
ArrayLen(a) == Len(a.elems)
SeqToArray(seq) == [elems |-> seq]
ArrayGet(a, i) == a.elems[i+1]
ArraySet(a, i, x) == [a EXCEPT !.elems[i+1] = x]
ArraySlice(a, startInclusive, endExclusive) == [elems |-> SubSeq(a.elems, startInclusive + 1, endExclusive)]
ArrayConcat(a1, a2) == [elems |-> a1.elems \o a2.elems]

WriteToFile(file, offset, data_to_write) ==
    LET
       file_len == ArrayLen(file)
       data_len == ArrayLen(data_to_write)
       length == Max(file_len, offset + data_len)
    IN
    MkArray(
        length,
        [i \in 0..(length-1) |->
            CASE
                i < offset -> IF i < file_len THEN ArrayGet(file, i) ELSE ArbitrarySymbol
                []
                i >= offset /\ i < offset + data_len -> ArrayGet(data_to_write, i - offset)
                []
                i >= offset + data_len -> ArrayGet(file, i)])

TruncateOrExtendFile(file, new_length) ==
    IF new_length > ArrayLen(file)
    THEN ArrayConcat(file, ConstArray(new_length - ArrayLen(file), ArbitrarySymbol))
    ELSE ArraySlice(file, 0, new_length)

===============================================================================

\* Copyright (c) 2024, Oracle and/or its affiliates.

-------------------------------- MODULE Common --------------------------------
\* This module contains constants and definitions common to both
\* RandomAccessFile and BufferedRandomAccessFile.

EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Symbols, \* data stored in the file (in reality there are 256 symbols: bytes 0x00 to 0xFF)
    ArbitrarySymbol, \* special token for an arbitrary symbol (to reduce the need for nondeterministic choice)
    MaxOffset \* the highest possible offset (in reality this is 2^63 - 1)

\* DiskF and TruncateOrExtendFile mention ArbitrarySymbol explicitly, so
\* Permutations(Symbols) is an unsound SYMMETRY set unless it is not a symbol.
ASSUME ArbitrarySymbolIsDistinct == ArbitrarySymbol \notin Symbols

\* Permutations requires a finite set, as does enumerating SymbolOrArbitrary.
ASSUME SymbolsIsFinite == IsFiniteSet(Symbols)

\* Not needed for soundness; without it every offset holds ArbitrarySymbol.
ASSUME SymbolsIsNonEmpty == Symbols # {}

\* Offset == 0..MaxOffset types curr, lo, diskPos, length, and file_pointer.
ASSUME MaxOffsetIsNat == MaxOffset \in Nat

\* The set of legal offsets
Offset == 0..MaxOffset

\* The set of things that can appear at an offset in a file
SymbolOrArbitrary == Symbols \union {ArbitrarySymbol}

\* Minimum and maximum of two numbers
Min(a, b) == IF a <= b THEN a ELSE b
Max(a, b) == IF a <= b THEN b ELSE a

\* Definitions for 0-indexed arrays (as opposed to TLA+ 1-indexed sequences).
\* A major goal of the BufferedRandomAccessFile spec is to prevent off-by-one
\* errors in the implementation; therefore it should use 0-indexed arrays like
\* Java.
\*
\* The definitions are deliberately crafted so that the usual sequence
\* operators do NOT work on them; this is to help avoid accidental mixing of
\* sequences and arrays.
ArrayOfAnyLength(T) == [elems: Seq(T)]
Array(T, len) == [elems: [1..len -> T]]
ConstArray(len, x) == [elems |-> [i \in 1..len |-> x]]
MkArray(len, f) == [elems |-> [i \in 1..len |-> f[i - 1]]]
EmptyArray == [elems |-> <<>>]
ArrayLen(a) == Len(a.elems)
ArrayToSeq(a) == a.elems
SeqToArray(seq) == [elems |-> seq]
ArrayGet(a, i) == a.elems[i+1]
ArraySet(a, i, x) == [a EXCEPT !.elems[i+1] = x]
ArraySlice(a, startInclusive, endExclusive) == [elems |-> SubSeq(a.elems, startInclusive + 1, endExclusive)]
ArrayConcat(a1, a2) == [elems |-> a1.elems \o a2.elems]

\* General contract of the file `write()` call: extend the file with
\* ArbitrarySymbols if necessary, then overlay some `data_to_write` at the
\* given offset.
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

\* General contract of the file `setLength()` call: truncate the file or fill
\* it with ArbitrarySymbol to reach the desired length.
TruncateOrExtendFile(file, new_length) ==
    IF new_length > ArrayLen(file)
    THEN ArrayConcat(file, ConstArray(new_length - ArrayLen(file), ArbitrarySymbol))
    ELSE ArraySlice(file, 0, new_length)

===============================================================================

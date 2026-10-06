--------------------------- MODULE ClientCentric ---------------------------
EXTENDS Naturals, Sequences, FiniteSets, Util
VARIABLES Keys, Values

r(k,v) == [op |-> "read",  key |-> k, value |-> v]
w(k,v) == [op |-> "write", key |-> k, value |-> v]

=============================================================================

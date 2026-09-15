------------- MODULE Utils ---------------

EXTENDS Integers

Max(S) == CHOOSE x \in S : \A y \in S : y <= x

==========================================

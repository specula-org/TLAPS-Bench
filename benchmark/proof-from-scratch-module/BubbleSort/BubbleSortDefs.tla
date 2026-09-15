----------------------------- MODULE BubbleSortDefs -----------------------------

EXTENDS BubbleSortModel

IsSortedTo(arr, n) == \A p, q \in 1..n : (p =< q) => (arr[p] =< arr[q])

IsSorted(arr) == IsSortedTo(arr, N)

Perms == { f \in [1..N -> 1..N] : 
                     \A p \in 1..N : \E q \in 1..N : f[p] = f[q] }

f ** g == [p \in 1..N |-> f[g[p]]]
   
IsPermOf(arr, brr) == \E f \in Perms : arr = (brr ** f)

=============================================================================


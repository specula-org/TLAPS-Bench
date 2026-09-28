# Allocator proof context

`SchedulingAllocator.PermSeqs` inlines the inner permutation set to avoid
incorrect recursive binding during TLAPM `INSTANCE` expansion. The recursive
function still ranges over `SUBSET S` and returns the same permutations.
The `PermsRec` helpers in both public proof companions use the same form.
Existing omitted proof steps remain omitted.

Regenerate both allocator proof companions in the proof-from-scratch and
proof-completion datasets, then regenerate the module suite. The regression
in `tests/dataset/test_proof_context_compatibility.py` checks the instantiated
recursive-function identity and permutation values for sets of up to four
elements.

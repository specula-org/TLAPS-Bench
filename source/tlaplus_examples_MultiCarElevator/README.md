# Multi-car elevator proof context

`GetDistance`, `GetDirection`, `CanServiceCall`, and `PeopleWaiting` use one
pair-valued argument over their original Cartesian-product domains. All call
sites, including the public proof companion, use explicit pairs. This preserves
the function values while allowing TLAPM to unfold applications.

The shared model also declares `FloorCount \in Int`. This is an explicit
restriction of the original parameter domain, not just a syntax adaptation:
`1..FloorCount` and the movement arithmetic need an integer bound. No positivity
or finite upper bound is added. The target invariants and transition actions
are otherwise unchanged. The reference companion still assumes that elevator
identifiers are disjoint from floors and retains its omitted proof steps.

Regenerate the proof-from-scratch and proof-completion datasets from
`Elevator_proof.tla`, then regenerate the module suite. Tests in
`tests/dataset/test_proof_context_compatibility.py` check function evaluation,
integer-interval reasoning, parameter boundaries, and a bounded reachable-state
model. Bounded model checking does not establish the complete temporal theorems.

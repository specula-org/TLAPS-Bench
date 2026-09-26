# Wildfire regression fixtures

These fixtures extend the actual source or generated `Wildfire` module.
They supply finite client programs and legal sentinel values for TLC; none of
these choices is added to the proof task.

- `LLSC`: Alpha's `LLSCPair` requires a successful SC to have a same-address LL
  with no intervening LL/SC in request order. In `LL a; LL b; SC a`, the SC has
  no such partner. The invariant counts pairable requests versus successful
  responses, so it does not depend on the hidden `beforeOrder` witness.
- `ProbeOrder`: the sole writes set `x` and `y` to one. A read of `y = 1`,
  together with the two processors' memory barriers, orders the write of `x`
  before the final read of `x`. Returning initial `x = 0` contradicts Alpha's
  source-order, request-order, transitivity, and value axioms.
- `ShadowEntry`: the middle processor reads `a = 1`, then passes a barrier and
  writes `b = 1`. The remote processor reads `b = 1`, passes its own barrier,
  then reads `a`. Returning initial `a = 0` gives the same Alpha contradiction.
- `VictimRouting`: four synthetic local transition checks assert the ack route
  for a local/remote sender with/without shadowing. These are routing checks,
  not reachable Alpha counterexamples.

`ShadowEntry` and `ProbeOrder` stage requests and conjoin a pruning predicate
to `Next`. An observed violation is a concrete safety witness; exhaustion only
covers that restricted graph. Their configurations disable deadlock checking
because pruning intentionally creates terminal states.

The Python tests restore old rules as negative controls, check all three task
layouts, reject invalid switch mappings, and check that TLAPM loads the goal.
No fixture checks the full refinement or its liveness component.

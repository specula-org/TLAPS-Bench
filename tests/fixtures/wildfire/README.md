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
- `ResponseEnvironment`: retains the historical one-read counterexample for
  the abstract callbacks. A callback that refuses every response violates
  completion despite the concrete weak fairness. This does not instantiate
  the new recorded-interface goal.
- `RecordedInterface`: exercises the canonical `Protocol` instance and its
  actual recorders, for local/remote memory and a read or LL/SC/MB/read program.
  Only client issue choices are restricted; internal processing and fairness
  are the protocol's. It checks legal histories, completion, the actual
  `TraceSpec`, and a reachable response. Original callback parameters are set
  to `FALSE` to detect a missing `WITH` binding. Removing response-send fairness
  must violate completion while recording is still enabled.

- `UpgradeForwarding`: reaches the pending-upgrade/forwarded-probe race and
  then permits every internal protocol action, with original fairness. Six
  variants cover shared/exclusive forwarding and ordinary/conditional writes,
  including upgrade success/failure and reservation invalidation. Completion,
  data values, exclusive ownership, and SC outcomes are checked in source and
  both generated layouts. Reverting only the guard reproduces the fair
  deadlock; a separate control witnesses completed responses. The fixed prefix
  and finite clients limit coverage and are never included in the proof task.

`ShadowEntry` and `ProbeOrder` stage requests and conjoin a pruning predicate
to `Next`. An observed violation is a concrete safety witness; exhaustion only
covers that restricted graph. Their configurations disable deadlock checking
because pruning intentionally creates terminal states.

The Python tests restore old rules as negative controls, check all three task
layouts, reject invalid switch mappings, and check that TLAPM loads the goal.
The response fixture checks only this finite instance's request completion.
No fixture checks the full parameterized refinement or its liveness component.

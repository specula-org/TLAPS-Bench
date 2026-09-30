# CCF Raft

One Proof-from-Scratch module, `CCF/CCFProof.tla`, belongs to the `next` set
and contains two upstream safety goals:

| Goal | Statement | Meaning |
|---|---|---|
| `CommittedLogsAgree` | `Spec => []LogInv` | Nodes' committed logs are prefix-compatible. |
| `CommittedLogsAppendOnly` | `Spec => CommittedLogAppendOnlyProp` | Each node's committed log only grows by extension. |

There is no reference TLAPS proof or Proof Completion task. Initialization,
protocol actions, fairness, and both property definitions are unchanged.

## Source and scope

The model comes from
[microsoft/CCF](https://github.com/microsoft/CCF/tree/6a2dc420f0166c93f92b773aa49c5203b0767750/tla/consensus)
at `6a2dc420f0166c93f92b773aa49c5203b0767750`. That revision includes the
upstream minimum-term assumption correction in `abs.tla` (CCF #8470).
`ccfraft.tla` and `abs.tla` are copied byte-for-byte. `Network.tla` exports its
helper definitions for TLAPS by removing their `LOCAL` qualifiers; all operator
bodies are unchanged. `upstream.json` records original hashes, the adapted hash,
the exact exported names, and licenses. The abstract refinement theorem is not
selected.

This is CCF's crash-fault-tolerant Raft variant: signatures determine the
committable prefix; elections can roll back unsigned entries; configurations
change dynamically; and retiring nodes continue helping the remaining nodes.
The model starts with one active node and admits further nodes through
reconfiguration. A node identity can join only once. The original initialization
disables PreVote; the benchmark does not import the different initial states
used by upstream simulation or trace-validation wrappers.

The theorem domain retains arbitrary finite nonempty server sets and unbounded
terms, log lengths, requests, and executions. Client payloads are abstracted:
the goals compare the modeled entry records, including terms, entry kinds,
configurations, and retirement records. They do not establish application-level
linearizability, cryptographic security, restart recovery, or the correctness
of every behavior of the C++ implementation.

## Explicit protocol premises

`CCFProof.tla` adds only two named assumptions:

- `DistinctProtocolLabels` distinguishes values within the six protocol enums.
  This follows the model values in upstream `MCccfraft.cfg`; it does not require
  unrelated enums or server identities to be disjoint. CCF's leadership and
  retirement enums are defined in `src/kv/kv_types.h:114-148` at the pinned
  revision.
- `OrderedNetwork` selects `Guarantee = OrderedNoDup`, as upstream
  `MCccfraft.cfg` does. The node channel rejects received nonces no greater
  than the last accepted nonce (`src/node/channels.h:279-300`). `INSTANCE
  Network` does not import its assumptions, so the wrapper states this
  supported network choice explicitly.

TLC's fixed server sets and exploration limits are validation settings, not
theorem assumptions. No protocol transition is disabled to aid proof search.

## Validation

`tests/dataset/test_ccf.py` checks the source, module task, and individual
theorem contexts. Reachable schedules cover joining a node, joint-configuration
commitment, a higher-term election with unsigned-log rollback, and completion
of the original leader's retirement. Each schedule is also checked against
`Init /\ [][Next]_vars`, and a reachability control rejects a stalled schedule.
These checks cover safety prefixes, not satisfaction of the original fairness
conditions by an infinite execution.

Fault controls inject conflicting committed entries or erase a committed
prefix, and require the corresponding safety check to fail. The matching safe
controls pass. Parameter tests reject colliding enum values, unsupported
network choices, and empty server sets; one- and five-server initializations
remain valid. Strict TLAPM canaries check that generated contexts load, expose
the network premise, and support action composition through `ExpandCdot`,
without admitting either target theorem.

The network visibility regression proves initialization, message insertion,
removal, and source selection equations through `INSTANCE Network`, in
the source and all generated contexts. Restoring `LOCAL` reproduces the missing
operator error. A byte-level provenance check reconstructs the exact upstream
module by restoring just those qualifiers, protecting protocol semantics.

`validation/results.json` records the historical time-limited TLC simulations
before the visibility adaptation. `validation/network-visibility.json` records
the adaptation's regression checks and updated input hashes.
TLC must use `-Dtlc2.tool.impl.Tool.cdot=true`, matching upstream `tla/tlc.py`,
to evaluate the model's action composition. This implementation of action
composition is experimental; finite schedules and simulations are supporting
evidence, not an unbounded proof.

```sh
uv run pytest -q tests/dataset/test_ccf.py
uv run tlaps-bench run --filter CCF/CCFProof.tla --dry-run
```

Regenerate the vetted targets with:

```sh
uv run python -m dataset.proof_from_scratch.generate --layered --allow-no-proof source/CCF/CCFProof.tla
uv run python -m dataset.proof_from_scratch.module_tasks
uv run python -m dataset.proof_from_scratch.module_tasks --verify
```

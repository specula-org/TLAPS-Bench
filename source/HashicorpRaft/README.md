# HashiCorp Raft

One proof-from-scratch module contains six top-level safety goals. No type
invariant, arithmetic fact, or internal bookkeeping lemma is scored separately.

| Goal | Requirement | Selection |
|---|---|---|
| `LeaderCompleteness` | Every leader elected in a later term contains the complete entries of every recorded committed prefix. | Core Raft goal, strengthened to full entries and retained history. |
| `StateMachineSafety` | Committed prefixes recorded at any two times or servers agree wherever they overlap. | New end-to-end agreement goal. |
| `CommittedEntriesPreserved` | Each server retains every prefix it previously committed, including after restart. | New durability goal. |
| `LogMatching` | Equal terms at an equal index imply equal complete log prefixes. | Existing goal strengthened beyond term-only equality. |
| `ElectionSafety` | At most one distinct server is ever elected in a term. | Existing goal strengthened beyond simultaneously active leaders. |
| `ConfigurationSafety` | A leader has at most one configuration entry beyond its known committed configuration/log prefix. | Existing top-level membership-change goal, corrected for recovery semantics. |

Each task is `Spec => []Property`, with an omitted proof. The predicates have
different observables: election events, current log contents, election-time
logs, cross-server commit histories, per-server durability, and outstanding
configuration changes. They can share proof lemmas; none is an alias of another
selected goal. `NoPhantomContact` and `LeaseImpliesLoyalty` are excluded because
the source case study records counterexamples caused by its lease/timing
abstraction. Their failures are not proof-capability evidence.

## Scope and provenance

`upstream.json` pins the Specula model and the instrumented HashiCorp Raft
implementation examined by that case study. This is an adapted operational
model with elections, log replication, independent heartbeats, log-disk stalls,
single-server membership changes, deferred vote responses, and crash/restart.
It retains arbitrary finite nonempty server sets, arbitrary nonempty client
value sets, and unbounded terms, log lengths, and executions. Three- and
five-server configurations are validation instances, not theorem assumptions.

Client entries contain a symbolic `value`; configuration entries contain the
complete voter set. Full-entry equality therefore observes more than terms.
`electionHistory` and `commitHistory` are passive observers of actual protocol
steps. No protocol action reads them, and no selected property is added to an
action guard. Restart cannot erase a prior election or commit observation.

The model abstracts successful log writes as durable atomic operations. It
separates current-term persistence from completion of the vote record and the
positive response; the two internal fields of a completed vote record are
updated together. Self-vote setup remains atomic, as in the source model. The
main RPC handler cannot process another main-loop request while awaiting vote
persistence; the independent heartbeat receive path remains enabled.

Snapshots, compaction, FSM execution, pipeline sessions, PreVote, leadership
transfer, partial log-write failures, and detailed clocks are outside this
model. The current-term commitment gate is modeled directly; a client entry can
serve the role of the implementation's initial no-op for that gate. Heartbeat
contacts retain the source's abstract recency treatment. No lease or liveness
theorem is claimed. These tasks concern the specified model, not every behavior
of the complete Go implementation.

## Implementation-backed repairs

| Area | Source-model gap | Benchmark behavior and implementation reference |
|---|---|---|
| Configuration admission | Compared voter sets and omitted the current-term commitment condition. | Compare latest/committed configuration indices and require a current-term committed entry (`raft.go:663–673`). Repeating the same voter set does not make two different configuration entries identical. |
| Configuration recovery | Reconstructed the committed configuration from commit index zero after restart. | Recover the latest and preceding configuration entries; processing a later configuration records its predecessor as committed (`api.go:605–615`, `raft.go:1615–1629`). |
| Membership removal | A leader could remain active after committing its own removal. | Step down when the committed configuration excludes the leader (`raft.go:804–819`). |
| Replication acknowledgments | Used the follower's entire log length, including a suffix absent from the request. | Acknowledge the request's last index and advance match indices monotonically (`replication.go:739–745`, `commitment.go:69–85`). Newly added voters do not inherit an unrelated old match index (`commitment.go:51–66`). |
| Vote recovery | Associated an old persisted candidate with the current term. | Track the vote record's term separately; after restart only a matching-term record supplies `votedFor` (`raft.go:1728–1747`, `2175–2197`). Positive responses remain deferred until vote persistence completes. |
| Vote handling | Allowed a request from a candidate outside the receiver's configuration; a same-term guard made the higher-term response branch unreachable. | Enforce candidate membership and process higher-term responses (`raft.go:1682–1688`, `runCandidate`). |
| RPC serialization | Another main-loop append handler could interleave with a pending vote write. | Serialize main-loop requests while retaining crash and independent-heartbeat interleavings. |

The conflict-aware `MergeEntries` repair already present in the case-study model
is retained. All operational changes are separate from goal strengthening and
the addition of passive histories.

## Validation

`tests/dataset/test_hashicorp_raft.py` checks reachable schedules from `Init` in
both the source and generated module contexts. Each schedule also checks the
original `Spec` as a temporal property, so the fixture cannot silently introduce
an operation outside `Next`. Scenarios cover removal/re-addition, a later-term
election, retained commits across restarts, delayed replication requests, a
crash during vote persistence, removal of the current leader, and a heartbeat
arriving during a pending vote write.

Fault controls reproduce failures when vote responses precede persistence,
quorum or log-freshness checks are removed, committed logs are lost, payloads are
changed, or multiple configurations are proposed concurrently. Additional
controls check acknowledgment bounds, old-vote recovery, and the current-term
configuration gate. Invalid parameter domains must be rejected before state
exploration. The task generator retains all six goals after SANY and the
nondegeneracy checks.

Longer TLC checks are recorded in `tests/fixtures/hashicorp_raft/validation.json`.
They are time-bounded exploration, not a full proof of these unbounded theorems.
No complete reference proof or model solve-rate claim accompanies this addition.

Run the regression suite with:

```sh
uv run pytest -q tests/dataset/test_hashicorp_raft.py
```

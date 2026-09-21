# B-tree allocation boundary and proof compatibility

The B-tree proof-from-scratch task has five original safety goals. The shared specification permits a finite nonempty node pool, but its split actions previously selected new nodes without checking that enough free nodes existed. This permits counterexamples to `TypeOkCorrect` and `LeavesCantHaveLastCorrect`. The evidence below does not show that all five goals are false.

## Reproducing the allocation defect

Use `Nodes = {n1}`, `Keys = {1, 2, 3}`, `Vals = {"v"}`, and `MaxOccupancy = 2`, with distinct state constants and suitable values outside the node/value domains for `NIL` and `MISSING`. These parameters satisfy the existing assumptions.

Starting from `Init`, insert key 1, insert key 2, then request another insertion of key 1. Each successful insertion takes `InsertReq`, `FindLeafToAdd`, and `AddToLeaf`. The third request takes `InsertReq`, `FindLeafToAdd`, and `WhichToSplit`, reaching `SPLIT_ROOT_LEAF` in state 10 with the only node already full. The next root split requires two free nodes, although none exist.

An unmodified TLC evaluation stops on the unsatisfied `CHOOSE`. That error alone is not an invariant counterexample. In TLA+, however, every choice with no satisfying value equals the same unspecified value `CHOOSE x : FALSE`; it need not belong to the bound set. See [Specifying Systems, section 16.1.2](https://lamport.azurewebsites.net/tla/book-02-02-27.pdf#page=310).

The regression controls reconstruct the unguarded actions and normalize their three node choices to an empty-aware selector. `tests/dataset/BTreeChoiceNormalizationCheck.tla` proves the general normalization and the two allocation forms with strict TLAPS and disabled fingerprint reuse: 12 obligations. The controls instantiate only the shared empty-choice value; a choice with a nonempty candidate set continues to return a satisfying member.

| Allowed empty-choice interpretation | State 11 after the root split | Refuted target |
| --- | --- | --- |
| The sole node `n1` | `isLeaf[n1] = TRUE` and `lastOf[n1] = n1`, while `NIL = "nil"` | `LeavesCantHaveLastCorrect` |
| `"lost-node"`, outside `Nodes` | `root = "lost-node"` | `TypeOkCorrect` |

Each bad prefix can stutter forever in its final `ADD_TO_LEAF` state. `GetReq` is disabled there, so the weak fairness conjunct in `Spec` does not exclude the behavior. `BTreeResourceWitness.tla` additionally restricts execution to the first path and checks both the original `Spec` and eventual violation of `LeavesCantHaveLast`; its 11-state temporal check completes successfully.

After `make setup`, run the reproductions and repair controls with:

```sh
PYTHONPATH=src uv run pytest -v tests/dataset/test_btree_resource_guards.py
```

The negative controls expect actual invariant violations and inspect the final counterexample state. TLC logs and JSON traces are saved in each test's temporary `spec/output/` directory. These are specification counterexamples, not claims about a separate B-tree implementation.

## Proposed exhaustion behavior

`SplitLeaf` now requires one free node. `SplitRootLeaf` and `SplitRootInner` require two distinct free nodes. If the fixed pool cannot satisfy the allocation, the split action is disabled and `Spec` permits stuttering. This changes the behavior at resource exhaustion; it does not add an infinite-pool assumption, exclude small parameter configurations, weaken the five targets, or promise that an insertion always completes.

The draft proposes blocking as the smallest explicit allocation policy for the existing safety task. Review should decide whether blocking is the intended specification behavior or whether a separate allocation-failure transition would better describe it. The guards leave split assignments unchanged when enough free nodes exist.

All five original invariants pass exhaustive finite checks for `(node count, key count)` values `(1,3)`, `(2,3)`, `(3,3)`, `(5,4)`, and `(7,4)`, using one value and occupancy 2. These checks cover 8,724 distinct states in total, including exhausted pools and successful splits. They are finite regression evidence, not a general proof of all five goals. `SPLIT_INNER` still has no implementing action in the existing `Next` relation; progress/completeness of the algorithm is outside this safety repair.

## Function-constructor compatibility

A separate preceding commit rewrites five constructors from `[n \in Nodes, k \in Keys |-> ...]` to `[nk \in Nodes \X Keys |-> ...]`, binding `n` and `k` locally where needed. The functions still have domain `Nodes \X Keys` and retain the same `f[n, k]` and `EXCEPT` access patterns. This addresses the [TLAPM multiple-binder limitation](https://github.com/tlaplus/tlapm/issues/294) without currying the functions.

`test_btree_function_encoding.py` checks initial table typing with TLAPS and compares initialization plus all three rewritten split constructors against the original expressions with TLC. The finite comparison covers seven states.

## Dataset and result provenance

Both generated B-tree contexts and the module manifest are synchronized with the repaired source. All five target statements and constant assumptions remain unchanged. The suite still contains 117 module tasks and 276 proof units. The source SHA-256 is `ec247d5d944643666fd5ec60c3c2b489b5560d67ccbc958ebd1710564fae23b2`.

Existing results on the unguarded source remain historical observations. They should not be counted as model-capability failures on the repaired task or silently mixed with results from a fresh run of the new source. The constructor-only version has source SHA-256 `d0ffc162611b0b456c4291d3d41db38b88c7f6d8a4eec7b380b8eec0675a9d12` and still has the allocation defect.

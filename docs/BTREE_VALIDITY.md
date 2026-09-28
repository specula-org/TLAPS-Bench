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

## Comparison compatibility for abstract keys

`KeysAreOrdered` specifies a strict total order on `Keys` using `<`. Three
expressions formerly used `>=`: the branch in `ChildNodeFor` and the right
partitions in `SplitRootLeaf` and `SplitLeaf`. TLAPM's arithmetic backends do
not provide all standard comparison facts outside their numeric domains,
so even the equal-separator branch can fail to unfold for an abstract key.

`KeyAtLeast(key, bound)` uses `~(key < bound)` when both operands are in `Keys`,
and retains `key >= bound` otherwise. The guard preserves the original
out-of-domain expression, including an unspecified `Max` or `PivotOf` result;
no assumption that every such result belongs to `Keys` is needed for this
rewrite. No parameter restriction, transition guard, or target is added.

In the standard definitions, `a >= b` is `b <= a`, `<` is `<=` plus inequality,
and `a <= a` is true for every value. Together with strict total ordering on
`Keys`, these imply `a >= b <=> ~(a < b)` for keys. The relevant definitions
are [ProtoReals, Figure 18.5b, and Naturals, Figure 18.6 of Specifying Systems](https://lamport.azurewebsites.net/tla/book-02-02-27.pdf#page=363).
A proposed interpretation making a key's comparison `k >= k` false therefore
does not establish a counterexample under these standard definitions.

`BTreeKeyOrderEquivalence.tla` extracts those standard comparison definitions
and proves the guarded replacement equivalent in conditionals and set
comprehensions, including arbitrary values outside `Keys`. Its real-order and
infinity premises are properties of the standard definitions, not new
benchmark assumptions. `test_btree_key_comparison.py` instantiates the check
with the helper body read from the source, proves the actual singleton
separator obligation without a numeric-key premise, and explores the union of
the original and repaired transition relations while checking both directions
of their equivalence and all five safety invariants. The finite transition
check complements the comparison proof; it is not a proof of all five
unbounded benchmark theorems.

## Root split branch selection

`WhichToSplit` now sets `splitParent` to `FALSE` when the current node is the
root. The existing `CASE` arms are then mutually exclusive, and the root path
does not depend on `ParentOf(root)` or a domain-external `keysOf` application.
Non-root branch conditions and assignments are unchanged.

The previous arms could both hold: with numeric keys `{1,2,3}`, occupancy 2,
and three nodes, insert 1 and 2 and begin inserting 3. The root has no parent,
so its empty choice may be `NIL`, and the unspecified `keysOf[NIL]` may have
occupancy 2. A legal selection of the second CASE arm pushes `NIL` onto
`toSplit`, violating `TypeOk` in state 10. This is independent of allocation
exhaustion and abstract-key comparison.

`test_btree_root_split.py` realizes these choices explicitly and puts the
parent arm first. It checks the old TypeOk counterexample, a fair witness
satisfying the old `Spec`, and the corrected path under the same choices.
A TLAPS lemma checks that the actual root action preserves the split stack
without assumptions about the parent's value. This repair removes erroneous
root behavior; it is not an equivalent rewrite. It adds no parameter premise
and preserves all five safety predicates.

## Dataset and result provenance

Both generated B-tree contexts and the module manifest are synchronized with
the repaired source. All five target statements and constant assumptions remain
unchanged. The suite contains 123 module tasks and 301 proof units. The earlier
allocation-guard revision had source SHA-256
`ec247d5d944643666fd5ec60c3c2b489b5560d67ccbc958ebd1710564fae23b2`;
the current source hash is recorded by the generated module manifest.

Existing results on the unguarded source remain historical observations. They should not be counted as model-capability failures on the repaired task or silently mixed with results from a fresh run of the new source. The constructor-only version has source SHA-256 `d0ffc162611b0b456c4291d3d41db38b88c7f6d8a4eec7b380b8eec0675a9d12` and still has the allocation defect.

---
name: tla-inductive-invariant-validation
description: Validate candidate inductive invariants for TLA+ safety proofs with Apalache or TLC. Use when designing or debugging an invariant, especially when TLAPS cannot discharge initiation, consecution, or safety-implication obligations.
---

# Validate a TLA+ inductive invariant

Use a model checker to falsify a candidate invariant before investing in its TLAPS proof. Treat a successful finite check as evidence only: prove the invariant in TLAPS, and finish with the benchmark's authoritative `check_proof_bin` command.

## Choose among the three Apalache checks

Shape the candidate as `IndInv == TypeOK /\ H`, where `TypeOK` contains one finite-domain membership clause for every variable and `H` contains the additional facts needed for induction. Given a target module `Target`, a typed wrapper `APTarget.tla`, and a safety predicate `Safety`, these commands explore different parts of the argument:

```sh
apalache-mc check --config=APTarget.cfg --init=Init --inv=IndInv --length=0 APTarget.tla
apalache-mc check --config=APTarget.cfg --init=IndInv --inv=IndInv --length=1 APTarget.tla
apalache-mc check --config=APTarget.cfg --init=IndInv --inv=Safety --length=0 APTarget.tla
```

Interpret these checks as:

1. `Init => IndInv`: legitimate initial states satisfy the candidate.
2. `IndInv /\ Next => IndInv'`: one step preserves the candidate.
3. `IndInv => Safety`: the candidate is strong enough to prove the goal.

The checks starting from `--init=IndInv` require the candidate to assign every variable. A bare safety predicate can instead produce an assignment error such as `x' is used before it is assigned`. Write the missing `TypeOK` if the stripped target has none. Bound `Nat`-typed values to small finite sets, for example `num \in [P -> 0..4]`, and widen a bound before trusting a counterexample that may depend on it.

When a check fails, read the counterexample. Apalache writes `violation1.tla` in a timestamped directory under `_apalache-out/<module>.tla/` unless redirected with `--out-dir` or `--run-dir`; the `Check the trace in: ...` log line gives the exact path.

- A failure of the first check means the candidate excludes a legitimate initial state.
- A failure of the second check gives a state satisfying `IndInv` and a successor violating it. The trailing `InvariantViolation` formula identifies the broken conjunct and usually exposes the fact missing from `H`.
- A failure of the third check means the candidate does not imply the safety goal.

Strengthen or correct the candidate from the trace. Choose which checks to run and when based on the changes, previous feedback, and their cost; related edits can be checked together. For example:

- After a consecution counterexample, rerunning the second check can quickly test a repair. Once the candidate stabilizes, the first and third checks can expose other gaps.
- If only a TLAPS proof changes while the invariant and model stay the same, repeating model checking usually adds no new information.
- Changing a shared definition or the candidate invariant may affect several obligations, so broader checking can be useful.

## Build a non-invasive Apalache wrapper

Keep tool-specific annotations out of `Target.tla`. Re-declare its constants and variables with Apalache types in a separate wrapper, then instantiate the target:

```tla
---- MODULE APTarget ----
EXTENDS Naturals

CONSTANT
  \* @type: Int;
  N

VARIABLE
  \* @type: Set(Int);
  active

INSTANCE Target

TypeOK == active \in SUBSET (0..N)
H == TRUE
IndInv == TypeOK /\ H

====
```

Match every re-declared name exactly so implicit `INSTANCE` substitution binds it. Put each `\* @type:` annotation between the `CONSTANT` or `VARIABLE` keyword and the name it annotates, including every name originally declared in a multi-name block. A comment above the keyword is not accepted and leads to `Expected a type annotation for VARIABLE <name>`.

Define `IndInv` in the wrapper. Fix finite constants in `APTarget.cfg`, for example:

```tla
INIT Init
NEXT Next

CONSTANT N = 5
```

Alternatively, use `--cinit`. For an uninterpreted constant, define a finite value operator such as `JugVal` in the wrapper and substitute it with `Jug <- JugVal` in the configuration. If a polymorphic helper such as `Sum`, `Range`, or `ToSet` defeats type checking, shadow it in the wrapper with a monomorphic version.

Only if the wrapper cannot be made to typecheck, annotate a private scratch copy:

```sh
mkdir -p scratch
cp Target.tla scratch/Candidate.tla
```

Never make the submitted solution extend or instantiate the wrapper or scratch module. Do not alter the target or any dependency as part of model-checking exploration.

## Fall back to TLC

Use TLC when Apalache cannot type the target through a wrapper. Create a separate `MCTarget.tla` that extends `Target` and defines `TypeOK`, `H`, and `IndInv`, with `MCTarget.cfg` beside it. TLC is not on `PATH`; run:

```sh
java -cp /opt/sany/lib/tla2tools.jar tlc2.TLC -deadlock -config MCTarget.cfg MCTarget.tla
```

Check the inductive step by making the candidate its own initial predicate:

```tla
INIT IndInv
NEXT Next
INVARIANT IndInv
```

This checks `IndInv /\ Next => IndInv'` because `IndInv` is an ordinary invariant of the specification started in `IndInv`. Check `Init => IndInv` separately on the real specification with `SPECIFICATION Spec` and `INVARIANT IndInv`. Include `Safety` as a conjunct of `IndInv` to check that the candidate implies it.

Use the same enumerable `TypeOK /\ H` shape as for Apalache. TLC first builds the states satisfying `TypeOK` and then filters them with `H`, so start with the smallest useful model. To reduce enumeration:

- Move a conjunct of `H` immediately after the `TypeOK` clauses that bind the variables it mentions, allowing TLC to prune earlier.
- Sample large domains with `RandomSubset(k, S)` from the `Randomization` module. Rewrite `v \subseteq W` as `v \in SUBSET W` and sample it with `RandomSetOfSubsets(k, p, W)`.

Aim for a few dozen initial states. A TLC violation supplies the same useful two-state signal as Apalache. Once random sampling is involved, a run with no violation proves nothing; rerun it about a dozen times and abandon a run whose search depth grows beyond roughly a dozen steps.

See Leslie Lamport's [Using TLC to Check Inductive Invariance](https://lamport.azurewebsites.net/tla/inductive-invariant.pdf) for the TLC technique.

Never cite an Apalache or TLC verdict as justification for a TLAPS proof step.

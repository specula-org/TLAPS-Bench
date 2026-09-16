# MongoDB Storage: intermediate proofs

**Work in progress. The full snapshot-isolation (SI) theorem is not proved.** This directory shares checked intermediate results for the standalone `Storage.tla` module, following [the discussion in #144](https://github.com/specula-org/tlaps-bench/pull/144#issuecomment-5666114086). It is an experimental snapshot, outside the benchmark dataset.

## Start here

- [StorageSICertificate.tla](StorageSICertificate.tla): the strongest checked theorem, combining the intermediate results.
- [StorageSafety.tla](StorageSafety.tla): interface properties, including writer exclusion, prepared-content stability, operation admission and lifecycle properties.
- [SI_GAP.md](SI_GAP.md): the exact open target and remaining mathematical work.
- [REPAIR.md](REPAIR.md): the transaction-identity and operation-position repair to the history predicate.
- [evidence/verification.json](evidence/verification.json): replay results and their coverage; [proof-checks.txt](evidence/proof-checks.txt) contains the checker summary for each proved module.

## What is established

The 30 proof modules contain 1,507 obligations checked with SANY and fresh, strict TLAPM (`--strict --nofp --threads 1`). The strongest checked theorem is:

```tla
CallerHistoryEpochSpec => []TimestampSICertificate
```

The certificate retains transaction identities and establishes a strict commit order, snapshot cuts before commit, read/write fidelity, and absence of intervening conflicting writes. It is a relational certificate; the bridge to the sequence-based SI predicate remains open.

This theorem starts from upstream `Init`, excludes `RollbackToStable`, and assumes `RC = "snapshot"`, `Timestamps \subseteq Nat`, `NoValue \notin MTxId`, and `FreshPrepareCall`. The latter requires each prepare timestamp to exceed the existing log timestamps at that node; the reference [MultiShardTxn](reference/MultiShardTxn.tla) supplies such timestamps through `Storage!NextTs`. There are no fixed transaction, key or timestamp cardinality bounds in the theorem. The local full-`Next` interface contracts also cover rollback; the stronger certificate does not.

The open target is:

```tla
(CallerHistoryEpochSpec /\ []SingleWritePerKey) => []FullSI
```

Here `FullSI` uses the new [IdentitySnapshotIsolation](IdentitySnapshotIsolation.tla) predicate. That definition and its relationship to the intended Storage interface are part of the work being shared for review. General equivalence to the original `ClientCentric` predicate is not claimed. Neither the number of proved obligations nor the finite model checks establishes the open theorem.

Two questions would help guide further work: is `FreshPrepareCall` part of the intended Storage caller contract, and should the isolation guarantee be scoped to a recovery-free epoch or use an explicit rule for withdrawing rolled-back transactions from the history?

## Reproduce

The scripts use Bash, Python 3.12+, Java 21+, ripgrep (`rg`), and GNU `timeout` and `sha256sum`. On macOS, install GNU coreutils and expose its commands on `PATH`; `gtimeout` is also detected automatically. The checked toolchain is TLAPM `4600b24` and TLC `5dbdb42` (v1.8.0). Repository locks record the exact tool artifacts and proof-library sources in [verification-toolchain.json](../../config/verification-toolchain.json) and [proof-library-sources.json](../../config/proof-library-sources.json).

From the repository root, install the pinned verification dependencies, then run:

```sh
bash scripts/install_deps.sh
cd experiments/mongodb-storage
./verify.sh
./verify.sh --with-tlc
```

`./verify.sh` checks all 30 proof modules and parses the executable regression models. `--with-tlc` additionally replays eleven small checks, including nineteen semantic controls and the duplicate-delete regression. Several controls intentionally reproduce an invariant violation or an executable-model error; the script checks their expected exit codes and diagnostics. A successful replay prints `Replay complete` and writes its run id to `spec/output/latest-replay.txt`. Proof caches, complete logs and generated traces stay in ignored local directories. Proof modules run sequentially with a 100-second limit each; each small TLC check also has a fixed time budget.

`StorageCoherenceAttempt.tla` is an unsuccessful candidate retained as a dependency of the coherence-induction negative control. Its attempted preservation theorem is excluded from the 30 proved modules and from the certificate's proof dependencies.

To reuse an existing installation, set `STORAGE_LIB_DIR` to the directory containing `tla2tools.jar`, `community/` and `tlapm/`. The optional overrides `STORAGE_TLAPM`, `STORAGE_TLAPM_STDLIB`, `STORAGE_COMMUNITY`, `STORAGE_TLAPM_LIBRARY` and `STORAGE_TLA2TOOLS_JAR` select individual locations. Use absolute paths for overrides.

The larger finite checks are separate:

```sh
python3 spec/check-identity-si.py StorageIdentityMC spec/IdentityCallerSmall.cfg small --seconds 180
python3 spec/check-identity-si.py StorageIdentityMC spec/IdentityCallerTwoKeys.cfg two-keys --seconds 300
python3 spec/check-identity-si.py StorageIdentityMC spec/IdentityCallerSimulation.cfg simulation --seconds 120 --simulate
```

Use a new tag on each run. The first two configurations bound histories to two operations, use two transaction ids and timestamps `0..2`, and respectively use one and two keys. The recorded exhaustive runs reached 120,730 and 1,394,800 distinct states. The simulation allows repeated writes with three transaction ids, two keys, timestamps `0..4`, depth 60 and seed 20260916; its 120-second budget is not an exhaustive search. A timeout is recorded as such and must not be read as a completed check.

## Source and provenance

Upstream model: [mongodb-labs/vldb25-dist-txns@74526c1](https://github.com/mongodb-labs/vldb25-dist-txns/tree/74526c1201109405172eb845413154f547a815ee). `Storage.tla`, `Util.tla`, and the reference inputs are unchanged. [reference/upstream.json](reference/upstream.json) and [spec/input-sha256.txt](spec/input-sha256.txt) preserve their identities; [spec/source-sha256.txt](spec/source-sha256.txt) also covers the shared proof and replay sources.

The reference README describes the separate distributed-transaction benchmark. This directory concerns the standalone Storage experiment. Upstream notices continue to apply; see the MongoDB entry in the repository [NOTICE](../../NOTICE) and the preserved [ClientCentric license](../../LICENSES/tla-ci-BSD-2-Clause.txt). The upstream files are not relicensed by this experiment.

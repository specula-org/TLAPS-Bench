# MongoDB Storage: intermediate proofs

**Work in progress. The full snapshot-isolation (SI) theorem is not proved.** This directory shares checked intermediate results for the standalone `Storage.tla` module, following [the discussion in #144](https://github.com/specula-org/tlaps-bench/pull/144#issuecomment-5666114086). It is an experimental snapshot, outside the benchmark dataset.

## Start here

- [StorageSICertificate.tla](StorageSICertificate.tla): the main result, combining the intermediate proofs.
- [StorageSafety.tla](StorageSafety.tla): interface properties covering concurrent writes, prepared transactions, read responses and transaction state changes.
- [SI_GAP.md](SI_GAP.md): the target theorem and what remains to be proved.
- [evidence/verification.json](evidence/verification.json): verification results; [proof-checks.txt](evidence/proof-checks.txt) gives the checker summary for each proved module.

## What is established

The 30 proof modules contain 1,507 obligations checked with SANY and fresh, strict TLAPM (`--strict --nofp --threads 1`). The strongest checked theorem is:

```tla
CallerHistoryEpochSpec => []TimestampSICertificate
```

The certificate records transaction identities, orders committed transactions, and identifies the snapshot each transaction reads. It also relates reads to logged writes and rules out conflicting writes between a transaction's snapshot and commit. We still need to use these facts to construct an execution that satisfies the SI definition.

This theorem starts from upstream `Init` and covers executions without `RollbackToStable`. It assumes `RC = "snapshot"`, `Timestamps \subseteq Nat` and `NoValue \notin MTxId`. It also requires `FreshPrepareCall`: each prepare timestamp must be newer than the existing log timestamps at that node. The reference [MultiShardTxn](reference/MultiShardTxn.tla) supplies such timestamps through `Storage!NextTs`.

The theorem places no fixed limits on the number of transactions or keys, or on timestamp values. The basic interface properties in `StorageSafety.tla` cover the full `Next`, including rollback.

The open target is:

```tla
(CallerHistoryEpochSpec /\ []SingleWritePerKey) => []FullSI
```

`SingleWritePerKey` requires each transaction to write a given key at most once. `FullSI` uses [IdentitySnapshotIsolation](IdentitySnapshotIsolation.tla), which keeps track of transaction identities and operation positions. We would welcome feedback on whether this definition captures the intended Storage guarantee. Its equivalence to the original `ClientCentric` definition has not been proved.

Two questions would help guide further work: should callers be required to satisfy `FreshPrepareCall`, and how should transactions whose commits are rolled back be treated in the SI history?

## Reproduce

The scripts require Bash, Python 3.12+, Java 21+, ripgrep (`rg`), and GNU `timeout` and `sha256sum`. On macOS, install GNU coreutils and expose its commands on `PATH`; the scripts also recognize `gtimeout`. We checked the proofs with TLAPM `4600b24` and used TLC `5dbdb42` (v1.8.0). The exact tool and library versions are recorded in [verification-toolchain.json](../../config/verification-toolchain.json) and [proof-library-sources.json](../../config/proof-library-sources.json).

From the repository root, install the pinned verification dependencies, then run:

```sh
bash scripts/install_deps.sh
cd experiments/mongodb-storage

# Choose one:
./verify.sh
./verify.sh --with-tlc
```

`./verify.sh` checks all 30 proof modules and parses the regression models. Adding `--with-tlc` also runs eleven small checks, including nineteen tests of the SI definition. Some checks intentionally reproduce a known invariant violation or model error; the script verifies the expected result in each case.

A successful run prints `Replay complete` and saves its run id in `spec/output/latest-replay.txt`. Logs, caches and traces stay in ignored local directories. Proof modules run one at a time, with a 100-second limit each; the TLC checks also have time limits.

`StorageCoherenceAttempt.tla` contains an unfinished proof attempt used by one negative test. It is excluded from the 30 proved modules, and the main result does not depend on it.

To reuse an existing installation, set `STORAGE_LIB_DIR` to the directory containing `tla2tools.jar`, `community/` and `tlapm/`. Individual tool paths can also be set through the variables in [spec/env.sh](spec/env.sh). Use absolute paths for these settings.

The larger finite checks are separate:

```sh
python3 spec/check-identity-si.py StorageIdentityMC spec/IdentityCallerSmall.cfg small --seconds 180
python3 spec/check-identity-si.py StorageIdentityMC spec/IdentityCallerTwoKeys.cfg two-keys --seconds 300
python3 spec/check-identity-si.py StorageIdentityMC spec/IdentityCallerSimulation.cfg simulation --seconds 120 --simulate
```

Use a new tag, such as `small`, on each run. The first two configurations use two transaction ids, histories of at most two operations and timestamps `0..2`, with one and two keys respectively. The completed searches explored 120,730 and 1,394,800 distinct states.

The simulation allows repeated writes and uses three transaction ids, two keys, timestamps `0..4`, depth 60 and seed 20260916. It runs for up to 120 seconds and records a timeout if that budget is reached. These checks cover only the specified configurations; the simulation is not exhaustive.

## Source and provenance

Upstream model: [mongodb-labs/vldb25-dist-txns@74526c1](https://github.com/mongodb-labs/vldb25-dist-txns/tree/74526c1201109405172eb845413154f547a815ee). `Storage.tla`, `Util.tla`, and the reference inputs are unchanged. [reference/upstream.json](reference/upstream.json) and [spec/input-sha256.txt](spec/input-sha256.txt) preserve their identities; [spec/source-sha256.txt](spec/source-sha256.txt) also covers the shared proof and replay sources.

The reference README describes the separate distributed-transaction benchmark. This directory concerns the standalone Storage experiment. Upstream notices continue to apply; see the MongoDB entry in the repository [NOTICE](../../NOTICE) and the preserved [ClientCentric license](../../LICENSES/tla-ci-BSD-2-Clause.txt). The upstream files are not relicensed by this experiment.

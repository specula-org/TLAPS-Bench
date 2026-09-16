#!/usr/bin/env bash
# Fresh strict replay of every locally proved dependency, followed optionally
# by bounded TLC checks and preserved negative controls. No source mutation.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=spec/env.sh
source spec/env.sh
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--with-tlc" ) ]]; then
  printf 'Usage: %s [--with-tlc]\n' "$0" >&2
  exit 2
fi
export TMPDIR="$PWD/tmp"
mkdir -p "$TMPDIR" spec/output
run_id="replay-$(date -u +%Y%m%dT%H%M%SZ)-$$"
sha256sum --check spec/source-sha256.txt > "spec/output/$run_id-inputs.log"
modules=(StorageContracts StorageReadContracts StoragePreparedContracts StorageAdmissionContracts StorageLifecycle StorageSafety StorageHistoryProjection StorageSeqLemmas StorageArithmetic StorageEpoch StorageLogAlgebra StorageProvenance StorageTimestamps StorageReadAlgebra StorageCommitProvenance StorageCoherence StorageVersionOrder StorageHistoryAlgebra StorageHistoryFidelity StorageCommitIdentity StorageCaller StorageReadStability StorageReadHistoryAlgebra StorageCallerHistory StorageHistoricalReads StorageOrderWitness StorageNoConf StorageLocalHistory StorageEpochSafety StorageSICertificate)
for module in "${modules[@]}"; do
  tag="$run_id-$module"
  if spec/check-proof.sh "$module.tla" "$tag" > "spec/output/$tag.console" 2>&1; then
    printf 'PASS %s\n' "$module"
  else
    cat "spec/output/$tag.console"
    exit 1
  fi
done
# New counterexample/audit modules are executable models, not additional proofs.
for model in IdentitySnapshotIsolation IdentitySIControls StorageIdentityMC StorageCallerCollapseSI StorageCallerCollapseAudit; do
  bash spec/check-sany.sh "$model.tla" "$run_id-$model"
done
if [[ "${1:-}" == "--with-tlc" ]]; then
  spec/run-tlc.sh spec/EpochContracts.cfg "$run_id-epoch-contracts" > "spec/output/$run_id-epoch-contracts.console" 2>&1
  spec/run-history.sh "$run_id-epoch-si" spec/HistoryEpochSmall.cfg > "spec/output/$run_id-epoch-si.console" 2>&1
  # Expected counterexamples: require both the TLC exit code and named failure.
  set +e
  spec/run-tlc.sh spec/CommitAppendOrder.cfg "$run_id-commit-order" > "spec/output/$run_id-commit-order.console" 2>&1
  order_rc=$?
  spec/run-rollback-si.sh "$run_id-rollback-si" > "spec/output/$run_id-rollback-si.console" 2>&1
  rollback_rc=$?
  bash spec/run-epoch-si.sh "$run_id-epoch-si-negative" > "spec/output/$run_id-epoch-si-negative.console" 2>&1
  epoch_negative_rc=$?
  spec/run-tlc.sh spec/FullNextContracts.cfg "$run_id-full-next" > "spec/output/$run_id-full-next.console" 2>&1
  full_rc=$?
  spec/run-coherence-induction.sh "$run_id-coherence-induction" > "spec/output/$run_id-coherence-induction.console" 2>&1
  coherence_rc=$?
  set -e
  [[ "$order_rc" -eq 12 && "$rollback_rc" -eq 12 && "$epoch_negative_rc" -eq 12 && "$full_rc" -eq 75 && "$coherence_rc" -eq 12 ]]
  rg -q 'Invariant CommitAppendOrder is violated' "spec/output/$run_id-commit-order.log"
  rg -q 'Invariant FullSI is violated' "spec/output/$run_id-rollback-si.log"
  rg -q 'Invariant FullSI is violated' "spec/output/$run_id-epoch-si-negative.log"
  rg -q 'Invariant ExternalCoherence is violated' "spec/output/$run_id-coherence-induction.log"
  rg -q 'no element of S satisfied P' "spec/output/$run_id-full-next.log"
  set +e
  bash spec/run-caller-collapse-si.sh "$run_id-caller-collapse-si" > "spec/output/$run_id-caller-collapse-si.console" 2>&1
  collapse_rc=$?
  set -e
  [[ "$collapse_rc" -eq 0 ]]
  rg -q 'Model checking completed. No error has been found.' "spec/output/$run_id-caller-collapse-si.log"
  rg -q '21 states generated, 21 distinct states found' "spec/output/$run_id-caller-collapse-si.log"
  bash spec/run-caller-collapse-audit.sh "$run_id-caller-collapse-audit" > "spec/output/$run_id-caller-collapse-audit.console" 2>&1
  rg -q 'Model checking completed. No error has been found.' "spec/output/$run_id-caller-collapse-audit.log"
  rg -q '21 states generated, 21 distinct states found' "spec/output/$run_id-caller-collapse-audit.log"
  python3 spec/check-identity-si.py IdentitySIControls spec/IdentitySIControls.cfg "$run_id-identity-controls"
  set +e
  python3 spec/check-identity-si.py StorageCallerCollapseSI spec/CallerCollapseLegacy.cfg "$run_id-legacy-collapse"
  legacy_rc=$?
  set -e
  [[ "$legacy_rc" -eq 12 ]]
  rg -q 'Invariant LegacyFullSI is violated' "spec/output/$run_id-legacy-collapse.log"
  printf 'PASS eleven bounded checks, including identity repair and nineteen semantic controls\n'
fi
sha256sum --check spec/source-sha256.txt >> "spec/output/$run_id-inputs.log"
printf '%s\n' "$run_id" > spec/output/latest-replay.txt
printf 'Replay complete: %s\n' "$run_id"

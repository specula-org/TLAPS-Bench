"""Replay existing reference proofs without model calls, including check recovery."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from common.proof_from_scratch_module import parse_module_task_regions
from common.proof_libraries import CATALOG_FILENAME, scan_official_libraries
from common.verification_budget import POLICY_ENV, TOOLCHAIN_ENV, VerificationPolicy
from common.verification_toolchain import verification_toolchain_identity
from evaluator.modes.proof_from_scratch import ProofFromScratch
from evaluator.proof_module_result import MODULE_RESULT_PREFIX, validate_module_result
from tlacore.model import Module
from tlacore.sany.dump import SanyStatus, run_normalized

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not hasattr(os, "sched_getaffinity"), reason="native PFS containment requires Linux")
@pytest.mark.parametrize("name", ["AddTwo", "FindHighest"])
@pytest.mark.parametrize("cpus", [1, 8])
@pytest.mark.parametrize("relative_session", [False, True])
def test_existing_reference_proofs_and_examination_recovery(tmp_path, name, cpus, relative_session):
    executable = next(
        (path for path in (Path("/opt/tlapm/bin/tlapm"), Path.home() / ".tlapm/bin/tlapm") if path.is_file()), None
    )
    if executable is None or not (REPO / "lib/tla2tools.jar").is_file():
        pytest.skip("requires the pinned verification toolchain (make setup)")
    tools = verification_toolchain_identity(executable, REPO / "lib/tla2tools.jar")
    mode = ProofFromScratch(str(REPO / "benchmark"), "/checker")
    task = REPO / "benchmark/proof-from-scratch-module/tlaplus_examples_LearnProofs" / f"{name}.tla"
    ids = mode.module_task_spec(str(task)).proof_unit_ids
    canonical, workspace = tmp_path / "canonical", tmp_path / "workspace"
    canonical.mkdir()
    workspace.mkdir()
    for path in (str(task), *mode.get_dependencies(str(task))):
        for destination in (canonical, workspace):
            shutil.copyfile(path, destination / Path(path).name)
    (canonical / CATALOG_FILENAME).write_bytes(scan_official_libraries().to_bytes())

    source = REPO / "source/tlaplus_examples_LearnProofs" / f"{name}.tla"
    parsed = run_normalized(str(source))
    assert parsed.status is SanyStatus.VALID, parsed.detail
    regions = parse_module_task_regions(task.read_text(), ids)
    theorems = Module.parse(parsed.raw).theorems
    assert len(theorems) == len(regions.proofs)
    lines = source.read_text().splitlines(keepends=True)
    proofs = {}
    for unit, theorem in zip(regions.proofs, theorems, strict=True):
        location = theorem.proof_loc
        assert location is not None
        fragment = lines[location.line_start - 1 : location.line_end]
        fragment[-1] = fragment[-1][: location.column_end]
        fragment[0] = fragment[0][location.column_start - 1 :]
        proofs[unit.task_id] = "".join(fragment)
    (workspace / task.name).write_text(regions.render(proofs=proofs))

    policy = VerificationPolicy.create(60, ids, cpus)
    env = {
        **os.environ,
        POLICY_ENV: json.dumps(policy.as_dict()),
        TOOLCHAIN_ENV: tools["digest"],
        "PYTHONPATH": str(REPO / "src"),
        "TLAPS_LIB": str(REPO / "lib/tlapm"),
        "COMMUNITY_LIB": str(REPO / "lib/community"),
        "SANY_RUN_SH": str(REPO / "src/dataset/sany-dump/run.sh"),
    }
    session = Path("state/examination") if relative_session else tmp_path / "examination"
    command = [
        sys.executable,
        str(REPO / "src/common/check_proof.py"),
        str(workspace / task.name),
        "--mode",
        "proof-from-scratch",
        "--no-container",
        "--no-git-track",
        "--no-cache",
        "--tlapm",
        str(executable),
        "--benchmark-dir",
        str(canonical),
        "--timeout",
        str(policy.effective_timeout_secs),
        "--check-session",
        str(session),
    ]
    reports = []
    for _ in range(2):
        result = subprocess.run(
            command, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=policy.effective_timeout_secs + 30
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = next(
            json.loads(line[len(MODULE_RESULT_PREFIX) :])
            for line in result.stdout.splitlines()
            if line.startswith(MODULE_RESULT_PREFIX)
        )
        validate_module_result(report, ids)
        assert report["complete"] and report["trusted_proof_unit_ids"] == list(ids)
        assert report["verification"]["policy"] == policy.as_dict()
        reports.append(report)
    assert reports[1]["units"] == reports[0]["units"]
    assert reports[1]["verification"]["wall_secs"] >= reports[0]["verification"]["wall_secs"]
    assert reports[1]["verification"]["cpu_secs"] >= reports[0]["verification"]["cpu_secs"]

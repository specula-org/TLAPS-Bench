"""End-to-end soundness checks for module-level proof-from-scratch tasks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from common.proof_from_scratch_module import begin_agent_proof, end_agent_proof
from common.proof_libraries import CATALOG_FILENAME, scan_official_libraries
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "src" / "common" / "check_proof.py"
SANY_RUN_SH = REPO / "src" / "dataset" / "sany-dump" / "run.sh"
UNIT_ID = "Suite/Task_B.tla"


def _tlapm() -> str:
    configured = os.environ.get("TLAPM")
    candidates = [Path(configured)] if configured else []
    candidates.extend((Path("/opt/tlapm/bin/tlapm"), Path.home() / ".tlapm" / "bin" / "tlapm"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    pytest.skip("tlapm is not installed")


def _task(proof: str) -> str:
    return "\n".join(
        (
            "---- MODULE Task ----",
            BEGIN_AGENT_HELPERS,
            END_AGENT_HELPERS,
            "",
            "THEOREM B == FALSE",
            begin_agent_proof(UNIT_ID),
            proof,
            end_agent_proof(UNIT_ID),
            "====",
            "",
        )
    )


def _run_checker(tmp_path: Path, submitted: str) -> subprocess.CompletedProcess[str]:
    canonical = tmp_path / "canonical"
    workspace = tmp_path / "workspace"
    canonical.mkdir(parents=True)
    workspace.mkdir()
    (canonical / "Task.tla").write_text(_task("PROOF OMITTED"))
    (canonical / CATALOG_FILENAME).write_bytes(scan_official_libraries().to_bytes())
    (workspace / "Task.tla").write_text(submitted)

    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src"),
        "SANY_RUN_SH": str(SANY_RUN_SH),
        "TLAPS_LIB": str(REPO / "lib" / "tlapm"),
        "COMMUNITY_LIB": str(REPO / "lib" / "community"),
    }
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            str(workspace / "Task.tla"),
            "--mode",
            "proof-from-scratch",
            "--no-container",
            "--no-git-track",
            "--no-cache",
            "--canonical-replay-required",
            "--benchmark-dir",
            str(canonical),
            "--tlapm",
            _tlapm(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def test_nested_proof_omitted_cannot_admit_a_false_target(tmp_path):
    result = _run_checker(
        tmp_path,
        _task("PROOF\n<1>1. FALSE\n  PROOF OMITTED\n<1> QED BY <1>1"),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "PROOF_OMITTED_ADDED" in result.stdout
    assert '"trusted_proof_unit_ids":[]' in result.stdout
    assert "PASS — 1/1" not in result.stdout

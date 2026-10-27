"""End-to-end marked proof-completion boundary acceptance."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from common.proof_completion_contract import BEGIN_AGENT_PROOF, END_AGENT_PROOF

REPO = Path(__file__).resolve().parents[2]
CHECKER = Path(os.environ.get("TLAPS_CHECKER", REPO / "src" / "common" / "check_proof.py"))
SANY_RUN_SH = REPO / "src" / "dataset" / "sany-dump" / "run.sh"


def _tlapm() -> str:
    for candidate in (Path("/opt/tlapm/bin/tlapm"), Path.home() / ".tlapm" / "bin" / "tlapm"):
        if candidate.is_file():
            return str(candidate)
    pytest.skip("tlapm is not installed")


def _task(
    *,
    definition: str = "Unrelated == TRUE",
    statement: str = "THEOREM Target == TRUE",
    proof: str = "PROOF OBVIOUS",
) -> str:
    return "\n".join(
        (
            "---- MODULE Task ----",
            "EXTENDS Scaffold",
            definition,
            statement,
            BEGIN_AGENT_PROOF,
            proof,
            END_AGENT_PROOF,
            "====",
            "",
        )
    )


def _run_checker(
    tmp_path: Path,
    submitted: str,
    *,
    missing_workspace_context: frozenset[str] = frozenset(),
    statement: str = "THEOREM Target == TRUE",
) -> subprocess.CompletedProcess[str]:
    canonical = tmp_path / "canonical"
    workspace = tmp_path / "workspace"
    canonical.mkdir(parents=True)
    workspace.mkdir()
    context = {
        "Model.tla": "---- MODULE Model ----\n====\n",
        "Scaffold.tla": "---- MODULE Scaffold ----\nEXTENDS Model\nTHEOREM Given == TRUE\nPROOF OMITTED\n====\n",
    }
    (canonical / "Task.tla").write_text(_task(statement=statement))
    (workspace / "Task.tla").write_text(submitted)
    for name, source in context.items():
        (canonical / name).write_text(source)
        if name not in missing_workspace_context:
            (workspace / name).write_text(source)

    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src"),
        "SANY_RUN_SH": str(SANY_RUN_SH),
    }
    env.pop("TLAPS_CANONICAL_REPLAY_REQUIRED", None)
    checker_command = [sys.executable, str(CHECKER)] if CHECKER.suffix == ".py" else [str(CHECKER)]
    return subprocess.run(
        [
            *checker_command,
            str(workspace / "Task.tla"),
            "--mode",
            "proof-completion",
            "--no-container",
            "--no-git-track",
            "--no-cache",
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


def test_real_checker_accepts_target_proof_and_rejects_boundary_violations(tmp_path):
    valid = _run_checker(tmp_path / "valid", _task(proof="PROOF BY Given"))

    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert "PASS — target goal genuinely proved" in valid.stdout

    declaration = _run_checker(
        tmp_path / "declaration",
        _task(proof="PROOF BY Given\nLate == TRUE"),
    )

    assert declaration.returncode == 1, declaration.stdout + declaration.stderr
    assert "module-level operator declarations are not allowed in the proof region" in declaration.stdout
    assert "CHEAT-DETECTED: editable_regions_valid" in declaration.stdout

    scaffold = _run_checker(
        tmp_path / "scaffold",
        _task(definition="Unrelated == FALSE", proof="PROOF BY Given"),
    )

    assert scaffold.returncode == 1, scaffold.stdout + scaffold.stderr
    assert "fixed task scaffold outside editable regions was modified" in scaffold.stdout

    missing_context = _run_checker(
        tmp_path / "missing-context",
        _task(proof="PROOF BY Given"),
        missing_workspace_context=frozenset({"Model.tla"}),
    )

    assert missing_context.returncode == 1, missing_context.stdout + missing_context.stderr
    assert "Dependency file Model.tla was removed or renamed" in missing_context.stdout


def test_real_checker_preserves_an_unnamed_target_statement(tmp_path):
    valid = _run_checker(
        tmp_path / "valid",
        _task(statement="THEOREM TRUE", proof="PROOF BY Given"),
        statement="THEOREM TRUE",
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert "PASS — target goal genuinely proved" in valid.stdout

    changed = _run_checker(
        tmp_path / "changed",
        _task(statement="THEOREM FALSE", proof="PROOF BY Given"),
        statement="THEOREM TRUE",
    )
    assert changed.returncode == 1, changed.stdout + changed.stderr
    assert "fixed task scaffold outside editable regions was modified" in changed.stdout

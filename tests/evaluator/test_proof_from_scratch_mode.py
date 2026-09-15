"""Manifest-driven proof-from-scratch evaluator mode."""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import pytest

from common.proof_from_scratch_manifest import ModuleTaskManifestError
from common.proof_from_scratch_module import (
    MODULE_TASK_FORMAT_VERSION,
    begin_agent_proof,
    end_agent_proof,
    statement_sha256,
)
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS
from evaluator.modes.proof_completion import ProofCompletion
from evaluator.modes.proof_from_scratch import ProofFromScratch

ALPHA_TASK_ID = "Alpha/Alpha.tla"
ALPHA_UNIT_A = "Alpha/Alpha_First.tla"
ALPHA_UNIT_B = "Alpha/Alpha_Second.tla"
ALPHA_STATEMENT_A = "THEOREM First == TRUE"
ALPHA_STATEMENT_B = "THEOREM Second == TRUE"
BETA_TASK_ID = "Beta/Beta.tla"
BETA_UNIT = "Beta/Beta_Target.tla"
BETA_STATEMENT = "THEOREM Target == TRUE"
CONTEXT_B = "Context/ModelB.tla"
CONTEXT_A = "Context/ModelA.tla"


def _write_module(suite: Path, relative_path: str, body: str = "") -> Path:
    path = suite / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---- MODULE {path.stem} ----\n{body}====\n", encoding="utf-8")
    return path.resolve()


def _write_task(
    suite: Path,
    relative_path: str,
    proof_units: tuple[tuple[str, str], ...],
    *,
    extends: tuple[str, ...] = (),
) -> Path:
    path = suite / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"---- MODULE {path.stem} ----"]
    if extends:
        lines.append(f"EXTENDS {', '.join(extends)}")
    lines.extend(("", BEGIN_AGENT_HELPERS, END_AGENT_HELPERS, ""))
    for index, (unit_id, statement) in enumerate(proof_units):
        if index:
            lines.append("")
        lines.extend(
            (
                statement,
                begin_agent_proof(unit_id),
                "PROOF OMITTED",
                end_agent_proof(unit_id),
            )
        )
    lines.extend(("====", ""))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path.resolve()


def _module_task_entry(
    task_id: str,
    task_path: Path,
    proof_units: tuple[tuple[str, str], ...],
    context: tuple[str, ...],
) -> dict:
    return {
        "spec": {
            "format_version": MODULE_TASK_FORMAT_VERSION,
            "task_id": task_id,
            "source_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
            "proof_units": [
                {"task_id": unit_id, "statement_sha256": statement_sha256(statement)}
                for unit_id, statement in proof_units
            ],
        },
        "context": list(context),
        "renamed_bindings": {},
    }


def _write_corpus_manifest(root: Path) -> bytes:
    corpus_root = root / "proof-from-scratch"
    corpus_root.mkdir(parents=True, exist_ok=True)
    corpus = {
        ALPHA_UNIT_A: {"spec_id": ALPHA_TASK_ID, "context": list((CONTEXT_B, CONTEXT_A))},
        ALPHA_UNIT_B: {"spec_id": ALPHA_TASK_ID, "context": list((CONTEXT_B, CONTEXT_A))},
        BETA_UNIT: {"spec_id": BETA_TASK_ID, "context": []},
    }
    corpus_bytes = (json.dumps(corpus, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (corpus_root / "manifest.json").write_bytes(corpus_bytes)
    return corpus_bytes


def _write_module_manifest(suite: Path, entries: list[dict], corpus_bytes: bytes) -> None:
    document = {
        "format_version": MODULE_TASK_FORMAT_VERSION,
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "complete": True,
        "module_tasks": entries,
    }
    (suite / "manifest.json").write_text(json.dumps(document), encoding="utf-8")


def _fixture(tmp_path: Path) -> dict[str, Path]:
    benchmark_root = tmp_path / "benchmark"
    suite = benchmark_root / "proof-from-scratch-module"
    corpus_bytes = _write_corpus_manifest(benchmark_root)

    alpha = _write_task(
        suite,
        ALPHA_TASK_ID,
        ((ALPHA_UNIT_A, ALPHA_STATEMENT_A), (ALPHA_UNIT_B, ALPHA_STATEMENT_B)),
        extends=("ModelB", "ModelA"),
    )
    beta = _write_task(suite, BETA_TASK_ID, ((BETA_UNIT, BETA_STATEMENT),))
    context_b = _write_module(suite, CONTEXT_B, "ModelB == TRUE\n")
    context_a = _write_module(suite, CONTEXT_A, "ModelA == TRUE\n")
    undeclared = _write_module(suite, "Alpha/Undeclared.tla", "THEOREM Leaked == TRUE\n")
    _write_module(suite, "Context/Unrelated.tla", "Unrelated == TRUE\n")

    source_root = tmp_path / "source"
    for task_id, task_path in ((ALPHA_TASK_ID, alpha), (BETA_TASK_ID, beta)):
        source_path = source_root / task_id
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(task_path.read_bytes())

    _write_module_manifest(
        suite,
        [
            _module_task_entry(
                ALPHA_TASK_ID,
                alpha,
                ((ALPHA_UNIT_A, ALPHA_STATEMENT_A), (ALPHA_UNIT_B, ALPHA_STATEMENT_B)),
                (CONTEXT_B, CONTEXT_A),
            ),
            _module_task_entry(BETA_TASK_ID, beta, ((BETA_UNIT, BETA_STATEMENT),), ()),
        ],
        corpus_bytes,
    )
    return {
        "suite": suite,
        "alpha": alpha,
        "beta": beta,
        "context_b": context_b,
        "context_a": context_a,
        "undeclared": undeclared,
    }


def _mode(tmp_path: Path) -> ProofFromScratch:
    return ProofFromScratch(str(tmp_path / "benchmark"), "/checker")


def test_both_modes_keep_dependencies_read_only(tmp_path):
    (tmp_path / "proof-completion").mkdir()

    assert ProofFromScratch.read_only_dependencies is True
    assert ProofCompletion(str(tmp_path), "/checker").read_only_dependencies is True


def test_discovers_only_sorted_manifest_module_tasks(tmp_path):
    fixture = _fixture(tmp_path)
    mode = _mode(tmp_path)

    assert mode.get_benchmark_files() == [str(fixture["alpha"]), str(fixture["beta"])]
    assert mode.is_benchmark_file(str(fixture["alpha"]))
    assert not mode.is_benchmark_file(str(fixture["undeclared"]))
    assert not mode.is_benchmark_file(str(fixture["context_a"]))


def test_filters_manifest_module_tasks_without_changing_manifest_order(tmp_path):
    fixture = _fixture(tmp_path)
    mode = _mode(tmp_path)

    assert mode.get_benchmark_files("Beta/, Alpha/") == [str(fixture["alpha"]), str(fixture["beta"])]
    assert mode.get_benchmark_files("Alpha/") == [str(fixture["alpha"])]
    assert mode.get_benchmark_files("missing,") == []


def test_returns_only_manifest_context_in_declared_order(tmp_path):
    fixture = _fixture(tmp_path)

    assert _mode(tmp_path).get_dependencies(str(fixture["alpha"])) == [
        str(fixture["context_b"]),
        str(fixture["context_a"]),
    ]


def test_rejects_dependency_lookup_for_undeclared_file(tmp_path):
    fixture = _fixture(tmp_path)

    with pytest.raises(ValueError, match="is not declared"):
        _mode(tmp_path).get_dependencies(str(fixture["undeclared"]))


def test_missing_manifest_fails_closed_during_discovery(tmp_path):
    benchmark_root = tmp_path / "benchmark"
    _write_corpus_manifest(benchmark_root)
    (benchmark_root / "proof-from-scratch-module").mkdir()

    with pytest.raises(ModuleTaskManifestError, match="cannot read module-task manifest"):
        _mode(tmp_path).get_benchmark_files()


def test_invalid_manifest_fails_closed_during_discovery(tmp_path):
    benchmark_root = tmp_path / "benchmark"
    _write_corpus_manifest(benchmark_root)
    suite = benchmark_root / "proof-from-scratch-module"
    suite.mkdir()
    (suite / "manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ModuleTaskManifestError, match="must contain exactly"):
        _mode(tmp_path).get_benchmark_files()


def test_rejects_a_mismatched_sibling_corpus_manifest(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "benchmark" / "proof-from-scratch" / "manifest.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ModuleTaskManifestError, match="different proof-from-scratch corpus"):
        _mode(tmp_path).get_benchmark_files()


def test_rejects_a_mismatched_shipped_source(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "source" / ALPHA_TASK_ID).write_text("changed source\n", encoding="utf-8")

    with pytest.raises(ModuleTaskManifestError, match="source_sha256 does not match"):
        _mode(tmp_path).get_benchmark_files()


def test_exposes_module_spec_proof_units_and_identity(tmp_path):
    fixture = _fixture(tmp_path)
    mode = _mode(tmp_path)

    spec = mode.module_task_spec(str(fixture["alpha"]))

    assert spec.task_id == ALPHA_TASK_ID
    assert spec.source_sha256 == hashlib.sha256(fixture["alpha"].read_bytes()).hexdigest()
    assert spec.proof_unit_ids == (ALPHA_UNIT_A, ALPHA_UNIT_B)
    assert [unit.statement_sha256 for unit in spec.proof_units] == [
        statement_sha256(ALPHA_STATEMENT_A),
        statement_sha256(ALPHA_STATEMENT_B),
    ]
    assert mode.module_task_entry(str(fixture["alpha"])).spec == spec
    assert mode.specification_ids() == {ALPHA_TASK_ID: ALPHA_TASK_ID, BETA_TASK_ID: BETA_TASK_ID}


def test_mode_remains_pickleable_after_manifest_discovery(tmp_path):
    fixture = _fixture(tmp_path)
    mode = _mode(tmp_path)
    mode.get_benchmark_files()

    restored = pickle.loads(pickle.dumps(mode))

    assert restored.get_benchmark_files() == [str(fixture["alpha"]), str(fixture["beta"])]
    assert restored.get_dependencies(str(fixture["alpha"])) == [
        str(fixture["context_b"]),
        str(fixture["context_a"]),
    ]
    assert restored.module_task_spec(str(fixture["alpha"])) == mode.module_task_spec(str(fixture["alpha"]))

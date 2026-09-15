"""Proof-from-scratch corpus/library identity and resume guards."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evaluator import runner
from evaluator.modes.base import Mode


class _Mode(Mode):
    name = "proof-from-scratch"


def _backend(**changes):
    values = {
        "name": "codex",
        "approach": "agentic",
        "model": "gpt-test",
        "reasoning_effort": "high",
        "max_output_tokens": 4096,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_canonical_inputs_materialize_frozen_library_catalog(tmp_path):
    target = tmp_path / "Task.tla"
    target.write_text("---- MODULE Task ----\n====\n")
    inputs = runner.CanonicalInputs.capture(
        str(target),
        target.name,
        [],
        proof_library_catalog=b'{"digest":"frozen"}\n',
    )
    destination = tmp_path / "materialized"
    destination.mkdir()

    inputs.materialize(str(destination))

    assert (destination / runner.CATALOG_FILENAME).read_bytes() == b'{"digest":"frozen"}\n'


def test_corpus_digest_changes_with_library_catalog(tmp_path):
    suite = tmp_path / "proof-from-scratch"
    suite.mkdir()
    (suite / "manifest.json").write_text("{}\n")
    (suite / "Task.tla").write_text("---- MODULE Task ----\n====\n")
    mode = _Mode(str(tmp_path), "/bin/true")

    assert runner._corpus_digest(mode, "catalog-a") != runner._corpus_digest(mode, "catalog-b")


def test_resume_rejects_different_proof_library_identity(tmp_path):
    expected = {"schema_version": 2, "proof_library_digest": "new"}
    (tmp_path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps({"schema_version": 2, "proof_library_digest": "old"}))
    (tmp_path / "results.json").write_text("[]")

    with pytest.raises(ValueError, match="different benchmark, execution, official proof-library"):
        runner._validate_resume_run_manifest(str(tmp_path), expected)


def test_resume_ignores_provenance_revision_when_inputs_match(tmp_path):
    recorded = {
        "schema_version": 1,
        "benchmark_revision": "old-revision",
        "execution_source_digest": "same-sources",
        "corpus_digest": "same-corpus",
        "proof_library_digest": "same-libraries",
    }
    expected = {**recorded, "benchmark_revision": "new-revision-dirty"}
    (tmp_path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps(recorded))

    runner._validate_resume_run_manifest(str(tmp_path), expected)


def test_resume_rejects_changed_execution_sources(tmp_path):
    recorded = {
        "schema_version": 1,
        "benchmark_revision": "same-revision-dirty",
        "execution_source_digest": "old-sources",
        "corpus_digest": "same-corpus",
        "proof_library_digest": "same-libraries",
    }
    expected = {**recorded, "execution_source_digest": "new-sources"}
    (tmp_path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps(recorded))

    with pytest.raises(ValueError, match="different benchmark, execution, official proof-library"):
        runner._validate_resume_run_manifest(str(tmp_path), expected)


def test_resume_rejects_changed_agent_skill_snapshot(tmp_path):
    recorded = {
        "schema_version": 4,
        "benchmark_revision": "same-revision",
        "agent_skills_digest": "old-skills",
        "agent_skills": ["tlaps-proof-hints"],
    }
    expected = {**recorded, "agent_skills_digest": "new-skills"}
    (tmp_path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps(recorded))

    with pytest.raises(ValueError, match="different benchmark, execution"):
        runner._validate_resume_run_manifest(str(tmp_path), expected)


def test_resume_rejects_changed_verification_toolchain(tmp_path):
    recorded = {
        "schema_version": 2,
        "benchmark_revision": "same-revision",
        "verification_toolchain_digest": "old-toolchain",
    }
    expected = {**recorded, "verification_toolchain_digest": "new-toolchain"}
    (tmp_path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps(recorded))

    with pytest.raises(ValueError, match="verification-toolchain inputs"):
        runner._validate_resume_run_manifest(str(tmp_path), expected)


def test_resume_rejects_changed_agent_or_budget_policy(tmp_path):
    policy = runner._execution_policy_identity(
        _backend(),
        use_container=True,
        timeout=100,
        check_timeout=20,
        infra_retries=3,
        max_continuations=1,
        session_dir="/tmp/tlaps-sessions",
    )
    recorded = {"schema_version": 3, "execution_policy": policy}
    (tmp_path / runner.RUN_MANIFEST_RECORD).write_text(json.dumps(recorded))

    for changed in (
        {**policy, "model": "different-model"},
        {**policy, "reasoning_effort": "low"},
        {**policy, "timeout": 101},
        {**policy, "check_timeout": 21},
        {**policy, "infra_retries": 0},
        {**policy, "max_continuations": 2},
        {**policy, "environment": "local"},
        {**policy, "session": {**policy["session"], "persistence": False}},
        {**policy, "session": {**policy["session"], "root": "/tmp/other-sessions"}},
        {**policy, "session": {**policy["session"], "key_scheme": "different"}},
    ):
        with pytest.raises(ValueError, match="different benchmark, execution"):
            runner._validate_resume_run_manifest(
                str(tmp_path),
                {**recorded, "execution_policy": changed},
            )


def test_resume_rejects_legacy_results_without_run_manifest(tmp_path):
    (tmp_path / "results.json").write_text("[]")

    with pytest.raises(ValueError, match="without the recorded run-manifest.json"):
        runner._validate_resume_run_manifest(
            str(tmp_path),
            {"schema_version": 2, "proof_library_digest": "current"},
        )

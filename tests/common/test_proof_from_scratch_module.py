"""Shared module-level proof-from-scratch contract tests."""

from __future__ import annotations

import json

import pytest

from common.proof_from_scratch_module import (
    ModuleTaskContractError,
    begin_agent_proof,
    compute_trusted_units,
    end_agent_proof,
    load_module_task_spec,
    parse_module_task_regions,
    statement_sha256,
    validate_module_task_spec_data,
)
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS

UNIT_A = "Suite/Source_A.tla"
UNIT_B = "Suite/Source_B.tla"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _raw_spec() -> dict:
    return {
        "format_version": 1,
        "task_id": "Suite/Source.tla",
        "source_sha256": SHA_A,
        "proof_units": [
            {"task_id": UNIT_A, "statement_sha256": SHA_A},
            {"task_id": UNIT_B, "statement_sha256": SHA_B},
        ],
    }


def _task_source(*, statement_b: str = "THEOREM B == Value", extra_marker: str = "") -> str:
    return "\n".join(
        [
            "---- MODULE Source ----",
            "EXTENDS SourceDefs",
            "",
            BEGIN_AGENT_HELPERS,
            "Helper == TRUE",
            END_AGENT_HELPERS,
            "",
            "THEOREM A == TRUE",
            begin_agent_proof(UNIT_A),
            "PROOF OMITTED",
            end_agent_proof(UNIT_A),
            "",
            statement_b,
            begin_agent_proof(UNIT_B),
            "PROOF OMITTED",
            end_agent_proof(UNIT_B),
            extra_marker,
            "====",
            "",
        ]
    )


def test_validates_strict_module_task_spec():
    spec = validate_module_task_spec_data(_raw_spec())

    assert spec.task_id == "Suite/Source.tla"
    assert spec.proof_unit_ids == (UNIT_A, UNIT_B)
    assert spec.proof_units[1].statement_sha256 == SHA_B


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(extra=True), "must contain exactly"),
        (lambda raw: raw.update(format_version=2), "unsupported"),
        (lambda raw: raw.update(task_id="../Source.tla"), "canonical relative"),
        (lambda raw: raw.update(source_sha256="not-a-digest"), "SHA-256"),
        (
            lambda raw: raw["proof_units"].append(dict(raw["proof_units"][0])),
            "repeats proof unit",
        ),
    ],
)
def test_rejects_invalid_module_task_spec(mutate, message):
    raw = _raw_spec()
    mutate(raw)

    with pytest.raises(ModuleTaskContractError, match=message):
        validate_module_task_spec_data(raw)


def test_loader_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / "module-task.json"
    path.write_text(
        '{"format_version":1,"task_id":"Suite/Source.tla",'
        '"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"proof_units":[],"proof_units":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ModuleTaskContractError, match="duplicate JSON object key"):
        load_module_task_spec(path)


def test_statement_digest_uses_exact_canonical_text():
    assert statement_sha256("THEOREM A == TRUE\n") != statement_sha256("THEOREM A == TRUE")


def test_parses_one_helper_and_ordered_identified_proofs():
    regions = parse_module_task_regions(_task_source(), (UNIT_A, UNIT_B))

    assert regions.helpers == "Helper == TRUE\n"
    assert regions.proof_unit_ids == (UNIT_A, UNIT_B)
    assert [proof.text for proof in regions.proofs] == ["PROOF OMITTED\n", "PROOF OMITTED\n"]
    assert regions.helper_line_bounds == (5, 5)
    assert [proof.line_bounds for proof in regions.proofs] == [(10, 10), (15, 15)]
    assert regions.render() == _task_source()


def test_render_changes_only_editable_bodies():
    canonical = parse_module_task_regions(_task_source(), (UNIT_A, UNIT_B))
    submitted_source = canonical.render(
        helpers="Invariant == TRUE\n",
        proofs={UNIT_A: "PROOF OBVIOUS\n", UNIT_B: "PROOF BY A\n"},
    )
    submitted = parse_module_task_regions(submitted_source, (UNIT_A, UNIT_B))

    assert submitted.fixed_segments == canonical.fixed_segments
    assert submitted.helpers == "Invariant == TRUE\n"
    assert [proof.text for proof in submitted.proofs] == ["PROOF OBVIOUS\n", "PROOF BY A\n"]


def test_render_terminates_nonempty_bodies_and_preserves_empty_bodies():
    source = _task_source().replace("Helper == TRUE\n", "")
    canonical = parse_module_task_regions(source, (UNIT_A, UNIT_B))

    assert canonical.render() == source

    submitted_source = canonical.render(
        helpers="Invariant == TRUE",
        proofs={UNIT_A: "PROOF OBVIOUS", UNIT_B: ""},
    )
    submitted = parse_module_task_regions(submitted_source, (UNIT_A, UNIT_B))

    assert submitted.helpers == "Invariant == TRUE\n"
    assert [proof.text for proof in submitted.proofs] == ["PROOF OBVIOUS\n", ""]


def test_fixed_segments_detect_statement_tampering():
    canonical = parse_module_task_regions(_task_source(), (UNIT_A, UNIT_B))
    submitted = parse_module_task_regions(_task_source(statement_b="THEOREM B == TRUE"), (UNIT_A, UNIT_B))

    assert submitted.fixed_segments != canonical.fixed_segments


@pytest.mark.parametrize(
    ("source", "expected", "message"),
    [
        (_task_source().replace(begin_agent_proof(UNIT_B), ""), (UNIT_A, UNIT_B), "exactly one BEGIN"),
        (_task_source(), (UNIT_B, UNIT_A), "out of order"),
        (_task_source(extra_marker=r"\* BEGIN AGENT PROOF Suite/Unknown.tla"), (UNIT_A, UNIT_B), "unknown"),
        (_task_source(extra_marker=r"\* BEGIN AGENT PROOF"), (UNIT_A, UNIT_B), "unknown"),
    ],
)
def test_rejects_missing_reordered_or_unknown_proof_markers(source, expected, message):
    with pytest.raises(ModuleTaskContractError, match=message):
        parse_module_task_regions(source, expected)


def test_trust_is_raw_pass_and_dependency_closed():
    dependencies = {
        "A": (),
        "B": ("A",),
        "C": (),
    }

    assert compute_trusted_units({"A", "B", "C"}, dependencies) == frozenset({"A", "B", "C"})
    assert compute_trusted_units({"B", "C"}, dependencies) == frozenset({"C"})


def test_raw_pass_cycle_cannot_trust_itself():
    dependencies = {
        "A": ("B",),
        "B": ("A",),
        "C": (),
    }

    assert compute_trusted_units(set(dependencies), dependencies) == frozenset({"C"})


@pytest.mark.parametrize(
    ("raw_pass", "dependencies", "message"),
    [
        ({"unknown"}, {"A": ()}, "raw PASS contains unknown"),
        ({"A"}, {"A": ("unknown",)}, "dependencies contain unknown"),
        ({"A"}, {"A": ("A", "A")}, "repeat a unit ID"),
        ("A", {"A": ()}, "must be an iterable"),
        ({"A"}, {"A": "A"}, "must be an iterable"),
    ],
)
def test_trust_inputs_fail_closed(raw_pass, dependencies, message):
    with pytest.raises(ModuleTaskContractError, match=message):
        compute_trusted_units(raw_pass, dependencies)


def test_spec_round_trips_through_json(tmp_path):
    path = tmp_path / "module-task.json"
    path.write_text(json.dumps(_raw_spec()), encoding="utf-8")

    assert load_module_task_spec(path).proof_unit_ids == (UNIT_A, UNIT_B)

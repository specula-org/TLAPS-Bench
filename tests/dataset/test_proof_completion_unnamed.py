"""Unnamed targets must retain their statements, context, and reviewed keys."""

from io import StringIO

import pytest

from common.proof_completion_contract import parse_proof_completion_region
from dataset.proof_completion.generate import (
    _engine,
    _is_structured_proof,
    _plan_targets,
    emit_layered_source,
)


def _source(theorems):
    lines = ["---- MODULE Src ----\n", "EXTENDS TLAPS\n", "Goal == TRUE\n"]
    nodes = []
    for name, rhs, proof in theorems:
        start = len(lines) + 1
        label = f"{name} == " if name else ""
        lines.append(f"THEOREM {label}Goal\n")
        proof_start = len(lines) + 1
        lines.extend(line + "\n" for line in proof)
        nodes.append(
            {
                "name": name,
                "loc": {"line_start": start, "line_end": len(lines)},
                "proof_loc": {"line_start": proof_start, "line_end": len(lines), "column_start": 1} if proof else None,
                "shape": {"kind": "other", "rhs_primary_name": rhs},
                "references": ["Goal"],
            }
        )
    lines.append("====\n")
    return lines, {
        "module": "Src",
        "theorems": nodes,
        "operators": [{"name": "Goal", "loc": {"line_start": 3, "line_end": 3}, "references": []}],
        "instances": [],
        "constants": [],
        "variables": [],
        "assumes": [],
        "extends": ["TLAPS"],
        "spec_formulas": [],
    }


PROOF = ["<1>1. TRUE BY SMT", "<1> QED BY <1>1 DEF Goal"]


def _plan(theorems, reference=None):
    lines, dump = _source(theorems)
    return _plan_targets(_engine(), dump, lines, "Src", "Group", reference, StringIO())


@pytest.mark.parametrize("rhs,label", [("Goal", "Goal"), ("C!Goal", "C_Goal"), (None, "line4")])
def test_unnamed_filename_uses_semantic_name_or_line_fallback(rhs, label):
    [(target, module, key)] = _plan([(None, rhs, PROOF)])
    assert module == f"Src_{label}"
    assert key == f"Group/Src_{label}.tla"
    assert target["name"] is None


def test_unnamed_goal_does_not_steal_a_later_named_task_key():
    planned = _plan([(None, "Goal", PROOF), ("Goal", None, PROOF), ("Goal_1", None, PROOF)])
    assert [module for _, module, _ in planned] == ["Src_Goal_2", "Src_Goal", "Src_Goal_1"]


@pytest.mark.parametrize("name", [None, "Goal"])
def test_unnamed_task_cannot_overwrite_another_tasks_scaffold(name):
    planned = _plan([(name, "Goal", PROOF), (None, "GoalScaffold", PROOF)])
    assert [module for _, module, _ in planned] == ["Src_Goal", "Src_GoalScaffold_1"]


def test_unnamed_scaffold_cannot_overwrite_a_named_task():
    planned = _plan([(None, "Goal", PROOF), ("GoalScaffold", None, PROOF)])
    assert [module for _, module, _ in planned] == ["Src_Goal_1", "Src_GoalScaffold"]


def test_repeated_unnamed_goals_keep_distinct_keys_for_different_contexts():
    planned = _plan([(None, "Goal", PROOF), (None, "Goal", PROOF)])
    assert [module for _, module, _ in planned] == ["Src_Goal", "Src_Goal_1"]
    assert planned[0][0]["loc"]["line_start"] < planned[1][0]["loc"]["line_start"]


def test_reviewed_selection_does_not_renumber_a_later_unnamed_goal():
    [(target, module, key)] = _plan([(None, "Goal", PROOF), (None, "Goal", PROOF)], {"Group/Src_Goal_1.tla"})
    assert target["loc"]["line_start"] == 7
    assert module == "Src_Goal_1"
    assert key == "Group/Src_Goal_1.tla"


def test_reviewed_named_selection_does_not_expand_with_unnamed_candidates():
    planned = _plan([(None, "Goal", PROOF), ("Kept", None, PROOF)], {"Group/Src_Kept.tla"})
    assert [key for _, _, key in planned] == ["Group/Src_Kept.tla"]


@pytest.mark.parametrize("proof", [[], ["OBVIOUS"], ["PROOF OBVIOUS"], ["PROOF OMITTED"]])
def test_unnamed_goals_require_reference_proofs(proof):
    assert not _plan([(None, "Goal", proof)])


@pytest.mark.parametrize("proof,structured", [("PROOF OBVIOUS", False), ("OMITTED", False), ("BY SMT", True)])
def test_inline_proof_classification_starts_at_the_proof_column(proof, structured):
    prefix = "THEOREM TRUE "
    node = {"proof_loc": {"line_start": 1, "line_end": 1, "column_start": len(prefix) + 1}}
    assert _is_structured_proof(_engine(), node, [prefix + proof + "\n"]) is structured


def test_existing_named_task_without_reference_proof_is_retained():
    planned = _plan([("Kept", None, ["PROOF OMITTED"])], {"Group/Src_Kept.tla"})
    assert [key for _, _, key in planned] == ["Group/Src_Kept.tla"]


@pytest.mark.parametrize("inline_first_step", [False, True])
def test_emission_preserves_unnamed_statement_and_records_reference_steps(tmp_path, monkeypatch, inline_first_step):
    lines, dump = _source([(None, "Goal", PROOF)])
    if inline_first_step:
        prefix = lines[3].rstrip() + " "
        lines[3:5] = [prefix + lines[4]]
        dump["theorems"][0]["loc"]["line_end"] -= 1
        dump["theorems"][0]["proof_loc"] = {
            "line_start": 4,
            "line_end": 5,
            "column_start": len(prefix) + 1,
        }
    source = tmp_path / "source" / "Src.tla"
    source.parent.mkdir()
    source.write_text("".join(lines))
    output = tmp_path / "benchmark" / "Group"
    engine = _engine()
    monkeypatch.setattr(engine, "dump_sany", lambda _path: dump)
    manifest, state, audit = {}, {}, StringIO()

    assert (
        emit_layered_source(
            engine,
            str(source),
            "Group",
            str(output),
            audit,
            manifest,
            state,
            source_root=str(source.parent),
        )
        == 1
    )

    task = (output / "Src_Goal.tla").read_text()
    regions = parse_proof_completion_region(task)
    assert "THEOREM Goal\n" in regions.fixed_prefix
    assert "THEOREM Goal ==" not in task
    assert regions.proof.strip() == "PROOF OBVIOUS"
    assert manifest["Group/Src_Goal.tla"]["reference_proof_steps"] == 2
    scaffold = (output / "Src_GoalScaffold.tla").read_text()
    assert "Goal == TRUE" in scaffold
    assert "THEOREM" not in scaffold
    assert "<1>" not in scaffold
    assert "LEAK" not in audit.getvalue()

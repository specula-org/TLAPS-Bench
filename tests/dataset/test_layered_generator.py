"""proof-from-scratch layered emission — the generator side of the Issue #64 boundary.

The generator and the evaluator implement two halves of one contract: the
generator emits read-only context, an editable task carrying the four marker
lines, and a manifest naming each task's exact context; the evaluator
(``src/common/proof_from_scratch_contract.py``) parses exactly that. These tests
pin the generator-side invariants that contract depends on, without needing
SANY or tlapm.

Run: PYTHONPATH=src python3 -m pytest tests/dataset/test_layered_generator.py
"""

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

from dataset.proof_from_scratch import generate
from dataset.proof_from_scratch.generate import (
    BEGIN_AGENT_HELPERS,
    BEGIN_AGENT_PROOF,
    END_AGENT_HELPERS,
    END_AGENT_PROOF,
    _defined_names,
    _plan_layered_targets,
    _strip_module_directives,
    _unneeded_decl_edits,
    build_task_module,
    copy_deps_layered,
    dep_keep_names,
    incremental_precondition_error,
    instance_qualified_uses,
    layered_cross_dir_dedup,
    load_dataset_task_keys,
    positional_targets,
    prune_dep_module,
    referenced_identifiers,
    tasks_owned_by,
)


def test_task_module_has_markers_once_and_in_order():
    text = build_task_module("Foo_Thm", "Foo_ThmDefs", "THEOREM Spec => []Inv")
    for marker in (BEGIN_AGENT_HELPERS, END_AGENT_HELPERS, BEGIN_AGENT_PROOF, END_AGENT_PROOF):
        assert text.count(marker) == 1, f"{marker} must appear exactly once"
    order = [text.index(m) for m in (BEGIN_AGENT_HELPERS, END_AGENT_HELPERS, BEGIN_AGENT_PROOF, END_AGENT_PROOF)]
    assert order == sorted(order)
    # Markers must be their own lines: the evaluator matches whole lines.
    lines = text.splitlines()
    for marker in (BEGIN_AGENT_HELPERS, END_AGENT_HELPERS, BEGIN_AGENT_PROOF, END_AGENT_PROOF):
        assert marker in lines


def test_task_module_ships_an_empty_helper_region_and_placeholder_proof():
    text = build_task_module("Foo_Thm", "Foo_ThmDefs", "THEOREM Spec => []Inv")
    helpers = text.split(BEGIN_AGENT_HELPERS)[1].split(END_AGENT_HELPERS)[0]
    proof = text.split(BEGIN_AGENT_PROOF)[1].split(END_AGENT_PROOF)[0]
    assert helpers.strip() == ""
    assert proof.strip() == "PROOF OBVIOUS"


def test_task_module_does_not_preload_proof_libraries():
    text = build_task_module("Foo_Thm", "Foo_ThmDefs", "THEOREM TRUE")
    assert text.startswith("---- MODULE Foo_Thm ----\nEXTENDS Foo_ThmDefs\n")
    assert text.count("EXTENDS ") == 1
    assert "INSTANCE TLAPS" not in text
    assert "INSTANCE NaturalsInduction" not in text
    assert "INSTANCE FiniteSetTheorems" not in text
    assert "INSTANCE WellFoundedInduction" not in text
    # The theorem is fixed scaffold, never inside an editable region.
    assert text.index("THEOREM TRUE") > text.index(END_AGENT_HELPERS)
    assert text.index("THEOREM TRUE") < text.index(BEGIN_AGENT_PROOF)


def test_module_directives_are_stripped_from_read_only_layers():
    # `USE`/`HIDE` are prover hints from the original proof; leaving them in a
    # read-only layer would hand the agent part of the proof strategy.
    text = "Op == 1\nUSE DEF Op\n  HIDE DEF Op\nOther == 2\n"
    assert _strip_module_directives(text) == "Op == 1\nOther == 2\n"


def test_read_only_layers_drop_content_after_the_outer_module():
    text = "---- MODULE Fixture ----\nOp == 1\n====\nIInit == TypeOK /\\ IInv\n"

    assert _strip_module_directives(text) == "---- MODULE Fixture ----\nOp == 1\n====\n"


def test_read_only_layer_truncation_preserves_nested_modules():
    text = (
        "---- MODULE Outer ----\n"
        "---- MODULE Inner ----\n"
        "InnerOp == TRUE\n"
        "====\n"
        "OuterOp == Inner!InnerOp\n"
        "====\n"
        "trailing notes\n"
    )

    stripped = _strip_module_directives(text)

    assert "OuterOp" in stripped
    assert "trailing notes" not in stripped
    assert stripped.count("====") == 2


def test_read_only_layer_truncation_preserves_whitespace_only_suffixes():
    text = "---- MODULE Fixture ----\nOp == 1\n====\n\n"

    assert _strip_module_directives(text) == text


def test_quantifier_is_not_read_as_a_use_of_a_variable_named_a():
    """`\\A x \\in S` must not count as a use of a VARIABLE named `A`.

    Regression: BubbleSort declares `VARIABLES A, A0, ...` after a theorem that
    binds `\\A A, B, C`. Hoisting that declaration into a module the task
    EXTENDS makes it shadow the bound variable and SANY rejects the task, so an
    unused declaration must actually be dropped.
    """
    source = "Perms == { f \\in S : \\A p \\in 1..N : TRUE }\n\nVARIABLES A, A0\n"
    dump = {
        "operators": [{"name": "Perms", "loc": {"line_start": 1, "line_end": 1}}],
        "assumes": [],
        "constants": [],
        "variables": [
            {"name": "A", "loc": {"line_start": 3, "line_end": 3}},
            {"name": "A0", "loc": {"line_start": 3, "line_end": 3}},
        ],
    }
    edits = _unneeded_decl_edits(source.splitlines(keepends=True), dump, {"Perms"})
    assert edits == [(3, 3, "")], "VARIABLE A is unused and must be dropped"


def test_declaration_actually_referenced_is_kept():
    source = "Init == x = 0\n\nVARIABLE x\n"
    dump = {
        "operators": [{"name": "Init", "loc": {"line_start": 1, "line_end": 1}}],
        "assumes": [],
        "constants": [],
        "variables": [{"name": "x", "loc": {"line_start": 3, "line_end": 3}}],
    }
    assert _unneeded_decl_edits(source.splitlines(keepends=True), dump, {"Init"}) == []


def _write_task(root, subdir, name, body="THEOREM TRUE", defs_body="Inv == TRUE"):
    d = root / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.tla").write_text(build_task_module(name, f"{name}Defs", body))
    (d / f"{name}Defs.tla").write_text(f"---- MODULE {name}Defs ----\n{defs_body}\n====\n")
    return f"{subdir}/{name}.tla", {
        "spec_id": "Fixture.tla",
        "context": [f"{subdir}/{name}Defs.tla"],
        "reference_proof_steps": 0,
    }


def test_dataset_selection_bootstraps_from_flat_task_tree(tmp_path):
    task_key, _entry = _write_task(tmp_path, "Existing", "Existing_Thm")
    (tmp_path / "Existing" / "Model_with_underscore.tla").write_text(
        "---- MODULE Model_with_underscore ----\nValue == 1\n====\n"
    )

    assert load_dataset_task_keys(str(tmp_path)) == {task_key}


def test_layered_manifest_becomes_the_dataset_selection(tmp_path):
    _write_task(tmp_path, "Legacy", "Legacy_Thm")
    manifest_key = "Current/Current_Thm.tla"
    (tmp_path / "manifest.json").write_text(
        json.dumps({manifest_key: {"spec_id": "Fixture.tla", "context": [], "reference_proof_steps": 0}})
    )

    assert load_dataset_task_keys(str(tmp_path)) == {manifest_key}


def test_positional_repository_files_keep_their_dataset_group(tmp_path):
    source_root = tmp_path / "source"
    nested = source_root / "OpenAddressing" / "OpenAddressing.tla"
    nested.parent.mkdir(parents=True)
    nested.write_text("---- MODULE OpenAddressing ----\n====\n")

    targets, repository_sources = positional_targets([str(nested)], str(source_root))

    assert targets == [(str(nested), "OpenAddressing")]
    assert repository_sources


def test_external_positional_file_disables_repository_selection(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    external = tmp_path / "source-other" / "External.tla"
    external.parent.mkdir()
    external.write_text("---- MODULE External ----\n====\n")

    targets, repository_sources = positional_targets([str(external)], str(source_root))

    assert targets == [(str(external), None)]
    assert not repository_sources


def test_mixed_positional_files_are_distinguishable_before_generation(tmp_path):
    source_root = tmp_path / "source"
    repository_file = source_root / "Group" / "Repository.tla"
    repository_file.parent.mkdir(parents=True)
    repository_file.write_text("---- MODULE Repository ----\n====\n")
    external = tmp_path / "external" / "External.tla"
    external.parent.mkdir()
    external.write_text("---- MODULE External ----\n====\n")

    targets, repository_sources = positional_targets([str(repository_file), str(external)], str(source_root))

    assert targets == [(str(repository_file), "Group"), (str(external), None)]
    assert not repository_sources


def test_positional_symlink_to_repository_source_uses_canonical_identity(tmp_path):
    source_root = tmp_path / "source"
    source = source_root / "Group" / "Canonical.tla"
    source.parent.mkdir(parents=True)
    source.write_text("---- MODULE Canonical ----\n====\n")
    alias = tmp_path / "Alias.tla"
    alias.symlink_to(source)

    targets, repository_sources = positional_targets([str(alias)], str(source_root))

    assert targets == [(str(source), "Group")]
    assert repository_sources


def test_positional_repository_run_keeps_overlapping_sibling_source_task(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source = source_root / "TwoPhase" / "TwoPhase.tla"
    source.parent.mkdir(parents=True)
    source.write_text("---- MODULE TwoPhase ----\n====\n")
    sibling_source = source.parent / "TwoPhase_proof.tla"
    sibling_source.write_text("---- MODULE TwoPhase_proof ----\n====\n")

    output = tmp_path / "benchmark"
    task_key, task_entry = _write_task(output, "TwoPhase", "TwoPhase_Implementation")
    sibling_key, sibling_entry = _write_task(output, "TwoPhase", "TwoPhase_proof_line17")
    existing = {task_key: task_entry, sibling_key: sibling_entry}
    (output / "manifest.json").write_text(json.dumps(existing))

    def fake_process_file(
        _path,
        _audit_writer,
        _output_root,
        *,
        module_subdir,
        manifest,
        reference_task_keys,
        **_kwargs,
    ):
        assert module_subdir == "TwoPhase"
        assert reference_task_keys == set(existing)
        manifest[task_key] = task_entry
        return 1

    monkeypatch.setattr(generate, "SOURCE_ROOT", str(source_root))
    monkeypatch.setattr(generate, "BENCHMARK_DIR", str(output))
    monkeypatch.setattr(generate, "process_file", fake_process_file)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate.py",
            "--layered",
            "--skip-gates",
            "--output-dir",
            str(output),
            str(source),
        ],
    )

    generate.main()

    assert set(json.loads((output / "manifest.json").read_text())) == set(existing)


def test_custom_source_dir_is_used_for_specification_identity(tmp_path, monkeypatch):
    source_root = tmp_path / "custom-source"
    source = source_root / "Group" / "Spec.tla"
    source.parent.mkdir(parents=True)
    source.write_text("---- MODULE Spec ----\n====\n")
    output = tmp_path / "benchmark"
    observed_roots = []

    def fake_process_file(_path, _audit_writer, _output_root, **kwargs):
        observed_roots.append(kwargs["source_root"])
        return 0

    monkeypatch.setattr(generate, "process_file", fake_process_file)
    monkeypatch.setattr(generate, "_finalize_layered", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate.py",
            "--layered",
            "--skip-gates",
            "--source-dir",
            str(source_root),
            "--output-dir",
            str(output),
        ],
    )

    generate.main()

    assert observed_roots == [str(source_root)]


def test_unnamed_target_preserves_an_existing_line_based_key():
    target = {
        "name": None,
        "loc": {"line_start": 17},
        "shape": {"rhs_primary_name": "A!Spec"},
    }
    audit = StringIO()

    planned = _plan_layered_targets(
        [(target, True, False, False)],
        "TP",
        "TwoPhase_proof",
        {"TP/TwoPhase_proof_line17.tla"},
        audit,
        "source/TP/TwoPhase_proof.tla",
    )

    assert planned == [(target, "TwoPhase_proof_line17", "TP/TwoPhase_proof_line17.tla")]
    assert "preserving that key" in audit.getvalue()


def test_candidate_outside_dataset_selection_is_audited_and_skipped():
    target = {
        "name": "NewTarget",
        "loc": {"line_start": 10},
        "shape": {"rhs_primary_name": None},
    }
    audit = StringIO()

    planned = _plan_layered_targets(
        [(target, False, False, True)],
        "Example",
        "Spec",
        {"Example/Spec_ExistingTarget.tla"},
        audit,
        "source/Example/Spec.tla",
    )

    assert planned == []
    assert "outside the existing dataset selection" in audit.getvalue()


def test_cross_dir_dedup_keeps_the_preferred_copy_and_sweeps_its_context(tmp_path, capsys):
    manifest = {}
    for subdir in ("Consensus", "Data"):
        key, entry = _write_task(tmp_path, subdir, "Sets_Thm")
        manifest[key] = entry
    # A task that differs only in its context must NOT be deduped.
    key, entry = _write_task(tmp_path, "Other", "Sets_Thm", defs_body="Inv == FALSE")
    manifest[key] = entry

    class _Audit:
        def write(self, _):
            pass

    removed = layered_cross_dir_dedup(str(tmp_path), manifest, _Audit())

    assert removed == 1
    assert "Data/Sets_Thm.tla" in manifest, "the Data/ copy is preferred"
    assert "Consensus/Sets_Thm.tla" not in manifest
    assert "Other/Sets_Thm.tla" in manifest, "different context is a different task"
    assert not (tmp_path / "Consensus" / "Sets_Thm.tla").exists(), "the losing task file goes"

    # Dedup drops the task; the caller sweeps orphaned context once, against the
    # complete manifest, so a filtered run cannot delete what it never touched.
    generate.sweep_unreferenced_context(str(tmp_path), manifest, _Audit())
    assert not (tmp_path / "Consensus" / "Sets_ThmDefs.tla").exists()
    assert (tmp_path / "Data" / "Sets_ThmDefs.tla").exists()
    assert (tmp_path / "Other" / "Sets_ThmDefs.tla").exists()


def test_manifest_round_trips_as_json(tmp_path):
    manifest = {}
    key, entry = _write_task(tmp_path, "Peterson", "Peterson_MutualExclusion")
    manifest[key] = entry
    text = json.dumps(dict(sorted(manifest.items())), indent=2)
    assert json.loads(text) == manifest


@pytest.mark.parametrize(
    "artifact",
    [
        "THEOREM Shortcut == TRUE\nPROOF OMITTED",
        "LEMMA Shortcut == TRUE\nBY TRUE",
        "Inv == TRUE\nBY TRUE",
        "Inv == TRUE\n<1>1. TRUE",
    ],
)
def test_finalize_rejects_proof_artifacts_in_read_only_context(tmp_path, artifact):
    task_key, entry = _write_task(tmp_path, "Group", "Group_Thm", defs_body=artifact)
    audit = StringIO()

    with pytest.raises(RuntimeError, match="failed integrity validation"):
        generate._finalize_layered(
            str(tmp_path),
            {task_key: entry},
            {},
            audit,
            run_gates=False,
        )

    assert "read-only context contains proof artifact" in audit.getvalue()
    assert not (tmp_path / "manifest.json").exists()


def test_finalize_rejects_a_missing_outer_module_terminator(tmp_path):
    task_key, entry = _write_task(tmp_path, "Group", "Group_Thm")
    (tmp_path / entry["context"][0]).write_text("---- MODULE Group_ThmDefs ----\nInv == TRUE\n")
    audit = StringIO()

    with pytest.raises(RuntimeError, match="failed integrity validation"):
        generate._finalize_layered(
            str(tmp_path),
            {task_key: entry},
            {},
            audit,
            run_gates=False,
        )

    assert "no complete outer module terminator" in audit.getvalue()


def test_finalize_rejects_content_after_the_outer_module(tmp_path):
    task_key, entry = _write_task(tmp_path, "Group", "Group_Thm")
    context_path = tmp_path / entry["context"][0]
    context_path.write_text(context_path.read_text() + "trailing hint\n")
    audit = StringIO()

    with pytest.raises(RuntimeError, match="failed integrity validation"):
        generate._finalize_layered(
            str(tmp_path),
            {task_key: entry},
            {},
            audit,
            run_gates=False,
        )

    assert "content remains after the outer module terminator" in audit.getvalue()


def test_shipped_layered_output_passes_read_only_integrity():
    suite = Path(generate.BENCHMARK_DIR)
    manifest = json.loads((suite / "manifest.json").read_text())
    audit = StringIO()

    generate.validate_layered_output(str(suite), manifest, audit)

    assert audit.getvalue() == ""


def test_shipped_tasks_do_not_preload_proof_libraries():
    suite = Path(generate.BENCHMARK_DIR)
    manifest = json.loads((suite / "manifest.json").read_text())

    for task_key in manifest:
        text = (suite / task_key).read_text()
        fixed_prefix = text[: text.index(BEGIN_AGENT_HELPERS)]
        assert "INSTANCE TLAPS" not in fixed_prefix, task_key
        assert "INSTANCE NaturalsInduction" not in fixed_prefix, task_key
        assert "INSTANCE FiniteSetTheorems" not in fixed_prefix, task_key
        assert "INSTANCE WellFoundedInduction" not in fixed_prefix, task_key


def test_multi_line_declaration_statement_is_deleted_as_one_unit():
    """A `VARIABLE a,\\n b` statement must never be half-deleted.

    Regression: SANY reports a separate loc per declared name, so deleting only
    the unused name's line left a dangling `VARIABLE votes,` that SANY rejects
    (tlaplus_examples_Paxos/Voting.tla declares `votes` and `maxBal` this way).
    """
    source = "VARIABLE votes,   \\* comment\n         maxBal\nOp == 1\n"
    lines = source.splitlines(keepends=True)
    dump = {
        "operators": [{"name": "Op", "loc": {"line_start": 3, "line_end": 3}}],
        "assumes": [],
        "constants": [],
        "variables": [
            {"name": "votes", "loc": {"line_start": 1, "line_end": 1}},
            {"name": "maxBal", "loc": {"line_start": 2, "line_end": 2}},
        ],
    }
    # Neither name is used by the kept definition, so the whole statement goes.
    assert _unneeded_decl_edits(lines, dump, {"Op"}) == [(1, 2, "")]


def test_partially_used_declaration_statement_is_kept_whole():
    source = "VARIABLE votes,\n         maxBal\nOp == votes\n"
    lines = source.splitlines(keepends=True)
    dump = {
        "operators": [{"name": "Op", "loc": {"line_start": 3, "line_end": 3}}],
        "assumes": [],
        "constants": [],
        "variables": [
            {"name": "votes", "loc": {"line_start": 1, "line_end": 1}},
            {"name": "maxBal", "loc": {"line_start": 2, "line_end": 2}},
        ],
    }
    # `maxBal` is unused but shares the statement with the used `votes`.
    assert _unneeded_decl_edits(lines, dump, {"Op"}) == []


def test_surviving_instance_disables_declaration_pruning():
    """An INSTANCE substitutes declarations implicitly, so nothing may be pruned.

    Regression: LockHS declares `VARIABLE s` purely to satisfy
    `INSTANCE Stuttering`, which substitutes it by name without mentioning it.
    Pruning it produced "Substitution missing for symbol s" under SANY.
    """
    source = "VARIABLE s\nINSTANCE Stuttering\nOp == 1\n"
    lines = source.splitlines(keepends=True)
    dump = {
        "operators": [{"name": "Op", "loc": {"line_start": 3, "line_end": 3}}],
        "assumes": [],
        "constants": [],
        "variables": [{"name": "s", "loc": {"line_start": 1, "line_end": 1}}],
        # An unnamed INSTANCE is always kept, so pruning must be skipped.
        "instances": [{"name": None, "module": "Stuttering", "loc": {"line_start": 2, "line_end": 2}}],
    }
    assert _unneeded_decl_edits(lines, dump, {"Op"}) == []


def test_copied_dependency_keeps_no_theorem_to_cite(tmp_path, monkeypatch):
    """A context module must not ship a THEOREM the agent can cite.

    Regression: `copy_deps` rewrote a dependency's proofs to `PROOF OMITTED` and
    kept the statements. An OMITTED theorem is a usable fact, so
    `Voting_proof_AllSafeAtZero_T` — whose goal restates `AllSafeAtZero` — was
    discharged by `BY AllSafeAtZero` without proving anything.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "Dep.tla").write_text(
        "---- MODULE Dep ----\n"
        "SafeAt(b, v) == TRUE\n"
        "THEOREM AllSafeAtZero == \\A v \\in Value : SafeAt(0, v)\n"
        "<1>1. TRUE OBVIOUS\n"
        "<1> QED BY <1>1\n"
        "====\n"
    )
    (src / "Main.tla").write_text("---- MODULE Main ----\nEXTENDS Dep\n====\n")
    out = tmp_path / "out"
    out.mkdir()

    dump = {"extends": ["Dep"], "instances": []}
    copied = copy_deps_layered(dump, str(src / "Main.tla"), str(out), set())

    assert copied == ["Dep.tla"]
    text = (out / "Dep.tla").read_text()
    assert "SafeAt" in text, "given definitions must survive"
    assert "THEOREM" not in text, "no goal may remain for the agent to cite"
    assert "AllSafeAtZero" not in text
    assert "OMITTED" not in text


def test_defined_names_reads_back_emitted_definitions():
    text = "---- MODULE M ----\nInv == TRUE\nSafeAt(b, v) == TRUE\nTHEOREM T == TRUE\n====\n"
    assert _defined_names(text) == {"Inv", "SafeAt"}


def test_prune_dep_module_drops_proof_helpers_but_keeps_needed_definitions(tmp_path, monkeypatch):
    """A dependency must not hand over the original proof's scaffolding.

    `TypeOK` is an inductive invariant no task's statement mentions, so it is
    exactly what a from-scratch task should make the agent rediscover;
    `Coherence` is named by the target theorem and has to stay.
    """
    dep = tmp_path / "Dep.tla"
    dep.write_text(
        "---- MODULE Dep ----\nVARIABLE x\nCoherence == x = 1\nTypeOK == x \\in Nat\nTHEOREM Safety == TypeOK\n====\n"
    )
    fake_dump = {
        "operators": [
            {"name": "Coherence", "loc": {"line_start": 3, "line_end": 3}, "references": []},
            {"name": "TypeOK", "loc": {"line_start": 4, "line_end": 4}, "references": []},
        ],
        "instances": [],
        "assumes": [],
    }
    monkeypatch.setattr(generate, "dump_sany", lambda _p: fake_dump)

    text = prune_dep_module(str(dep), {"Coherence"})

    assert "Coherence" in text, "a definition the target statement needs must stay"
    assert "TypeOK" not in text, "an unused proof helper must be pruned"
    assert "THEOREM" not in text, "a dependency never states a goal"
    assert "VARIABLE x" in text, "declarations are always kept"


def test_unnamed_instance_stays_live_without_disabling_pruning(tmp_path, monkeypatch):
    """An unnamed INSTANCE line is never deleted, so the names it mentions stay.

    That must not stop the rest of the module being pruned: keeping the whole
    group would hand a task definitions only a sibling needs, which is the very
    thing the split exists to prevent.
    """
    dep = tmp_path / "Dep.tla"
    dep.write_text("---- MODULE Dep ----\nINSTANCE Other WITH chosen <- chosen\nchosen == 1\nTypeOK == TRUE\n====\n")
    fake_dump = {
        "module": "Dep",
        "extends": [],
        "operators": [
            {"name": "chosen", "loc": {"line_start": 3, "line_end": 3}, "references": []},
            {"name": "TypeOK", "loc": {"line_start": 4, "line_end": 4}, "references": []},
        ],
        "instances": [{"name": None, "module": "Other", "loc": {"line_start": 2, "line_end": 2}}],
        "assumes": [],
    }
    monkeypatch.setattr(generate, "dump_sany", lambda _p: fake_dump)

    keep = dep_keep_names([str(dep)], set())

    assert keep is not None, "an unnamed INSTANCE must not disable pruning"
    assert "chosen" in keep[str(dep)], "a name the INSTANCE substitutes stays live"
    assert "TypeOK" not in keep[str(dep)], "an unused proof helper is still pruned"
    text = prune_dep_module(str(dep), keep[str(dep)])
    assert "INSTANCE Other" in text, "the INSTANCE line itself is never deleted"
    assert "TypeOK" not in text


def test_dep_keep_names_closes_across_sibling_dependencies(tmp_path, monkeypatch):
    """Closure must span the group: a definition one dep needs from another
    must survive, or the pruned module stops parsing."""
    a, b = tmp_path / "A.tla", tmp_path / "B.tla"
    a.write_text("---- MODULE A ----\nEXTENDS B\nUsesChosen == chosen\n====\n")
    b.write_text("---- MODULE B ----\nchosen == 1\nUnused == 2\n====\n")
    dumps = {
        str(a): {
            "module": "A",
            "extends": ["B"],
            "operators": [{"name": "UsesChosen", "loc": {"line_start": 3, "line_end": 3}, "references": ["chosen"]}],
            "instances": [],
            "assumes": [],
        },
        str(b): {
            "module": "B",
            "extends": [],
            "operators": [
                {"name": "chosen", "loc": {"line_start": 2, "line_end": 2}, "references": []},
                {"name": "Unused", "loc": {"line_start": 3, "line_end": 3}, "references": []},
            ],
            "instances": [],
            "assumes": [],
        },
    }
    monkeypatch.setattr(generate, "dump_sany", lambda p: dumps[str(p)])

    keep = dep_keep_names([str(a), str(b)], {"UsesChosen"})

    assert "UsesChosen" in keep[str(a)]
    assert "chosen" in keep[str(b)], "a sibling dep's definition must survive"
    assert "Unused" not in keep[str(b)]


def test_dep_keep_names_does_not_keep_a_homonym_in_another_module(tmp_path, monkeypatch):
    """A local Inv must not keep Consensus.Inv just because the identifier matches.

    Voting states Spec => []Inv and Spec => C!Spec. The first Inv is Voting's;
    the second Spec is Consensus's. Matching only the bare name used to copy
    Consensus.Inv into the read-only context as C!Inv.
    """
    consensus = tmp_path / "Consensus.tla"
    consensus.write_text("---- MODULE Consensus ----\nSpec == TRUE\nInv == TRUE\n====\n")
    dumps = {
        str(consensus): {
            "module": "Consensus",
            "extends": [],
            "operators": [
                {"name": "Spec", "loc": {"line_start": 2, "line_end": 2}, "references": []},
                {"name": "Inv", "loc": {"line_start": 3, "line_end": 3}, "references": []},
            ],
            "instances": [],
            "assumes": [],
        }
    }
    monkeypatch.setattr(generate, "dump_sany", lambda p: dumps[str(p)])

    keep = dep_keep_names(
        [str(consensus)],
        {"Inv", "Spec", "C"},
        source_defined={"Inv", "Spec", "C"},
        instance_modules={"C": "Consensus"},
        qualified_uses={("C", "Spec")},
    )

    assert "Spec" in keep[str(consensus)]
    assert "Inv" not in keep[str(consensus)]


def test_dep_keep_names_resolves_instance_declared_in_a_sibling(tmp_path, monkeypatch):
    """C!Spec must find C even when the INSTANCE lives in an EXTENDS'd sibling.

    PaxosProof states V!Next, but V == INSTANCE Voting is in PaxosTuple. Matching
    only the source module's INSTANCE table dropped Voting.Next.
    """
    model = tmp_path / "PaxosTuple.tla"
    voting = tmp_path / "Voting.tla"
    model.write_text("---- MODULE PaxosTuple ----\nV == INSTANCE Voting\nNext == TRUE\n====\n")
    voting.write_text("---- MODULE Voting ----\nNext == TRUE\nInv == TRUE\n====\n")
    dumps = {
        str(model): {
            "module": "PaxosTuple",
            "extends": [],
            "operators": [{"name": "Next", "loc": {"line_start": 3, "line_end": 3}, "references": []}],
            "instances": [{"name": "V", "module": "Voting", "loc": {"line_start": 2, "line_end": 2}}],
            "assumes": [],
        },
        str(voting): {
            "module": "Voting",
            "extends": [],
            "operators": [
                {"name": "Next", "loc": {"line_start": 2, "line_end": 2}, "references": []},
                {"name": "Inv", "loc": {"line_start": 3, "line_end": 3}, "references": []},
            ],
            "instances": [],
            "assumes": [],
        },
    }
    monkeypatch.setattr(generate, "dump_sany", lambda p: dumps[str(p)])

    keep = dep_keep_names(
        [str(model), str(voting)],
        {"Next", "Inv", "V"},
        source_defined={"Inv"},
        instance_modules={},
        qualified_uses={("V", "Next")},
        imported_modules=["PaxosTuple"],
    )

    assert "Next" in keep[str(voting)]
    assert "Inv" not in keep[str(voting)]


def test_dep_keep_names_does_not_seed_an_extends_spec_from_a_qualified_use(tmp_path, monkeypatch):
    """P!Spec must not keep Lock.Spec just because Lock is EXTENDS'd."""
    lock = tmp_path / "Lock.tla"
    peterson = tmp_path / "Peterson.tla"
    lock.write_text("---- MODULE Lock ----\nInit == TRUE\nproc == TRUE\nNext == proc\nSpec == Init /\\ Next\n====\n")
    peterson.write_text("---- MODULE Peterson ----\nInit == TRUE\nNext == TRUE\nSpec == Init /\\ Next\n====\n")
    dumps = {
        str(lock): {
            "module": "Lock",
            "extends": [],
            "operators": [
                {"name": "Init", "loc": {"line_start": 2, "line_end": 2}, "references": []},
                {"name": "proc", "loc": {"line_start": 3, "line_end": 3}, "references": []},
                {"name": "Next", "loc": {"line_start": 4, "line_end": 4}, "references": ["proc"]},
                {"name": "Spec", "loc": {"line_start": 5, "line_end": 5}, "references": ["Init", "Next"]},
            ],
            "instances": [],
            "assumes": [],
        },
        str(peterson): {
            "module": "Peterson",
            "extends": [],
            "operators": [
                {"name": "Init", "loc": {"line_start": 2, "line_end": 2}, "references": []},
                {"name": "Next", "loc": {"line_start": 3, "line_end": 3}, "references": []},
                {"name": "Spec", "loc": {"line_start": 4, "line_end": 4}, "references": ["Init", "Next"]},
            ],
            "instances": [],
            "assumes": [],
        },
    }
    monkeypatch.setattr(generate, "dump_sany", lambda p: dumps[str(p)])

    keep = dep_keep_names(
        [str(lock), str(peterson)],
        referenced_identifiers("InitHS == Init", "THEOREM SpecHS => P!Spec"),
        source_defined={"InitHS", "SpecHS", "P"},
        instance_modules={"P": "Peterson"},
        qualified_uses=instance_qualified_uses("THEOREM SpecHS => P!Spec"),
        imported_modules=["Lock"],
    )

    assert "Spec" in keep[str(peterson)]
    assert "Init" in keep[str(lock)]
    assert "Spec" not in keep[str(lock)]
    assert "Next" not in keep[str(lock)]
    assert "proc" not in keep[str(lock)]


def test_unused_operator_qualified_uses_do_not_seed_a_dependency(tmp_path, monkeypatch):
    """A dropped local operator's C!Inv must not keep Consensus.Inv."""
    consensus = tmp_path / "Consensus.tla"
    model = tmp_path / "Model.tla"
    consensus.write_text("---- MODULE Consensus ----\nSpec == TRUE\nInv == TRUE\n====\n")
    model.write_text("---- MODULE Model ----\nC == INSTANCE Consensus\nUnused == C!Inv\nSpec == C!Spec\n====\n")
    dumps = {
        str(consensus): {
            "module": "Consensus",
            "extends": [],
            "operators": [
                {"name": "Spec", "loc": {"line_start": 2, "line_end": 2}, "references": []},
                {"name": "Inv", "loc": {"line_start": 3, "line_end": 3}, "references": []},
            ],
            "instances": [],
            "assumes": [],
        },
        str(model): {
            "module": "Model",
            "extends": [],
            "operators": [
                {"name": "Unused", "loc": {"line_start": 3, "line_end": 3}, "references": ["C"]},
                {"name": "Spec", "loc": {"line_start": 4, "line_end": 4}, "references": ["C"]},
            ],
            "instances": [{"name": "C", "module": "Consensus", "loc": {"line_start": 2, "line_end": 2}}],
            "assumes": [],
        },
    }
    monkeypatch.setattr(generate, "dump_sany", lambda p: dumps[str(p)])

    keep = dep_keep_names(
        [str(model), str(consensus)],
        {"Spec"},
        source_defined=set(),
        qualified_uses={("C", "Spec")},
        imported_modules=["Model"],
    )

    assert "Spec" in keep[str(consensus)]
    assert "Inv" not in keep[str(consensus)]


def test_instance_qualified_uses_ignore_string_literals():
    assert instance_qualified_uses('C!Spec /\\ x = "C!Inv"') == {("C", "Spec")}


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("Storage(s)!Start", {("Storage", "Start")}),
        ("Storage(F(s), G(H(s)))!Read", {("Storage", "Read")}),
        ("Storage(Other!Argument) ! Read", {("Storage", "Read"), ("Other", "Argument")}),
        ('Storage(")!Unused")!Read', {("Storage", "Read")}),
        ("Storage((* )!Unused *) s)\n! Read", {("Storage", "Read")}),
    ],
)
def test_instance_qualified_uses_with_parameters(expression, expected):
    assert instance_qualified_uses(expression) == expected


def test_referenced_identifiers_skip_the_right_hand_name_of_a_qualified_use():
    """P!Spec must not put Spec in the bare seed set."""
    assert "Spec" not in referenced_identifiers("SpecHS => P!Spec")
    assert "P" in referenced_identifiers("SpecHS => P!Spec")
    assert "Spec" not in referenced_identifiers("SpecHS => P(1) ! (* context *) Spec")
    assert "Spec" in referenced_identifiers("Spec => P!Spec")
    assert "Spec" not in referenced_identifiers('C!Spec /\\ x = "C!Inv"')


def test_referenced_identifiers_ignores_tla_backslash_operators():
    assert "A" not in referenced_identifiers("\\A p \\in S : TRUE")
    assert {"p", "S", "TRUE"} <= referenced_identifiers("\\A p \\in S : TRUE")


def test_missing_tlapm_fails_generation_rather_than_skipping(tmp_path, monkeypatch):
    """A degenerate task PASSes with an empty submission, so it must never ship.

    Without tlapm the gate cannot tell, and skipping would let one through, so
    generation fails instead. `--skip-gates` is the deliberate opt-out.
    """
    monkeypatch.setattr(generate, "find_tlapm", lambda: None, raising=False)
    monkeypatch.setattr("dataset.triviality_audit.find_tlapm", lambda: None)

    class _Audit:
        def write(self, _):
            pass

    with pytest.raises(RuntimeError, match="tlapm not found"):
        generate.layered_triviality_gate(str(tmp_path), {}, _Audit())


def test_subscript_names_are_seen_as_references():
    """`[][Next]_vars` and `WF_vars(p)` bind `vars` with a leading underscore.

    Regression: the raw token is `_vars`, so `vars` looked unused and was pruned
    out of a dependency that still needed it (Unknown operator: `vars').
    """
    names = referenced_identifiers("Spec == Init /\\ [][Next]_vars /\\ WF_vars(proc)")
    assert "vars" in names
    assert {"Init", "Next", "Spec", "proc"} <= names


def test_filtered_run_keeps_tasks_outside_the_filter(tmp_path):
    """A `--filter` run must leave the rest of the dataset alone.

    Regression: the sweep deleted every file the filtered manifest did not
    reference, so regenerating one group wiped the other tasks off disk and
    replaced the manifest with just the filtered subset.
    """
    untouched_key, untouched_entry = _write_task(tmp_path, "Peterson", "Peterson_MutualExclusion")
    stored = {untouched_key: untouched_entry}
    (tmp_path / "manifest.json").write_text(json.dumps(stored, indent=2))

    regenerated_key, regenerated_entry = _write_task(tmp_path, "Paxos", "Paxos_Consistent")

    class _Audit:
        def write(self, _):
            pass

    generate._finalize_layered(
        str(tmp_path), {regenerated_key: regenerated_entry}, {}, _Audit(), run_gates=False, incremental=True
    )

    written = json.loads((tmp_path / "manifest.json").read_text())
    assert set(written) == {untouched_key, regenerated_key}, "unselected tasks stay in the manifest"
    assert (tmp_path / untouched_key).exists(), "unselected task file survives"
    assert (tmp_path / "Peterson" / "Peterson_MutualExclusionDefs.tla").exists(), "its context survives"


def test_full_run_replaces_the_manifest(tmp_path):
    """Without a filter the run owns the whole dataset, so a task that is no
    longer generated must disappear rather than linger from the old manifest."""
    stale_key, stale_entry = _write_task(tmp_path, "Old", "Old_Thm")
    (tmp_path / "manifest.json").write_text(json.dumps({stale_key: stale_entry}, indent=2))
    fresh_key, fresh_entry = _write_task(tmp_path, "New", "New_Thm")

    class _Audit:
        def write(self, _):
            pass

    generate._finalize_layered(
        str(tmp_path), {fresh_key: fresh_entry}, {}, _Audit(), run_gates=False, incremental=False
    )

    assert set(json.loads((tmp_path / "manifest.json").read_text())) == {fresh_key}


def test_dataset_selection_difference_is_audited_not_rejected(tmp_path):
    fresh_key, fresh_entry = _write_task(tmp_path, "New", "New_Thm")
    audit = StringIO()

    final_count = generate._finalize_layered(
        str(tmp_path),
        {fresh_key: fresh_entry},
        {},
        audit,
        run_gates=False,
        reference_task_keys={"Old/Old_Thm.tla"},
    )

    assert final_count == 1
    assert set(json.loads((tmp_path / "manifest.json").read_text())) == {fresh_key}
    assert "Old/Old_Thm.tla: existing dataset task was not regenerated" in audit.getvalue()
    assert "New/New_Thm.tla: generated task is not in the existing dataset selection" in audit.getvalue()


def test_regenerated_source_drops_its_stale_tasks(tmp_path):
    """A target its source no longer emits must leave the manifest.

    Regression: keying the removal on what the run PRODUCED meant a task that
    stopped being generated — filtered out, deduped, or gated — survived from
    the previous manifest.
    """
    stale_key, stale_entry = _write_task(tmp_path, "Group", "Source_OldTarget")
    kept_key, kept_entry = _write_task(tmp_path, "Other", "Other_Thm")
    (tmp_path / "manifest.json").write_text(json.dumps({stale_key: stale_entry, kept_key: kept_entry}, indent=2))
    fresh_key, fresh_entry = _write_task(tmp_path, "Group", "Source_NewTarget")

    class _Audit:
        def write(self, _):
            pass

    all_bases = {"Group": {"Source"}, "Other": {"Other"}}
    generate._finalize_layered(
        str(tmp_path),
        {fresh_key: fresh_entry},
        {},
        _Audit(),
        run_gates=False,
        incremental=True,
        scope=(all_bases, {"Group": {"Source"}}),
    )

    written = json.loads((tmp_path / "manifest.json").read_text())
    assert stale_key not in written, "a target its source no longer emits must go"
    assert not (tmp_path / stale_key).exists(), "and its file must be swept"
    assert kept_key in written, "a source this run skipped is untouched"
    assert fresh_key in written


def test_task_ownership_uses_the_longest_matching_source():
    """`TwoPhase_proof_line17` belongs to TwoPhase_proof, not to its sibling
    source TwoPhase — otherwise regenerating one would delete the other's tasks.
    """
    all_bases = {"TP": {"TwoPhase", "TwoPhase_proof"}}
    existing = {"TP/TwoPhase_Implementation.tla": {}, "TP/TwoPhase_proof_line17.tla": {}}

    assert tasks_owned_by(existing, all_bases, {"TP": {"TwoPhase"}}) == {"TP/TwoPhase_Implementation.tla"}
    assert tasks_owned_by(existing, all_bases, {"TP": {"TwoPhase_proof"}}) == {"TP/TwoPhase_proof_line17.tla"}


def test_partial_run_refuses_an_output_dir_with_no_usable_manifest(tmp_path):
    """A partial run trusts the manifest to know what it is not regenerating.

    Without one it would treat its own tasks as the whole dataset and sweep
    everything else away, so it must refuse before writing anything.
    """
    assert incremental_precondition_error(str(tmp_path)) is None, "an empty dir has nothing to lose"

    (tmp_path / "Peterson").mkdir()
    (tmp_path / "Peterson" / "X_Thm.tla").write_text("---- MODULE X_Thm ----\n====\n")
    assert "no manifest.json" in incremental_precondition_error(str(tmp_path))

    (tmp_path / "manifest.json").write_text("not json")
    assert "unreadable" in incremental_precondition_error(str(tmp_path))

    (tmp_path / "manifest.json").write_text("[]")
    assert "not a JSON object" in incremental_precondition_error(str(tmp_path))

    (tmp_path / "manifest.json").write_text("{}")
    assert incremental_precondition_error(str(tmp_path)) is None


# --- the triviality gate's timeout handling --------------------------------


def _triviality_env(tmp_path, monkeypatch, verdicts):
    """A one-task manifest plus a `check_task` returning `verdicts` in order."""
    from dataset import triviality_audit

    (tmp_path / "Group").mkdir()
    (tmp_path / "Group" / "Group_Thm.tla").write_text("---- MODULE Group_Thm ----\nTHEOREM TRUE\nPROOF OBVIOUS\n====\n")
    monkeypatch.setattr(triviality_audit, "find_tlapm", lambda: "/bin/true")
    monkeypatch.setattr(triviality_audit, "find_tlapm_lib", lambda _p: "/lib")

    calls = []

    def fake_check_task(path, tlapm_path, tlapm_lib, timeout, community_lib=None):
        calls.append(timeout)
        return verdicts[len(calls) - 1]

    monkeypatch.setattr(triviality_audit, "check_task", fake_check_task)
    return {"Group/Group_Thm.tla": {"spec_id": "Fixture.tla", "context": [], "reference_proof_steps": 0}}, calls


def test_a_timed_out_task_is_rechecked_alone_on_the_graders_budget(tmp_path, monkeypatch):
    """Regression: Data/SequencesTheorems_AppendDef verifies unchanged in 24s.

    It survived the gate because the parallel pass — 16 tlapm at once, each able
    to start a multi-GB Isabelle — ran out of budget, and a timeout reads as
    "not degenerate". The re-check has to be un-starved AND on the grader's
    budget, or it cannot overturn that.
    """
    from dataset.triviality_audit import TIMEOUT_DETAIL

    manifest, calls = _triviality_env(
        tmp_path, monkeypatch, [(False, TIMEOUT_DETAIL), (True, "placeholder PROOF OBVIOUS verifies unchanged")]
    )
    audit = StringIO()
    dropped, slow, errored = generate.layered_triviality_gate(
        str(tmp_path), manifest, audit, timeout=10, retry_timeout=40
    )

    assert calls == [10, 40], "a timeout must be re-checked on the longer budget"
    assert dropped == ["Group/Group_Thm.tla"]
    assert slow == []
    assert errored == []
    assert manifest == {}
    assert not (tmp_path / "Group" / "Group_Thm.tla").exists()
    assert "verifies on the re-check" in audit.getvalue()


def test_the_recheck_budget_defaults_to_the_graders_own_deadline(tmp_path, monkeypatch):
    """A shorter re-check proves nothing: "did not verify in 120s" does not
    imply "cannot pass grading", which allows 600s."""
    from common.check_proof import resolve_timeout
    from dataset.triviality_audit import TIMEOUT_DETAIL

    manifest, calls = _triviality_env(tmp_path, monkeypatch, [(False, TIMEOUT_DETAIL), (False, "")])
    generate.layered_triviality_gate(str(tmp_path), manifest, StringIO(), timeout=10)

    assert calls == [10, resolve_timeout(None)]


def test_a_task_that_really_fails_the_recheck_is_kept_with_a_reason(tmp_path, monkeypatch):
    """Keeping it is a conclusion, not a guess: if the un-starved re-check
    reaches a real "does not verify" verdict within the grader's budget, a no-op
    submission cannot PASS grading either, so the task stays."""
    from dataset.triviality_audit import TIMEOUT_DETAIL

    manifest, calls = _triviality_env(tmp_path, monkeypatch, [(False, TIMEOUT_DETAIL), (False, "")])
    audit = StringIO()
    dropped, slow, errored = generate.layered_triviality_gate(
        str(tmp_path), manifest, audit, timeout=10, retry_timeout=40
    )

    assert calls == [10, 40]
    assert dropped == []
    assert slow == ["Group/Group_Thm.tla"]
    assert errored == []
    assert set(manifest) == {"Group/Group_Thm.tla"}, "a genuine task must survive"
    assert "cannot PASS grading either" in audit.getvalue()


def test_a_second_timeout_is_a_generation_error(tmp_path, monkeypatch):
    """A re-check that ALSO times out is a non-verdict, not "does not verify".

    The re-check still runs 16-wide, so contention can time it out; reading that
    as "kept, cannot pass grading" would ship a task the gate never actually
    judged. Qian-Cheng-nju asked for a second timeout to fail the run instead —
    so it is reported as errored and the task is neither dropped nor blessed.
    """
    from dataset.triviality_audit import TIMEOUT_DETAIL

    manifest, calls = _triviality_env(tmp_path, monkeypatch, [(False, TIMEOUT_DETAIL), (False, TIMEOUT_DETAIL)])
    audit = StringIO()
    dropped, slow, errored = generate.layered_triviality_gate(
        str(tmp_path), manifest, audit, timeout=10, retry_timeout=40
    )

    assert calls == [10, 40]
    assert dropped == []
    assert slow == []
    assert errored == ["Group/Group_Thm.tla"]
    assert set(manifest) == {"Group/Group_Thm.tla"}, "an errored task is left for the caller to fail on"
    assert "timed out again" in audit.getvalue()


def test_a_missing_module_is_a_generation_error(tmp_path, monkeypatch):
    """A module the gate cannot resolve is a non-verdict, not "does not verify".

    The grader supplies the vendored Community Modules; a task that only errors
    because the gate lacked them (SumSequence_Lemma2a) must not be kept as
    non-degenerate. It is reported as errored so the run fails rather than
    shipping a task the gate could not judge.
    """
    from dataset.triviality_audit import missing_module_detail

    manifest, calls = _triviality_env(tmp_path, monkeypatch, [(False, missing_module_detail("SequencesExtTheorems"))])
    audit = StringIO()
    dropped, slow, errored = generate.layered_triviality_gate(str(tmp_path), manifest, audit, timeout=10)

    assert calls == [10], "a missing module is a verdict-less result; no re-check helps"
    assert dropped == []
    assert slow == []
    assert errored == ["Group/Group_Thm.tla"]
    assert "could not judge" in audit.getvalue()


def test_a_task_that_fails_its_placeholder_is_kept_without_a_recheck(tmp_path, monkeypatch):
    manifest, calls = _triviality_env(tmp_path, monkeypatch, [(False, "")])
    dropped, slow, errored = generate.layered_triviality_gate(str(tmp_path), manifest, StringIO(), timeout=10)

    assert calls == [10], "a real verdict is not re-checked"
    assert (dropped, slow, errored) == ([], [], [])
    assert set(manifest) == {"Group/Group_Thm.tla"}

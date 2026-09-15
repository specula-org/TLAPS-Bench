"""proof-from-scratch module-task generation — the Issue #132 dataset side.

One task per source module, every corpus target present as an identified
``PROOF OMITTED`` region, so a proof can cite the sibling the author cited. The
generator reads the 244-task corpus and never writes to it; these tests pin the
grouping, the emitted module shape, the binder repair that a shared module
makes necessary, and a verifier that trusts neither the manifest it reads nor
the tree it finds.

Run: PYTHONPATH=src python3 -m pytest tests/dataset/test_module_tasks.py
"""

import hashlib
import json
import shutil
from io import StringIO
from pathlib import Path

import pytest

from common.proof_from_scratch_module import (
    MODULE_TASK_FORMAT_VERSION,
    ModuleTaskContractError,
    begin_agent_proof,
    end_agent_proof,
    parse_module_task_regions,
    statement_sha256,
    validate_module_task_spec_data,
)
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS
from dataset.proof_from_scratch import generate, module_tasks
from dataset.proof_from_scratch.module_tasks import (
    CANONICAL_PROOF,
    MANIFEST_FILENAME,
    ModuleTaskError,
    _assert_writable_output,
    _read_statements,
    build_module_task,
    check_module_task,
    expected_suite_files,
    generate_module_tasks,
    group_targets_by_specification,
    identifier_tokens,
    plan_statement_renames,
    rewrite_identifiers,
    verify_module_tasks,
)

REPO_ROOT = Path(module_tasks.PROJECT_ROOT)
TLA2TOOLS = REPO_ROOT / "lib" / "tla2tools.jar"

requires_sany = pytest.mark.skipif(
    shutil.which("java") is None or not TLA2TOOLS.is_file(),
    reason="SANY needs java and lib/tla2tools.jar",
)


def test_targets_group_by_specification_in_sorted_order():
    grouped = group_targets_by_specification(
        {
            "B/B_Two.tla": {"spec_id": "B/B.tla"},
            "A/A_Late.tla": {"spec_id": "A/A.tla"},
            "B/B_One.tla": {"spec_id": "B/B.tla"},
            "A/A_Early.tla": {"spec_id": "A/A.tla"},
        }
    )

    assert list(grouped) == ["A/A.tla", "B/B.tla"]
    assert grouped["A/A.tla"] == ["A/A_Early.tla", "A/A_Late.tla"]
    assert grouped["B/B.tla"] == ["B/B_One.tla", "B/B_Two.tla"]


@pytest.mark.parametrize("entry", [{}, {"spec_id": ""}, {"spec_id": 3}, "not a mapping"])
def test_manifest_entry_without_a_specification_is_an_error(entry):
    with pytest.raises(ModuleTaskError, match="has no spec_id"):
        group_targets_by_specification({"A/A_Thm.tla": entry})


def test_shipped_corpus_groups_every_task_exactly_once():
    corpus = json.loads((Path(generate.BENCHMARK_DIR) / MANIFEST_FILENAME).read_text())
    grouped = group_targets_by_specification(corpus)

    covered = [task_id for keys in grouped.values() for task_id in keys]
    assert sorted(covered) == sorted(corpus)
    assert len(covered) == len(set(covered))


UNITS = [
    ("Group/Group_First.tla", "THEOREM First == Spec => []Inv"),
    ("Group/Group_Second.tla", "THEOREM Second == Spec => []TypeOK"),
]


def test_module_task_carries_one_identified_region_per_proof_unit():
    text = build_module_task("Group", "GroupDefs", UNITS)

    assert text.startswith("---- MODULE Group ----\nEXTENDS GroupDefs\n")
    assert text.count("EXTENDS ") == 1
    assert text.count(BEGIN_AGENT_HELPERS) == 1
    assert text.count(END_AGENT_HELPERS) == 1
    lines = text.splitlines()
    for task_id, statement in UNITS:
        assert begin_agent_proof(task_id) in lines
        assert end_agent_proof(task_id) in lines
        assert statement in text
    assert text.count(CANONICAL_PROOF) == len(UNITS)
    assert text.endswith("====\n")


def test_module_task_keeps_the_corpus_order_of_its_proof_units():
    text = build_module_task("Group", "GroupDefs", UNITS)
    positions = [text.index(begin_agent_proof(task_id)) for task_id, _ in UNITS]

    assert positions == sorted(positions)
    assert text.index(UNITS[0][1]) < positions[0] < text.index(UNITS[1][1]) < positions[1]


def test_module_task_parses_as_the_shared_region_contract():
    text = build_module_task("Group", "GroupDefs", UNITS)
    regions = parse_module_task_regions(text, [task_id for task_id, _ in UNITS])

    assert regions.proof_unit_ids == tuple(task_id for task_id, _ in UNITS)
    assert regions.helpers.strip() == ""
    assert [proof.text.strip() for proof in regions.proofs] == [CANONICAL_PROOF] * len(UNITS)
    assert regions.render() == text


def test_module_task_leaves_room_for_a_submitted_proof_and_helper():
    text = build_module_task("Group", "GroupDefs", UNITS)
    regions = parse_module_task_regions(text, [task_id for task_id, _ in UNITS])

    submitted = regions.render(helpers="Aux == TRUE\n", proofs={UNITS[0][0]: "BY Aux\n"})

    assert "Aux == TRUE" in submitted
    assert "BY Aux" in submitted
    assert submitted.count(CANONICAL_PROOF) == len(UNITS) - 1
    for task_id, statement in UNITS:
        assert begin_agent_proof(task_id) in submitted.splitlines()
        assert statement in submitted


def test_module_task_without_a_proof_unit_is_refused():
    with pytest.raises(ModuleTaskError, match="no proof units"):
        build_module_task("Group", "GroupDefs", [])


def test_statements_are_read_back_from_the_emitted_bytes(tmp_path):
    text = build_module_task("Group", "GroupDefs", UNITS)
    (tmp_path / "Group").mkdir()
    (tmp_path / "Group" / "Group.tla").write_text(text)
    entry = {
        "spec": {
            "task_id": "Group/Group.tla",
            "proof_units": [{"task_id": task_id, "statement_sha256": statement_sha256(s)} for task_id, s in UNITS],
        }
    }

    assert _read_statements(entry, tmp_path) == UNITS


def test_quantifier_is_not_read_as_an_identifier():
    assert identifier_tokens(r"\A A \in S : A \in Nat") == {"A", "S", "Nat"}
    assert "in" not in identifier_tokens(r"x \in Nat")


def test_string_contents_are_not_identifiers():
    assert identifier_tokens('pc = "Done" => x') == {"pc", "x"}


def test_instance_qualified_name_is_not_renamed():
    assert identifier_tokens("C!Spec /\\ C") == {"C"}
    assert rewrite_identifiers("C!Spec /\\ Spec", {"Spec": "Spec1"}) == "C!Spec /\\ Spec1"


def test_rename_matches_whole_identifiers_only():
    text = r"\A A \in [1..N -> Int] : [A EXCEPT ![i] = A0[i]] /\ A1 = A"

    assert rewrite_identifiers(text, {"A": "A2", "i": "i1"}) == (
        r"\A A2 \in [1..N -> Int] : [A2 EXCEPT ![i1] = A0[i1]] /\ A1 = A2"
    )


def test_rename_leaves_string_literals_alone():
    assert rewrite_identifiers('pc = "pc" /\\ pc', {"pc": "pc1"}) == 'pc1 = "pc" /\\ pc1'


def _dump(**line_by_name):
    groups = {"constants": [], "variables": [], "operators": [], "instances": [], "theorems": []}
    for name, (group, line) in line_by_name.items():
        groups[group].append({"name": name, "loc": {"line_start": line}})
    return groups


def test_binder_captured_by_a_later_declaration_is_renamed():
    dump = _dump(A=("variables", 131), i=("variables", 131), pc=("variables", 131))
    theorem = {"loc": {"line_start": 69}}

    renames = plan_statement_renames(theorem, r"\A A \in S, i \in T : P(A, i)", dump, {"A", "i", "pc"})

    assert renames == {"A": "A1", "i": "i1"}


def test_name_already_in_scope_at_the_statement_is_never_renamed():
    dump = _dump(A=("variables", 10), pc=("variables", 10))
    theorem = {"loc": {"line_start": 202}}

    assert plan_statement_renames(theorem, 'A /\\ pc = "Done"', dump, {"A", "pc"}) == {}


def test_declaration_that_does_not_survive_into_the_layers_cannot_capture():
    dump = _dump(A=("variables", 131))
    theorem = {"loc": {"line_start": 69}}

    assert plan_statement_renames(theorem, r"\A A \in S : TRUE", dump, set()) == {}


def test_fresh_binder_name_avoids_every_name_the_module_uses():
    dump = _dump(A=("variables", 131), A1=("operators", 5), A2=("operators", 6))
    theorem = {"loc": {"line_start": 69}}

    assert plan_statement_renames(theorem, r"\A A \in S : A3 = A", dump, {"A"}) == {"A": "A4"}


def test_binder_rename_is_deterministic():
    dump = _dump(A=("variables", 131), i=("variables", 131), j=("variables", 131))
    theorem = {"loc": {"line_start": 69}}
    statement = r"\A A \in S, i, j \in T : P(A, i, j)"
    exposed = {"A", "i", "j"}

    first = plan_statement_renames(theorem, statement, dump, exposed)
    assert first == plan_statement_renames(theorem, statement, dump, exposed)
    assert first == {"A": "A1", "i": "i1", "j": "j1"}


def _emit(tmp_path, *, task_text=None, defs_body="Inv == TRUE"):
    (tmp_path / "Group").mkdir(exist_ok=True)
    (tmp_path / "Group" / "Group.tla").write_text(task_text or build_module_task("Group", "GroupDefs", UNITS))
    (tmp_path / "Group" / "GroupDefs.tla").write_text(
        f"---- MODULE GroupDefs ----\n{defs_body}\n====\n",
    )
    entry = {
        "spec": {
            "format_version": MODULE_TASK_FORMAT_VERSION,
            "task_id": "Group/Group.tla",
            "source_sha256": "0" * 64,
            "proof_units": [{"task_id": task_id, "statement_sha256": statement_sha256(s)} for task_id, s in UNITS],
        },
        "context": ["Group/GroupDefs.tla"],
        "renamed_bindings": {},
    }
    return entry


def test_a_clean_module_task_reports_no_structural_error(tmp_path):
    entry = _emit(tmp_path)
    assert check_module_task(entry, UNITS, tmp_path) == []
    validate_module_task_spec_data(entry["spec"])


def test_edited_statement_no_longer_matches_its_recorded_digest(tmp_path):
    entry = _emit(tmp_path)
    tampered = [(UNITS[0][0], "THEOREM First == Spec => []FALSE"), UNITS[1]]

    errors = check_module_task(entry, tampered, tmp_path)

    assert any("statement digest" in error for error in errors)


def test_a_proof_left_in_the_task_outside_a_region_is_rejected(tmp_path):
    text = build_module_task("Group", "GroupDefs", UNITS).replace("====\n", "<1> QED\n  OBVIOUS\n====\n")
    entry = _emit(tmp_path, task_text=text)

    errors = check_module_task(entry, UNITS, tmp_path)

    assert any("outside an identified region" in error for error in errors)


def test_a_prefilled_proof_region_is_rejected(tmp_path):
    text = build_module_task("Group", "GroupDefs", UNITS).replace(CANONICAL_PROOF, "BY DEF Inv", 1)
    entry = _emit(tmp_path, task_text=text)

    errors = check_module_task(entry, UNITS, tmp_path)

    assert any("is not the canonical" in error for error in errors)


def test_a_prefilled_helper_region_is_rejected(tmp_path):
    text = build_module_task("Group", "GroupDefs", UNITS).replace(
        END_AGENT_HELPERS, f"Aux == TRUE\n{END_AGENT_HELPERS}", 1
    )
    entry = _emit(tmp_path, task_text=text)

    errors = check_module_task(entry, UNITS, tmp_path)

    assert any("helper region is not empty" in error for error in errors)


def test_an_extra_theorem_in_the_task_is_rejected(tmp_path):
    text = build_module_task("Group", "GroupDefs", UNITS).replace("====\n", "THEOREM Bonus == TRUE\n====\n")
    entry = _emit(tmp_path, task_text=text)

    errors = check_module_task(entry, UNITS, tmp_path)

    assert any("THEOREM statement" in error for error in errors)


@pytest.mark.parametrize(
    "defs_body",
    [
        "THEOREM Shortcut == TRUE\nPROOF OMITTED",
        "LEMMA Shortcut == TRUE\nBY TRUE",
        "Inv == TRUE\n<1>1. TRUE",
    ],
)
def test_a_proof_artifact_in_read_only_context_is_rejected(tmp_path, defs_body):
    entry = _emit(tmp_path, defs_body=defs_body)

    errors = check_module_task(entry, UNITS, tmp_path)

    assert any("read-only context contains proof artifact" in error for error in errors)


def test_content_after_the_outer_module_is_rejected(tmp_path):
    entry = _emit(tmp_path)
    path = tmp_path / "Group" / "GroupDefs.tla"
    path.write_text(path.read_text() + "trailing hint\n")

    errors = check_module_task(entry, UNITS, tmp_path)

    assert any("content remains after the outer module terminator" in error for error in errors)


def test_a_task_missing_a_region_marker_is_rejected(tmp_path):
    text = build_module_task("Group", "GroupDefs", UNITS).replace(end_agent_proof(UNITS[1][0]) + "\n", "")
    entry = _emit(tmp_path, task_text=text)

    errors = check_module_task(entry, UNITS, tmp_path)

    assert errors and "violates the region contract" in errors[0]


def test_the_generator_refuses_to_write_into_the_corpus(tmp_path):
    corpus = tmp_path / "benchmark" / "proof-from-scratch"
    corpus.mkdir(parents=True)

    for output in (corpus, corpus / "nested", corpus.parent):
        with pytest.raises(ModuleTaskError, match="may not be written into the corpus tree"):
            _assert_writable_output(output, corpus)

    _assert_writable_output(tmp_path / "benchmark" / "proof-from-scratch-module", corpus)


TINY_SOURCE = """---- MODULE Tiny ----
EXTENDS Naturals

VARIABLE x

vars == << x >>

Init == x = 0

Next == x' = x + 1

Spec == Init /\\ [][Next]_vars

\\* An inductive invariant the author needed, reachable only from a proof.
Helper == x >= 0

TypeOK == x \\in Nat

Correct == x >= 0

THEOREM TypeInvariant == Spec => []TypeOK
<1> QED
  BY DEF Spec, Init, Next, TypeOK

LEMMA Aux == TRUE
OBVIOUS

THEOREM IsCorrect == Spec => []Correct
<1> QED
  BY TypeInvariant, Aux DEF Correct, Helper
====
"""

TINY_UNITS = ["Tiny/Tiny_TypeInvariant.tla", "Tiny/Tiny_IsCorrect.tla"]


@pytest.fixture
def tiny(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "Tiny").mkdir(parents=True)
    (source_root / "Tiny" / "Tiny.tla").write_text(TINY_SOURCE)
    corpus_dir = tmp_path / "benchmark" / "proof-from-scratch"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / MANIFEST_FILENAME).write_text(
        json.dumps({task_id: {"spec_id": "Tiny/Tiny.tla", "context": []} for task_id in sorted(TINY_UNITS)}, indent=2)
    )
    return {
        "source_root": source_root,
        "corpus_dir": corpus_dir,
        "output_root": tmp_path / "benchmark" / "proof-from-scratch-module",
    }


def _run(tiny, **overrides):
    return generate_module_tasks(audit=StringIO(), **{**tiny, **overrides})


@requires_sany
def test_one_module_task_carries_every_corpus_target(tiny):
    document = _run(tiny)

    assert document["format_version"] == MODULE_TASK_FORMAT_VERSION
    assert document["complete"] is True
    assert len(document["module_tasks"]) == 1
    spec = validate_module_task_spec_data(document["module_tasks"][0]["spec"])
    assert spec.task_id == "Tiny/Tiny.tla"
    assert sorted(spec.proof_unit_ids) == sorted(TINY_UNITS)


@requires_sany
def test_the_module_task_keeps_the_union_of_the_statements_definitions(tiny):
    _run(tiny)
    defs = (tiny["output_root"] / "Tiny" / "TinyDefs.tla").read_text()

    # Each target needs the predicate the other one is about; per-theorem
    # generation would have kept only one of these.
    assert "TypeOK ==" in defs
    assert "Correct ==" in defs
    # A definition reachable only from a proof stays a proof artifact.
    assert "Helper ==" not in defs


@requires_sany
def test_the_module_task_drops_lemmas_proofs_and_comments(tiny):
    _run(tiny)
    task = (tiny["output_root"] / "Tiny" / "Tiny.tla").read_text()
    regions = parse_module_task_regions(task, TINY_UNITS)
    outside = "".join(regions.fixed_segments)

    assert "LEMMA" not in task
    assert "Aux" not in task
    assert "BY " not in outside
    assert "\\* An inductive invariant" not in (tiny["output_root"] / "Tiny" / "TinyDefs.tla").read_text()
    assert [proof.text.strip() for proof in regions.proofs] == [CANONICAL_PROOF] * len(TINY_UNITS)


@requires_sany
def test_the_corpus_is_untouched_by_generation(tiny):
    before = {path: path.read_bytes() for path in tiny["corpus_dir"].rglob("*") if path.is_file()}
    _run(tiny)

    assert {path: path.read_bytes() for path in tiny["corpus_dir"].rglob("*") if path.is_file()} == before


@requires_sany
def test_regeneration_is_byte_for_byte_deterministic(tiny, tmp_path):
    first = _run(tiny)
    second_root = tmp_path / "again"
    second = _run(tiny, output_root=second_root)

    assert first == second
    for relative in expected_suite_files(first):
        assert (tiny["output_root"] / relative).read_bytes() == (second_root / relative).read_bytes()


@requires_sany
def test_a_spot_check_cannot_reduce_a_complete_suite(tiny):
    _run(tiny)

    # A --spec run writes the manifest like any other, so aimed at a shipped
    # suite it would leave every other module's files unnamed by any entry.
    with pytest.raises(ModuleTaskError, match="already holds a complete suite"):
        _run(tiny, only=["Tiny/Tiny.tla"])

    assert json.loads((tiny["output_root"] / MANIFEST_FILENAME).read_text())["complete"] is True


@requires_sany
def test_a_specification_outside_the_corpus_is_a_clean_error(tiny):
    with pytest.raises(ModuleTaskError, match="no corpus task belongs to specification"):
        _run(tiny, only=["Tiny/Missing.tla"])


@requires_sany
def test_a_partial_run_does_not_claim_a_complete_suite(tiny):
    document = _run(tiny, only=["Tiny/Tiny.tla"])

    assert document["complete"] is False


DEP_BASE = """---- MODULE TinyBase ----
EXTENDS Naturals

Bump(n) == n + 1

\\* Scaffolding the base module's own proof needed; nothing the task states
\\* reaches it, so it must not travel with the task.
BaseInv == TRUE

TypeOK == TRUE

THEOREM BaseThm == BaseInv
OBVIOUS
====
"""

DEP_SOURCE = """---- MODULE TinyDep ----
EXTENDS TinyBase

VARIABLE x

vars == << x >>

Init == x = 0

Next == x' = Bump(x)

Spec == Init /\\ [][Next]_vars

Safe == x >= 0

THEOREM IsSafe == Spec => []Safe
<1> QED
  BY DEF Spec, Init, Next, Safe, Bump
====
"""


@pytest.fixture
def tiny_dep(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "Dep").mkdir(parents=True)
    (source_root / "Dep" / "TinyBase.tla").write_text(DEP_BASE)
    (source_root / "Dep" / "TinyDep.tla").write_text(DEP_SOURCE)
    corpus_dir = tmp_path / "benchmark" / "proof-from-scratch"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / MANIFEST_FILENAME).write_text(
        json.dumps({"Dep/TinyDep_IsSafe.tla": {"spec_id": "Dep/TinyDep.tla", "context": []}}, indent=2)
    )
    return {
        "source_root": source_root,
        "corpus_dir": corpus_dir,
        "output_root": tmp_path / "benchmark" / "proof-from-scratch-module",
    }


@requires_sany
def test_a_copied_dependency_is_pruned_to_what_the_task_reaches(tiny_dep):
    document = _run(tiny_dep)
    entry = document["module_tasks"][0]
    dep = next(rel for rel in entry["context"] if rel.endswith("TinyBase.tla"))
    text = (tiny_dep["output_root"] / dep).read_text()

    assert "Bump(n) ==" in text
    # Scaffolding a from-scratch task must rediscover cannot travel with it.
    assert "BaseInv" not in text
    assert "TypeOK" not in text
    assert "THEOREM" not in text


@requires_sany
def test_a_dependency_that_cannot_be_analyzed_stops_generation(tiny_dep, monkeypatch):
    original_dump_sany = generate.dump_sany

    def fail_for_dependency(path):
        if Path(path).name == "TinyBase.tla":
            raise RuntimeError("dependency analysis failed")
        return original_dump_sany(path)

    monkeypatch.setattr(generate, "dump_sany", fail_for_dependency)
    audit = StringIO()

    with pytest.raises(ModuleTaskError, match="refusing to expose unpruned definitions"):
        generate_module_tasks(audit=audit, validate=False, **tiny_dep)

    assert "not dumpable, group kept whole" in audit.getvalue()
    assert not (tiny_dep["output_root"] / MANIFEST_FILENAME).exists()


HOMONYM_BASE = """---- MODULE TinyBase ----
EXTENDS Naturals

Init == TRUE

Next == TRUE

Spec == Init /\\ Next

\\* Unrelated to TinyHomonym's Inv; keeping it would leak as C!Inv.
Inv == TRUE
====
"""

HOMONYM_SOURCE = """---- MODULE TinyHomonym ----
EXTENDS Naturals

VARIABLE x

vars == << x >>

Init == x = 0

Next == x' = x + 1

Spec == Init /\\ [][Next]_vars

Inv == x >= 0

C == INSTANCE TinyBase

THEOREM Invariant == Spec => []Inv
OBVIOUS

THEOREM Refinement == Spec => C!Spec
OBVIOUS
====
"""


@pytest.fixture
def tiny_homonym(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "Homonym").mkdir(parents=True)
    (source_root / "Homonym" / "TinyBase.tla").write_text(HOMONYM_BASE)
    (source_root / "Homonym" / "TinyHomonym.tla").write_text(HOMONYM_SOURCE)
    corpus_dir = tmp_path / "benchmark" / "proof-from-scratch"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / MANIFEST_FILENAME).write_text(
        json.dumps(
            {
                "Homonym/TinyHomonym_Invariant.tla": {"spec_id": "Homonym/TinyHomonym.tla", "context": []},
                "Homonym/TinyHomonym_Refinement.tla": {"spec_id": "Homonym/TinyHomonym.tla", "context": []},
            },
            indent=2,
        )
    )
    return {
        "source_root": source_root,
        "corpus_dir": corpus_dir,
        "output_root": tmp_path / "benchmark" / "proof-from-scratch-module",
    }


@requires_sany
def test_a_local_name_does_not_keep_the_same_name_in_a_dependency(tiny_homonym):
    document = _run(tiny_homonym)
    entry = document["module_tasks"][0]
    dep = next(rel for rel in entry["context"] if rel.endswith("TinyBase.tla"))
    text = (tiny_homonym["output_root"] / dep).read_text()

    assert "Spec ==" in text
    assert "Inv ==" not in text


QUALIFIED_LOCK = """---- MODULE TinyLock ----
EXTENDS Naturals

VARIABLE x

vars == << x >>

Init == x = 0

proc == x' = x + 1

Next == proc

Spec == Init /\\ [][Next]_vars
====
"""

QUALIFIED_PETERSON = """---- MODULE TinyPeterson ----
EXTENDS Naturals

VARIABLE y

Init == y = 0

Next == y' = y

Spec == Init /\\ [][Next]_y
====
"""

QUALIFIED_SOURCE = """---- MODULE TinyLockHS ----
EXTENDS TinyLock

VARIABLE h

InitHS == Init /\\ h = 0

NextHS == UNCHANGED << x, h >>

SpecHS == InitHS /\\ [][NextHS]_<< vars, h >>

P == INSTANCE TinyPeterson WITH y <- h

THEOREM Refinement == SpecHS => P!Spec
OBVIOUS
====
"""


@pytest.fixture
def tiny_qualified(tmp_path):
    source_root = tmp_path / "source"
    (source_root / "LockHSQ").mkdir(parents=True)
    (source_root / "LockHSQ" / "TinyLock.tla").write_text(QUALIFIED_LOCK)
    (source_root / "LockHSQ" / "TinyPeterson.tla").write_text(QUALIFIED_PETERSON)
    (source_root / "LockHSQ" / "TinyLockHS.tla").write_text(QUALIFIED_SOURCE)
    corpus_dir = tmp_path / "benchmark" / "proof-from-scratch"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / MANIFEST_FILENAME).write_text(
        json.dumps(
            {"LockHSQ/TinyLockHS_Refinement.tla": {"spec_id": "LockHSQ/TinyLockHS.tla", "context": []}},
            indent=2,
        )
    )
    return {
        "source_root": source_root,
        "corpus_dir": corpus_dir,
        "output_root": tmp_path / "benchmark" / "proof-from-scratch-module",
    }


@requires_sany
def test_a_qualified_use_does_not_keep_the_same_name_in_an_extends_dependency(tiny_qualified):
    document = _run(tiny_qualified)
    entry = document["module_tasks"][0]
    lock = next(rel for rel in entry["context"] if rel.endswith("TinyLock.tla"))
    peterson = next(rel for rel in entry["context"] if rel.endswith("TinyPeterson.tla"))
    lock_text = (tiny_qualified["output_root"] / lock).read_text()
    peterson_text = (tiny_qualified["output_root"] / peterson).read_text()

    assert "Init ==" in lock_text
    assert "Spec ==" not in lock_text
    assert "Next ==" not in lock_text
    assert "proc ==" not in lock_text
    assert "Spec ==" in peterson_text


@requires_sany
def test_a_pruned_dependency_still_leaves_a_SANY_valid_task(tiny_dep):
    # Generation SANY-checks each emitted task, so completing at all proves the
    # pruning did not cut a name the module still needs.
    document = _run(tiny_dep)

    assert verify_module_tasks(**tiny_dep) == []
    assert len(document["module_tasks"]) == 1


@requires_sany
def test_a_freshly_generated_suite_verifies(tiny):
    _run(tiny)

    assert verify_module_tasks(**tiny) == []


@requires_sany
def test_an_edited_task_does_not_survive_verification(tiny):
    _run(tiny)
    task = tiny["output_root"] / "Tiny" / "Tiny.tla"
    task.write_text(task.read_text().replace(CANONICAL_PROOF, "OBVIOUS", 1))

    assert any("differ from a regeneration" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_an_edited_read_only_layer_does_not_survive_verification(tiny):
    _run(tiny)
    defs = tiny["output_root"] / "Tiny" / "TinyDefs.tla"
    defs.write_text(defs.read_text().replace("====", "Hint == TRUE\n===="))

    assert any("differ from a regeneration" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_regenerating_over_a_populated_suite_reproduces_it(tiny):
    first = _run(tiny)
    before = {
        p.relative_to(tiny["output_root"]).as_posix(): p.read_bytes()
        for p in tiny["output_root"].rglob("*")
        if p.is_file()
    }

    second = _run(tiny)

    assert first == second
    after = {
        p.relative_to(tiny["output_root"]).as_posix(): p.read_bytes()
        for p in tiny["output_root"].rglob("*")
        if p.is_file()
    }
    assert after == before


@requires_sany
def test_an_unexpected_file_in_the_suite_is_reported(tiny):
    _run(tiny)
    (tiny["output_root"] / "Tiny" / "Extra.tla").write_text("---- MODULE Extra ----\n====\n")

    assert any("no manifest entry names" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_a_missing_context_file_is_reported(tiny):
    _run(tiny)
    (tiny["output_root"] / "Tiny" / "TinyDefs.tla").unlink()

    assert any("is missing" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_a_tampered_statement_digest_is_reported(tiny):
    _run(tiny)
    path = tiny["output_root"] / MANIFEST_FILENAME
    document = json.loads(path.read_text())
    document["module_tasks"][0]["spec"]["proof_units"][0]["statement_sha256"] = "f" * 64
    path.write_text(json.dumps(document, indent=2) + "\n")

    assert any("does not reproduce the shipped manifest" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_a_dropped_proof_unit_is_reported(tiny):
    _run(tiny)
    path = tiny["output_root"] / MANIFEST_FILENAME
    document = json.loads(path.read_text())
    document["module_tasks"][0]["spec"]["proof_units"].pop()
    path.write_text(json.dumps(document, indent=2) + "\n")

    errors = verify_module_tasks(**tiny)

    assert any("do not match the corpus tasks" in error for error in errors)
    assert any("proof unit(s); the corpus has" in error for error in errors)


@requires_sany
def test_a_stale_corpus_digest_is_reported(tiny):
    _run(tiny)
    corpus_manifest = tiny["corpus_dir"] / MANIFEST_FILENAME
    corpus = json.loads(corpus_manifest.read_text())
    corpus_manifest.write_text(json.dumps(corpus, indent=4))

    assert any("corpus_sha256 does not match" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_a_changed_source_specification_is_reported(tiny):
    _run(tiny)
    source = tiny["source_root"] / "Tiny" / "Tiny.tla"
    source.write_text(TINY_SOURCE.replace("Correct == x >= 0", "Correct == x >= 1"))

    assert any("source_sha256 does not match" in error for error in verify_module_tasks(**tiny))


@requires_sany
def test_a_suite_that_does_not_claim_completeness_is_reported(tiny):
    _run(tiny, only=["Tiny/Tiny.tla"])

    assert any("does not claim a complete suite" in error for error in verify_module_tasks(**tiny))


def test_a_missing_manifest_is_reported(tmp_path):
    errors = verify_module_tasks(
        output_root=tmp_path,
        corpus_dir=Path(generate.BENCHMARK_DIR),
        source_root=Path(module_tasks.SOURCE_ROOT),
    )

    assert errors == [f"{MANIFEST_FILENAME} is missing from {tmp_path}"]


def test_a_corrupt_manifest_is_reported(tmp_path):
    (tmp_path / MANIFEST_FILENAME).write_text("{ not json")

    errors = verify_module_tasks(
        output_root=tmp_path,
        corpus_dir=Path(generate.BENCHMARK_DIR),
        source_root=Path(module_tasks.SOURCE_ROOT),
    )

    assert errors and "is not valid JSON" in errors[0]


SUITE = Path(module_tasks.OUTPUT_DIR)

requires_suite = pytest.mark.skipif(
    not (SUITE / MANIFEST_FILENAME).is_file(),
    reason="the module-task suite has not been generated yet",
)


@pytest.fixture(scope="module")
def shipped():
    return json.loads((SUITE / MANIFEST_FILENAME).read_text())


@requires_suite
def test_shipped_suite_covers_the_corpus_exactly(shipped):
    corpus = json.loads((Path(generate.BENCHMARK_DIR) / MANIFEST_FILENAME).read_text())
    grouped = group_targets_by_specification(corpus)

    units = [unit["task_id"] for entry in shipped["module_tasks"] for unit in entry["spec"]["proof_units"]]
    assert sorted(entry["spec"]["task_id"] for entry in shipped["module_tasks"]) == sorted(grouped)
    assert sorted(units) == sorted(corpus)
    assert len(units) == len(set(units))
    assert shipped["complete"] is True


@requires_suite
def test_shipped_suite_pins_the_corpus_and_sources_it_was_cut_from(shipped):
    corpus_bytes = (Path(generate.BENCHMARK_DIR) / MANIFEST_FILENAME).read_bytes()
    assert shipped["corpus_sha256"] == hashlib.sha256(corpus_bytes).hexdigest()

    for entry in shipped["module_tasks"]:
        spec = validate_module_task_spec_data(entry["spec"])
        source = Path(module_tasks.SOURCE_ROOT) / spec.task_id
        assert hashlib.sha256(source.read_bytes()).hexdigest() == spec.source_sha256


@requires_suite
def test_shipped_suite_contains_exactly_the_files_it_names(shipped):
    actual = {path.relative_to(SUITE).as_posix() for path in SUITE.rglob("*") if path.is_file()}

    assert actual == expected_suite_files(shipped)


@requires_suite
def test_every_shipped_module_task_is_structurally_clean(shipped):
    for entry in shipped["module_tasks"]:
        statements = _read_statements(entry, SUITE)
        assert check_module_task(entry, statements, SUITE) == [], entry["spec"]["task_id"]


@requires_suite
def test_shipped_renamed_bindings_are_recorded_against_real_proof_units(shipped):
    for entry in shipped["module_tasks"]:
        unit_ids = {unit["task_id"] for unit in entry["spec"]["proof_units"]}
        for task_id, renames in entry["renamed_bindings"].items():
            assert task_id in unit_ids
            assert renames and all(old != new for old, new in renames.items())


@requires_suite
def test_shipped_module_tasks_do_not_preload_proof_libraries(shipped):
    for entry in shipped["module_tasks"]:
        text = (SUITE / entry["spec"]["task_id"]).read_text()
        assert text.count("EXTENDS ") == 1
        assert "INSTANCE" not in text


@requires_suite
def test_the_shipped_corpus_is_not_inside_the_module_suite():
    with pytest.raises(ModuleTaskError):
        _assert_writable_output(SUITE, SUITE)


@requires_suite
def test_shipped_voting_dependency_does_not_keep_unreferenced_consensus_inv():
    text = (SUITE / "Consensus" / "Voting" / "Consensus.tla").read_text()

    assert "Spec ==" in text
    assert "Inv ==" not in text


@requires_suite
def test_shipped_lockhs_does_not_keep_lock_spec_from_a_qualified_use():
    text = (SUITE / "tlaplus_examples_locks_auxiliary_vars" / "LockHS" / "Lock.tla").read_text()

    assert "Init ==" in text
    assert "Spec ==" not in text
    assert "Next ==" not in text
    assert "proc(" not in text


@requires_suite
def test_shipped_regions_round_trip_through_the_contract(shipped):
    for entry in shipped["module_tasks"]:
        unit_ids = [unit["task_id"] for unit in entry["spec"]["proof_units"]]
        text = (SUITE / entry["spec"]["task_id"]).read_text()
        regions = parse_module_task_regions(text, unit_ids)
        assert regions.render() == text
        with pytest.raises(ModuleTaskContractError):
            parse_module_task_regions(text, unit_ids + ["Group/Absent.tla"])

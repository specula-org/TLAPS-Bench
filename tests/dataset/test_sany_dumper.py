"""Regression tests for the SANY semantic dependency dump."""

import importlib
import subprocess

from dataset.proof_from_scratch.generate import compute_reachable, dep_keep_names, dump_sany, prune_dep_module
from tlacore.sany.dump import SanyStatus, run_normalized, run_raw

sany_dump = importlib.import_module("tlacore.sany.dump")


def test_parameterized_instance_dependencies_survive_pruning(tmp_path):
    inner = tmp_path / "Inner.tla"
    outer = tmp_path / "Outer.tla"
    inner.write_text("---- MODULE Inner ----\nCONSTANT seed\nValue == seed\nUnusedInvariant == TRUE\n====\n")
    outer.write_text(
        "---- MODULE Outer ----\nEXTENDS Naturals\n"
        "S(p) == INSTANCE Inner WITH seed <- p\n"
        "Used == S(1 + 0)!Value\nUnused == S(0)!UnusedInvariant\n====\n"
    )

    kept = dep_keep_names([str(outer), str(inner)], {"Used"}, imported_modules=["Outer"])

    assert kept[str(inner)] == {"Value"}
    pruned = {path: prune_dep_module(str(path), kept[str(path)]) for path in (outer, inner)}
    for path, text in pruned.items():
        path.write_text(text)
    assert {operator["name"] for operator in dump_sany(str(outer))["operators"]} == {"Used"}


def test_named_operator_argument_is_reachable(tmp_path):
    source = tmp_path / "OperatorArgument.tla"
    source.write_text(
        """------------------------- MODULE OperatorArgument -------------------------
EXTENDS Sequences

CONSTANT Items

Keep(item) == TRUE
Filtered == SelectSeq(Items, Keep)

THEOREM Goal == Filtered = Filtered
PROOF OBVIOUS
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    filtered = next(op for op in dump["operators"] if op["name"] == "Filtered")
    target = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Goal")

    assert filtered["references"] == ["Keep"]
    assert {"Filtered", "Keep"} <= compute_reachable(dump, target)


def test_proof_local_definition_cannot_hide_a_theorem_dependency(tmp_path):
    source = tmp_path / "ProofLocalDefinition.tla"
    source.write_text(
        """---------------------- MODULE ProofLocalDefinition ----------------------
THEOREM Earlier == TRUE
PROOF OMITTED

THEOREM Later == TRUE
<1> DEFINE Alias == Earlier
<1>. QED BY DEF Alias
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == ["Earlier"]


def test_operator_definition_cannot_hide_a_theorem_dependency(tmp_path):
    source = tmp_path / "OperatorDefinition.tla"
    source.write_text(
        """------------------------ MODULE OperatorDefinition ------------------------
THEOREM Earlier == FALSE
PROOF OMITTED

Alias == Earlier

THEOREM Later == FALSE
<1>. QED BY Alias DEF Alias
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == ["Earlier"]


def test_operator_argument_cannot_hide_a_theorem_dependency(tmp_path):
    source = tmp_path / "OperatorArgumentDependency.tla"
    source.write_text(
        """------------------ MODULE OperatorArgumentDependency ------------------
THEOREM Earlier == FALSE
PROOF OMITTED

Id(x) == x

THEOREM Later == FALSE
PROOF BY Id(Earlier) DEF Id
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == ["Earlier"]


def test_theorem_name_in_a_suffices_formula_is_not_a_fact_dependency(tmp_path):
    source = tmp_path / "SufficesFormula.tla"
    source.write_text(
        """-------------------------- MODULE SufficesFormula --------------------------
THEOREM Earlier == FALSE
PROOF OMITTED

THEOREM Later == Earlier => Earlier
PROOF
  <1> SUFFICES Earlier => Earlier
    OBVIOUS
  <1> QED OBVIOUS
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == []


def test_theorem_name_in_a_composite_by_fact_is_conservatively_a_dependency(tmp_path):
    source = tmp_path / "CompositeByFact.tla"
    source.write_text(
        """-------------------------- MODULE CompositeByFact --------------------------
THEOREM Earlier == FALSE
PROOF OMITTED

THEOREM Later == Earlier => Earlier
PROOF BY Earlier => Earlier
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == ["Earlier"]


def test_let_fact_cannot_hide_a_theorem_dependency(tmp_path):
    source = tmp_path / "LetFactDependency.tla"
    source.write_text(
        """------------------------- MODULE LetFactDependency -------------------------
THEOREM Earlier == FALSE
PROOF OMITTED

THEOREM Later == FALSE
PROOF BY (LET Id(x) == x IN Id(Earlier))
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == ["Earlier"]


def test_hide_directive_does_not_create_a_theorem_dependency(tmp_path):
    source = tmp_path / "HideIsNotDependency.tla"
    source.write_text(
        """------------------------- MODULE HideIsNotDependency -------------------------
THEOREM Earlier == FALSE
PROOF OMITTED

THEOREM Later == TRUE
PROOF
  <1> HIDE Earlier
  <1> QED OBVIOUS
=============================================================================
"""
    )

    dump = dump_sany(str(source))
    later = next(theorem for theorem in dump["theorems"] if theorem["name"] == "Later")

    assert later["references"] == []


def test_duplicate_record_fields_are_rejected_by_sany(tmp_path):
    source = tmp_path / "Foo.tla"
    source.write_text(
        """---- MODULE Foo -----
THEOREM Eq    == [a |-> 1, a |-> 2] = [a |-> 1, a |-> 3] OBVIOUS
THEOREM False == ASSUME NEW r, r = [a |-> 1, a |-> 2] PROVE FALSE OBVIOUS
=====
"""
    )

    run = run_normalized(str(source))

    assert run.status is SanyStatus.INVALID
    assert run.returncode == 3
    assert "Non-unique fields in constructor" in run.stderr


def test_exit_three_is_invalid_without_matching_diagnostic_text(monkeypatch, tmp_path):
    source = tmp_path / "Foo.tla"
    source.write_text("---- MODULE Foo ----\n====\n")
    stderr = "x" * 800 + " diagnostic without a known keyword"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 3, stdout="", stderr=stderr),
    )

    run = run_raw(str(source))

    assert run.status is SanyStatus.INVALID
    assert stderr in run.detail


def test_missing_sany_runner_is_unavailable(monkeypatch, tmp_path):
    source = tmp_path / "Foo.tla"
    source.write_text("---- MODULE Foo ----\n====\n")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("run.sh missing")

    monkeypatch.setattr(subprocess, "run", missing)

    run = run_raw(str(source))

    assert run.status is SanyStatus.UNAVAILABLE
    assert "run.sh missing" in run.detail


def test_sany_timeout_is_unavailable_without_retry(monkeypatch, tmp_path):
    source = tmp_path / "Foo.tla"
    source.write_text("---- MODULE Foo ----\n====\n")
    calls = 0

    def timeout(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(["sany"], 120)

    monkeypatch.setattr(subprocess, "run", timeout)

    run = run_raw(str(source), timeout=120)

    assert run.status is SanyStatus.UNAVAILABLE
    assert calls == 1


def test_normalized_staging_directory_failure_is_unavailable(monkeypatch, tmp_path):
    source = tmp_path / "solution.tla"
    source.write_text("---- MODULE Foo ----\n====\n")

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sany_dump.tempfile, "mkdtemp", fail)

    run = run_normalized(str(source))

    assert run.status is SanyStatus.UNAVAILABLE
    assert "SANY staging failed" in run.detail
    assert "disk full" in run.detail


def test_normalized_copy_failure_is_unavailable(monkeypatch, tmp_path):
    source = tmp_path / "solution.tla"
    source.write_text("---- MODULE Foo ----\n====\n")

    def fail(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(sany_dump.shutil, "copy2", fail)

    run = run_normalized(str(source))

    assert run.status is SanyStatus.UNAVAILABLE
    assert "SANY staging failed" in run.detail
    assert "copy failed" in run.detail

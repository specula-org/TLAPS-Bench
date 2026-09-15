"""Provider-neutral prompts for one-shot proof generation."""

import pytest

from evaluator.modes.proof_completion import ProofCompletion
from evaluator.modes.proof_from_scratch import ProofFromScratch

TARGET = """\
---- MODULE Target ----
EXTENDS Naturals, HelperA
THEOREM Goal == TRUE
PROOF OBVIOUS
====
"""


def _mode(cls, tmp_path):
    return cls(str(tmp_path), "/bin/true")


def test_one_shot_prompt_inlines_target_and_sorted_dependencies(tmp_path):
    target = tmp_path / "Target_Goal.tla"
    dep_b = tmp_path / "ZHelper.tla"
    dep_a = tmp_path / "AHelper.tla"
    target.write_text(TARGET)
    dep_b.write_text("---- MODULE ZHelper ----\nZMarker == {2}\n====\n")
    dep_a.write_text("---- MODULE AHelper ----\nAMarker == {1}\n====\n")

    mode = _mode(ProofCompletion, tmp_path)
    prompt = mode.build_one_shot_prompt(str(target), [str(dep_b), str(dep_a), str(dep_a)])
    reversed_prompt = mode.build_one_shot_prompt(str(target), [str(dep_a), str(dep_b)])

    assert prompt == reversed_prompt
    assert prompt.count(TARGET) == 1
    assert prompt.count("AMarker == {1}") == 1
    assert prompt.count("ZMarker == {2}") == 1
    assert prompt.index("BEGIN DEPENDENCY FILE: AHelper.tla") < prompt.index("BEGIN DEPENDENCY FILE: ZHelper.tla")


def test_one_shot_prompt_excludes_target_from_dependency_list(tmp_path):
    target = tmp_path / "Target_Goal.tla"
    target.write_text(TARGET)

    prompt = _mode(ProofCompletion, tmp_path).build_one_shot_prompt(str(target), [str(target)])

    assert prompt.count(TARGET) == 1
    assert "BEGIN DEPENDENCY FILE: Target_Goal.tla" not in prompt
    assert "# Read-only context files\n\n(none)" in prompt


def test_one_shot_prompt_rejects_ambiguous_dependency_basenames(tmp_path):
    target = tmp_path / "Target_Goal.tla"
    target.write_text(TARGET)
    first = tmp_path / "first" / "Helper.tla"
    second = tmp_path / "second" / "Helper.tla"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("---- MODULE Helper ----\nA == 1\n====\n")
    second.write_text("---- MODULE Helper ----\nB == 2\n====\n")

    mode = _mode(ProofCompletion, tmp_path)
    try:
        mode.build_one_shot_prompt(str(target), [str(first), str(second)])
    except ValueError as exc:
        assert str(exc) == "duplicate one-shot dependency basename: Helper.tla"
    else:
        raise AssertionError("duplicate dependency basenames must be rejected")


def test_proof_completion_one_shot_prompt_is_not_agentic(tmp_path):
    target = tmp_path / "Target_Goal.tla"
    target.write_text(TARGET)
    mode = _mode(ProofCompletion, tmp_path)

    prompt = mode.build_one_shot_prompt(str(target), [])
    agentic_prompt = mode.build_prompt(target.name, "/opt/tlapm", "/opt/tlapm/lib")

    assert "Return a complete, valid TLAPS solution" in prompt
    assert "Only change text inside the target's marked proof region" in prompt
    assert "Keep editing" not in prompt
    assert "run tlapm" not in prompt.lower()
    assert "check_proof_bin" not in prompt
    assert "Keep refining" in agentic_prompt
    assert '-I /opt/tlapm/lib -I "$COMMUNITY_LIB"' in agentic_prompt


def test_agentic_prompts_include_community_modules(tmp_path):
    target = tmp_path / "Target_Goal.tla"
    target.write_text(TARGET)

    for cls in (ProofCompletion, ProofFromScratch):
        prompt = _mode(cls, tmp_path).build_prompt(target.name, "/custom/tlapm", "/custom/tlapm/lib")
        assert "$COMMUNITY_LIB" in prompt
        assert '-I /custom/tlapm/lib -I "$COMMUNITY_LIB"' in prompt


def test_proof_from_scratch_rejects_one_shot_prompt(tmp_path):
    target = tmp_path / "Target_Goal.tla"
    target.write_text(TARGET)

    with pytest.raises(ValueError, match="requires a backend with workspace tools"):
        _mode(ProofFromScratch, tmp_path).build_one_shot_prompt(str(target), [])


def test_proof_from_scratch_agentic_prompt_enforces_same_boundary(tmp_path):
    mode = _mode(ProofFromScratch, tmp_path)

    prompt = mode.build_prompt("Target_Goal.tla", "/opt/tlapm", "/opt/tlapm/lib")

    assert "This is the only submitted file" in prompt
    assert "temporary wrappers, configs, traces, and other scratch files" in prompt
    assert "the final task must not import or depend on scratch files" in prompt
    assert r"\* BEGIN AGENT HELPERS" in prompt
    assert r"\* BEGIN AGENT PROOF" in prompt
    assert "Do not change the module header, imports, marker lines" in prompt
    assert "Every helper `LEMMA` or `THEOREM` must be named and fully proved" in prompt
    assert "$TLAPS_PROOF_LIBRARY_CATALOG" in prompt
    assert "LOCAL <alias> == INSTANCE <module>" in prompt
    assert "must not modify library files or use `WITH`" in prompt
    assert "check_proof_bin Target_Goal.tla --mode proof-from-scratch" in prompt

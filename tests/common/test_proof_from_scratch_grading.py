"""Pure tests for module-level proof-from-scratch grading analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pytest

from common.proof_from_scratch_grading import (
    HELPER_UNIT_PREFIX,
    ModuleSubmissionError,
    analyze_module_submission,
    proof_unit_ids_from_markers,
)
from common.proof_from_scratch_module import (
    begin_agent_proof,
    compute_trusted_units,
    end_agent_proof,
)
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS
from tlacore.model import Assumption, Loc, Module, ModuleDirective, Symbol, Theorem

UNIT_A = "Suite/Task_A.tla"
UNIT_B = "Suite/Task_B.tla"
UNITS = (UNIT_A, UNIT_B)
STATEMENTS = {
    UNIT_A: "THEOREM A == TRUE",
    UNIT_B: "THEOREM B == TRUE",
}
PROOF_BODIES = {UNIT_A: "PROOF OMITTED", UNIT_B: "PROOF OMITTED"}


def _source(
    *,
    helper_lines: Sequence[str] = (),
    proof_bodies: Mapping[str, str] | None = None,
    statements: Mapping[str, str] | None = None,
    marker_order: Sequence[str] = UNITS,
) -> str:
    bodies = dict(PROOF_BODIES if proof_bodies is None else proof_bodies)
    target_statements = dict(STATEMENTS if statements is None else statements)
    lines = [
        "---- MODULE Task ----",
        "EXTENDS TaskDefs",
        "",
        BEGIN_AGENT_HELPERS,
        *helper_lines,
        END_AGENT_HELPERS,
    ]
    for unit_id in marker_order:
        lines.extend(
            [
                "",
                target_statements[unit_id],
                begin_agent_proof(unit_id),
                *bodies[unit_id].splitlines(),
                end_agent_proof(unit_id),
            ]
        )
    lines.extend(("====", ""))
    return "\n".join(lines)


def _line_loc(source: str, text: str, *, occurrence: int = 0) -> Loc:
    matches = [line_no for line_no, line in enumerate(source.splitlines(), start=1) if line == text]
    if len(matches) <= occurrence:
        raise AssertionError(f"could not find occurrence {occurrence} of {text!r}")
    line_no = matches[occurrence]
    return Loc(line_no, 1, line_no, len(text) + 1)


def _body_loc(source: str, begin_marker: str, end_marker: str) -> Loc | None:
    lines = source.splitlines()
    begin = lines.index(begin_marker)
    end = lines.index(end_marker)
    if begin + 1 >= end:
        return None
    return Loc(begin + 2, 1, end, len(lines[end - 1]) + 1)


def _helper_lines(helper_specs: Iterable[tuple[str, Sequence[str], str]]) -> list[str]:
    lines: list[str] = []
    for name, _references, proof_body in helper_specs:
        lines.extend([f"THEOREM {name} == TRUE", *proof_body.splitlines()])
    return lines


def _module(
    source: str,
    *,
    target_references: Mapping[str, Sequence[str]] | None = None,
    helper_specs: Sequence[tuple[str, Sequence[str], str]] = (),
    statements: Mapping[str, str] | None = None,
    proof_loc_overrides: Mapping[str, Loc | None] | None = None,
    helper_loc_overrides: Mapping[str, Loc | None] | None = None,
    constants: Sequence[Symbol] = (),
    variables: Sequence[Symbol] = (),
    assumes: Sequence[Assumption] = (),
    inner_modules: Sequence[Symbol] = (),
    directives: Sequence[ModuleDirective] = (),
) -> Module:
    target_references = target_references or {}
    target_statements = dict(STATEMENTS if statements is None else statements)
    proof_loc_overrides = proof_loc_overrides or {}
    helper_loc_overrides = helper_loc_overrides or {}

    theorems: list[Theorem] = []
    for unit_id in UNITS:
        statement = target_statements[unit_id]
        statement_loc = _line_loc(source, statement)
        body_loc = _body_loc(source, begin_agent_proof(unit_id), end_agent_proof(unit_id))
        proof_loc = proof_loc_overrides.get(unit_id, body_loc)
        body_text = (
            "" if body_loc is None else "\n".join(source.splitlines()[body_loc.line_start - 1 : body_loc.line_end])
        )
        theorems.append(
            Theorem(
                name=statement.split()[1],
                loc=Loc(statement_loc.line_start, 1, proof_loc.line_end if proof_loc else statement_loc.line_end, 1),
                statement_loc=statement_loc,
                proof_loc=proof_loc,
                proof_is_omitted=body_text.strip() == "PROOF OMITTED",
                references=list(target_references.get(unit_id, ())),
                statement_references=[],
                shape={},
            )
        )

    lines = source.splitlines()
    for name, references, proof_body in helper_specs:
        declaration = f"THEOREM {name} == TRUE"
        declaration_loc = _line_loc(source, declaration)
        declaration_index = declaration_loc.line_start - 1
        proof_lines = proof_body.splitlines()
        body_loc = Loc(
            declaration_loc.line_start + 1,
            1,
            declaration_loc.line_start + len(proof_lines),
            len(lines[declaration_index + len(proof_lines)]) + 1,
        )
        proof_loc = helper_loc_overrides.get(name, body_loc)
        theorems.append(
            Theorem(
                name=name,
                loc=Loc(
                    declaration_loc.line_start, 1, proof_loc.line_end if proof_loc else declaration_loc.line_end, 1
                ),
                statement_loc=declaration_loc,
                proof_loc=proof_loc,
                proof_is_omitted=proof_body.strip() == "PROOF OMITTED",
                references=list(references),
                statement_references=[],
                shape={},
            )
        )

    theorems.sort(key=lambda theorem: theorem.loc.line_start if theorem.loc else 0)
    return Module(
        name="Task",
        source_file="Task.tla",
        filename="Task.tla",
        line_start=1,
        line_end=len(lines),
        extends=["TaskDefs"],
        constants=list(constants),
        variables=list(variables),
        assumes=list(assumes),
        instances=[],
        operators=[],
        spec_formulas=[],
        theorems=theorems,
        inner_modules=list(inner_modules),
        directives=list(directives),
    )


def _submission(
    *,
    helper_specs: Sequence[tuple[str, Sequence[str], str]] = (),
    helper_lines: Sequence[str] | None = None,
    target_references: Mapping[str, Sequence[str]] | None = None,
    proof_bodies: Mapping[str, str] | None = None,
    statements: Mapping[str, str] | None = None,
    marker_order: Sequence[str] = UNITS,
    proof_loc_overrides: Mapping[str, Loc | None] | None = None,
    helper_loc_overrides: Mapping[str, Loc | None] | None = None,
    constants: Sequence[Symbol] = (),
    variables: Sequence[Symbol] = (),
    assumes: Sequence[Assumption] = (),
    inner_modules: Sequence[Symbol] = (),
    directives: Sequence[ModuleDirective] = (),
) -> tuple[str, str, Module]:
    submitted_helper_lines = _helper_lines(helper_specs) if helper_lines is None else list(helper_lines)
    submitted = _source(
        helper_lines=submitted_helper_lines,
        proof_bodies=proof_bodies,
        statements=statements,
        marker_order=marker_order,
    )
    canonical = _source()
    module = _module(
        submitted,
        target_references=target_references,
        helper_specs=helper_specs,
        statements=statements,
        proof_loc_overrides=proof_loc_overrides,
        helper_loc_overrides=helper_loc_overrides,
        constants=constants,
        variables=variables,
        assumes=assumes,
        inner_modules=inner_modules,
        directives=directives,
    )
    return canonical, submitted, module


def _analyze(**kwargs) -> object:
    canonical, submitted, module = _submission(**kwargs)
    return analyze_module_submission(
        canonical_source=canonical,
        submitted_source=submitted,
        expected_unit_ids=UNITS,
        module=module,
    )


def test_independent_targets_allow_partial_trust():
    analysis = _analyze(
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY TRUE"},
    )

    assert analysis.local_dependencies == {UNIT_A: (), UNIT_B: ()}
    assert compute_trusted_units({UNIT_A}, analysis.local_dependencies) == frozenset({UNIT_A})


def test_target_to_target_dependency_requires_the_prerequisite():
    analysis = _analyze(
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY A"},
        target_references={UNIT_B: ("A",)},
    )

    assert analysis.local_dependencies == {UNIT_A: (), UNIT_B: (UNIT_A,)}
    assert compute_trusted_units({UNIT_B}, analysis.local_dependencies) == frozenset()
    assert compute_trusted_units(set(UNITS), analysis.local_dependencies) == frozenset(UNITS)


def test_reachable_helper_dependencies_are_included_in_the_graph():
    helper = HELPER_UNIT_PREFIX + "Bridge"
    analysis = _analyze(
        helper_specs=(("Bridge", ("A",), "PROOF BY A"),),
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY Bridge"},
        target_references={UNIT_B: ("Bridge",)},
    )

    assert [unit.unit_id for unit in analysis.helper_units] == [helper]
    assert analysis.local_dependencies == {
        UNIT_A: (),
        UNIT_B: (helper,),
        helper: (UNIT_A,),
    }
    assert compute_trusted_units(set(analysis.local_dependencies), analysis.local_dependencies) == frozenset(
        analysis.local_dependencies
    )


def test_unused_helpers_are_not_scored_or_added_to_local_dependencies():
    helper = HELPER_UNIT_PREFIX + "Unused"
    analysis = _analyze(
        helper_specs=(("Unused", (), "PROOF BY TRUE"),),
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY TRUE"},
    )

    assert analysis.helper_units == ()
    assert analysis.unused_helper_names == ("Unused",)
    assert helper not in analysis.local_dependencies


def test_cycle_of_targets_cannot_trust_itself():
    analysis = _analyze(
        proof_bodies={UNIT_A: "PROOF BY B", UNIT_B: "PROOF BY A"},
        target_references={UNIT_A: ("B",), UNIT_B: ("A",)},
    )

    assert analysis.local_dependencies == {UNIT_A: (UNIT_B,), UNIT_B: (UNIT_A,)}
    assert compute_trusted_units(set(UNITS), analysis.local_dependencies) == frozenset()


def test_omitted_helper_is_rejected_before_dependency_scoring():
    with pytest.raises(ModuleSubmissionError) as caught:
        _analyze(
            helper_specs=(("Bridge", (), "PROOF OMITTED"),),
            proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY Bridge"},
            target_references={UNIT_B: ("Bridge",)},
        )

    assert caught.value.code == "PROOF_OMITTED_ADDED"


def test_nested_omitted_step_in_target_is_rejected():
    with pytest.raises(ModuleSubmissionError) as caught:
        _analyze(
            proof_bodies={
                UNIT_A: "PROOF\n<1>1. TRUE\n  PROOF OMITTED\n<1> QED BY <1>1",
                UNIT_B: "PROOF BY TRUE",
            }
        )

    assert caught.value.code == "PROOF_OMITTED_ADDED"


def test_omitted_text_in_comments_and_strings_is_not_an_admission():
    analysis = _analyze(
        helper_lines=('Message == "OMITTED"',),
        proof_bodies={
            UNIT_A: 'PROOF BY "OMITTED" = "OMITTED"',
            UNIT_B: r"PROOF BY TRUE \* OMITTED is forbidden here",
        },
    )

    assert analysis.local_dependencies == {UNIT_A: (), UNIT_B: ()}


@pytest.mark.parametrize("budget", ["1", "5", "30", "01"])
@pytest.mark.parametrize("spacing", ["", " ", "  \n  "])
def test_deterministic_smt_budget_accepts_bounded_smt_calls(budget: str, spacing: str):
    smt_call = f'SMTT{spacing}({spacing}"r{budget}"{spacing})'
    analysis = _analyze(
        helper_lines=[f"Helper == {smt_call}"],
        proof_bodies={UNIT_A: f"PROOF BY {smt_call}", UNIT_B: "PROOF BY TRUE"},
    )

    assert analysis.local_dependencies == {UNIT_A: (), UNIT_B: ()}


@pytest.mark.parametrize(
    "smt_call",
    [
        "SMT",
        "SMTT",
        'SMTT("r0")',
        'SMTT("r31")',
        "SMTT(5)",
        'SMTT("R5")',
        'SMTT("r5", 1)',
    ],
)
def test_invalid_deterministic_smt_budget_is_rejected(smt_call: str):
    with pytest.raises(ModuleSubmissionError) as caught:
        _analyze(proof_bodies={UNIT_A: f"PROOF BY {smt_call}", UNIT_B: "PROOF BY TRUE"})

    assert caught.value.code == "SMT_BUDGET_INVALID"


def test_smt_budget_scan_ignores_comments_and_strings():
    analysis = _analyze(
        helper_lines=[r'Message == "SMT SMTT(5) SMTT(\"r0\")"'],
        proof_bodies={
            UNIT_A: 'PROOF BY TRUE \\* SMT SMTT(5) SMTT("r0")',
            UNIT_B: r'PROOF BY "SMT SMTT(5) SMTT(\"r0\")" = "SMT"',
        },
    )

    assert analysis.local_dependencies == {UNIT_A: (), UNIT_B: ()}


def test_proof_unit_ids_are_read_in_marker_order():
    assert proof_unit_ids_from_markers(_source()) == UNITS


def test_unknown_forged_marker_is_rejected():
    forged = "Suite/Forged.tla"
    canonical, submitted, module = _submission()
    submitted = submitted.replace(
        "====\n",
        f"{begin_agent_proof(forged)}\nPROOF BY TRUE\n{end_agent_proof(forged)}\n====\n",
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "MODULE_MARKERS_INVALID"


def test_reordered_markers_are_rejected():
    canonical, submitted, module = _submission(
        marker_order=(UNIT_B, UNIT_A),
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY TRUE"},
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "MODULE_MARKERS_INVALID"


@pytest.mark.parametrize(
    ("mutated", "statements"),
    [
        ("EXTENDS OtherDefs", None),
        ("THEOREM B == FALSE", {UNIT_A: STATEMENTS[UNIT_A], UNIT_B: "THEOREM B == FALSE"}),
    ],
)
def test_scaffold_and_statement_modification_are_rejected(mutated: str, statements: Mapping[str, str] | None):
    canonical = _source()
    submitted = (
        canonical.replace("EXTENDS TaskDefs", mutated)
        if mutated.startswith("EXTENDS")
        else canonical.replace(STATEMENTS[UNIT_B], mutated)
    )
    module = _module(submitted, statements=statements)

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "SCAFFOLD_MODIFIED"


def test_extra_eof_newlines_are_allowed():
    canonical, submitted, module = _submission(
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY TRUE"},
    )

    analysis = analyze_module_submission(
        canonical_source=canonical,
        submitted_source=submitted + "\r\n\n",
        expected_unit_ids=UNITS,
        module=module,
    )

    assert tuple(unit.unit_id for unit in analysis.target_units) == UNITS


@pytest.mark.parametrize(
    "transform",
    [
        lambda source: source.replace("\n", "\r\n"),
        lambda source: source.removesuffix("\n"),
    ],
    ids=("line-ending-style", "missing-final-newline"),
)
def test_newline_only_scaffold_changes_are_format_failures(transform):
    canonical, submitted, module = _submission(
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY TRUE"},
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=transform(submitted),
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "SCAFFOLD_FORMAT_MODIFIED"


def test_proof_region_cannot_lexically_extend_the_fixed_target_statement():
    canonical, submitted, module = _submission(
        proof_bodies={UNIT_A: "=> TRUE\nPROOF OBVIOUS", UNIT_B: "PROOF BY TRUE"},
    )
    statement = _line_loc(submitted, STATEMENTS[UNIT_A])
    extension = _line_loc(submitted, "=> TRUE")
    module.theorems[0].statement_loc = Loc(
        statement.line_start,
        statement.column_start,
        extension.line_end,
        extension.column_end,
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "TARGET_STATEMENT_MODIFIED"


def test_helper_region_cannot_lexically_extend_canonical_imports():
    submitted = _source(helper_lines=[", Naturals"])
    module = _module(submitted)
    module.extends.append("Naturals")

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=_source(),
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
            expected_extends=("TaskDefs",),
        )

    assert caught.value.code == "MODULE_EXTENDS_MODIFIED"


def test_proof_outside_its_identified_region_is_rejected():
    canonical, submitted, module = _submission(
        proof_bodies={UNIT_A: "PROOF BY TRUE", UNIT_B: "PROOF BY TRUE"},
        proof_loc_overrides={UNIT_A: Loc(1, 1, 1, 5)},
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "PROOF_OUTSIDE_REGION"


@pytest.mark.parametrize(
    ("helper_line", "declaration_kind"),
    [
        ("CONSTANT C", "constant"),
        ("VARIABLE v", "variable"),
        ("ASSUME A", "assume"),
        ("---- MODULE Inner ----", "inner_module"),
        ("USE Fact", "directive"),
    ],
)
def test_forbidden_helper_declarations_are_rejected(helper_line: str, declaration_kind: str):
    submitted = _source(helper_lines=[helper_line])
    location = _line_loc(submitted, helper_line)
    declarations = {
        "constant": {"constants": [Symbol("C", location)]},
        "variable": {"variables": [Symbol("v", location)]},
        "assume": {"assumes": [Assumption("A", False, location, [])]},
        "inner_module": {"inner_modules": [Symbol("Inner", location)]},
        "directive": {"directives": [ModuleDirective("USE", False, location)]},
    }[declaration_kind]
    module = _module(submitted, **declarations)

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=_source(),
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code in {"FORBIDDEN_HELPER_DECLARATION", "FORBIDDEN_HELPER_DIRECTIVE"}


def test_extra_top_level_theorem_inside_target_proof_region_is_rejected():
    proof_bodies = {
        UNIT_A: "PROOF OBVIOUS\n\nTHEOREM Admitted == FALSE\nPROOF OMITTED",
        UNIT_B: "PROOF BY Admitted",
    }
    canonical, submitted, module = _submission(
        proof_bodies=proof_bodies,
        target_references={UNIT_B: ("Admitted",)},
    )
    declaration = _line_loc(submitted, "THEOREM Admitted == FALSE")
    proof = _line_loc(submitted, "PROOF OMITTED")
    module.theorems.append(
        Theorem(
            name="Admitted",
            loc=Loc(declaration.line_start, 1, proof.line_end, proof.column_end),
            statement_loc=declaration,
            proof_loc=proof,
            proof_is_omitted=True,
            references=[],
            statement_references=[],
            shape={},
        )
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=canonical,
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "TOP_LEVEL_DECLARATION_IN_PROOF"


def test_axiom_inside_target_proof_region_is_rejected():
    proof_bodies = {
        UNIT_A: "PROOF OBVIOUS\n\nAXIOM Bad == FALSE",
        UNIT_B: "PROOF BY Bad",
    }
    submitted = _source(proof_bodies=proof_bodies)
    bad_location = _line_loc(submitted, "AXIOM Bad == FALSE")
    module = _module(
        submitted,
        target_references={UNIT_B: ("Bad",)},
        assumes=[Assumption("Bad", True, bad_location, [])],
    )

    with pytest.raises(ModuleSubmissionError) as caught:
        analyze_module_submission(
            canonical_source=_source(),
            submitted_source=submitted,
            expected_unit_ids=UNITS,
            module=module,
        )

    assert caught.value.code == "TOP_LEVEL_DECLARATION_IN_PROOF"

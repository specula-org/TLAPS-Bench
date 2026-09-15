#!/usr/bin/env python3
"""Generate one proof-from-scratch task per source module (Issue #132).

The per-theorem corpus emits a task for each target theorem, deleting every
sibling result. A task cannot cite what the author cited, so a proof two steps
downstream is scored as if it were written from nothing, and work shared between
siblings is repeated once per task.

This generator groups the existing manifest targets by ``spec_id`` and emits one
editable module per source specification: the same layered ownership as before —
a read-only Model, a read-only Defs, and one task module — but now the task
carries every target statement of that module, each followed by its own
identified ``PROOF OMITTED`` region. The existing theorem task IDs become the
scored proof-unit IDs, so a module scores k/n.

The current 244-task corpus is the target-selection source and is never written
to; module tasks are emitted into their own suite root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from io import StringIO
from pathlib import Path, PurePosixPath

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
from dataset.proof_from_scratch import generate

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "source"
CORPUS_DIR = PROJECT_ROOT / "benchmark" / "proof-from-scratch"
OUTPUT_DIR = PROJECT_ROOT / "benchmark" / "proof-from-scratch-module"

MANIFEST_FILENAME = "manifest.json"
MODEL_SUFFIX = "Model"
DEFS_SUFFIX = "Defs"

#: The unresolved state of a proof unit. An unchanged region is an unproved
#: target, never a trusted fact -- see ``compute_trusted_units``.
CANONICAL_PROOF = "PROOF OMITTED"


class ModuleTaskError(RuntimeError):
    """A module task cannot be generated from its source specification."""


_ASCII_IDENT_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_ASCII_IDENT_BODY = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _walk_identifiers(text: str) -> Iterator[tuple[int, int, str, bool]]:
    """Yield ``(start, end, token, qualified)`` for each TLA+ identifier.

    String literals are skipped, and so is the letter run after a backslash: in
    ``\\A A \\in S`` only the second ``A`` is an identifier, and reading the
    quantifier as one is exactly the bug ``_unneeded_decl_edits`` guards against
    on the declaration side. ``qualified`` marks an instance-qualified use
    (``C!Spec``), whose right half names something in another module.
    """

    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]
        if in_string:
            if char == "\\" and index + 1 < length:
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
        elif char == '"':
            in_string = True
            index += 1
        elif char == "\\":
            index += 1
            while index < length and text[index] in _ASCII_IDENT_BODY:
                index += 1
        elif char in _ASCII_IDENT_START:
            start = index
            while index < length and text[index] in _ASCII_IDENT_BODY:
                index += 1
            yield start, index, text[start:index], start > 0 and text[start - 1] == "!"
        else:
            index += 1


def identifier_tokens(text: str) -> set[str]:
    """Unqualified TLA+ identifiers mentioned in ``text``."""

    return {token for _start, _end, token, qualified in _walk_identifiers(text) if not qualified}


def rewrite_identifiers(text: str, renames: Mapping[str, str]) -> str:
    """Rename whole identifiers in ``text``, leaving strings and operators alone."""

    if not renames:
        return text
    out: list[str] = []
    cursor = 0
    for start, end, token, qualified in _walk_identifiers(text):
        replacement = None if qualified else renames.get(token)
        if replacement is None:
            continue
        out.append(text[cursor:start])
        out.append(replacement)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _fresh_name(base: str, taken: set[str]) -> str:
    index = 1
    while f"{base}{index}" in taken:
        index += 1
    return f"{base}{index}"


def plan_statement_renames(theorem: Mapping, statement: str, dump: Mapping, exposed: set[str]) -> dict[str, str]:
    """Rename statement binders that the layered module would capture.

    TLA+ scoping is order-sensitive, and the layered Model puts every
    declaration above every statement. ``BubbleSort`` binds ``\\A A \\in ...``
    at line 69 and only declares ``VARIABLES A, A0, i, j, pc`` at line 131, so
    in source order the two never meet, but in one module the declaration
    captures the binder and SANY rejects the task. This is a property of the
    module, not of any one theorem, so it appears only now that siblings share a
    module.

    A name is renamed only when the source declares it *after* this statement.
    SANY accepted the source, so a name that is not yet in scope there cannot be
    free in the statement -- every occurrence is bound by the statement itself,
    and renaming them together is alpha-equivalence, not a change of goal. Names
    already in scope at the statement are left alone, so a genuine reference is
    never rewritten.
    """

    line = theorem["loc"]["line_start"]
    declared_later = {
        entry["name"]
        for entry in (
            *dump.get("constants", []),
            *dump.get("variables", []),
            *dump.get("operators", []),
            *dump.get("instances", []),
        )
        if entry.get("name") and entry.get("loc", {}).get("line_start", 0) > line and entry["name"] in exposed
    }
    tokens = identifier_tokens(statement)
    captured = sorted(declared_later & tokens)
    if not captured:
        return {}

    taken = set(tokens)
    for group in ("constants", "variables", "operators", "instances", "theorems"):
        taken.update(entry["name"] for entry in dump.get(group, []) if entry.get("name"))
    renames: dict[str, str] = {}
    for name in captured:
        fresh = _fresh_name(name, taken)
        taken.add(fresh)
        renames[name] = fresh
    return renames


def group_targets_by_specification(manifest: Mapping[str, Mapping[str, object]]) -> dict[str, list[str]]:
    """Group the corpus task IDs by the specification they were cut from.

    The manifest is the only target-selection source: this generator never
    rediscovers theorems the corpus chose to leave out.
    """

    grouped: dict[str, list[str]] = {}
    for task_key, entry in manifest.items():
        spec_id = entry.get("spec_id") if isinstance(entry, Mapping) else None
        if not isinstance(spec_id, str) or not spec_id:
            raise ModuleTaskError(f"manifest entry {task_key!r} has no spec_id")
        grouped.setdefault(spec_id, []).append(task_key)
    return {spec_id: sorted(keys) for spec_id, keys in sorted(grouped.items())}


def plan_proof_units(spec_id: str, task_keys: Sequence[str], source_root: Path, audit: StringIO):
    """Resolve one module's corpus task IDs back to their source theorems.

    Re-runs the generator's own target selection so the module task cannot drift
    from the corpus: the same top-level rule, the same naming, and the same
    existing-dataset filter that produced these task IDs in the first place.
    Returns ``(dump, source_lines, units)`` with units in source order.
    """

    source_path = source_root / spec_id
    if not source_path.is_file():
        raise ModuleTaskError(f"source specification for {spec_id!r} does not exist: {source_path}")
    source_lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)

    try:
        dump = generate.dump_sany(str(source_path))
    except RuntimeError as exc:
        raise ModuleTaskError(f"SANY could not parse {spec_id!r}: {exc}") from exc

    for theorem in dump["theorems"]:
        theorem["_keyword"] = generate.determine_keyword(source_lines, theorem["loc"]["line_start"])
    candidates = [theorem for theorem in dump["theorems"] if theorem["_keyword"] == "THEOREM"]
    top_level = generate.find_top_level(candidates, set(dump["spec_formulas"]))

    # The output subdirectory of the per-theorem corpus is the first component
    # of its task keys, which is not always the directory of the spec_id.
    subdir = os.path.dirname(task_keys[0])
    base_module = PurePosixPath(spec_id).stem
    planned = generate._plan_layered_targets(top_level, subdir, base_module, set(task_keys), audit, str(source_path))

    resolved = {task_key: theorem for theorem, _module, task_key in planned}
    missing = sorted(set(task_keys) - set(resolved))
    if missing:
        raise ModuleTaskError(f"{spec_id!r}: {len(missing)} corpus task(s) map to no source theorem: {missing[:3]}")
    unexpected = sorted(set(resolved) - set(task_keys))
    if unexpected:
        raise ModuleTaskError(f"{spec_id!r}: produced tasks outside the corpus: {unexpected[:3]}")

    units = [(task_key, theorem) for theorem, _module, task_key in planned]
    return dump, source_lines, units


def build_module_task(module_name: str, defs_module: str, units: Sequence[tuple[str, str]]) -> str:
    """Build the editable module: one helper region, one proof region per unit.

    Each proof region is identified by the corpus task ID it scores, so the
    grader can attribute a submitted proof to the theorem it discharges without
    depending on order. ``PROOF OMITTED`` is the unresolved state, not a fact:
    an unchanged region is an unproved target.
    """

    if not units:
        raise ModuleTaskError(f"module task {module_name!r} has no proof units")

    lines = [
        f"---- MODULE {module_name} ----",
        f"EXTENDS {defs_module}",
        "",
        BEGIN_AGENT_HELPERS,
        END_AGENT_HELPERS,
    ]
    for task_id, statement in units:
        lines.extend(
            [
                "",
                statement.rstrip("\n"),
                begin_agent_proof(task_id),
                CANONICAL_PROOF,
                end_agent_proof(task_id),
            ]
        )
    lines.extend(["====", ""])
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def emit_module_task(
    spec_id: str,
    task_keys: Sequence[str],
    *,
    source_root: Path,
    output_root: Path,
    audit: StringIO,
) -> dict:
    """Emit the Model, Defs, and task module for one specification.

    Definitions are the union of every target statement's dependency closure, so
    a theorem can name the predicate its sibling is about. Everything else the
    source carried -- original lemmas, non-target theorems, proof bodies,
    comments, and definitions reachable only from a proof -- is dropped by the
    same rules the per-theorem corpus uses.
    """

    dump, source_lines, units = plan_proof_units(spec_id, task_keys, source_root, audit)
    targets = [theorem for _task_id, theorem in units]
    base_module = PurePosixPath(spec_id).stem
    relative_dir = PurePosixPath(spec_id).parent

    model_set, _main_specs = generate.compute_model_set(dump, targets)
    reachable: set[str] = set()
    for theorem in targets:
        reachable |= generate.compute_reachable(dump, theorem)

    context: list[str] = []
    model_module = None
    model_text = ""
    if model_set:
        model_module = f"{base_module}{MODEL_SUFFIX}"
        model_text = generate._rename_header(
            generate._strip_module_directives(generate.build_model(source_lines, dump, model_set)),
            model_module,
        )
        _write(output_root / relative_dir / f"{model_module}.tla", model_text)
        context.append((relative_dir / f"{model_module}.tla").as_posix())

    use_model = model_module is not None
    defs_set = reachable - model_set if use_model else reachable
    defs_module = f"{base_module}{DEFS_SUFFIX}"
    defs_text = generate.build_defs(source_lines, dump, defs_set, defs_module, model_module, not use_model)
    _write(output_root / relative_dir / f"{defs_module}.tla", defs_text)
    context.append((relative_dir / f"{defs_module}.tla").as_posix())

    # Whatever survives into Model or Defs is in scope above every statement and
    # can capture a binder the source only introduced later.
    exposed = set(reachable)
    exposed.update(entry["name"] for entry in dump.get("constants", []) if entry.get("name"))
    exposed.update(entry["name"] for entry in dump.get("variables", []) if entry.get("name"))

    statements: list[tuple[str, str]] = []
    renamed: dict[str, dict[str, str]] = {}
    for task_id, theorem in units:
        statement = generate.strip_comments(generate._statement_text(theorem, source_lines)).strip()
        renames = plan_statement_renames(theorem, statement, dump, exposed)
        if renames:
            statement = rewrite_identifiers(statement, renames)
            renamed[task_id] = renames
            pairs = ", ".join(f"{old} -> {new}" for old, new in sorted(renames.items()))
            audit.write(f"[audit] {task_id}: renamed statement binder(s) captured by a hoisted declaration: {pairs}\n")
        statements.append((task_id, statement))

    _write(output_root / spec_id, build_module_task(base_module, defs_module, statements))

    # Anything a dependency defines is handed to the agent for free, so left
    # whole `Consensus.tla` gives away the `TypeOK`/`Inv` scaffolding a
    # from-scratch task exists to make the agent rediscover. Seeded from every
    # statement, and closed over the group because dependencies reference
    # each other. The closure is module-aware: a local `Inv` does not keep an
    # unrelated `Inv` behind `C!`.
    dep_paths = [path for _module, path in generate.layered_dep_paths(dump, str(source_root / spec_id), reachable)]
    if dep_paths:
        dep_dir = output_root / relative_dir / base_module
        layer_texts = (defs_text, model_text, *(text for _id, text in statements))
        keep = generate.dep_keep_names(
            dep_paths,
            generate.referenced_identifiers(*layer_texts),
            audit,
            source_defined=generate.source_defined_names(dump),
            instance_modules=generate.source_instance_modules(dump),
            qualified_uses=generate.instance_qualified_uses(*layer_texts),
            imported_modules=generate.source_imported_modules(dump),
        )
        if keep is None:
            raise ModuleTaskError(
                f"{spec_id!r}: dependency pruning could not safely analyze every dependency; "
                "refusing to expose unpruned definitions"
            )
        for dep_path in dep_paths:
            _write(dep_dir / os.path.basename(dep_path), generate.prune_dep_text(dep_path, keep, audit))
            context.append((relative_dir / base_module / os.path.basename(dep_path)).as_posix())

    return {
        "spec": {
            "format_version": MODULE_TASK_FORMAT_VERSION,
            "task_id": spec_id,
            "source_sha256": hashlib.sha256((source_root / spec_id).read_bytes()).hexdigest(),
            "proof_units": [
                {"task_id": task_id, "statement_sha256": statement_sha256(statement)}
                for task_id, statement in statements
            ],
        },
        "context": sorted(set(context)),
        "renamed_bindings": {task_id: dict(sorted(renames.items())) for task_id, renames in sorted(renamed.items())},
    }


#: Proof syntax that must not appear outside an identified proof region. The
#: theorem keywords are checked separately: the task states its targets, so
#: `THEOREM` is expected there and forbidden in read-only context.
_TASK_PROOF_ARTIFACT = re.compile(
    r"^[ \t]*(?:(?:PROOF|OMITTED|OBVIOUS|BY|QED|USE|HIDE|DEFINE|SUFFICES|WITNESS|PICK|TAKE)\b|<\d+>)",
    re.MULTILINE,
)


def _module_tail_error(relative: str, text: str) -> str | None:
    _module, tail = generate._split_outer_module(text)
    if tail is None:
        return f"{relative}: no complete outer module terminator"
    if tail.strip():
        return f"{relative}: content remains after the outer module terminator"
    return None


def check_module_task(entry: Mapping, statements: Sequence[tuple[str, str]], output_root: Path) -> list[str]:
    """Structural problems with one emitted module task, as messages.

    This is the half of validation that needs no SANY: the task carries exactly
    the recorded statements, the editable regions are the canonical unresolved
    ones, the parsed regions rebuild the file byte for byte, and no proof
    survives outside them.
    """

    spec = entry["spec"]
    unit_ids = [unit["task_id"] for unit in spec["proof_units"]]
    errors: list[str] = []

    task_relative = spec["task_id"]
    task_text = (output_root / task_relative).read_text(encoding="utf-8")
    try:
        regions = parse_module_task_regions(task_text, unit_ids)
    except ModuleTaskContractError as exc:
        return [f"{task_relative}: emitted task violates the region contract: {exc}"]

    if regions.render() != task_text:
        errors.append(f"{task_relative}: parsed regions do not rebuild the emitted task")
    if regions.helpers.strip():
        errors.append(f"{task_relative}: helper region is not empty")
    for proof in regions.proofs:
        if proof.text.strip() != CANONICAL_PROOF:
            errors.append(f"{task_relative}: proof region {proof.task_id!r} is not the canonical {CANONICAL_PROOF!r}")

    recorded = dict(statements)
    for unit in spec["proof_units"]:
        statement = recorded.get(unit["task_id"])
        if statement is None:
            errors.append(f"{task_relative}: no statement was read for {unit['task_id']!r}")
        elif statement_sha256(statement) != unit["statement_sha256"]:
            errors.append(f"{task_relative}: statement digest for {unit['task_id']!r} does not match the manifest")

    outside = "".join(regions.fixed_segments)
    artifact = _TASK_PROOF_ARTIFACT.search(outside)
    if artifact:
        errors.append(f"{task_relative}: proof artifact `{artifact.group(0).strip()}` outside an identified region")
    keywords = generate._THEOREM_SCAN.findall(outside)
    if keywords != ["THEOREM"] * len(unit_ids):
        errors.append(f"{task_relative}: expected {len(unit_ids)} THEOREM statement(s), found {keywords}")
    for _task_id, statement in statements:
        if statement not in outside:
            errors.append(f"{task_relative}: a recorded statement is missing from the emitted task")
            break

    tail_error = _module_tail_error(task_relative, task_text)
    if tail_error:
        errors.append(tail_error)

    for relative in entry["context"]:
        text = (output_root / relative).read_text(encoding="utf-8")
        tail_error = _module_tail_error(relative, text)
        if tail_error:
            errors.append(tail_error)
        stripped = generate.strip_comments(text)
        leak = generate._PROOF_ARTIFACT_SCAN.search(stripped)
        if leak:
            errors.append(f"{relative}: read-only context contains proof artifact `{leak.group(0).strip()}`")
    return errors


def sany_check_module_task(task_id: str, context: Sequence[str], output_root: Path) -> str | None:
    """SANY-check one emitted module task; return the failure text, or None.

    The task and its read-only layers are copied flat into a scratch directory,
    which is how the runner presents them, so a task that only parses because of
    the suite's directory layout fails here.
    """

    with tempfile.TemporaryDirectory() as scratch:
        workspace = Path(scratch)
        shutil.copyfile(output_root / task_id, workspace / PurePosixPath(task_id).name)
        for relative in context:
            shutil.copyfile(output_root / relative, workspace / PurePosixPath(relative).name)
        try:
            generate.dump_sany(str(workspace / PurePosixPath(task_id).name))
        except RuntimeError as exc:
            detail = [line for line in str(exc).splitlines() if line.strip()]
            return detail[-1][:200] if detail else "SANY rejected the module task"
    return None


def _assert_writable_output(output_root: Path, corpus_dir: Path) -> None:
    """Refuse to emit into the 244-task corpus, which this generator only reads."""

    corpus = corpus_dir.resolve()
    output = output_root.resolve()
    if output == corpus or corpus in output.parents or output in corpus.parents:
        raise ModuleTaskError(f"module tasks may not be written into the corpus tree: {output_root}")


def _assert_partial_run_is_safe(output_root: Path, only: Sequence[str] | None) -> None:
    """Refuse to reduce a complete suite's manifest to a one-module spot check.

    A ``--spec`` run writes the manifest like any other, so aimed at a shipped
    suite it would leave 108 modules of files that no entry names. Emitting a
    partial suite is only safe where no complete one already stands.
    """

    if only is None:
        return
    manifest_path = output_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if existing.get("complete") is True:
        raise ModuleTaskError(
            f"{output_root} already holds a complete suite; emit a partial run into a separate --output-root"
        )


def generate_module_tasks(
    *,
    corpus_dir: Path = CORPUS_DIR,
    source_root: Path = SOURCE_ROOT,
    output_root: Path = OUTPUT_DIR,
    only: Sequence[str] | None = None,
    audit: StringIO | None = None,
    validate: bool = True,
) -> dict:
    """Emit every module task and return the versioned manifest."""

    audit = audit if audit is not None else StringIO()
    corpus_manifest_path = corpus_dir / MANIFEST_FILENAME
    _assert_writable_output(output_root, corpus_dir)
    _assert_partial_run_is_safe(output_root, only)
    corpus_bytes = corpus_manifest_path.read_bytes()
    grouped = group_targets_by_specification(json.loads(corpus_bytes.decode("utf-8")))
    if only is None:
        selected = grouped
    else:
        unknown = sorted(set(only) - set(grouped))
        if unknown:
            raise ModuleTaskError(f"no corpus task belongs to specification(s): {unknown}")
        selected = {spec_id: grouped[spec_id] for spec_id in sorted(set(only))}

    tasks: dict[str, dict] = {}
    rejected: list[tuple[str, str]] = []
    for spec_id, task_keys in selected.items():
        entry = emit_module_task(spec_id, task_keys, source_root=source_root, output_root=output_root, audit=audit)
        validate_module_task_spec_data(entry["spec"])
        statements = _read_statements(entry, output_root)
        for message in check_module_task(entry, statements, output_root):
            audit.write(f"[audit] {message}\n")
            rejected.append((spec_id, message))
        if validate:
            failure = sany_check_module_task(spec_id, entry["context"], output_root)
            if failure is not None:
                message = f"emitted module task is not SANY-valid -- {failure}"
                audit.write(f"[audit] {spec_id}: {message}\n")
                rejected.append((spec_id, message))
        tasks[spec_id] = entry

    if rejected:
        raise ModuleTaskError(
            f"{len(rejected)} module task validation error(s): "
            + "; ".join(f"{spec_id} ({reason})" for spec_id, reason in rejected[:5])
        )

    document = {
        "format_version": MODULE_TASK_FORMAT_VERSION,
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "complete": only is None,
        "module_tasks": [tasks[spec_id] for spec_id in sorted(tasks)],
    }
    _write(output_root / MANIFEST_FILENAME, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return document


def _read_statements(entry: Mapping, output_root: Path) -> list[tuple[str, str]]:
    """Statements as the emitted task actually carries them.

    Read back rather than remembered, so a digest can only agree with the
    manifest when the bytes on disk do.
    """

    spec = entry["spec"]
    unit_ids = [unit["task_id"] for unit in spec["proof_units"]]
    text = (output_root / spec["task_id"]).read_text(encoding="utf-8")
    regions = parse_module_task_regions(text, unit_ids)
    lines = text.splitlines(keepends=True)
    statements: list[tuple[str, str]] = []
    # ``line_bounds`` are inclusive one-based body bounds, so each value equals
    # the zero-based index of the marker line just outside that body. A unit's
    # statement is everything between the preceding region's closing marker and
    # its own opening marker.
    cursor = regions.helper_line_bounds[1] + 1
    for proof in regions.proofs:
        statements.append((proof.task_id, "".join(lines[cursor : proof.line_bounds[0] - 2]).strip()))
        cursor = proof.line_bounds[1] + 1
    return statements


def expected_suite_files(document: Mapping) -> set[str]:
    """Every relative path the manifest claims the suite contains."""

    files = {MANIFEST_FILENAME}
    for entry in document["module_tasks"]:
        files.add(entry["spec"]["task_id"])
        files.update(entry["context"])
    return files


def verify_module_tasks(
    *,
    output_root: Path = OUTPUT_DIR,
    corpus_dir: Path = CORPUS_DIR,
    source_root: Path = SOURCE_ROOT,
    validate: bool = True,
) -> list[str]:
    """Check a shipped suite against the corpus and the source, and report.

    Nothing here trusts the shipped manifest. The expected grouping is derived
    from the corpus, the expected bytes from a regeneration into a scratch tree,
    and the shipped tree is compared in both directions, so an edited task, a
    stale digest, a dropped proof unit, or an extra file that no manifest entry
    names is all a reported error.
    """

    errors: list[str] = []
    manifest_path = output_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return [f"{MANIFEST_FILENAME} is missing from {output_root}"]
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{MANIFEST_FILENAME} is not valid JSON: {exc}"]

    if document.get("format_version") != MODULE_TASK_FORMAT_VERSION:
        errors.append(f"manifest format_version is {document.get('format_version')!r}")
    if document.get("complete") is not True:
        errors.append("manifest does not claim a complete suite")

    corpus_bytes = (corpus_dir / MANIFEST_FILENAME).read_bytes()
    if document.get("corpus_sha256") != hashlib.sha256(corpus_bytes).hexdigest():
        errors.append("manifest corpus_sha256 does not match the current proof-from-scratch corpus")

    grouped = group_targets_by_specification(json.loads(corpus_bytes.decode("utf-8")))
    entries = document.get("module_tasks")
    if not isinstance(entries, list):
        return errors + ["manifest module_tasks is not a list"]

    shipped_units: list[str] = []
    for entry in entries:
        try:
            spec = validate_module_task_spec_data(entry["spec"])
        except (ModuleTaskContractError, KeyError, TypeError) as exc:
            errors.append(f"manifest entry is not a valid module task spec: {exc}")
            continue
        shipped_units.extend(spec.proof_unit_ids)
        expected_units = grouped.get(spec.task_id)
        if expected_units is None:
            errors.append(f"{spec.task_id}: no corpus task belongs to this specification")
            continue
        if sorted(spec.proof_unit_ids) != expected_units:
            errors.append(f"{spec.task_id}: proof units do not match the corpus tasks for this specification")
        source_path = source_root / spec.task_id
        if not source_path.is_file():
            errors.append(f"{spec.task_id}: source specification is missing")
        elif hashlib.sha256(source_path.read_bytes()).hexdigest() != spec.source_sha256:
            errors.append(f"{spec.task_id}: source_sha256 does not match the current source")

    shipped_specs = sorted({entry["spec"]["task_id"] for entry in entries if isinstance(entry.get("spec"), dict)})
    if shipped_specs != sorted(grouped):
        errors.append(f"suite covers {len(shipped_specs)} specification(s); the corpus has {len(grouped)}")
    corpus_units = sorted(key for keys in grouped.values() for key in keys)
    if sorted(shipped_units) != corpus_units:
        errors.append(f"suite covers {len(shipped_units)} proof unit(s); the corpus has {len(corpus_units)}")
    if len(set(shipped_units)) != len(shipped_units):
        errors.append("suite repeats a proof unit ID across module tasks")

    expected_files = expected_suite_files(document)
    actual_files = {path.relative_to(output_root).as_posix() for path in output_root.rglob("*") if path.is_file()}
    for extra in sorted(actual_files - expected_files):
        errors.append(f"{extra}: file in the suite that no manifest entry names")
    for missing in sorted(expected_files - actual_files):
        errors.append(f"{missing}: file named by the manifest is missing")

    with tempfile.TemporaryDirectory() as scratch:
        rebuilt_root = Path(scratch) / "suite"
        rebuilt = generate_module_tasks(
            corpus_dir=corpus_dir,
            source_root=source_root,
            output_root=rebuilt_root,
            audit=StringIO(),
            validate=validate,
        )
        if rebuilt != document:
            errors.append("regeneration does not reproduce the shipped manifest")
        for relative in sorted(expected_suite_files(rebuilt)):
            shipped = output_root / relative
            if not shipped.is_file():
                continue
            if shipped.read_bytes() != (rebuilt_root / relative).read_bytes():
                errors.append(f"{relative}: shipped bytes differ from a regeneration")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", default=str(CORPUS_DIR))
    parser.add_argument("--source-root", default=str(SOURCE_ROOT))
    parser.add_argument("--output-root", default=str(OUTPUT_DIR))
    parser.add_argument("--spec", action="append", dest="specs", help="emit only this spec_id (repeatable)")
    parser.add_argument("--no-validate", action="store_true", help="skip the SANY check on each emitted task")
    parser.add_argument("--verify", action="store_true", help="check the suite at --output-root instead of writing it")
    args = parser.parse_args(argv)

    if args.verify:
        errors = verify_module_tasks(
            output_root=Path(args.output_root),
            corpus_dir=Path(args.corpus_dir),
            source_root=Path(args.source_root),
            validate=not args.no_validate,
        )
        for error in errors:
            print(f"[error] {error}", file=sys.stderr)
        print(f"{'FAILED' if errors else 'OK'}: {args.output_root} ({len(errors)} error(s))")
        return 1 if errors else 0

    audit = StringIO()
    document = generate_module_tasks(
        corpus_dir=Path(args.corpus_dir),
        source_root=Path(args.source_root),
        output_root=Path(args.output_root),
        only=args.specs,
        audit=audit,
        validate=not args.no_validate,
    )
    units = sum(len(task["spec"]["proof_units"]) for task in document["module_tasks"])
    print(f"generated {len(document['module_tasks'])} module task(s), {units} proof unit(s) -> {args.output_root}")
    if audit.getvalue():
        print(audit.getvalue(), end="", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

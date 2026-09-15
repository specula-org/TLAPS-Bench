#!/usr/bin/env python3
"""Generate proof-from-scratch benchmarks from source .tla files.

Core principle (strict mode, from src/dataset/proof_from_scratch/design.md, Issue #1/#3):
  Keep only what is needed to STATE the top-level theorem; delete every
  other definition, all other theorems/lemmas, all proof content, and all
  comments. The AI must rediscover the inductive invariant and design the
  proof structure from scratch.

For each top-level THEOREM in source/<Module>/<File>.tla we emit one
file benchmark/proof-from-scratch/<Module>/<File>_<TheoremName>.tla in which:
  - The module + EXTENDS + CONSTANT/VARIABLE/ASSUME/AXIOM are kept.
  - Only the `==` definitions / named INSTANCE bindings reachable from the
    target theorem's STATEMENT (transitive closure over the definition-
    dependency graph, seeded by the statement + kept ASSUME/AXIOM) survive;
    unreachable ones (inductive invariants like `Inv`/`TypeOK`, helper
    operators like `SafeAt`/`MsgInv`) are deleted as proof artifacts.
    When the goal IS an invariant (`Spec => []Inv`), that invariant is in
    the statement, so it is reachable and kept — the goal can't be hidden.
  - All other THEOREMs and all LEMMAs (statement + proof) are deleted.
  - The target THEOREM's proof body is replaced with `PROOF OBVIOUS`.
  - All comments (`\\*` line, `(* … *)` block) are stripped.
  - Dep .tla files (EXTENDS, or kept INSTANCEs) are copied alongside with
    their proofs stripped (`PROOF OMITTED`) and comments stripped.

Top-level selection (OR rule, applied to THEOREM-keyword decls only):
  1. Unnamed rule: T has no name (TLA+ syntax can't reference it → standalone).
  2. Shape rule:   statement is `<S> => ...` where `<S>` is a spec formula.
  3. Graph rule:   T has a name and no other theorem references it.

Post-selection filters:
  A. Manual-proof filter: drop candidates whose source has no structured
     TLAPS proof (bare statement / PROOF OMITTED / PROOF OBVIOUS). proof-from-scratch's
     contract is "AI writes a proof, compared against a human reference",
     so candidates without ground truth are out of scope for now.
     Known cost: PaxosTuple.tla:79 `Spec => V!Spec` (proof lives in the
     companion file PaxosProof.tla) and PConProof.tla:520
     `Spec => [](chosen = V!chosen)` (model-checked by TLC, no TLAPS
     proof written). Both are genuine main theorems; they can be revived
     later in a separate "no-reference-proof" track if we ever want it.
  A'. Known-false filter: drop a top-level theorem whose goal TLC has shown
     to be FALSE, even though the source "proves" it via an OMITTED sub-step
     that papers over the gap (e.g. PaxosProof StructOK3). A false goal admits
     no honest proof, so it cannot be a benchmark. This is now the ONLY reason
     an OMITTED-sub-step theorem is dropped: every other such theorem is a
     published/verified result and is KEPT as a (hard) from-scratch benchmark,
     since proof-from-scratch grades by tlapm rather than by the human reference proof.
     See KNOWN_FALSE_TARGETS for the per-target TLC evidence.
  B. Within-file dedup: collapse exact-text-duplicate statements. Catches
     Peterson.tla L124/L134/L183 — three identical
     `THEOREM Spec => []MutualExclusion` decls the author wrote to
     showcase different prover backends; as proof-from-scratch prompts they are
     indistinguishable, so keep the first by line.
  C. Cross-directory dedup: across all output directories, collapse
     byte-identical target benchmarks. Catches the seven `Sets_*.tla`
     pairs that arise because source/Consensus/Sets.tla and
     source/Data/Sets.tla are near-identical copies of the same
     utility library (only two prover-hint lines differ, both inside
     proof bodies that proof-from-scratch strips, so the emitted proof-from-scratch prompts are
     byte-identical). When duplicates are detected, the copy under
     `Data/` is kept (utility libraries are at home in `Data/`); the
     copies in other directories are removed and the audit log records
     each drop. Dep files (e.g. `Sets.tla` itself, copied alongside
     targets) are not subject to this pass — they may legitimately need
     to live in multiple directories because other targets in those
     directories depend on them.

Spec formulas are identified by SANY-AST shape (see src/dataset/sany-dump/),
not by name match. The audit log flags non-`Spec` names, zero specs,
multiple specs, multiple top-level theorems, unnamed top-levels, and
every drop made by filters A, B, and C.

Layered layout (`--layered`, Issue #64)
---------------------------------------
By default everything above lands in ONE editable module, so an agent can make
the theorem easier without proving the original obligation (redefine the target
property, weaken fairness). `--layered` instead splits each task by ownership so
the obligation is immutable by construction:

    <base>Model.tla    declarations, assumptions, state machine, Spec, fairness
    <task>Defs.tla     EXTENDS the model; only this target's given definitions
    <task>.tla         EXTENDS its Defs; the theorem, the markers, the proof

Only `<task>.tla` is editable, and within it only the two marked regions:

    \\* BEGIN AGENT HELPERS / \\* END AGENT HELPERS   fresh helper defs + lemmas
    \\* BEGIN AGENT PROOF   / \\* END AGENT PROOF     the proof

A suite-level `manifest.json` maps each task to the exact read-only modules
assigned to it, so the evaluator never infers context by copying siblings and
one task cannot inherit another task's target definitions. Each manifest entry
also records the originating source specification. The marker strings and
manifest schema are the contract in src/common/proof_from_scratch_contract.py;
the two must stay byte-compatible.

Only spec-goal targets extend the shared model; a pure lemma target keeps a
self-contained Defs layer with just the declarations it uses.

Agents may add named instances of approved official proof libraries inside the
helper region. The evaluator validates those imports against the frozen library
catalog for the run.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SOURCE_ROOT = os.path.join(PROJECT_ROOT, "source")
BENCHMARK_DIR = os.path.join(PROJECT_ROOT, "benchmark", "proof-from-scratch")
SANY_DUMP = os.path.join(PROJECT_ROOT, "src", "dataset", "sany-dump", "run.sh")

# Reuse proof-completion's proof-stripping logic for dependency .tla copies.
from dataset.proof_completion.generate import (  # noqa: E402
    STDLIB_MODULES,
    parse_extends,
    parse_instances,
    parse_theorems,
    strip_all_proofs,
)
from dataset.sany_audit import gate as sany_gate  # noqa: E402
from dataset.sany_audit import is_task_file  # noqa: E402
from dataset.specification_identity import source_spec_id  # noqa: E402
from dataset.triviality_audit import gate as triviality_gate  # noqa: E402

KEYWORD_PATTERN = re.compile(r"^\s*(THEOREM|LEMMA|AXIOM|COROLLARY|PROPOSITION)\b")
MODULE_HEADER = re.compile(r"^(-+\s*MODULE\s+)(\w+)(\s*-+)")

# Top-level theorems whose goal is actually FALSE — TLC finds a counterexample —
# even though the source "proves" them with an OMITTED sub-step that papers over
# the gap. A false goal admits no honest proof (an agent can only pass it by
# cheating), so it must never become a benchmark. Keyed by
# (source-module basename, target name); each entry is justified by a TLC run.
# This is the *only* reason filter A' now drops an OMITTED-sub-step theorem —
# every other such theorem is a published, verified result and is kept.
KNOWN_FALSE_TARGETS = {
    ("PaxosProof", "StructOK3"): "TLC counterexample: PaxosTuple.tla Phase2a's uniqueness guard tests "
    "m[3] (the value field) instead of m[2] (the ballot), so a single ballot "
    "can carry two distinct 2a values, violating StructOK3's one-value-per-"
    "ballot conjunct. The author commented StructOK3 out of the proven "
    "StructOK and left its inductive step PROOF OMITTED.",
}


def dump_sany(tla_path):
    res = subprocess.run([SANY_DUMP, tla_path], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"SANY dump failed for {tla_path}:\n--stdout--\n{res.stdout}\n--stderr--\n{res.stderr}")
    # SANY's PlusCal label-adder and parse-error reporter print to System.out
    # from inside frontEndMain. Skip past the sentinel marker we print in
    # DumpSemantics.java to find the actual JSON.
    marker = "--- BEGIN SANY-DUMP JSON ---"
    idx = res.stdout.find(marker)
    if idx < 0:
        raise RuntimeError(f"SANY produced no JSON for {tla_path}:\n{res.stdout!r}\nstderr:\n{res.stderr}")
    return json.loads(res.stdout[idx + len(marker) :])


def determine_keyword(lines, line_start):
    """Read source at line_start (1-indexed) and return the leading keyword."""
    if not (1 <= line_start <= len(lines)):
        return None
    m = KEYWORD_PATTERN.match(lines[line_start - 1])
    return m.group(1) if m else None


def find_top_level(theorems, spec_formulas):
    """Top-level iff any of:
      - unnamed: T has no name (TLA+ syntax can't reference it → it can't
        be a helper; it must be a standalone claim by the author's intent).
      - shape:   T's statement is `<S> => ...` where <S> is a spec formula.
      - graph:   T has a name and no other theorem references it.

    Returns (theorem_dict, by_unnamed, by_shape, by_graph) tuples.
    """
    incoming = {}
    for t in theorems:
        if t["name"]:
            incoming.setdefault(t["name"], set())
    for t in theorems:
        src_name = t["name"] or f"__unnamed_{t['loc']['line_start']}"
        for ref in t["references"]:
            if ref in incoming:
                incoming[ref].add(src_name)

    out = []
    for t in theorems:
        unnamed_match = not t["name"]
        shape_match = t["shape"]["kind"] == "implies" and t["shape"]["lhs_spec_ref"] in spec_formulas
        graph_match = not unnamed_match and len(incoming.get(t["name"], set())) == 0
        if unnamed_match or shape_match or graph_match:
            out.append((t, unnamed_match, shape_match, graph_match))
    return out


def _statement_text(target_thm, source_lines):
    """Extract the statement portion of a THEOREM (everything before its proof body).

    SANY's `loc` for a TheoremNode spans the whole `THEOREM ... <proof>` range,
    so we trim off the proof using `proof_loc.line_start - 1`. If there is no
    proof, the statement runs to `loc.line_end`. Returned text is the joined
    source lines, stripped of surrounding whitespace.
    """
    loc = target_thm["loc"]
    ploc = target_thm.get("proof_loc")
    end_line = ploc["line_start"] - 1 if ploc and ploc.get("line_start", -1) > 0 else loc["line_end"]
    return "".join(source_lines[loc["line_start"] - 1 : end_line]).strip()


def _has_manual_proof(target_thm, source_lines):
    """Return True iff the source has a structured TLAPS proof body.

    Returns False for:
      - no proof body at all (SANY emits no `proof_loc`, e.g. PConProof.tla L505)
      - `PROOF OMITTED` / `OMITTED` placeholder
      - `PROOF OBVIOUS` / `OBVIOUS` placeholder

    All other proof bodies (a `<N>` proof tree, a `BY ...` leaf, a `PROOF BY`
    line, etc.) count as manual proofs.
    """
    ploc = target_thm.get("proof_loc")
    if not (ploc and ploc.get("line_start", -1) > 0):
        return False
    body = "".join(source_lines[ploc["line_start"] - 1 : ploc["line_end"]]).strip()
    if body.startswith("PROOF"):
        body = body[5:].lstrip()
    return body not in ("OMITTED", "OBVIOUS")


def _proof_has_omitted_substep(target_thm, source_lines):
    """Return True iff the source proof admits a sub-step with OMITTED.

    A multi-step proof whose top level is structured but which contains an
    `OMITTED` leaf anywhere (e.g. PaxosProof.tla's `THEOREM Spec => []StructOK3`,
    whose inductive step `<1>2` is `PROOF OMITTED`) was NEVER actually verified
    by tlapm — the admitted step papers over a gap, and in the StructOK3 case
    the statement is in fact false (TLC finds a counterexample). Such theorems
    must not become benchmarks: there is no ground truth that the goal is even
    provable, so an honest agent that reports "unprovable" gets marked wrong
    while an unsound proof gets marked right.

    `_has_manual_proof` already rejects a proof that is *entirely* OMITTED; this
    catches the subtler case of an OMITTED leaf inside an otherwise-structured
    proof. Matches the OMITTED keyword on word boundaries.
    """
    ploc = target_thm.get("proof_loc")
    if not (ploc and ploc.get("line_start", -1) > 0):
        return False
    body = "".join(source_lines[ploc["line_start"] - 1 : ploc["line_end"]])
    return re.search(r"\bOMITTED\b", body) is not None


def target_theorem_name(theorem):
    """Pick a name string used for the benchmark filename.

    Returns (name, was_sanitized). If the RHS primary name carries an INSTANCE
    namespace separator `!` (e.g. `V!Spec`), it is replaced with `_` because
    `!` is not legal in a TLA+ module identifier.
    """
    if theorem["name"]:
        return theorem["name"], False
    rhs = theorem["shape"].get("rhs_primary_name")
    if rhs:
        sanitized = rhs.replace("!", "_")
        return sanitized, sanitized != rhs
    return f"line{theorem['loc']['line_start']}", False


def compute_reachable(dump, target_thm):
    """Names of `==` definitions / INSTANCE bindings needed to STATE the target.

    Seeds from the target theorem's statement references plus every kept
    ASSUME/AXIOM (the model's hypotheses), then takes the transitive closure
    over the definition-dependency graph (operator + instance `references`
    emitted by the SANY dumper). Everything NOT in the returned set is a proof
    artifact (inductive invariant, helper lemma/operator) and is stripped.

    Note the target's *proof* references are deliberately excluded: the proof is
    replaced by `PROOF OBVIOUS`, so any definition used only inside it is gone.
    For `Spec => []Inv` targets, `Inv` is in the statement, so it (and its
    decomposition) is reachable and kept — the goal cannot be hidden.
    """
    adj = {}
    for o in dump["operators"]:
        adj.setdefault(o["name"], set()).update(o.get("references", []))
    for i in dump["instances"]:
        if i.get("name"):
            adj.setdefault(i["name"], set()).update(i.get("references", []))

    seed = set(target_thm.get("statement_references", []))
    for a in dump["assumes"]:
        seed.update(a.get("references", []))

    reachable = set()
    stack = list(seed)
    while stack:
        name = stack.pop()
        if name in reachable:
            continue
        reachable.add(name)
        stack.extend(r for r in adj.get(name, ()) if r not in reachable)
    return reachable


def strip_comments(text):
    """Remove every TLA+ comment from `text`, preserving line structure.

    Handles `\\*` line comments and nested `(* ... *)` block comments, and skips
    comment markers that appear inside string literals. Newlines are always
    preserved so source line geometry (and the `---- MODULE` / `====` lines)
    survives. Stripping comments is what removes residual strategy hints — e.g.
    EWD840's "Dijkstra's invariant" banner and the trailing "here is a more
    detailed, hierarchical proof" note left over from a deleted proof.
    """
    out = []
    i = 0
    n = len(text)
    depth = 0  # block-comment nesting depth
    in_line = False  # inside a \* line comment
    in_str = False  # inside a "..." string literal
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
        elif depth > 0:
            if c == "(" and nxt == "*":
                depth += 1
                i += 2
            elif c == "*" and nxt == ")":
                depth -= 1
                i += 2
            elif c == "\n":
                out.append(c)  # keep blank line where the comment sat
                i += 1
            else:
                i += 1
        elif in_str:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
            else:
                if c == '"':
                    in_str = False
                i += 1
        else:
            if c == "\\" and nxt == "*":
                in_line = True
                i += 2
            elif c == "(" and nxt == "*":
                depth = 1
                i += 2
            elif c == '"':
                in_str = True
                out.append(c)
                i += 1
            else:
                out.append(c)
                i += 1
    return "".join(out)


def apply_edits(lines, edits):
    """Apply (start_line, end_line, replacement_text) edits.

    Lines are 1-indexed, inclusive. Edits must not overlap. The replacement
    text replaces the entire range; lines outside any range are emitted
    unchanged.
    """
    edits = sorted(edits, key=lambda e: e[0])
    for i in range(len(edits) - 1):
        if edits[i][1] >= edits[i + 1][0]:
            raise ValueError(f"Overlapping edits: {edits[i]} and {edits[i + 1]}")
    out = []
    cursor = 1
    for start, end, repl in edits:
        if start > cursor:
            out.extend(lines[cursor - 1 : start - 1])
        if repl:
            out.append(repl)
        cursor = end + 1
    if cursor <= len(lines):
        out.extend(lines[cursor - 1 :])
    return "".join(out)


def build_benchmark(source_lines, dump, target_thm, benchmark_module_name, reachable):
    """Build the benchmark .tla text by editing source_lines.

    Strict proof-from-scratch (per Issue #1 / #3): keep only the model + target property + the
    bare THEOREM statement; strip every proof artifact. Concretely we:
      - replace the target theorem's proof body with `PROOF OBVIOUS`,
      - delete all other THEOREM/LEMMA declarations,
      - delete every `==` definition / named INSTANCE not in `reachable`
        (the closure of definitions needed to state the goal) — this is what
        removes the inductive invariant `Inv`, `TypeOK`, `MsgInv`, `SafeAt`, …,
      - strip all comments, and tidy the resulting blank-line runs.
    """
    edits = []
    target_id = id(target_thm)
    for t in dump["theorems"]:
        if id(t) == target_id:
            ploc = t.get("proof_loc")
            # Filter A in process_file guarantees the target has a real proof body.
            assert ploc and ploc.get("line_start", -1) > 0, (
                f"build_benchmark invoked on target without proof body at "
                f"{source_lines[t['loc']['line_start'] - 1].rstrip()!r}; "
                "should have been filtered upstream."
            )
            edits.append((ploc["line_start"], ploc["line_end"], "PROOF OBVIOUS\n"))
        else:
            # Delete other theorems/lemmas entirely.
            loc = t["loc"]
            edits.append((loc["line_start"], loc["line_end"], ""))

    # Delete operator definitions not reachable from the target statement —
    # the inductive invariants and helper operators the AI must rediscover.
    for o in dump["operators"]:
        if o["name"] not in reachable:
            loc = o["loc"]
            edits.append((loc["line_start"], loc["line_end"], ""))
    # Delete named INSTANCE bindings that aren't needed to state the goal.
    # Unnamed (bare) INSTANCEs import names into scope unqualified and can't be
    # tracked by reachability, so they are always kept.
    for inst in dump["instances"]:
        if inst.get("name") and inst["name"] not in reachable:
            loc = inst["loc"]
            edits.append((loc["line_start"], loc["line_end"], ""))

    text = apply_edits(source_lines, edits)
    text = strip_comments(text)

    # Rename module header to the benchmark module name.
    out_lines = text.splitlines(keepends=True)
    for i, line in enumerate(out_lines):
        m = MODULE_HEADER.match(line)
        if m:
            out_lines[i] = f"{m.group(1)}{benchmark_module_name}{m.group(3)}\n"
            break
    text = "".join(out_lines)

    # Collapse the blank-line runs left behind by deleted defs / stripped
    # comments down to a single blank line.
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    return text


def _gather_local_deps(start_mods, src_dir):
    """Transitively collect local-module deps (EXTENDS + INSTANCE) starting
    from `start_mods`. Standard-library modules are excluded.

    Returns a list of (module_name, .tla path) pairs in BFS discovery order.
    """
    out = []
    seen = set()
    queue = list(start_mods)
    while queue:
        mod = queue.pop(0)
        if not mod or mod in seen or mod in STDLIB_MODULES:
            continue
        dep_path = os.path.join(src_dir, f"{mod}.tla")
        if not os.path.isfile(dep_path):
            continue
        seen.add(mod)
        out.append((mod, dep_path))
        with open(dep_path, encoding="utf-8") as f:
            dep_content = f.read()
        for ext in parse_extends(dep_content):
            if ext not in STDLIB_MODULES and ext not in seen:
                queue.append(ext)
        for _, inst_mod in parse_instances(dep_content):
            if inst_mod not in seen:
                queue.append(inst_mod)
    return out


def copy_deps(dump, source_path, out_dir, reachable):
    """Copy every local-module dep of `source_path` into `out_dir`, with all
    proofs stripped to PROOF OMITTED. Covers both EXTENDS (e.g. EuclidEx -> GCD)
    and INSTANCE (e.g. Paxos -> Consensus) references, transitively.

    EXTENDS deps are always copied (the module is unconditionally in scope).
    A *named* INSTANCE's dep is copied only if that instance binding survived
    reachability stripping — e.g. Consensus.tla is needed by `Spec => C!Spec`
    (Refinement) but not by `Spec => []Consistency` (Consistent), which drops
    the `C` binding. Unnamed INSTANCEs are always copied (always kept).

    Returns the list of copied basenames.
    """
    src_dir = os.path.dirname(os.path.abspath(source_path))
    direct_deps = []
    for ext in dump.get("extends", []):
        if ext not in STDLIB_MODULES:
            direct_deps.append(ext)
    for inst in dump.get("instances", []):
        mod = inst.get("module")
        if not mod:
            continue
        name = inst.get("name")
        if name and name not in reachable:
            continue  # instance was stripped from the benchmark
        direct_deps.append(mod)

    copied = []
    for _mod, dep_path in _gather_local_deps(direct_deps, src_dir):
        with open(dep_path, encoding="utf-8") as f:
            dep_text = f.read()
        dep_lines = dep_text.split("\n")
        dep_thms = parse_theorems(dep_lines)
        dest = os.path.join(out_dir, os.path.basename(dep_path))
        if dep_thms:
            dep_text = strip_all_proofs(dep_lines, dep_thms)
        # Scrub comments here too: a dependency module the AI can read (its
        # THEOREM statements stay, only proofs become OMITTED) would otherwise
        # leak strategy prose just like the main file.
        dep_text = strip_comments(dep_text)
        dep_text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", dep_text)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(dep_text if dep_text.endswith("\n") else dep_text + "\n")
        copied.append(os.path.basename(dep_path))
    return copied


def layered_dep_paths(dump, source_path, reachable):
    """Local-module dependencies a task needs, as (module, path) pairs.

    Same edge set as `copy_deps`: every non-stdlib EXTENDS, plus the module
    behind each INSTANCE whose binding survived reachability stripping.
    """
    src_dir = os.path.dirname(os.path.abspath(source_path))
    direct = [e for e in dump.get("extends", []) if e not in STDLIB_MODULES]
    for inst in dump.get("instances", []):
        mod = inst.get("module")
        if not mod:
            continue
        if inst.get("name") and inst["name"] not in reachable:
            continue
        direct.append(mod)
    return _gather_local_deps(direct, src_dir)


def copy_deps_layered(dump, source_path, out_dir, reachable):
    """Like `copy_deps`, but DELETES every THEOREM/LEMMA from the dependency.

    `copy_deps` admits a dependency's proofs as `PROOF OMITTED` and keeps the
    statements, which is a cheat vector: an OMITTED theorem is a usable fact, so
    a task whose goal restates one is discharged by citing it. Returns the
    copied basenames.
    """
    copied = []
    for _mod, dep_path in layered_dep_paths(dump, source_path, reachable):
        with open(dep_path, encoding="utf-8") as f:
            dep_lines = f.read().split("\n")
        drop = set()
        for thm in parse_theorems(dep_lines):
            end = thm.proof_end if thm.proof_end is not None else thm.statement_end
            drop.update(range(thm.statement_start, end + 1))
        dep_text = "\n".join(line for i, line in enumerate(dep_lines) if i not in drop)
        dep_text = _strip_module_directives(strip_comments(dep_text))
        dep_text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", dep_text)
        dest = os.path.join(out_dir, os.path.basename(dep_path))
        with open(dest, "w", encoding="utf-8") as f:
            f.write(dep_text if dep_text.endswith("\n") else dep_text + "\n")
        copied.append(os.path.basename(dep_path))
    return copied


_IDENTIFIER = re.compile(r"(?<!\\)\b[A-Za-z_]\w*\b")


def _text_without_strings(text):
    """Copy of ``text`` with string literals blanked so ``C!Spec`` is not read from quotes."""

    out = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(" ")
            if char == "\\" and index + 1 < length:
                out.append(" ")
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
        elif char == '"':
            in_string = True
            out.append(" ")
            index += 1
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _scan_identifiers(text):
    """Bare identifiers mentioned in `text`, including TLA+ subscript forms.

    A stuttering subscript binds the name with a leading underscore —
    `[][Next]_vars` and `WF_vars(p)` both use `vars` — so the raw token is
    `_vars`. Yield the bare name too, or `vars` looks unused and gets pruned
    out of a dependency that still needs it.

    Skip the right-hand name of ``P!Spec``; ``instance_qualified_uses`` seeds it.
    """
    names = set()
    cleaned = _text_without_strings(strip_comments(text))
    for match in _IDENTIFIER.finditer(cleaned):
        previous = match.start() - 1
        while previous >= 0 and cleaned[previous].isspace():
            previous -= 1
        if previous >= 0 and cleaned[previous] == "!":
            continue
        tok = match.group(0)
        names.add(tok)
        if tok.startswith("_") and len(tok) > 1:
            names.add(tok.lstrip("_"))
    return names


def instance_qualified_uses(*texts):
    """``C!Spec`` and ``C(args)!Spec`` uses as ``(instance, name)`` pairs."""

    uses = set()
    for text in texts:
        cleaned = _text_without_strings(strip_comments(text))
        for instance in _IDENTIFIER.finditer(cleaned):
            cursor = instance.end()
            while cursor < len(cleaned) and cleaned[cursor].isspace():
                cursor += 1
            if cursor < len(cleaned) and cleaned[cursor] == "(":
                depth = 1
                cursor += 1
                while cursor < len(cleaned) and depth:
                    if cleaned[cursor] == "(":
                        depth += 1
                    elif cleaned[cursor] == ")":
                        depth -= 1
                    cursor += 1
            while cursor < len(cleaned) and cleaned[cursor].isspace():
                cursor += 1
            if cursor >= len(cleaned) or cleaned[cursor] != "!":
                continue
            cursor += 1
            while cursor < len(cleaned) and cleaned[cursor].isspace():
                cursor += 1
            member = _IDENTIFIER.match(cleaned, cursor)
            if member:
                uses.add((instance.group(), member.group()))
    return uses


def source_defined_names(dump):
    """Operator and named-INSTANCE identifiers that bind in the source module."""

    names = {entry["name"] for entry in dump.get("operators", []) if entry.get("name")}
    names.update(entry["name"] for entry in dump.get("instances", []) if entry.get("name"))
    return names


def source_instance_modules(dump):
    """Named INSTANCE bindings in ``dump``: ``C`` → ``Consensus``."""

    return {
        entry["name"]: entry["module"]
        for entry in dump.get("instances", [])
        if entry.get("name") and entry.get("module")
    }


def source_imported_modules(dump):
    """Local modules whose names are imported unqualified (EXTENDS / unnamed INSTANCE)."""

    imported = [entry for entry in dump.get("extends", []) if entry not in STDLIB_MODULES]
    imported.extend(
        entry["module"] for entry in dump.get("instances", []) if not entry.get("name") and entry.get("module")
    )
    return imported


def prune_dep_module(dep_path, keep_names, audit_writer=None):
    """Text of a dependency module reduced to the definitions in `keep_names`.

    Anything a dependency defines is given to the agent for free, so left whole
    it hands over the original proof's scaffolding (`TypeOK`, `Inv`) that a
    from-scratch task must make the agent rediscover. Declarations and ASSUMEs
    are always kept and every theorem deleted; `keep_names=None` keeps all
    definitions, so a dependency is never silently emptied.
    """
    with open(dep_path, encoding="utf-8") as f:
        dep_lines = f.read().split("\n")

    drop_lines = set()
    for thm in parse_theorems(dep_lines):
        end = thm.proof_end if thm.proof_end is not None else thm.statement_end
        drop_lines.update(range(thm.statement_start, end + 1))

    if keep_names is not None:
        try:
            dep_dump = dump_sany(dep_path)
        except Exception as e:
            if audit_writer:
                audit_writer.write(f"[audit] {os.path.basename(dep_path)}: not dumpable, definitions kept — {e}\n")
            dep_dump = None
        if dep_dump is not None:
            for o in dep_dump["operators"]:
                if o["name"] not in keep_names:
                    drop_lines.update(range(o["loc"]["line_start"] - 1, o["loc"]["line_end"]))

    text = "\n".join(line for i, line in enumerate(dep_lines) if i not in drop_lines)
    text = _strip_module_directives(strip_comments(text))
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)


def _module_name(dump, path):
    return dump.get("module") or os.path.splitext(os.path.basename(path))[0]


def _slice(lines, loc):
    if not loc:
        return ""
    start = loc.get("line_start", 0)
    end = loc.get("line_end", start)
    if start < 1:
        return ""
    return strip_comments("\n".join(lines[start - 1 : end]))


def dep_keep_names(
    dep_entries,
    seeds,
    audit_writer=None,
    *,
    source_defined=(),
    instance_modules=None,
    qualified_uses=(),
    imported_modules=(),
):
    """Definitions to keep in each dependency, keyed by path.

    The closure is over ``(module, name)`` pairs, not bare names: a local
    ``Inv`` in the task must not keep an unrelated ``Inv`` in ``Consensus.tla``
    just because the identifier matches. Cross-module edges come from EXTENDS,
    unnamed INSTANCE, and ``C!Spec`` / ``C(args)!Spec`` uses.

    The closure still spans the whole group, not each file: dependencies
    reference each other (``PaxosProof`` uses ``chosen`` from a sibling), so
    closing per file prunes a definition another dependency still needs and the
    module stops parsing. Returns ``None`` to mean "keep everything" only when
    a module cannot be dumped at all, since then nothing can be shown unused.
    """
    dumps = []
    for path in dep_entries:
        try:
            dump = dump_sany(path)
        except Exception as e:
            if audit_writer:
                audit_writer.write(f"[audit] {os.path.basename(path)}: not dumpable, group kept whole — {e}\n")
            return None
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        dumps.append((path, dump, lines))

    ops_of = {}
    extends_of = {}
    inst_of = {}
    unnamed_of = {}
    path_of = {}
    for path, dump, _lines in dumps:
        mod = _module_name(dump, path)
        path_of[mod] = path
        ops_of[mod] = {entry["name"] for entry in dump.get("operators", []) if entry.get("name")}
        extends_of[mod] = list(dump.get("extends", []) or [])
        inst_of[mod] = source_instance_modules(dump)
        unnamed_of[mod] = [
            entry["module"] for entry in dump.get("instances", []) if not entry.get("name") and entry.get("module")
        ]

    def resolve(mod, name):
        if name in ops_of.get(mod, ()):
            return (mod, name)
        for ext in extends_of.get(mod, ()):
            if name in ops_of.get(ext, ()):
                return (ext, name)
        for target in unnamed_of.get(mod, ()):
            if name in ops_of.get(target, ()):
                return (target, name)
        return None

    adj = {}
    stack = []
    seen_stack = set()

    def seed_pair(mod, name):
        pair = (mod, name)
        if name in ops_of.get(mod, ()) and pair not in seen_stack:
            seen_stack.add(pair)
            stack.append(pair)

    def seed_resolved(mod, names):
        for name in names:
            pair = resolve(mod, name)
            if pair:
                seed_pair(*pair)

    def seed_qualified(uses, bindings):
        for inst, name in uses:
            target = bindings.get(inst)
            if target:
                seed_pair(target, name)

    source_defined = set(source_defined)
    task_bindings = dict(instance_modules or {})
    imported = [mod for mod in imported_modules if mod in ops_of]
    # INSTANCE names used as C!Spec often live in an EXTENDS'd dependency
    # (PaxosProof's V is declared in PaxosTuple), not in the source module.
    group_bindings = {}
    for inst_map in inst_of.values():
        group_bindings.update(inst_map)
    group_bindings.update(task_bindings)

    seed_qualified(qualified_uses, group_bindings)
    for name in seeds:
        if name in source_defined:
            continue
        preferred = [mod for mod in imported if name in ops_of[mod]]
        candidates = preferred or [mod for mod, ops in ops_of.items() if name in ops]
        for mod in candidates:
            seed_pair(mod, name)

    for path, dump, lines in dumps:
        mod = _module_name(dump, path)
        bindings = inst_of[mod]
        for operator in dump.get("operators", []):
            op_name = operator.get("name")
            if not op_name:
                continue
            body = _slice(lines, operator.get("loc"))
            refs = set(operator.get("references", [])) | _scan_identifiers(body)
            neighbors = adj.setdefault((mod, op_name), set())
            for ref in refs:
                pair = resolve(mod, ref)
                if pair:
                    neighbors.add(pair)
            for inst, name in instance_qualified_uses(body):
                target = bindings.get(inst)
                if target and name in ops_of.get(target, ()):
                    neighbors.add((target, name))
        for inst in dump.get("instances", []):
            # An INSTANCE line is never deleted. SANY's references are the local
            # WITH / implicit substitutions (`chosen` in `C == INSTANCE Consensus`),
            # not the instantiated module's unused operators.
            live = set(inst.get("references", []))
            live |= _scan_identifiers(_slice(lines, inst.get("loc")))
            seed_resolved(mod, live)
            seed_qualified(instance_qualified_uses(_slice(lines, inst.get("loc"))), bindings)
        for assume in dump.get("assumes", []):
            live = set(assume.get("references", []))
            live |= _scan_identifiers(_slice(lines, assume.get("loc")))
            seed_resolved(mod, live)
            seed_qualified(instance_qualified_uses(_slice(lines, assume.get("loc"))), bindings)

    kept_pairs = set()
    while stack:
        pair = stack.pop()
        if pair in kept_pairs:
            continue
        kept_pairs.add(pair)
        for neighbor in adj.get(pair, ()):
            if neighbor not in kept_pairs:
                stack.append(neighbor)

    keep_by_path = {path: set() for path, _dump, _lines in dumps}
    for mod, name in kept_pairs:
        path = path_of.get(mod)
        if path is not None:
            keep_by_path[path].add(name)
    return keep_by_path


def prune_dep_text(dep_path, keep_by_path, audit_writer=None):
    """Prune one dependency using a per-path keep set, or keep all definitions."""

    keep_names = None if keep_by_path is None else keep_by_path.get(dep_path, set())
    return prune_dep_module(dep_path, keep_names, audit_writer)


def referenced_identifiers(*texts):
    """Bare identifiers mentioned across `texts` — the seeds for dep pruning."""
    names = set()
    for t in texts:
        names.update(_scan_identifiers(t))
    return names


def cross_dir_dedup(target_paths, audit_writer, preferred_dir="Data"):
    """Filter C — drop target benchmarks that are byte-identical to a target
    in another output directory.

    When duplicates exist we keep the copy under `preferred_dir` (default
    `Data` — the natural home for utility-library benchmarks); if no copy
    is under `preferred_dir`, the alphabetically-first path wins. The
    other copies are deleted and every drop is recorded in the audit log.

    Returns the number of files removed.
    """
    import hashlib

    by_hash = {}
    for path in target_paths:
        with open(path, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        by_hash.setdefault(h, []).append(path)

    sep = os.sep
    preferred_marker = f"{sep}{preferred_dir}{sep}"
    removed = 0
    for group in by_hash.values():
        if len(group) < 2:
            continue
        preferred = sorted(p for p in group if preferred_marker in p)
        keeper = preferred[0] if preferred else sorted(group)[0]
        for path in group:
            if path == keeper:
                continue
            os.remove(path)
            audit_writer.write(
                f"[audit] {os.path.relpath(path, PROJECT_ROOT)}: "
                f"byte-identical to {os.path.relpath(keeper, PROJECT_ROOT)} "
                f"— removed (filter C, cross-dir dedup)\n"
            )
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Shared-model emission (closure(Spec) model + EXTENDS tasks). Opt-in via
# --shared-model. De-duplicates the spec that self-contained tasks inline:
# one `<Module>.tla` model per output dir, each spec-based task EXTENDS it. The
# grader already copies co-located *.tla, so EXTENDS resolves with no grader
# change. Certified sound (obligation-set equivalence) — see tmp/split_poc.
# ---------------------------------------------------------------------------
_BARE_DECL = re.compile(r"^[ \t]*(CONSTANTS?|VARIABLES?)[ \t]*,?[ \t]*$", re.M)
_EXTENDS_START = re.compile(r"^EXTENDS\b")


def _model_closure(dump, seed):
    adj = {}
    for o in dump["operators"]:
        adj.setdefault(o["name"], set()).update(o.get("references", []))
    for i in dump["instances"]:
        if i.get("name"):
            adj.setdefault(i["name"], set()).update(i.get("references", []))
    out, stack = set(), list(seed)
    while stack:
        n = stack.pop()
        if n in out:
            continue
        out.add(n)
        stack.extend(r for r in adj.get(n, ()) if r not in out)
    return out


def compute_model_set(dump, targets):
    """Leak-free shared base = closure of the GOAL spec(s) only, intersected
    with every spec-goal's reachable set. Seeded ONLY from the `lhs_spec_ref` of
    emitted targets (NOT all spec_formulas) so an inductive-invariant spec like
    `ISpec`/`LiveSpec` can't drag `Inv` into the model. The intersection drops
    anything a task is meant to hide; what remains is the common state machine,
    provably free of inductive invariants/proofs."""
    spec_formulas = dump.get("spec_formulas", [])
    main_specs = {t["shape"].get("lhs_spec_ref") for t in targets if t["shape"].get("lhs_spec_ref") in spec_formulas}
    if not main_specs:
        return set(), main_specs
    seed = set(main_specs)
    for a in dump["assumes"]:
        seed.update(a.get("references", []))
    reachable = {id(t): compute_reachable(dump, t) for t in targets}
    model = _model_closure(dump, seed)
    for t in targets:
        if t["shape"].get("lhs_spec_ref") in main_specs:
            model &= reachable[id(t)]
    return model, main_specs


def _decl_edits(dump):
    """Delete CONSTANT/VARIABLE/ASSUME declarations (one per distinct loc) —
    they come via EXTENDS in the task/model-extending file."""
    seen, edits = set(), []
    for e in list(dump.get("constants", [])) + list(dump.get("variables", [])) + list(dump.get("assumes", [])):
        loc = e.get("loc")
        if not loc:
            continue
        key = (loc["line_start"], loc["line_end"])
        if key in seen:
            continue
        seen.add(key)
        edits.append((loc["line_start"], loc["line_end"], ""))
    return edits


def _rewrite_extends_line(text, module):
    """Replace the (possibly multi-line) EXTENDS statement with `EXTENDS <module>`."""
    lines = text.split("\n")
    out, i, done = [], 0, False
    while i < len(lines):
        if not done and _EXTENDS_START.match(lines[i]):
            j = i
            while lines[j].rstrip().endswith(","):
                j += 1
            out.append(f"EXTENDS {module}")
            i = j + 1
            done = True
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


_DEFINED_NAME = re.compile(r"(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*(?:\([^)]*\))?[ \t]*==")
_RECURSIVE_DECL = re.compile(r"([A-Za-z_]\w*)[ \t]*(\([^)]*\))?")


def _prune_recursive_decls(text):
    """Drop RECURSIVE declarations whose definition is no longer in the module.

    A RECURSIVE declaration is a statement in its own right, so stripping the
    definition it announces leaves SANY with `Symbol X declared in RECURSIVE
    statement but not defined`. The same applies in the Defs layer when the
    definition moved to the shared model.
    """
    defined = set(_DEFINED_NAME.findall(text))
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("RECURSIVE "):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while lines[j].rstrip().endswith(","):
            j += 1
        indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        body = " ".join(ln.strip() for ln in lines[i : j + 1])[len("RECURSIVE ") :]
        kept = [f"{n}{a or ''}" for n, a in _RECURSIVE_DECL.findall(body) if n in defined]
        if kept:
            out.append(f"{indent}RECURSIVE " + ", ".join(kept))
        i = j + 1
    return "\n".join(out)


def _sm_tidy(text):
    """Drop stranded pure-dash `----` dividers and collapse blank runs."""
    text = _prune_recursive_decls(text)
    text = re.sub(r"(?m)^-{4,}[ \t]*$\n?", "", text)
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)


def _rename_header(text, new_name):
    # Rename the FIRST `---- MODULE X ----` line wherever it is — a leading blank
    # line or comment can precede it (e.g. BPConProof), so don't require it to be
    # the first output line, else the rename silently no-ops and the task module
    # name collides with the co-located model.
    out, done = [], False
    for line in text.splitlines(keepends=True):
        if not done:
            m = MODULE_HEADER.match(line)
            if m:
                out.append(f"{m.group(1)}{new_name}{m.group(3)}\n")
                done = True
                continue
        out.append(line)
    return "".join(out)


def build_model(source_lines, dump, model_set):
    """Proof-free shared model (delete-from-source, preserves declaration order
    so an ASSUME/AXIOM that references a later operator still resolves)."""
    edits = []
    for t in dump["theorems"]:
        edits.append((t["loc"]["line_start"], t["loc"]["line_end"], ""))
    for o in dump["operators"]:
        if o["name"] not in model_set:
            edits.append((o["loc"]["line_start"], o["loc"]["line_end"], ""))
    for inst in dump["instances"]:
        if inst.get("name") and inst["name"] not in model_set:
            edits.append((inst["loc"]["line_start"], inst["loc"]["line_end"], ""))
    return _sm_tidy(strip_comments(apply_edits(source_lines, edits)))


def build_benchmark_extends(source_lines, dump, target_thm, bench_module_name, reachable, model_set, module):
    """Like build_benchmark, but the spec lives in the EXTENDS'd model: also
    delete model operators + the CONSTANT/VARIABLE/ASSUME decls, and rewrite the
    EXTENDS line to `EXTENDS <module>`."""
    edits = list(_decl_edits(dump))
    tid = id(target_thm)
    for t in dump["theorems"]:
        if id(t) == tid:
            ploc = t["proof_loc"]
            edits.append((ploc["line_start"], ploc["line_end"], "PROOF OBVIOUS\n"))
        else:
            loc = t["loc"]
            edits.append((loc["line_start"], loc["line_end"], ""))
    for o in dump["operators"]:
        if o["name"] in model_set or o["name"] not in reachable:
            edits.append((o["loc"]["line_start"], o["loc"]["line_end"], ""))
    for inst in dump["instances"]:
        if inst.get("name") and (inst["name"] in model_set or inst["name"] not in reachable):
            edits.append((inst["loc"]["line_start"], inst["loc"]["line_end"], ""))
    text = apply_edits(source_lines, edits)
    text = strip_comments(text)
    text = _strip_bare_decls(text)
    text = _rewrite_extends_line(text, module)
    text = _rename_header(text, bench_module_name)
    return _sm_tidy(text)


def _strip_bare_decls(text):
    return _BARE_DECL.sub("", text)


# These four markers must match src/common/proof_from_scratch_contract.py
# byte-for-byte; the evaluator compares them to detect scaffold tampering.
MANIFEST_FILENAME = "manifest.json"

BEGIN_AGENT_HELPERS = r"\* BEGIN AGENT HELPERS"
END_AGENT_HELPERS = r"\* END AGENT HELPERS"
BEGIN_AGENT_PROOF = r"\* BEGIN AGENT PROOF"
END_AGENT_PROOF = r"\* END AGENT PROOF"

# `USE`/`HIDE` are prover hints from the original proof, not given semantics, so
# they never belong in a read-only layer. Every occurrence in source/ is one line.
_MODULE_DIRECTIVE = re.compile(r"(?m)^[ \t]*(USE|HIDE)\b[^\n]*\n?")
_MODULE_TERMINATOR = re.compile(r"={4,}")


def _split_outer_module(text):
    """Return the complete outer module and any text that follows it."""
    original_lines = text.splitlines(keepends=True)
    scan_lines = strip_comments(text).splitlines(keepends=True)
    depth = 0
    for index, scan_line in enumerate(scan_lines):
        stripped = scan_line.strip()
        if MODULE_HEADER.match(stripped):
            depth += 1
        elif depth and _MODULE_TERMINATOR.fullmatch(stripped):
            depth -= 1
            if depth == 0:
                return "".join(original_lines[: index + 1]), "".join(original_lines[index + 1 :])
    return text, None


def _truncate_after_outer_module(text):
    """Remove prompt-visible content after the outer module terminator."""
    module, tail = _split_outer_module(text)
    return module if tail is not None and tail.strip() else text


def _strip_module_directives(text):
    return _MODULE_DIRECTIVE.sub("", _truncate_after_outer_module(text))


def _set_extends(text, module):
    """Force the module's EXTENDS clause to be exactly `EXTENDS <module>`.

    Rewrites an existing (possibly multi-line) EXTENDS statement, or inserts one
    right after the `---- MODULE ... ----` header when the source has none. Used
    for the Defs layer, which pulls all declarations in through the shared model.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _EXTENDS_START.match(line):
            j = i
            # `EXTENDS` alone on its line continues onto the next one, as does a
            # line ending in a comma. Missing the first form leaves the module
            # names behind as a dangling statement.
            while lines[j].rstrip().endswith(",") or lines[j].strip() == "EXTENDS":
                j += 1
            return "\n".join(lines[:i] + [f"EXTENDS {module}"] + lines[j + 1 :])
    for i, line in enumerate(lines):
        if MODULE_HEADER.match(line):
            return "\n".join(lines[: i + 1] + [f"EXTENDS {module}"] + lines[i + 1 :])
    return f"EXTENDS {module}\n" + text


_DECL_KEYWORD = re.compile(r"^[ \t]*(CONSTANTS?|VARIABLES?)\b")


def _decl_statement_extent(source_lines, line):
    """Line span of the whole declaration statement containing `line`.

    SANY reports one loc per declared name, but a single `VARIABLE a, b`
    statement can span several lines (Voting.tla puts `votes` on line 40 and
    `maxBal` on 41). Deleting one name's line alone leaves a dangling
    `VARIABLE votes,` that no longer parses, so the statement is one unit.
    """
    if not 1 <= line <= len(source_lines):
        return (line, line)
    start = line
    while start > 1 and not _DECL_KEYWORD.match(source_lines[start - 1]):
        start -= 1
    if not _DECL_KEYWORD.match(source_lines[start - 1]):
        return (line, line)  # no keyword found; fall back to the reported loc
    end = start
    while end < len(source_lines) and strip_comments(source_lines[end - 1]).rstrip().endswith(","):
        end += 1
    return (start, max(end, line))


def _unneeded_decl_edits(source_lines, dump, defs_set):
    """Delete CONSTANT/VARIABLE statements no kept content refers to.

    Besides over-exposure this is a correctness hazard: TLA+ scoping is
    order-sensitive, so a VARIABLE declared *after* a theorem does not shadow
    that theorem's bound variables — but once hoisted into a module the task
    EXTENDS, it does (BubbleSort binds `\\A A, B, C`; the source later declares
    `VARIABLES A, A0`). A name is needed if it occurs in a kept definition or
    ASSUME; a statement goes only when none of its names are.
    """
    # An INSTANCE substitutes declarations implicitly by name — `INSTANCE
    # Stuttering` needs the local `VARIABLE s` though nothing mentions `s`. No
    # textual scan sees that, so if one survives here, prune nothing.
    for inst in dump.get("instances", []):
        if not inst.get("name") or inst["name"] in defs_set:
            return []

    kept = []
    for o in dump["operators"]:
        if o["name"] in defs_set:
            kept.append("".join(source_lines[o["loc"]["line_start"] - 1 : o["loc"]["line_end"]]))
    for a in dump.get("assumes", []):
        loc = a.get("loc")
        if loc:
            kept.append("".join(source_lines[loc["line_start"] - 1 : loc["line_end"]]))
    kept_text = strip_comments("\n".join(kept))

    by_stmt = {}
    for d in list(dump.get("constants", [])) + list(dump.get("variables", [])):
        loc = d.get("loc")
        name = d.get("name")
        if not loc or not name:
            continue
        by_stmt.setdefault(_decl_statement_extent(source_lines, loc["line_start"]), []).append(name)

    edits = []
    for (start, end), names in by_stmt.items():
        # The lookbehind keeps TLA+ backslash operators from counting as uses:
        # without it `\A p \in ...` reads as a use of a VARIABLE named `A`.
        if not any(re.search(rf"(?<!\\)\b{re.escape(n)}\b", kept_text) for n in names):
            edits.append((start, end, ""))
    return edits


def build_defs(source_lines, dump, defs_set, defs_module_name, model_module, keep_decls):
    """Read-only target-definitions module (the `<task>Defs.tla` layer).

    Keeps only the definitions in `defs_set` — reachable from the theorem
    statement, minus the shared model — and removes every theorem and proof: a
    Defs file states given semantics, never a goal. With a shared model
    (`keep_decls=False`) it becomes `EXTENDS <model_module>`, which owns the
    declarations; otherwise those stay here.
    """
    edits = []
    if keep_decls:
        edits += _unneeded_decl_edits(source_lines, dump, defs_set)
    else:
        edits += _decl_edits(dump)
    for t in dump["theorems"]:
        loc = t["loc"]
        edits.append((loc["line_start"], loc["line_end"], ""))
    for o in dump["operators"]:
        if o["name"] not in defs_set:
            edits.append((o["loc"]["line_start"], o["loc"]["line_end"], ""))
    for inst in dump["instances"]:
        if inst.get("name") and inst["name"] not in defs_set:
            edits.append((inst["loc"]["line_start"], inst["loc"]["line_end"], ""))
    text = apply_edits(source_lines, edits)
    text = strip_comments(text)
    text = _strip_module_directives(text)
    if not keep_decls:
        text = _strip_bare_decls(text)
        text = _set_extends(text, model_module)
    text = _rename_header(text, defs_module_name)
    return _sm_tidy(text)


def build_task_module(task_module_name, defs_module, statement_text):
    """Build a task with two editable regions.

    The task extends its Defs layer, then places the four marker lines around an
    empty helper region and a ``PROOF OBVIOUS`` proof region. The theorem
    statement remains fixed between them. Building from scratch keeps the
    evaluator's marker contract exact.
    """
    stmt = statement_text.rstrip("\n")
    return (
        f"---- MODULE {task_module_name} ----\n"
        f"EXTENDS {defs_module}\n\n"
        f"{BEGIN_AGENT_HELPERS}\n"
        f"{END_AGENT_HELPERS}\n"
        f"{stmt}\n"
        f"{BEGIN_AGENT_PROOF}\n"
        f"PROOF OBVIOUS\n"
        f"{END_AGENT_PROOF}\n"
        f"====\n"
    )


def compute_sibling_deps(targets):
    """Map output-subdir -> set of local module names that a SIBLING source file
    EXTENDS or INSTANCEs. Such a module must stay FULL (a stripped shared model
    can't serve as an EXTENDS/INSTANCE target — e.g. BPConProof INSTANCEs
    VoteProof, so VoteProof must keep all 55 ops, not its 17-op spec model)."""
    by_subdir = {}
    for path, subdir in targets:
        key = subdir if subdir is not None else os.path.splitext(os.path.basename(path))[0]
        by_subdir.setdefault(key, []).append(path)
    result = {}
    for key, paths in by_subdir.items():
        stems = {os.path.splitext(os.path.basename(p))[0] for p in paths}
        deps = set()
        for p in paths:
            try:
                with open(p, encoding="utf-8") as _f:
                    content = _f.read()
            except OSError:
                continue
            self_stem = os.path.splitext(os.path.basename(p))[0]
            for ext in parse_extends(content):
                if ext in stems and ext != self_stem:
                    deps.add(ext)
            for _, inst_mod in parse_instances(content):
                if inst_mod in stems and inst_mod != self_stem:
                    deps.add(inst_mod)
        result[key] = deps
    return result


_THEOREM_SCAN = re.compile(r"^[ \t]*(THEOREM|LEMMA|COROLLARY|PROPOSITION)\b", re.MULTILINE)
_PROOF_ARTIFACT_SCAN = re.compile(
    r"^[ \t]*(?:(?:LOCAL[ \t]+)?(?:THEOREM|LEMMA|COROLLARY|PROPOSITION)\b"
    r"|(?:PROOF|OMITTED|OBVIOUS|BY|QED)\b|<\d+>)",
    re.MULTILINE,
)
_DEFINITION_SCAN = re.compile(r"^([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*==", re.MULTILINE)


def _defined_names(text):
    """Names a module defines at top level, read back from emitted text."""
    return set(_DEFINITION_SCAN.findall(text))


def load_dataset_task_keys(root):
    """Task keys that define the repository's curated dataset selection.

    Once a layered manifest exists it is authoritative. During the first
    migration, derive the same set from the existing flat benchmark tree using
    the evaluator's task-file rule. The dataset itself is the selection input;
    the generator carries no per-group or per-theorem allow-list.
    """
    manifest_path = os.path.join(root, MANIFEST_FILENAME)
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            if isinstance(manifest, dict):
                return set(manifest)
        except (OSError, json.JSONDecodeError):
            pass

    keys = set()
    if not os.path.isdir(root):
        return keys
    for current_root, _dirs, files in os.walk(root):
        for fname in files:
            if not fname.endswith(".tla"):
                continue
            path = os.path.join(current_root, fname)
            if is_task_file(path):
                keys.add(os.path.relpath(path, root).replace(os.sep, "/"))
    return keys


def positional_targets(files, source_root=SOURCE_ROOT):
    """Resolve positional files without losing repository dataset ownership.

    Files below the repository source root use the same first-directory
    grouping as a normal source-tree scan.  This keeps partial layered runs in
    the correct manifest namespace instead of treating each module as a new
    top-level group.
    """
    canonical_root = os.path.realpath(os.path.abspath(source_root))
    targets = []
    all_repository_sources = bool(files)
    for path in files:
        absolute = os.path.abspath(path)
        canonical_path = os.path.realpath(absolute)
        try:
            in_repository = os.path.commonpath([canonical_root, canonical_path]) == canonical_root
        except ValueError:
            in_repository = False

        subdir = None
        if in_repository:
            relative = os.path.relpath(canonical_path, canonical_root)
            if relative != ".":
                parts = relative.split(os.sep)
                subdir = parts[0] if len(parts) > 1 else os.path.splitext(parts[0])[0]
            else:
                in_repository = False

        all_repository_sources &= in_repository
        targets.append((canonical_path, subdir))
    return targets, all_repository_sources


def scan_source_targets(source_root):
    """Return source-tree targets with the repository's output grouping."""
    targets = []
    for root, _, files in os.walk(os.path.abspath(source_root)):
        if ".tlaps" in root:
            continue
        for fname in sorted(files):
            if not fname.endswith(".tla"):
                continue
            subdir = os.path.relpath(root, source_root).split(os.sep)[0]
            if subdir == ".":
                subdir = os.path.splitext(fname)[0]
            targets.append((os.path.join(root, fname), subdir))
    return targets


def _plan_layered_targets(top_level, subdir, base_module, reference_task_keys, audit_writer, source_path):
    """Choose task module names before writing any layered files.

    A repository generation uses the existing dataset/manifest as its vetted
    target selection. An unnamed theorem may have acquired a semantic RHS name
    since its first generation; if its historical line-based key still exists,
    preserve that key generically. Candidates outside the reference set are
    audited and skipped, never treated as errors.
    """
    used_names = set()
    planned = []
    for entry in top_level:
        target_thm = entry[0]
        thm_name, _ = target_theorem_name(target_thm)
        bench_module_name = f"{base_module}_{thm_name}"
        if bench_module_name in used_names:
            bench_module_name = f"{bench_module_name}_L{target_thm['loc']['line_start']}"
        used_names.add(bench_module_name)

        task_key = f"{subdir}/{bench_module_name}.tla"
        if reference_task_keys is not None and task_key not in reference_task_keys:
            legacy_module = None
            if not target_thm["name"]:
                line = target_thm["loc"]["line_start"]
                candidate = f"{base_module}_line{line}"
                candidate_key = f"{subdir}/{candidate}.tla"
                if candidate_key in reference_task_keys:
                    legacy_module = candidate
                    audit_writer.write(
                        f"[audit] {source_path}: generated target name `{bench_module_name}` maps to "
                        f"existing line-based task key {candidate_key} — preserving that key\n"
                    )
            if legacy_module is None:
                audit_writer.write(
                    f"[audit] {task_key}: source candidate is outside the existing dataset selection — skipped\n"
                )
                continue
            bench_module_name = legacy_module
            task_key = f"{subdir}/{bench_module_name}.tla"

        planned.append((target_thm, bench_module_name, task_key))
    return planned


def _emit_layered(
    source_path,
    source_lines,
    dump,
    top_level,
    out_dir,
    subdir,
    base_module,
    audit_writer,
    generated_paths,
    manifest,
    audit_state,
    reference_task_keys,
    source_root,
):
    """Emit the three-layer split + manifest entries for one source file.

    Layout per task (Issue #64 / PR #71 contract):
      <base>Model.tla   shared benchmark-owned model      (read-only)
      <task>Defs.tla    target-specific given definitions (read-only)
      <task>.tla        theorem + markers + PROOF OBVIOUS (editable)
    """
    planned = _plan_layered_targets(
        top_level,
        subdir,
        base_module,
        reference_task_keys,
        audit_writer,
        source_path,
    )
    if not planned:
        return 0

    targets = [target for target, _module, _key in planned]
    spec_id = source_spec_id(source_path, source_root)
    model_set, main_specs = compute_model_set(dump, targets)

    model_module = None
    model_text = ""
    if model_set:
        model_module = f"{base_module}Model"
        model_text = _rename_header(_strip_module_directives(build_model(source_lines, dump, model_set)), model_module)
        model_path = os.path.join(out_dir, f"{model_module}.tla")
        with open(model_path, "w", encoding="utf-8") as f:
            f.write(model_text if model_text.endswith("\n") else model_text + "\n")
        if _THEOREM_SCAN.search(model_text):
            audit_writer.write(f"[audit] {source_path}: LEAK model {model_module} contains a THEOREM/LEMMA\n")
        print(f"  generated model: {os.path.relpath(model_path, PROJECT_ROOT)}")

    all_ops = {o["name"] for o in dump["operators"]}
    union_reach = set()
    for t in targets:
        union_reach |= compute_reachable(dump, t)
    artifacts = all_ops - union_reach

    count = 0
    for target_thm, bench_module_name, task_key in planned:
        reachable = compute_reachable(dump, target_thm)
        is_spec = target_thm["shape"].get("lhs_spec_ref") in main_specs
        use_model = model_module is not None and is_spec
        defs_set = reachable - model_set if use_model else reachable
        defs_module = f"{bench_module_name}Defs"
        keep_decls = not use_model

        defs_text = build_defs(source_lines, dump, defs_set, defs_module, model_module, keep_decls)
        defs_path = os.path.join(out_dir, f"{defs_module}.tla")
        with open(defs_path, "w", encoding="utf-8") as f:
            f.write(defs_text if defs_text.endswith("\n") else defs_text + "\n")
        if _THEOREM_SCAN.search(defs_text):
            audit_writer.write(f"[audit] {source_path}: LEAK Defs {defs_module} contains a THEOREM/LEMMA\n")

        statement_text = strip_comments(_statement_text(target_thm, source_lines)).strip()
        task_text = build_task_module(bench_module_name, defs_module, statement_text)
        task_path = os.path.join(out_dir, f"{bench_module_name}.tla")
        with open(task_path, "w", encoding="utf-8") as f:
            f.write(task_text)

        # Per-task copies: sharing one would leak a sibling's definitions. The
        # filename may repeat since each task is graded in its own workspace.
        context = []
        if use_model:
            context.append(f"{subdir}/{model_module}.tla")
        context.append(f"{subdir}/{defs_module}.tla")
        seeds = referenced_identifiers(defs_text, statement_text, model_text or "")
        dep_paths = [p for _mod, p in layered_dep_paths(dump, source_path, reachable)]
        for dep_path in dep_paths:
            context.append(f"{subdir}/{bench_module_name}/{os.path.basename(dep_path)}")
        if dep_paths and audit_state is not None:
            audit_state.setdefault("deps", {})[f"{subdir}/{bench_module_name}"] = {
                "paths": dep_paths,
                "seeds": seeds,
                "source_defined": source_defined_names(dump),
                "instance_modules": source_instance_modules(dump),
                "qualified_uses": instance_qualified_uses(defs_text, statement_text, model_text or ""),
                "imported_modules": source_imported_modules(dump),
            }
        context = sorted(set(context))

        # Read the files back rather than trust the sets that built them. Only
        # this source's layers: a dependency is a different namespace.
        own_layers = {f"{subdir}/{defs_module}.tla"} | ({f"{subdir}/{model_module}.tla"} if use_model else set())
        for rel in sorted(own_layers):
            ctx_text = Path(out_dir, os.path.basename(rel)).read_text(encoding="utf-8")
            if _THEOREM_SCAN.search(ctx_text):
                audit_writer.write(f"[audit] {task_key}: LEAK context {rel} states a THEOREM/LEMMA\n")
            leaked = _defined_names(ctx_text) & artifacts
            if leaked:
                audit_writer.write(
                    f"[audit] {task_key}: LEAK context {rel} defines proof artifact(s) {sorted(leaked)}\n"
                )

        if manifest is not None:
            manifest[task_key] = {
                "spec_id": spec_id,
                "context": context,
            }
        if audit_state is not None:
            audit_state.setdefault("defs_owner", {}).setdefault(f"{subdir}/{defs_module}.tla", []).append(task_key)

        count += 1
        if generated_paths is not None:
            generated_paths.append(task_path)
        print(f"  generated task: {os.path.relpath(task_path, PROJECT_ROOT)}")

    return count


def process_file(
    source_path,
    audit_writer,
    output_root,
    module_subdir=None,
    generated_paths=None,
    shared_model=False,
    skip_model_modules=(),
    allow_no_proof=False,
    layered=False,
    manifest=None,
    audit_state=None,
    reference_task_keys=None,
    source_root=None,
):
    """Generate proof-from-scratch benchmarks for one source .tla file. Returns count emitted.

    If `generated_paths` is a list, each generated target benchmark path is
    appended to it (for downstream cross-directory dedup).

    When `layered` is True, each task is emitted as three files by ownership
    (`<base>Model.tla`, `<task>Defs.tla`, `<task>.tla`) plus a `manifest`
    entry mapping the task to its exact read-only context (Issue #64). This is
    mutually exclusive with `shared_model`. `audit_state` accumulates data for
    the cross-file isolation audit (each Defs used by exactly one task).
    """
    with open(source_path, encoding="utf-8") as f:
        text = f.read()
    source_lines = text.splitlines(keepends=True)
    base_module = os.path.splitext(os.path.basename(source_path))[0]

    try:
        dump = dump_sany(source_path)
    except RuntimeError as e:
        audit_writer.write(f"[audit] {source_path}: SANY parse failed — {e}\n")
        return 0

    module = dump["module"]
    spec_formulas = set(dump["spec_formulas"])

    if not spec_formulas:
        audit_writer.write(f"[audit] {source_path}: no spec formula identified — shape rule will not match\n")
    elif len(spec_formulas) > 1:
        audit_writer.write(f"[audit] {source_path}: multiple spec formulas: {sorted(spec_formulas)}\n")
    elif "Spec" not in spec_formulas:
        only = next(iter(spec_formulas))
        audit_writer.write(f"[audit] {source_path}: identified spec formula `{only}` — name != `Spec`\n")

    for t in dump["theorems"]:
        t["_keyword"] = determine_keyword(source_lines, t["loc"]["line_start"])

    theorem_candidates = [t for t in dump["theorems"] if t["_keyword"] == "THEOREM"]
    top_level = find_top_level(theorem_candidates, spec_formulas)

    # Filter A — require a manual TLAPS proof in the source.
    # See module docstring for the rationale and the two known-dropped main
    # theorems. We treat PROOF OMITTED and PROOF OBVIOUS as "no manual proof"
    # because both leave nothing for AI to compare against (OMITTED is an
    # explicit deferral; OBVIOUS is a 1-token placeholder that passes
    # trivially and so carries no benchmark signal).
    survivors = []
    for entry in top_level:
        target_thm = entry[0]
        line = target_thm["loc"]["line_start"]
        name = target_thm["name"] or f"<unnamed L{line}>"
        has_proof = _has_manual_proof(target_thm, source_lines)
        if not has_proof and not allow_no_proof and reference_task_keys is None:
            audit_writer.write(
                f"[audit] {source_path}: top-level THEOREM {name} at line "
                f"{line} has no manual TLAPS proof body — skipped (filter A)\n"
            )
        elif (
            base_module,
            target_theorem_name(target_thm)[0],
        ) in KNOWN_FALSE_TARGETS:
            # Filter A' — drop ONLY a goal TLC has shown to be false. An OMITTED
            # sub-step that papers over a *false* claim (e.g. PaxosProof
            # StructOK3) admits no honest proof, so it must not become a
            # benchmark. See KNOWN_FALSE_TARGETS for the per-target evidence.
            reason = KNOWN_FALSE_TARGETS[(base_module, target_theorem_name(target_thm)[0])]
            audit_writer.write(
                f"[audit] {source_path}: top-level THEOREM {name} at line "
                f"{line} asserts a FALSE goal — skipped (filter A', known-false): "
                f"{reason}\n"
            )
        elif _proof_has_omitted_substep(target_thm, source_lines):
            # An OMITTED sub-step is NO LONGER grounds for dropping: the proof is
            # structured (an OMITTED leaf still "counts as a proof"), the goal is
            # a published/verified result, and proof-from-scratch grades by tlapm — not by the
            # human reference — so a missing reference proof is fine. Keep it as
            # a (hard) from-scratch benchmark. Record that it carries an OMITTED
            # sub-step for traceability.
            audit_writer.write(
                f"[audit] {source_path}: top-level THEOREM {name} at line "
                f"{line} has an OMITTED sub-step — kept (goal vetted true; hard "
                f"from-scratch benchmark)\n"
            )
            survivors.append(entry)
        elif not has_proof:
            if reference_task_keys is not None:
                audit_writer.write(
                    f"[audit] {source_path}: top-level THEOREM {name} at line "
                    f"{line} has no manual proof — retained for existing-dataset selection\n"
                )
            else:
                # --allow-no-proof: the source carries only PROOF OBVIOUS/OMITTED
                # (no reference proof), but the goal is a vetted hard property
                # (e.g. the ZooKeeper Zab safety theorems). proof-from-scratch grades by tlapm, not
                # by the human reference, so keep it as a from-scratch benchmark.
                audit_writer.write(
                    f"[audit] {source_path}: top-level THEOREM {name} at line "
                    f"{line} has no manual proof — kept (--allow-no-proof; tlapm-graded "
                    f"from-scratch benchmark)\n"
                )
            survivors.append(entry)
        else:
            survivors.append(entry)
    top_level = survivors

    # Filter B — within-file exact-text statement dedup. Keep first by line.
    seen_stmts = {}
    deduped = []
    for entry in top_level:
        target_thm = entry[0]
        stmt = _statement_text(target_thm, source_lines)
        if stmt in seen_stmts:
            line = target_thm["loc"]["line_start"]
            kept_line = seen_stmts[stmt]
            name = target_thm["name"] or f"<unnamed L{line}>"
            audit_writer.write(
                f"[audit] {source_path}: top-level THEOREM {name} at line "
                f"{line} has identical statement text to candidate kept at line "
                f"{kept_line} — skipped (filter B)\n"
            )
        else:
            seen_stmts[stmt] = target_thm["loc"]["line_start"]
            deduped.append(entry)
    top_level = deduped

    if not top_level:
        audit_writer.write(f"[audit] {source_path}: no top-level THEOREM identified — no benchmarks generated\n")
        return 0
    if len(top_level) > 1:
        names = []
        for t, unnamed, shp, grph in top_level:
            label = t["name"] or f"<unnamed L{t['loc']['line_start']}>"
            tag = "[unnamed]" if unnamed else f"[shape={'Y' if shp else 'N'}/graph={'Y' if grph else 'N'}]"
            names.append(label + tag)
        audit_writer.write(f"[audit] {source_path}: multiple top-level THEOREMs: {names}\n")

    out_dir = os.path.join(output_root, module_subdir or module)
    subdir = module_subdir or module
    os.makedirs(out_dir, exist_ok=True)

    if layered:
        return _emit_layered(
            source_path,
            source_lines,
            dump,
            top_level,
            out_dir,
            subdir,
            base_module,
            audit_writer,
            generated_paths,
            manifest,
            audit_state,
            reference_task_keys,
            source_root or SOURCE_ROOT,
        )

    # Shared-model mode: emit one proof-free `<module>.tla` model and have
    # spec-based tasks EXTEND it instead of inlining the spec. A module that a
    # sibling depends on stays full (self-contained tasks) so the sibling's
    # EXTENDS/INSTANCE still resolves.
    model_set, main_specs = (set(), set())
    if shared_model and module in skip_model_modules:
        audit_writer.write(
            f"[audit] {source_path}: module {module} is a local dependency of a sibling — kept full (no shared model)\n"
        )
    if shared_model and module not in skip_model_modules:
        targets = [entry[0] for entry in top_level]
        model_set, main_specs = compute_model_set(dump, targets)
        if model_set:
            model_text = build_model(source_lines, dump, model_set)
            model_path = os.path.join(out_dir, f"{module}.tla")
            with open(model_path, "w", encoding="utf-8") as f:
                f.write(model_text)
            print(f"  generated model: {os.path.relpath(model_path, PROJECT_ROOT)}")

    used_names = set()
    count = 0
    for target_thm, _, _, _ in top_level:
        if not target_thm["name"]:
            # Not a warning: unnamed THEOREMs are top-level by construction.
            # This entry just records how the filename was derived.
            line = target_thm["loc"]["line_start"]
            rhs = target_thm["shape"].get("rhs_primary_name")
            if rhs:
                audit_writer.write(
                    f"[audit] {source_path}: unnamed top-level THEOREM at line "
                    f"{line} — filename derived from rhs primary name `{rhs}`\n"
                )
            else:
                audit_writer.write(
                    f"[audit] {source_path}: unnamed top-level THEOREM at line "
                    f"{line} — no usable rhs primary name; filename uses line "
                    f"number `line{line}`\n"
                )
        thm_name, sanitized = target_theorem_name(target_thm)
        if sanitized:
            audit_writer.write(
                f"[audit] {source_path}: rhs primary name "
                f"`{target_thm['shape'].get('rhs_primary_name')}` contains `!` "
                f"(INSTANCE namespace separator); sanitized to `{thm_name}` for module identifier\n"
            )
        bench_module_name = f"{base_module}_{thm_name}"
        # Disambiguate filename collisions (e.g. Peterson.tla has 3 unnamed
        # `THEOREM Spec => []MutualExclusion` lines that all map to the same name).
        if bench_module_name in used_names:
            bench_module_name = f"{bench_module_name}_L{target_thm['loc']['line_start']}"
            audit_writer.write(
                f"[audit] {source_path}: filename collision on `{base_module}_{thm_name}`, "
                f"disambiguated to `{bench_module_name}`\n"
            )
        used_names.add(bench_module_name)
        bench_file = os.path.join(out_dir, f"{bench_module_name}.tla")

        reachable = compute_reachable(dump, target_thm)
        # Spec-based targets EXTEND the shared model; non-spec lemmas stay
        # self-contained (the model would over-expose context they hide).
        is_spec = target_thm["shape"].get("lhs_spec_ref") in main_specs
        if shared_model and model_set and is_spec:
            bench_text = build_benchmark_extends(
                source_lines, dump, target_thm, bench_module_name, reachable, model_set, module
            )
        else:
            bench_text = build_benchmark(source_lines, dump, target_thm, bench_module_name, reachable)
        with open(bench_file, "w", encoding="utf-8") as f:
            f.write(bench_text)
        copy_deps(dump, source_path, out_dir, reachable)
        count += 1
        if generated_paths is not None:
            generated_paths.append(bench_file)
        print(f"  generated: {os.path.relpath(bench_file, PROJECT_ROOT)}")

    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", default=SOURCE_ROOT, help="Directory of source .tla files (default: %(default)s)"
    )
    parser.add_argument(
        "--output-dir", default=BENCHMARK_DIR, help="Output directory for benchmarks (default: %(default)s)"
    )
    parser.add_argument("--filter", default=None, help="Glob-ish substring to limit which source files we process")
    parser.add_argument("files", nargs="*", help="Specific .tla files to process (overrides --source-dir scan)")
    parser.add_argument(
        "--shared-model",
        action="store_true",
        help="Emit one proof-free <Module>.tla model per output dir "
        "and have spec-based tasks EXTEND it instead of inlining "
        "the spec (de-duplicates the spec; grader resolves the "
        "co-located model automatically).",
    )
    parser.add_argument(
        "--allow-no-proof",
        action="store_true",
        help="Keep top-level theorems whose source has only PROOF "
        "OBVIOUS/OMITTED (no reference proof). Use for vetted "
        "hard from-scratch benchmarks (e.g. ZooKeeper Zab) that "
        "are graded by tlapm, not against a human reference. In a "
        "repository-wide layered run, this explicitly expands beyond "
        "the existing dataset selection.",
    )
    parser.add_argument(
        "--layered",
        action="store_true",
        help="Split each task into <base>Model.tla + <task>Defs.tla + "
        "<task>.tla (editable, with helper/proof markers) and write "
        "manifest.json mapping each task to its source specification and exact read-only context "
        "(Issue #64 / PR #71 contract). For the repository source tree, "
        "the existing dataset/manifest supplies the vetted target selection. "
        "Implies the shared-model split.",
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        help="Layered mode only: skip the SANY and triviality gates. "
        "For fast iteration — a shipped dataset must be generated with them.",
    )
    args = parser.parse_args()
    if args.layered and args.shared_model:
        parser.error("--layered already performs the model split; do not combine with --shared-model")

    output_root = os.path.abspath(args.output_dir)
    os.makedirs(output_root, exist_ok=True)
    audit_path = os.path.join(output_root, "audit.log")

    # Scan unfiltered, then select: a filtered run needs every possible source to
    # tell a regenerated task's source from one it skipped.
    source_root = SOURCE_ROOT
    if args.files:
        all_targets, repository_sources = positional_targets(args.files, SOURCE_ROOT)
        if args.layered and not repository_sources and any(subdir is not None for _, subdir in all_targets):
            parser.error(
                "a layered positional run cannot mix repository source files with external files; "
                "run the two source sets separately"
            )
        ownership_targets = scan_source_targets(SOURCE_ROOT) if repository_sources else all_targets
    else:
        src_root = os.path.abspath(args.source_dir)
        source_root = src_root
        repository_sources = os.path.realpath(src_root) == os.path.realpath(SOURCE_ROOT)
        all_targets = scan_source_targets(src_root)
        ownership_targets = all_targets
    targets = [t for t in all_targets if not args.filter or args.filter in t[0]]

    reference_task_keys = None
    if args.layered and not args.allow_no_proof and repository_sources:
        keys = load_dataset_task_keys(BENCHMARK_DIR)
        if keys:
            reference_task_keys = keys
            print(f"Using existing proof-from-scratch dataset selection: {len(keys)} tasks")

    incremental = bool(args.layered and (args.filter or args.files))
    if incremental:
        reason = incremental_precondition_error(output_root)
        if reason:
            parser.error(f"a partial run needs a valid manifest to preserve the tasks it is not regenerating: {reason}")
    scope = (source_bases(ownership_targets), source_bases(targets))

    sibling_deps = compute_sibling_deps(targets) if args.shared_model else {}

    total = 0
    generated_paths = []
    manifest = {} if args.layered else None
    audit_state = {} if args.layered else None
    with open(audit_path, "w", encoding="utf-8") as audit_writer:
        for path, subdir in targets:
            print(f"\nProcessing {os.path.relpath(path, PROJECT_ROOT)}")
            key = subdir if subdir is not None else os.path.splitext(os.path.basename(path))[0]
            try:
                total += process_file(
                    path,
                    audit_writer,
                    output_root,
                    module_subdir=subdir,
                    generated_paths=generated_paths,
                    shared_model=args.shared_model,
                    skip_model_modules=sibling_deps.get(key, set()),
                    allow_no_proof=args.allow_no_proof,
                    layered=args.layered,
                    manifest=manifest,
                    audit_state=audit_state,
                    reference_task_keys=reference_task_keys,
                    source_root=source_root,
                )
            except Exception as e:
                audit_writer.write(f"[audit] {path}: ERROR {e!r}\n")
                print(f"  ERROR: {e}", file=sys.stderr)

        if args.layered:
            removed = dropped = 0
            final_count = _finalize_layered(
                output_root,
                manifest,
                audit_state,
                audit_writer,
                run_gates=not args.skip_gates,
                incremental=incremental,
                scope=scope,
                reference_task_keys=reference_task_keys,
            )
        else:
            removed = cross_dir_dedup(generated_paths, audit_writer)
            # Input SANY gate: every emitted task must parse under standalone
            # tla2sany. Flags failures (manifest + audit log); does not drop.
            sany_gate(output_root, audit_writer=audit_writer, label="sany-gate-l2")
            # Triviality gate: a task whose PROOF OBVIOUS placeholder already
            # verifies is degenerate (a no-op submission would PASS grading).
            dropped = len(
                triviality_gate(output_root, audit_writer=audit_writer, label="triviality-gate-l2", drop=True)
            )

    if args.layered:
        print(
            f"\nTotal proof-from-scratch tasks: {final_count} "
            f"({total} generated before dedup/gates; layered manifest written)"
        )
    else:
        print(
            f"\nTotal proof-from-scratch benchmarks: {total - removed - dropped} "
            f"({total} generated, {removed} removed by cross-dir dedup, {dropped} dropped as degenerate)"
        )
    print(f"Audit log: {os.path.relpath(audit_path, PROJECT_ROOT)}")


def _materialize_task(output_root, task_key, context, dest):
    """Copy a task and exactly its manifest context into `dest`.

    This is the environment the evaluator builds, so the gates below see what
    grading will see — no sibling module the manifest did not assign.
    """
    import shutil

    shutil.copy2(os.path.join(output_root, task_key), os.path.join(dest, os.path.basename(task_key)))
    for rel in context:
        shutil.copy2(os.path.join(output_root, rel), os.path.join(dest, os.path.basename(rel)))
    return os.path.join(dest, os.path.basename(task_key))


def layered_sany_gate(output_root, manifest, audit_writer, jobs=16):
    """Every task must parse under standalone SANY with only its own context.

    The suite-wide `sany_gate` cannot serve here: it finds tasks by filename and
    hands each one every sibling module in the directory, so it would both miss
    manifest tasks and hide a missing context entry. Flags; does not drop.
    """
    import tempfile
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from dataset.sany_audit import validate_task

    def check(item):
        task_key, entry = item
        with tempfile.TemporaryDirectory(prefix="layered_sany_") as tmp:
            path = _materialize_task(output_root, task_key, entry["context"], tmp)
            ok, err = validate_task(path, tmp)
            return task_key, ok, err

    failures = []
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(check, it) for it in manifest.items()]
        for fut in as_completed(futs):
            task_key, ok, err = fut.result()
            if not ok:
                failures.append((task_key, err))
                audit_writer.write(f"[audit] {task_key}: FAILED standalone SANY with its manifest context — {err}\n")

    if failures:
        print(f"⚠️  [layered-sany-gate] {len(failures)}/{len(manifest)} task(s) FAILED standalone SANY")
        for task_key, err in sorted(failures):
            print(f"     {task_key}: {err[:160]}")
    return sorted(failures)


def layered_triviality_gate(output_root, manifest, audit_writer, jobs=16, timeout=120, retry_timeout=None):
    """Drop tasks whose `PROOF OBVIOUS` placeholder already verifies.

    Such a task is worthless: an empty submission PASSes grading. Checked with
    the task's exact context so the verdict matches what the grader will do.

    A timeout is not a verdict, so every timed-out task is re-checked once on the
    grader's own (larger) budget, un-confounded by the 16-wide load here. After
    the re-check a task is dropped if its placeholder verifies; kept if it
    reaches a real "does not verify" (a no-op cannot PASS grading either); or
    reported as errored if the gate still cannot judge it (a second timeout or an
    unresolved module), so the caller leaves the dataset unchanged.

    Returns `(dropped, slow, errored)`.
    """
    import tempfile
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from common.check_proof import resolve_timeout
    from dataset.triviality_audit import (
        check_task,
        find_tlapm,
        find_tlapm_lib,
        is_indeterminate,
        is_missing_module,
    )
    from tlacore.tlapm.locate import find_community_lib

    # A degenerate task PASSes with an empty submission, so skipping this check
    # silently would ship one. `--skip-gates` is the deliberate opt-out.
    tlapm_path = find_tlapm()
    if not tlapm_path:
        raise RuntimeError("tlapm not found — cannot run the layered triviality gate (pass --skip-gates to bypass)")
    tlapm_lib = find_tlapm_lib(tlapm_path)
    if not tlapm_lib:
        raise RuntimeError("tlapm lib not found — cannot run the layered triviality gate (pass --skip-gates to bypass)")

    # Give tlapm the same Community Modules the grader supplies; the throwaway
    # check dir is outside the repo, so resolve it once here.
    community_lib = find_community_lib()

    # Re-check on the grader's deadline: "does not verify within the budget
    # grading allows" is exactly "a no-op submission cannot PASS".
    retry_timeout = retry_timeout or max(timeout, resolve_timeout(None))

    def check(item):
        task_key, entry = item
        with tempfile.TemporaryDirectory(prefix="layered_triv_") as tmp:
            path = _materialize_task(output_root, task_key, entry["context"], tmp)
            return task_key, check_task(path, tlapm_path, tlapm_lib, timeout, community_lib=community_lib)

    flagged, timed_out, errored = [], [], []
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(check, it) for it in manifest.items()]
        for fut in as_completed(futs):
            task_key, (degenerate, detail) = fut.result()
            if degenerate:
                flagged.append(task_key)
                audit_writer.write(f"[audit] {task_key}: degenerate (placeholder verifies) — dropped — {detail}\n")
            elif is_missing_module(detail):
                errored.append(task_key)
                audit_writer.write(
                    f"[audit] {task_key}: could not judge — {detail}; supply the module the grader uses\n"
                )
            elif is_indeterminate(detail):
                timed_out.append(task_key)

    slow = []
    if timed_out:
        print(
            f"[layered-triviality-gate] re-checking {len(timed_out)} timed-out task(s) "
            f"on the grader's {retry_timeout}s budget"
        )

        def recheck(task_key):
            with tempfile.TemporaryDirectory(prefix="layered_triv_retry_") as tmp:
                path = _materialize_task(output_root, task_key, manifest[task_key]["context"], tmp)
                return task_key, check_task(path, tlapm_path, tlapm_lib, retry_timeout, community_lib=community_lib)

        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = [ex.submit(recheck, key) for key in sorted(timed_out)]
            for fut in as_completed(futs):
                task_key, (degenerate, detail) = fut.result()
                if degenerate:
                    flagged.append(task_key)
                    audit_writer.write(
                        f"[audit] {task_key}: degenerate (placeholder verifies on the re-check) — dropped — {detail}\n"
                    )
                elif is_missing_module(detail):
                    errored.append(task_key)
                    audit_writer.write(
                        f"[audit] {task_key}: could not judge on the re-check — {detail}; "
                        f"supply the module the grader uses\n"
                    )
                elif is_indeterminate(detail):
                    # A second timeout is still a non-verdict (the re-check runs
                    # 16-wide too), so fail rather than ship an unjudged task.
                    errored.append(task_key)
                    audit_writer.write(
                        f"[audit] {task_key}: could not judge — timed out again on the grader's "
                        f"{retry_timeout}s budget (resource contention); regenerate\n"
                    )
                else:
                    slow.append(task_key)
                    audit_writer.write(
                        f"[audit] {task_key}: kept — the placeholder did not verify within the grader's "
                        f"{retry_timeout}s budget, so a no-op submission cannot PASS grading either\n"
                    )

    for task_key in flagged:
        del manifest[task_key]
        path = os.path.join(output_root, task_key)
        if os.path.exists(path):
            os.remove(path)
    if flagged:
        print(f"⚠️  [layered-triviality-gate] dropped {len(flagged)} degenerate task(s)")
    if slow:
        print(f"[layered-triviality-gate] kept {len(slow)} task(s) that exceed the grader's budget unproved")
    if errored:
        print(f"⚠️  [layered-triviality-gate] {len(errored)} task(s) could not be judged — generation error")
    return sorted(flagged), sorted(slow), sorted(errored)


def sweep_unreferenced_context(output_root, manifest, audit_writer):
    """Delete context files no surviving task references."""
    still_used = {rel for entry in manifest.values() for rel in entry["context"]}
    removed = 0
    for root, _dirs, files in os.walk(output_root, topdown=False):
        for fname in sorted(files):
            if not fname.endswith(".tla"):
                continue
            rel = os.path.relpath(os.path.join(root, fname), output_root).replace(os.sep, "/")
            if rel in manifest or rel in still_used:
                continue
            os.remove(os.path.join(root, fname))
            audit_writer.write(f"[audit] {rel}: unreferenced by any task — removed\n")
            removed += 1
        if root != output_root and not os.listdir(root):
            os.rmdir(root)
    return removed


def layered_cross_dir_dedup(output_root, manifest, audit_writer, preferred_dir="Data"):
    """Filter C for the layered layout — drop a task whose scaffold AND whole
    read-only context are byte-identical to another directory's (the `Sets_*`
    pairs under `Consensus/` and `Data/`). Identity spans the context because
    the task file is a thin scaffold: two tasks are the same prompt only if
    their given semantics match. Returns the number removed.
    """
    import hashlib

    def digest(task_key):
        h = hashlib.sha256()
        for rel in [task_key] + list(manifest[task_key]["context"]):
            h.update(os.path.basename(rel).encode())
            with open(os.path.join(output_root, rel), "rb") as f:
                h.update(f.read())
        return h.hexdigest()

    groups = {}
    for task_key in manifest:
        groups.setdefault(digest(task_key), []).append(task_key)

    removed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        preferred = sorted(k for k in group if k.split("/")[0] == preferred_dir)
        keeper = preferred[0] if preferred else sorted(group)[0]
        for task_key in group:
            if task_key == keeper:
                continue
            del manifest[task_key]
            os.remove(os.path.join(output_root, task_key))
            audit_writer.write(
                f"[audit] {task_key}: identical task and context to {keeper} — removed (filter C, cross-dir dedup)\n"
            )
            removed += 1

    # The caller sweeps once against the complete manifest; sweeping the
    # regenerated subset here would delete files a filtered run never touched.
    return removed


def write_pruned_deps(output_root, audit_state, audit_writer):
    """Write every dependency module, pruned to the union of what its users need.

    Deferred to finalize because several tasks — sometimes from different source
    files — share one dependency filename, so the kept set is only known once
    every task has been emitted.
    """
    deps = (audit_state or {}).get("deps", {})
    written = 0
    for task_dir, entry in sorted(deps.items()):
        # One closure over the task's dependencies together: they reference each
        # other, so closing per file prunes what a sibling still needs.
        keep = dep_keep_names(
            entry["paths"],
            entry["seeds"],
            audit_writer,
            source_defined=entry.get("source_defined", ()),
            instance_modules=entry.get("instance_modules"),
            qualified_uses=entry.get("qualified_uses", ()),
            imported_modules=entry.get("imported_modules", ()),
        )
        dest_dir = os.path.join(output_root, *task_dir.split("/"))
        os.makedirs(dest_dir, exist_ok=True)
        for dep_path in entry["paths"]:
            text = prune_dep_text(dep_path, keep, audit_writer)
            dest = os.path.join(dest_dir, os.path.basename(dep_path))
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
            if _THEOREM_SCAN.search(text):
                audit_writer.write(f"[audit] LEAK dependency {task_dir}/{os.path.basename(dep_path)} states a goal\n")
            written += 1
    return written


def validate_layered_output(output_root, manifest, audit_writer):
    """Reject prompt-visible tails and proof artifacts in read-only context."""
    context_files = {rel for entry in manifest.values() for rel in entry["context"]}
    all_files = set(manifest) | context_files
    errors = []

    for rel in sorted(all_files):
        path = os.path.join(output_root, rel)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        _module, tail = _split_outer_module(text)
        if tail is None:
            errors.append(f"{rel}: no complete outer module terminator")
        elif tail.strip():
            errors.append(f"{rel}: content remains after the outer module terminator")
        if rel in context_files:
            artifact = _PROOF_ARTIFACT_SCAN.search(strip_comments(text))
            if artifact:
                errors.append(f"{rel}: read-only context contains proof artifact `{artifact.group(0).strip()}`")

    for error in errors:
        audit_writer.write(f"[audit] {error}\n")
    if errors:
        raise RuntimeError(f"generated read-only context failed integrity validation ({len(errors)} error(s))")


def incremental_precondition_error(output_root):
    """Why a partial run must not touch `output_root`, or None if it may.

    A partial run trusts the stored manifest to know what it is not
    regenerating. Without one it would treat its own tasks as the whole dataset
    and sweep everything else away, so refuse before writing anything.
    """
    manifest_path = os.path.join(output_root, MANIFEST_FILENAME)
    has_tla = any(f.endswith(".tla") for _r, _d, files in os.walk(output_root) for f in files)
    if not has_tla:
        return None  # empty output dir: nothing to lose
    if not os.path.isfile(manifest_path):
        return f"{output_root} already holds .tla files but no {MANIFEST_FILENAME}"
    try:
        with open(manifest_path, encoding="utf-8") as f:
            if not isinstance(json.load(f), dict):
                return f"{manifest_path} is not a JSON object"
    except (OSError, json.JSONDecodeError) as e:
        return f"{manifest_path} is unreadable ({e})"
    return None


def source_bases(targets):
    """Map output subdir -> the source module basenames it is generated from."""
    bases = {}
    for path, subdir in targets:
        stem = os.path.splitext(os.path.basename(path))[0]
        bases.setdefault(subdir if subdir is not None else stem, set()).add(stem)
    return bases


def tasks_owned_by(existing, all_bases, processed_bases):
    """Stored task keys whose source module was regenerated by this run.

    A task is named `<source-stem>_<target>`, so its owner is the LONGEST source
    basename prefixing it: `TwoPhase_proof_line17` belongs to `TwoPhase_proof`,
    not to the sibling source `TwoPhase`. The caller drops these before adding
    the new output, so a target no longer emitted disappears rather than
    lingering from the previous manifest.
    """
    owned = set()
    for key in existing:
        parts = key.split("/")
        if len(parts) < 2:
            continue
        subdir, stem = parts[0], os.path.splitext(parts[-1])[0]
        candidates = [b for b in all_bases.get(subdir, ()) if stem == b or stem.startswith(f"{b}_")]
        if candidates and max(candidates, key=len) in processed_bases.get(subdir, ()):
            owned.add(key)
    return owned


def _load_existing_manifest(output_root):
    path = os.path.join(output_root, MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _finalize_layered(
    output_root,
    manifest,
    audit_state,
    audit_writer,
    run_gates=True,
    incremental=False,
    scope=None,
    reference_task_keys=None,
):
    """Dedup, gate, audit isolation, then write manifest.json.

    Both gates run against each task's exact manifest context, so their verdict
    is the one the grader will reach. Each `<task>Defs.tla` must belong to
    exactly one task; anything shared is flagged as a leak.

    `incremental` (a `--filter` run) drops every stored task belonging to a
    regenerated source and replaces it with this run's output, leaving skipped
    sources untouched. `scope` is `(all_bases, processed_bases)`.
    """
    existing = _load_existing_manifest(output_root) if incremental else {}
    all_bases, processed_bases = scope or ({}, {})
    superseded = tasks_owned_by(existing, all_bases, processed_bases) if incremental else set(existing)

    write_pruned_deps(output_root, audit_state, audit_writer)

    removed = layered_cross_dir_dedup(output_root, manifest, audit_writer)

    dropped = []
    if run_gates:
        layered_sany_gate(output_root, manifest, audit_writer)
        dropped, _slow, _errored = layered_triviality_gate(output_root, manifest, audit_writer)

    for key in sorted(superseded - set(manifest)):
        audit_writer.write(f"[audit] {key}: no longer generated by its source — removed from the manifest\n")
    complete = {k: v for k, v in existing.items() if k not in superseded}
    complete.update(manifest)
    validate_layered_output(output_root, complete, audit_writer)
    sweep_unreferenced_context(output_root, complete, audit_writer)

    if reference_task_keys is not None:
        if incremental:
            expected = tasks_owned_by(reference_task_keys, all_bases, processed_bases)
            actual = tasks_owned_by(complete, all_bases, processed_bases)
        else:
            expected = set(reference_task_keys)
            actual = set(complete)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        for key in missing:
            audit_writer.write(f"[audit] {key}: existing dataset task was not regenerated\n")
        for key in unexpected:
            audit_writer.write(f"[audit] {key}: generated task is not in the existing dataset selection\n")
        print(
            f"Dataset selection: {len(expected)} reference, {len(actual)} generated "
            f"({len(missing)} missing, {len(unexpected)} unexpected)"
        )

    owners = (audit_state or {}).get("defs_owner", {})
    owners = {k: [t for t in v if t in manifest] for k, v in owners.items()}
    owners = {k: v for k, v in owners.items() if v}
    for defs_key, task_keys in sorted(owners.items()):
        if len(task_keys) > 1:
            audit_writer.write(
                f"[audit] LEAK Defs {defs_key} is shared by multiple tasks {sorted(task_keys)} "
                f"— target-specific definitions must belong to exactly one task\n"
            )

    manifest_path = os.path.join(output_root, MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(complete.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")
    scope = f"{len(manifest)} regenerated, {len(complete)} total" if incremental else f"{len(complete)} tasks"
    print(
        f"Manifest: {os.path.relpath(manifest_path, PROJECT_ROOT)} "
        f"({scope}, {removed} removed by cross-dir dedup, {len(dropped)} dropped as degenerate)"
    )
    return len(complete)


if __name__ == "__main__":
    main()

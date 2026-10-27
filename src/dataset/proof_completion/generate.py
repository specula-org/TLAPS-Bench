#!/usr/bin/env python3
"""
Generate TLAPS benchmarks from TLA+ proof files.

For each THEOREM/LEMMA/COROLLARY/PROPOSITION with a proof in the source files,
generate a standalone .tla file where:
- All preceding theorems are admitted (PROOF OMITTED)
- The target theorem has its proof stripped (so TLAPS will fail, requiring proof)
- Files with local EXTENDS dependencies are merged into the benchmark file
- Files with INSTANCE dependencies have dependency files copied alongside
- Each benchmark file works standalone (with its dependency files)

Layered layout (default, Issue #86)
-----------------------------------
The layouts above put the whole task in ONE editable module, so an agent can
"prove" the goal by weakening the specification, redefining the scaffolding, or
restating the theorem. The default generator splits each task by ownership
instead:

    <base>Model.tla        declarations, assumptions, state machine, Spec, fairness
    <task>Scaffold.tla     this target's given definitions + preceding lemmas
                           (structured proofs admitted as PROOF OMITTED)
    <task>.tla             the target theorem, the markers, the proof

Unlike proof-from-scratch, the scaffolding is deliberately kept: proof completion
gives the agent the invariants and the preceding lemmas. What changes is that
they now live in benchmark-owned modules the agent cannot write, and the target
theorem statement sits in the fixed part of the submitted file, so only the
marked proof region is editable:

    \\* BEGIN AGENT PROOF / \\* END AGENT PROOF     the proof

A suite-level `manifest.json` maps each task to its originating specification
and the exact read-only modules assigned to it, so the evaluator never infers
context by copying siblings. The marker strings and manifest schema come from
`src/common/task_contract.py` — the same contract the evaluator parses — and
every emitted task is re-read through it before the manifest is written.
"""

import glob
import json
import os
import re
import sys
from pathlib import Path

from common import tla_modules as _tla_modules
from common.proof_completion_contract import (
    BEGIN_AGENT_PROOF,
    END_AGENT_PROOF,
    load_proof_completion_manifest,
    parse_proof_completion_region,
)
from common.task_contract import MANIFEST_FILENAME
from dataset.proof_completion.reference_steps import count_reference_proof_steps, reference_proof_steps_for_name
from dataset.specification_identity import source_spec_id

COMMUNITY_MODULES = _tla_modules.COMMUNITY_MODULES
RESOLVABLE_MODULES = _tla_modules.RESOLVABLE_MODULES
STDLIB_MODULES = _tla_modules.STDLIB_MODULES

# Directories to process (top-level module dirs).
# File lives at <repo>/src/dataset/proof_completion/generate.py; ascend three levels for the repo root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SOURCE_ROOT = os.path.join(PROJECT_ROOT, "source")
BENCHMARK_DIR = os.path.join(PROJECT_ROOT, "benchmark", "proof-completion")
_DUPLICATE_TASK_FAMILIES_PATH = os.path.join(os.path.dirname(__file__), "duplicate_task_families.json")
_KNOWN_DEGENERATE_PATH = os.path.join(os.path.dirname(__file__), "known_degenerate_targets.json")


def find_source_dirs():
    """Find all top-level module directories under source/ containing .tla files."""
    dirs = set()
    for f in glob.glob(os.path.join(SOURCE_ROOT, "**", "*.tla"), recursive=True):
        if ".tlaps" in f:
            continue
        rel = os.path.relpath(f, SOURCE_ROOT)
        parts = rel.split(os.sep)
        if len(parts) >= 2:
            dirs.add(parts[0])
    return sorted(dirs)


def find_tla_files(module_dir):
    """Find all .tla files in a module directory (excluding .tlaps subdirs)."""
    files = []
    for f in glob.glob(os.path.join(module_dir, "**", "*.tla"), recursive=True):
        if ".tlaps" in f:
            continue
        files.append(f)
    return files


def parse_module_name(content):
    """Extract the MODULE name from TLA+ content."""
    m = re.search(r"-+\s*MODULE\s+(\w+)\s*-+", content)
    return m.group(1) if m else None


def parse_extends(content):
    """Extract EXTENDS modules from TLA+ content.

    Handles `\\*` line comments (e.g. tlaplus_examples_glowingRaccoon's
    `EXTENDS Naturals \\* an import`) and multi-line EXTENDS that wraps onto
    indented continuation lines (e.g. tlaplus_examples_allocator's
    SchedulingAllocator_proof).
    """
    lines = content.split("\n")
    for i, line in enumerate(lines):
        m = re.match(r"^EXTENDS\s+(.+)$", line)
        if not m:
            continue
        parts = []
        cur = m.group(1)
        j = i
        while True:
            code = re.split(r"\\\*", cur)[0]  # drop trailing line comment
            parts.append(code)
            if code.rstrip().endswith(","):
                j += 1
                if j < len(lines):
                    cur = lines[j]
                    continue
            break
        joined = " ".join(parts)
        return [x.strip() for x in joined.split(",") if x.strip()]
    return []


def parse_instances(content):
    """Extract INSTANCE references (local module references, not stdlib)."""
    instances = []
    for m in re.finditer(r"(?:(\w+)\s*==\s*)?INSTANCE\s+(\w+)", content):
        alias = m.group(1)
        mod = m.group(2)
        if mod not in RESOLVABLE_MODULES:
            instances.append((alias, mod))
    return instances


def get_local_dependencies(content, available_modules):
    """Get set of local module names this content depends on."""
    deps = set()
    for ext in parse_extends(content):
        if ext in available_modules and ext not in RESOLVABLE_MODULES:
            deps.add(ext)
    for _, mod in parse_instances(content):
        if mod in available_modules:
            deps.add(mod)
    return deps


def get_extends_dependencies(content, available_modules):
    """Get set of local module names this content EXTENDS (safe to merge)."""
    deps = set()
    for ext in parse_extends(content):
        if ext in available_modules and ext not in RESOLVABLE_MODULES:
            deps.add(ext)
    return deps


def get_instance_dependencies(content, available_modules):
    """Get set of local module names this content INSTANCEs (need to copy, not merge)."""
    deps = set()
    for _, mod in parse_instances(content):
        if mod in available_modules:
            deps.add(mod)
    return deps


def get_all_instance_deps(mod, files_by_module, visited=None):
    """Get all transitive INSTANCE + EXTENDS dependencies that need to be copied as files."""
    if visited is None:
        visited = set()
    filepath = files_by_module.get(mod)
    if not filepath:
        return visited
    with open(filepath) as f:
        content = f.read()
    available = set(files_by_module.keys())
    # All dependencies of INSTANCE'd modules (both EXTENDS and INSTANCE) need to be copied
    for _, inst_mod in parse_instances(content):
        if inst_mod in available and inst_mod not in visited:
            visited.add(inst_mod)
            # Recursively get all deps of this module
            get_all_file_deps(inst_mod, files_by_module, visited)
    return visited


def get_all_file_deps(mod, files_by_module, visited=None):
    """Get ALL transitive dependencies of a module (both EXTENDS and INSTANCE)."""
    if visited is None:
        visited = set()
    filepath = files_by_module.get(mod)
    if not filepath:
        return visited
    with open(filepath) as f:
        content = f.read()
    available = set(files_by_module.keys())
    for dep in get_local_dependencies(content, available):
        if dep not in visited:
            visited.add(dep)
            get_all_file_deps(dep, files_by_module, visited)
    return visited


def build_dependency_graph(files_by_module):
    """Build a dependency graph: module -> set of local modules it depends on."""
    available = set(files_by_module.keys())
    graph = {}
    for mod, filepath in files_by_module.items():
        with open(filepath) as f:
            content = f.read()
        graph[mod] = get_local_dependencies(content, available)
    return graph


def topo_sort(graph):
    """Topological sort of modules."""
    visited = set()
    order = []
    temp = set()

    def visit(node):
        if node in temp:
            return  # cycle, skip
        if node in visited:
            return
        temp.add(node)
        for dep in graph.get(node, set()):
            visit(dep)
        temp.discard(node)
        visited.add(node)
        order.append(node)

    for node in graph:
        visit(node)
    return order


def find_all_deps(mod, graph, visited=None):
    """Find all transitive dependencies of a module."""
    if visited is None:
        visited = set()
    for dep in graph.get(mod, set()):
        if dep not in visited:
            visited.add(dep)
            find_all_deps(dep, graph, visited)
    return visited


class TheoremInfo:
    """Represents a theorem/lemma found in the source."""

    def __init__(self, keyword, name, statement_start, statement_end, proof_start, proof_end, has_proof):
        self.keyword = keyword  # THEOREM, LEMMA, etc.
        self.name = name
        self.statement_start = statement_start  # line index of the keyword line
        self.statement_end = statement_end  # line index of last line of statement (before PROOF/BY/OBVIOUS/OMITTED)
        self.proof_start = proof_start  # line index of first proof line (None if no proof)
        self.proof_end = proof_end  # line index of last proof line
        self.has_proof = has_proof  # True if has a non-trivial proof


def find_proof_end(lines, start_idx):
    """Find the end of a proof starting from start_idx.

    A proof ends when we encounter another top-level definition/theorem/separator
    or end of module. We must be careful not to stop on ASSUME/SUFFICES etc. that
    appear inside proof steps.
    """
    i = start_idx

    while i < len(lines):
        line = lines[i].strip()

        # End of module
        if re.match(r"^={3,}", line):
            return i - 1

        if i > start_idx:
            # A new top-level theorem/lemma (these only appear at column 0)
            if re.match(r"^(THEOREM|LEMMA|COROLLARY|PROPOSITION)\s", line):
                return i - 1
            # Separator line
            if re.match(r"^-{3,}", line):
                return i - 1
            # New top-level operator definition: must start at column 0 with a name
            # and == but NOT be a proof step. Also exclude lines that are indented
            # or inside proof context.
            orig_line = lines[i]
            if orig_line and not orig_line[0].isspace():
                # At column 0, not indented
                if re.match(r"^\w+(\(.*?\))?\s*==(\s|$)", line) and not re.match(r"^<\d+>", line):
                    return i - 1
                # Top-level CONSTANT/VARIABLE/AXIOM/ASSUME declarations (at column 0 only)
                if re.match(r"^(CONSTANT|CONSTANTS|VARIABLE|VARIABLES|AXIOM|ASSUME|ASSUMPTION)\s", line):
                    return i - 1

        i += 1

    return i - 1


def parse_theorems(lines):
    """Parse all theorems/lemmas from TLA+ file lines.

    Returns list of TheoremInfo objects.
    """
    theorems = []
    i = 0
    comment_depth = 0

    while i < len(lines):
        line = lines[i].strip()

        # Skip lines inside block comments
        if comment_depth > 0:
            for j in range(len(lines[i]) - 1):
                if lines[i][j : j + 2] == "(*":
                    comment_depth += 1
                elif lines[i][j : j + 2] == "*)":
                    comment_depth -= 1
            i += 1
            continue

        # Track comment opens on this line
        line_depth = 0
        for j in range(len(lines[i]) - 1):
            if lines[i][j : j + 2] == "(*":
                line_depth += 1
            elif lines[i][j : j + 2] == "*)":
                line_depth -= 1
        if line_depth > 0:
            comment_depth = line_depth
            i += 1
            continue

        # Match theorem/lemma declaration with a name
        m = re.match(r"^(THEOREM|LEMMA|COROLLARY|PROPOSITION)\s+(\w+)\s*==", line)
        if not m:
            # Also match unnamed theorems like "THEOREM Spec => []Inv"
            m2 = re.match(r"^(THEOREM|LEMMA|COROLLARY|PROPOSITION)\s+(.+)", line)
            if m2 and "==" not in line:
                m = m2  # treat as unnamed theorem, fall through
            if not m:
                i += 1
                continue

        keyword = m.group(1)
        name = f"__unnamed_{i}" if "==" not in line else m.group(2)
        stmt_start = i

        # Scan forward to find where the proof starts (or where the theorem ends)
        # The theorem statement can span multiple lines (ASSUME ... PROVE ...)
        # Proof indicators: PROOF, <N>, BY (at start of line or after statement), OBVIOUS, OMITTED
        proof_start = None
        has_proof = False

        # Check the first line itself for single-line proofs
        # e.g. "THEOREM X == ... BY DEFS ..." or "THEOREM X == ... OBVIOUS"
        # But be careful: "BY" inside the statement body is different
        # For single-line: the theorem declaration + proof are all on one line
        first_line = lines[i]
        # Check for trailing BY/OBVIOUS/OMITTED on the declaration line
        # Only if the entire theorem is on one line (has == and then proof keyword)
        if re.search(r"\bBY\s", first_line) or re.search(r"\bPROOF\s+BY\s", first_line):
            proof_start = i
            has_proof = True
        elif (
            re.search(r"\bOBVIOUS\s*$", first_line)
            or re.search(r"\bOMITTED\s*$", first_line)
            or re.search(r"\bPROOF\s+OMITTED\s*$", first_line)
        ):
            proof_start = i
            has_proof = False

        if proof_start is None:
            j = i + 1
            inner_comment_depth = 0
            while j < len(lines):
                sline = lines[j].strip()
                orig = lines[j]

                # Track comment depth
                line_cd = 0
                for ci in range(len(orig) - 1):
                    if orig[ci : ci + 2] == "(*":
                        line_cd += 1
                    elif orig[ci : ci + 2] == "*)":
                        line_cd -= 1
                inner_comment_depth += line_cd
                if inner_comment_depth > 0:
                    j += 1
                    continue

                # End of module
                if re.match(r"^={3,}", sline):
                    break

                # Another top-level theorem/lemma (not indented)
                if re.match(r"^(THEOREM|LEMMA|COROLLARY|PROPOSITION)\s", sline) and (not orig or not orig[0].isspace()):
                    break

                # Separator
                if re.match(r"^-{3,}", sline):
                    break

                # Top-level definitions (not indented, at column 0)
                if orig and not orig[0].isspace():
                    if re.match(r"^[A-Z]\w*(\(.*?\))?\s*==(\s|$)", sline) and not re.match(r"^<\d+>", sline):
                        break
                    # Definitions starting with digits (e.g., 1bOr2bMsgs ==)
                    if re.match(r"^\d\w*\s*==(\s|$)", sline) and not re.match(r"^<\d+>", sline):
                        break
                    if re.match(r"^(CONSTANT|CONSTANTS|VARIABLE|VARIABLES)\s", sline):
                        break

                # Proof indicators
                if sline == "PROOF" or re.match(r"^PROOF\s+BY\s", sline):
                    proof_start = j
                    has_proof = True
                    break
                if sline == "OBVIOUS" or sline.startswith("OBVIOUS "):
                    proof_start = j
                    has_proof = False
                    break
                # Missing this left the line orphaned when the theorem was
                # rewritten: a copied dependency carried both `PROOF OMITTED`
                # and a stray `PROOF OBVIOUS`, and SANY rejected the module.
                if sline == "PROOF OBVIOUS" or sline.startswith("PROOF OBVIOUS "):
                    proof_start = j
                    has_proof = False
                    break
                if sline == "OMITTED" or sline == "PROOF OMITTED" or sline.startswith("PROOF OMITTED "):
                    proof_start = j
                    has_proof = False
                    break
                if re.match(r"^<\d+>", sline):
                    proof_start = j
                    has_proof = True
                    break
                # BY at start of line (possibly indented)
                if re.match(r"^\s*BY\s", orig) or sline.startswith("BY ") or sline == "BY":
                    proof_start = j
                    has_proof = True
                    break

                j += 1

        if proof_start is not None:
            stmt_end = (proof_start - 1) if proof_start > stmt_start else stmt_start
            proof_end = find_proof_end(lines, proof_start)
        else:
            # No proof body in source — the forward scan stopped at `j` (the next
            # top-level declaration or end of module). A theorem's multi-line
            # statement is its keyword line plus any *indented* continuation
            # lines (TLA+ uses indentation to denote line continuation). Blank
            # lines and comment blocks (col-0) between this theorem and the
            # next decl belong to the next decl, not to this one.
            stmt_end = stmt_start
            for k in range(stmt_start + 1, j):
                line = lines[k]
                if not line.strip():
                    continue  # blank line — not part of statement
                if not line[0].isspace():
                    break  # col-0 line (comment block or other) — not a continuation
                stmt_end = k
            proof_end = stmt_end

        # Include all theorems (even OMITTED/OBVIOUS) so generate_benchmark_file
        # can properly handle their line ranges (e.g., skip commented proof sketches)
        theorems.append(TheoremInfo(keyword, name, stmt_start, stmt_end, proof_start, proof_end, has_proof))

        i = (proof_end + 1) if proof_end is not None else (j if proof_start is None else proof_end + 1)
        continue

    return theorems


def extract_preamble(lines, theorems):
    """Extract everything before the first theorem - the preamble (module header, extends, constants, vars, defs)."""
    if not theorems:
        return lines[:]
    return lines[: theorems[0].statement_start]


def get_theorem_statement_lines(lines, thm):
    """Get the statement lines of a theorem (without proof)."""
    # Handle single-line theorem with proof on same line
    if thm.proof_start == thm.statement_start:
        line = lines[thm.statement_start]
        # Remove the BY/OBVIOUS/OMITTED part
        # Find the theorem body by removing proof
        for pat in [r"\s+BY\s+.*$", r"\s+OBVIOUS\s*$", r"\s+OMITTED\s*$", r"\s+PROOF\s+OMITTED\s*$"]:
            line = re.sub(pat, "", line)
        return [line]

    result = lines[thm.statement_start : thm.statement_end + 1]
    # Clean trailing empty lines
    while result and result[-1].strip() == "":
        result.pop()
    # Remove trailing comment blocks that contain proof steps (e.g. <1>2.)
    # Properly handle nested/inline comments like (* PTL *)
    while result:
        last = len(result) - 1
        if result[last].strip().endswith("*)"):
            # Scan backward tracking comment depth to find the matching opener
            depth = 0
            comment_start = None
            for j in range(last, -1, -1):
                line_text = result[j]
                # Count opens/closes on this line (scan left to right)
                opens = 0
                closes = 0
                for k in range(len(line_text) - 1):
                    if line_text[k : k + 2] == "(*":
                        opens += 1
                    elif line_text[k : k + 2] == "*)":
                        closes += 1
                depth += closes - opens  # going backward: closes add depth, opens reduce
                if depth <= 0 and opens > 0:
                    comment_start = j
                    break
            if comment_start is not None and comment_start > 0:
                comment_text = "\n".join(result[comment_start : last + 1])
                if re.search(r"<\d+>", comment_text):
                    result = result[:comment_start]
                    while result and result[-1].strip() == "":
                        result.pop()
                    continue
        break
    return result


def get_theorem_proof_lines(lines, thm):
    """Dual of get_theorem_statement_lines: return a theorem's proof body lines.

    For an inline proof (proof on the same line as the declaration, e.g.
    'LEMMA Foo == x  BY DEF y'), return only the proof tail (['BY DEF y'])
    rather than the whole declaration line -- otherwise porting the proof into
    a benchmark re-declares the theorem and produces a malformed module. For a
    multi-line proof, return lines[proof_start:proof_end+1] verbatim.
    """
    if thm.proof_start is None or not thm.has_proof:
        return []
    if thm.proof_start == thm.statement_start:
        line = lines[thm.statement_start]
        m = re.search(r"\s+(PROOF\s+BY\b.*|BY\b.*)$", line)
        return [m.group(1)] if m else [line]
    return lines[thm.proof_start : thm.proof_end + 1]


def merge_files(files_by_module, dep_graph, target_module):
    """Merge all dependencies of target_module into a single content string.

    Returns merged lines and the module name to use.
    """
    all_deps = find_all_deps(target_module, dep_graph)

    if not all_deps:
        # No local dependencies, just return the file content
        with open(files_by_module[target_module]) as f:
            return f.readlines(), target_module

    # Topological order of all deps + target
    order = topo_sort(dep_graph)
    relevant = [m for m in order if m in all_deps or m == target_module]

    # Merge: collect all extends (stdlib only), then all content from each module
    all_extends = set()
    merged_body_lines = []

    for mod in relevant:
        with open(files_by_module[mod]) as f:
            content = f.read()

        mod_lines = content.split("\n")

        # Collect resolvable extends
        for ext in parse_extends(content):
            if ext in RESOLVABLE_MODULES:
                all_extends.add(ext)

        # Extract body (between MODULE header and ending ====)
        body_start = None
        body_end = None
        for idx, line in enumerate(mod_lines):
            if body_start is None and re.match(r"^-+\s*MODULE\s+\w+\s*-+", line.strip()):
                body_start = idx + 1
            if re.match(r"^={3,}", line.strip()):
                body_end = idx

        if body_start is None:
            continue
        if body_end is None:
            body_end = len(mod_lines)

        body = mod_lines[body_start:body_end]

        # Remove EXTENDS line(s) from body (we'll put a unified one). Skip the
        # EXTENDS line and any continuation lines of a multi-line EXTENDS, whose
        # wrapped 2nd line would otherwise be orphaned and cause a parse error
        # (e.g. tlaplus_examples_allocator's SchedulingAllocator_proof).
        filtered_body = []
        in_extends = False
        for line in body:
            if in_extends:
                # still consuming continuation lines of a multi-line EXTENDS;
                # stop after a line whose code part lacks a trailing comma
                code = re.split(r"\\\*", line)[0].rstrip()
                in_extends = code.endswith(",")
                continue
            if re.match(r"^EXTENDS\s", line.strip()):
                code = re.split(r"\\\*", line)[0].rstrip()
                in_extends = code.endswith(",")  # multi-line if trailing comma
                continue
            filtered_body.append(line)

        if mod != target_module:
            merged_body_lines.append(f"(* ---- Content from module {mod} ---- *)")
        merged_body_lines.extend(filtered_body)
        if mod != target_module:
            merged_body_lines.append("")

    # Build final content
    header_lines = []
    extends_str = ", ".join(sorted(all_extends)) if all_extends else ""

    # We'll use a placeholder module name; caller will set it
    header_lines.append("---- MODULE __PLACEHOLDER__ ----")
    if extends_str:
        header_lines.append(f"EXTENDS {extends_str}")

    result_lines = header_lines + merged_body_lines + ["=" * 40]
    return [ln + "\n" for ln in result_lines], target_module


def strip_all_proofs(lines, theorems):
    """Strip all proofs from a file, replacing them with PROOF OMITTED.

    Used for dependency files that are copied alongside benchmarks.
    """
    result = []
    i = 0
    while i < len(lines):
        found_thm = None
        for idx, thm in enumerate(theorems):
            if i == thm.statement_start:
                found_thm = idx
                break

        if found_thm is not None:
            thm = theorems[found_thm]
            end = thm.proof_end if thm.proof_end is not None else thm.statement_end
            if not thm.has_proof and thm.proof_start is not None:
                # Source already has explicit OMITTED/OBVIOUS — copy verbatim
                for li in range(thm.statement_start, end + 1):
                    result.append(lines[li])
            else:
                # Either has a real proof (which we strip) OR has no proof at all
                # (in which case we still need to mark it OMITTED so the file parses
                # as a valid TLAPS module — bare THEOREM without proof obligates
                # checker to either accept or reject it).
                stmt_lines = get_theorem_statement_lines(lines, thm)
                result.extend(stmt_lines)
                result.append("  PROOF OMITTED")
                result.append("")
            i = end + 1
            continue

        # Check if inside a theorem range
        inside = False
        for thm in theorems:
            start = thm.statement_start
            end = thm.proof_end if thm.proof_end is not None else thm.statement_end
            if start < i <= end:
                inside = True
                break
        if inside:
            i += 1
            continue

        result.append(lines[i])
        i += 1

    return "\n".join(result)


def generate_benchmark_file(lines_or_content, theorems, target_idx, module_name, benchmark_name):
    """Generate a benchmark file for the target_idx-th theorem.

    - All theorems before target_idx: keep statement, add PROOF OMITTED
    - Target theorem: keep statement, remove proof entirely
    - All theorems after target_idx: removed entirely
    """
    if isinstance(lines_or_content, str):
        lines = lines_or_content.split("\n")
    else:
        lines = [ln.rstrip("\n") for ln in lines_or_content]

    # We'll rebuild the file by going through lines and replacing theorem sections
    result = []

    # Track which line ranges belong to which theorems
    thm_ranges = {}
    for idx, thm in enumerate(theorems):
        start = thm.statement_start
        end = thm.proof_end if thm.proof_end is not None else thm.statement_end
        thm_ranges[idx] = (start, end)

    i = 0
    while i < len(lines):
        # Check if this line is the start of any theorem
        found_thm = None
        for idx, thm in enumerate(theorems):
            if i == thm.statement_start:
                found_thm = idx
                break

        if found_thm is not None:
            thm = theorems[found_thm]
            stmt_lines = get_theorem_statement_lines(lines, thm)

            if found_thm < target_idx:
                # Preceding theorem: admit it
                if not thm.has_proof:
                    # Already OMITTED/OBVIOUS — copy original lines verbatim
                    end = thm.proof_end if thm.proof_end is not None else thm.statement_end
                    for li in range(thm.statement_start, end + 1):
                        result.append(lines[li])
                else:
                    result.extend(stmt_lines)
                    result.append("  PROOF OMITTED")
                    result.append("")
            elif found_thm == target_idx:
                # Target theorem: replace proof with OBVIOUS (will fail for non-trivial theorems)
                result.extend(stmt_lines)
                result.append("PROOF OBVIOUS")
                result.append("")
            else:
                # Theorems after target: skip entirely
                pass

            # Skip past the theorem's proof
            end = thm.proof_end if thm.proof_end is not None else thm.statement_end
            i = end + 1
            continue

        # Check if this line is inside a theorem range (shouldn't happen, but safety)
        inside = False
        for _idx, (start, end) in thm_ranges.items():
            if start < i <= end:
                inside = True
                break

        if inside:
            i += 1
            continue

        # For lines after the target theorem, skip non-theorem content too
        # (definitions that may depend on later theorems)
        # Actually, keep all definitions/content that appears before or between theorems
        # up to the target. After the target, only keep the module end.
        if found_thm is None:
            # Check if we're past the target theorem
            if target_idx < len(theorems) and i > theorems[target_idx].statement_start:
                # Only keep the module end line (====)
                if re.match(r"^={3,}", lines[i].strip()):
                    result.append(lines[i])
                i += 1
                continue
            result.append(lines[i])

        i += 1

    # Ensure module ends with ====
    if not any(re.match(r"^={3,}", ln.strip()) for ln in result[-3:] if ln.strip()):
        result.append("=" * 40)

    # Remove comment blocks containing proof steps (e.g. <1>2.)
    # Must properly track nested comment depth
    cleaned = []
    comment_depth = 0
    comment_buf = []
    for line in result:
        # Count comment opens/closes on this line
        line_opens = 0
        line_closes = 0
        for k in range(len(line) - 1):
            if line[k : k + 2] == "(*":
                line_opens += 1
            elif line[k : k + 2] == "*)":
                line_closes += 1

        if comment_depth == 0 and line_opens > 0:
            # Entering a comment block
            comment_depth = line_opens - line_closes
            if comment_depth > 0:
                comment_buf = [line]
            elif comment_depth == 0:
                # Single-line comment (opens and closes on same line)
                if not re.search(r"<\d+>\d+\.", line):
                    cleaned.append(line)
            # comment_depth < 0 shouldn't happen
        elif comment_depth > 0:
            comment_buf.append(line)
            comment_depth += line_opens - line_closes
            if comment_depth <= 0:
                # Comment block closed
                comment_text = "\n".join(comment_buf)
                if not re.search(r"<\d+>\d+\.", comment_text):
                    cleaned.extend(comment_buf)
                comment_buf = []
                comment_depth = 0
        else:
            cleaned.append(line)
    if comment_buf:
        cleaned.extend(comment_buf)
    result = cleaned

    # Fix unclosed comments: count (* and *) and close any open ones
    depth = 0
    for line in result:
        for j in range(len(line) - 1):
            if line[j : j + 2] == "(*":
                depth += 1
            elif line[j : j + 2] == "*)":
                depth -= 1
    # Insert closing comments before the ==== line
    if depth > 0:
        eq_idx = next(
            (i for i in range(len(result) - 1, -1, -1) if re.match(r"^={3,}", result[i].strip())), len(result)
        )
        for _ in range(depth):
            result.insert(eq_idx, "*)")

    # Replace module name in header
    final = []
    for line in result:
        if re.match(r"^-+\s*MODULE\s+\w+\s*-+", line.strip()):
            line = re.sub(r"MODULE\s+\w+", f"MODULE {benchmark_name}", line)
        if "__PLACEHOLDER__" in line:
            line = line.replace("__PLACEHOLDER__", benchmark_name)
        final.append(line)

    return "\n".join(final)


def process_module_dir(module_dir_name):
    """Process a single module directory and generate benchmarks."""
    module_path = os.path.join(SOURCE_ROOT, module_dir_name)
    tla_files = find_tla_files(module_path)

    if not tla_files:
        return 0

    # Build module -> filepath mapping
    files_by_module = {}
    for f in tla_files:
        with open(f) as fh:
            content = fh.read()
        mod_name = parse_module_name(content)
        if mod_name:
            files_by_module[mod_name] = f

    # Build dependency graph
    build_dependency_graph(files_by_module)
    available = set(files_by_module.keys())

    benchmark_count = 0
    out_dir = os.path.join(BENCHMARK_DIR, module_dir_name)

    for mod_name, filepath in files_by_module.items():
        with open(filepath) as f:
            content = f.read()

        raw_lines = content.split("\n")
        theorems = parse_theorems(raw_lines)

        if not theorems or not any(t.has_proof for t in theorems):
            continue
        # - EXTENDS local deps: merge into the benchmark file
        # - INSTANCE local deps: copy as separate files alongside benchmark
        extends_deps = get_extends_dependencies(content, available)
        instance_deps = get_instance_dependencies(content, available)

        # For EXTENDS deps, also get their transitive EXTENDS deps (for merging)
        all_extends_deps = set()
        for ed in extends_deps:
            all_extends_deps.add(ed)
            # Get transitive EXTENDS-only deps
            ed_filepath = files_by_module.get(ed)
            if ed_filepath:
                with open(ed_filepath) as f:
                    ed_content = f.read()
                all_extends_deps |= get_extends_dependencies(ed_content, available)

        # For INSTANCE deps, collect all files that need to be copied
        # (the INSTANCE'd module + all its transitive deps)
        # Include INSTANCE deps from both the main module AND merged EXTENDS deps
        files_to_copy = set()
        for inst_mod in instance_deps:
            files_to_copy.add(inst_mod)
            get_all_file_deps(inst_mod, files_by_module, files_to_copy)
        # Also get INSTANCE deps from EXTENDS deps (they're merged into the benchmark)
        for ed in all_extends_deps:
            ed_filepath = files_by_module.get(ed)
            if ed_filepath:
                with open(ed_filepath) as f:
                    ed_content = f.read()
                for _, inst_mod in parse_instances(ed_content):
                    if inst_mod in available and inst_mod not in all_extends_deps:
                        files_to_copy.add(inst_mod)
                        get_all_file_deps(inst_mod, files_by_module, files_to_copy)
        # Remove any extends deps from files_to_copy (they'll be merged)
        files_to_copy -= all_extends_deps

        # A copied dep file keeps its own EXTENDS/INSTANCE clauses, so close
        # files_to_copy under transitive deps — otherwise a merged-only module
        # that a copied dep file references is absent (e.g. tlaplus_examples_
        # MisraReachability copies Reachable but it EXTENDS Reachability).
        copy_closure = set(files_to_copy)
        for cf in list(files_to_copy):
            get_all_file_deps(cf, files_by_module, copy_closure)
        files_to_copy = copy_closure

        # Merge only EXTENDS dependencies
        if all_extends_deps:
            # Build a restricted dep graph for EXTENDS-only merging
            extends_graph = {}
            for ed in all_extends_deps:
                ed_filepath = files_by_module.get(ed)
                if ed_filepath:
                    with open(ed_filepath) as f:
                        ed_content = f.read()
                    extends_graph[ed] = get_extends_dependencies(ed_content, available) & all_extends_deps
            extends_graph[mod_name] = all_extends_deps

            merged_lines, _ = merge_files(files_by_module, extends_graph, mod_name)
            work_lines = [ln.rstrip("\n") for ln in merged_lines]
            theorems = parse_theorems(work_lines)
            if not theorems or not any(t.has_proof for t in theorems):
                continue
        else:
            work_lines = raw_lines

        # Generate one benchmark file per theorem
        source_basename = os.path.splitext(os.path.basename(filepath))[0]

        # Track used names to handle duplicates
        name_counts = {}
        for idx, thm in enumerate(theorems):
            # Skip unnamed theorems as benchmark targets (they still get PROOF OMITTED as preceding theorems)
            if thm.name.startswith("__unnamed_"):
                continue
            # Skip theorems without real proofs (PROOF OMITTED / OBVIOUS only)
            if not thm.has_proof:
                continue
            base_name = f"{source_basename}_{thm.name}"
            if base_name in name_counts:
                name_counts[base_name] += 1
                benchmark_name = f"{base_name}_{name_counts[base_name]}"
            else:
                name_counts[base_name] = 0
                benchmark_name = base_name
            benchmark_file = os.path.join(out_dir, f"{benchmark_name}.tla")

            os.makedirs(out_dir, exist_ok=True)

            content = generate_benchmark_file(work_lines, theorems, idx, mod_name, benchmark_name)

            with open(benchmark_file, "w") as f:
                f.write(content)

            # Copy INSTANCE dependency files alongside the benchmark
            # Strip all proofs from copied files (replace with PROOF OMITTED)
            # to avoid leaking proof information
            for dep_mod in files_to_copy:
                dep_filepath = files_by_module.get(dep_mod)
                if dep_filepath:
                    dest = os.path.join(out_dir, os.path.basename(dep_filepath))
                    if not os.path.exists(dest):
                        # Read, strip proofs, write
                        with open(dep_filepath) as df:
                            dep_content = df.read()
                        dep_lines = dep_content.split("\n")
                        dep_theorems = parse_theorems(dep_lines)
                        if dep_theorems:
                            # Use generate_benchmark_file logic but admit ALL theorems
                            stripped = strip_all_proofs(dep_lines, dep_theorems)
                            with open(dest, "w") as df:
                                df.write(stripped)
                        else:
                            # No theorems, just copy as-is
                            import shutil

                            shutil.copy2(dep_filepath, dest)

            benchmark_count += 1
            print(f"  Generated: {os.path.relpath(benchmark_file, SOURCE_ROOT)}")

    return benchmark_count


# ---------------------------------------------------------------------------
# Legacy shared-model proof-completion (opt-in via --legacy --shared-model). Reuses the certified proof-from-scratch dump
# engine (src/dataset/proof_from_scratch/generate.py) for the model extraction + helpers,
# and adds an proof-completion-specific task builder.
# ---------------------------------------------------------------------------
def _load_l2_engine():
    """Load the proof-from-scratch generator as the shared-model engine. proof-from-scratch does
    `from generate import ...` expecting THIS module's helpers, so alias us as
    `generate` first."""
    import importlib.util
    import sys

    sys.modules.setdefault("generate", sys.modules.get("__main__", sys.modules[__name__]))
    path = os.path.join(os.path.dirname(__file__), "..", "proof_from_scratch", "generate.py")
    spec = importlib.util.spec_from_file_location("l2_sm_engine", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["l2_sm_engine"] = mod
    spec.loader.exec_module(mod)
    return mod


def _is_structured_proof(sm, t, lines):
    """True iff the proof is a real structured/BY proof (not OBVIOUS/OMITTED).
    Strips comments first so `OBVIOUS (*{hint}*)` is seen as OBVIOUS."""
    ploc = t.get("proof_loc")
    if not (ploc and ploc.get("line_start", -1) > 0):
        return False
    proof_lines = lines[ploc["line_start"] - 1 : ploc["line_end"]]
    proof_lines[0] = proof_lines[0][ploc.get("column_start", 1) - 1 :]
    body = "".join(proof_lines)
    body = sm.strip_comments(body).strip()
    if body.startswith("PROOF"):
        body = body[5:].lstrip()
    return body not in ("OMITTED", "OBVIOUS", "")


def _proof_edit(source_lines, ploc, keyword):
    """An apply_edits tuple that replaces a proof body with `keyword`, PRESERVING
    any statement text that shares the proof's first line. One-line lemmas like
    `LEMMA X == s  BY DEF Y` put the proof (col 41) on the statement line (cols
    1-40); a whole-line replace would delete the statement and leave a stray
    `PROOF OMITTED`."""
    line = source_lines[ploc["line_start"] - 1]
    col = ploc.get("column_start", 1)
    prefix = line[: col - 1].rstrip()
    repl = (prefix + "\n  " + keyword + "\n") if prefix else (keyword + "\n")
    return (ploc["line_start"], ploc["line_end"], repl)


def build_l1_task(sm, source_lines, dump, target_thm, bench_module_name, model_set, module):
    """proof-completion task: keep ALL scaffolding (Inv etc.), admit STRUCTURED preceding
    proofs as PROOF OMITTED (keep OBVIOUS verbatim → it still emits an
    obligation), stub the target PROOF OBVIOUS, drop later theorems, keep
    comments. If model_set is non-empty, EXTEND the shared model (delete its ops
    + the inherited decls); else stay self-contained."""
    use_model = bool(model_set)
    edits = list(sm._decl_edits(dump)) if use_model else []
    tid = id(target_thm)
    tstart = target_thm["loc"]["line_start"]
    for t in dump["theorems"]:
        loc, ploc = t["loc"], t.get("proof_loc")
        has_body = ploc and ploc.get("line_start", -1) > 0
        if id(t) == tid:
            if has_body:
                edits.append(_proof_edit(source_lines, ploc, "PROOF OBVIOUS"))
        elif loc["line_start"] < tstart:
            if has_body and _is_structured_proof(sm, t, source_lines):
                edits.append(_proof_edit(source_lines, ploc, "PROOF OMITTED"))
        else:
            edits.append((loc["line_start"], loc["line_end"], ""))
    if use_model:
        for o in dump["operators"]:
            if o["name"] in model_set:
                edits.append((o["loc"]["line_start"], o["loc"]["line_end"], ""))
        for inst in dump["instances"]:
            if inst.get("name") and inst["name"] in model_set:
                edits.append((inst["loc"]["line_start"], inst["loc"]["line_end"], ""))
    text = sm.apply_edits(source_lines, edits)
    if use_model:
        text = sm._strip_bare_decls(text)
        text = sm._rewrite_extends_line(text, module)
    text = sm._rename_header(text, bench_module_name)
    return sm._sm_tidy(text)


def generate_shared_model_l1(output_root=None):
    """Dump-based proof-completion generation: one shared `<Module>.tla` per output dir +
    EXTENDS-based proof-completion tasks. Mirrors the proof-from-scratch shared-model layout."""
    import shutil
    import sys

    sm = _load_l2_engine()
    output_root = output_root or BENCHMARK_DIR

    if os.path.exists(output_root):
        shutil.rmtree(output_root)
    os.makedirs(output_root, exist_ok=True)

    targets = []
    for f in sorted(glob.glob(os.path.join(SOURCE_ROOT, "**", "*.tla"), recursive=True)):
        if ".tlaps" in f:
            continue
        subdir = os.path.relpath(f, SOURCE_ROOT).split(os.sep)[0]
        targets.append((f, subdir))
    sibling_deps = sm.compute_sibling_deps(targets)

    total = 0
    for path, subdir in targets:
        try:
            dump = sm.dump_sany(path)
        except Exception as e:
            print(f"  SANY failed on {path}: {e}", file=sys.stderr)
            continue
        module = dump["module"]
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        # proof-completion targets: NAMED theorems with a structured proof.
        l1_targets = [t for t in dump["theorems"] if t.get("name") and _is_structured_proof(sm, t, lines)]
        if not l1_targets:
            continue
        out_dir = os.path.join(output_root, subdir)
        os.makedirs(out_dir, exist_ok=True)

        model_set = set()
        if module not in sibling_deps.get(subdir, set()):
            model_set, _ = sm.compute_model_set(dump, l1_targets)
            if model_set:
                model_text = sm.build_model(lines, dump, model_set)
                with open(os.path.join(out_dir, f"{module}.tla"), "w") as f:
                    f.write(model_text)

        base = os.path.splitext(os.path.basename(path))[0]
        used = {}
        reachable_all = {i["name"] for i in dump["instances"] if i.get("name")}
        for t in l1_targets:
            name = f"{base}_{t['name']}"
            if name in used:
                used[name] += 1
                bench = f"{name}_{used[name]}"
            else:
                used[name] = 0
                bench = name
            text = build_l1_task(sm, lines, dump, t, bench, model_set, module)
            with open(os.path.join(out_dir, f"{bench}.tla"), "w") as f:
                f.write(text)
            total += 1
            print(f"  generated: {os.path.relpath(os.path.join(out_dir, bench + '.tla'), PROJECT_ROOT)}")
        sm.copy_deps(dump, path, out_dir, reachable_all)
    print(f"\nGenerated {total} proof-completion benchmark(s) (shared-model)")
    return total


# ---------------------------------------------------------------------------
# Layered proof-completion (Issue #86). Shares the dump/edit engine with
# proof-from-scratch; the marker strings and manifest schema come from the
# evaluator's own contract module, so the two sides cannot drift apart.
# ---------------------------------------------------------------------------

_COL0_DIRECTIVE = re.compile(r"^(USE|HIDE)\b")
_PROOF_STEP_IN_COMMENT = re.compile(r"<\d+>")
_STRUCTURED_PROOF_SCAN = re.compile(r"(?m)^[ \t]*(<\d+>|BY\b|PROOF\s+BY\b)")
_BLANK_RUN = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")


def _engine():
    """The proof-from-scratch generator, used as the shared dump/edit engine.

    Imported lazily: proof-from-scratch imports *this* module at import time, so
    a module-level import here would be circular.
    """
    import importlib

    return importlib.import_module("dataset.proof_from_scratch.generate")


def _write_module(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def theorem_spans(dump):
    """Inclusive source line spans covered by each theorem and its proof."""
    spans = []
    for t in dump["theorems"]:
        loc, ploc = t["loc"], t.get("proof_loc")
        end = loc["line_end"]
        if ploc and ploc.get("line_start", -1) > 0:
            end = max(end, ploc["line_end"])
        spans.append((loc["line_start"], end))
    return spans


def module_directives_before(source_lines, dump, target_line):
    """Module-level `USE`/`HIDE` lines that precede the target theorem.

    These must travel WITH the theorem into the task file: a module-level `USE`
    is scoped to the proofs that follow it in its own module and is NOT
    inherited through EXTENDS, so leaving `USE NAssumption` behind in the
    scaffold would silently drop a fact the reference proof relies on. They land
    outside the editable region, so they stay benchmark-owned.

    Only column-0 lines outside every theorem span count; an indented `USE`
    inside a proof body belongs to that proof.
    """
    spans = theorem_spans(dump)
    out = []
    for line_number, line in enumerate(source_lines, start=1):
        if line_number >= target_line or not _COL0_DIRECTIVE.match(line):
            continue
        if any(start <= line_number <= end for start, end in spans):
            continue
        out.append(line.rstrip("\n"))
    return out


def strip_proof_step_comments(text):
    """Drop comments that quote structured proof steps, keeping prose comments.

    proof-completion keeps the source's comments — they are part of the given
    context — but a comment such as "here is a more detailed proof of <1>1" is a
    leftover of the reference proof this task asks the agent to write.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "(*":
            depth = 1
            j = i + 2
            while j < n and depth:
                if text[j : j + 2] == "(*":
                    depth += 1
                    j += 2
                elif text[j : j + 2] == "*)":
                    depth -= 1
                    j += 2
                else:
                    j += 1
            block = text[i:j]
            if not _PROOF_STEP_IN_COMMENT.search(block):
                out.append(block)
            else:
                out.append("\n" * block.count("\n"))  # keep line geometry
            i = j
        elif two == "\\*":
            j = text.find("\n", i)
            j = n if j < 0 else j
            if not _PROOF_STEP_IN_COMMENT.search(text[i:j]):
                out.append(text[i:j])
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def target_statement_text(sm, source_lines, target_thm):
    """The target theorem's statement, without its proof and without comments.

    SANY's theorem `loc` spans `THEOREM ... <proof>`, so the statement ends
    where the proof begins — which may be mid-line for a one-line lemma such as
    `LEMMA Foo == x  BY DEF y`; the proof's `column_start` is what separates
    them there. Comments are stripped because this text is fixed scaffold in the
    submitted file, and an attached comment can carry the original proof sketch.
    """
    loc = target_thm["loc"]
    ploc = target_thm.get("proof_loc")
    if ploc and ploc.get("line_start", -1) > 0:
        text = "".join(source_lines[loc["line_start"] - 1 : ploc["line_start"] - 1])
        text += source_lines[ploc["line_start"] - 1][: ploc.get("column_start", 1) - 1]
    else:
        text = "".join(source_lines[loc["line_start"] - 1 : loc["line_end"]])
    return _BLANK_RUN.sub("\n", sm.strip_comments(text)).strip()


def build_task_module(task_module_name, scaffold_module, statement_text, directives=()):
    """The editable task file: EXTENDS the scaffold, then the fixed theorem
    statement and the marked proof region holding the `PROOF OBVIOUS`
    placeholder. Built from scratch rather than by editing source, so the marker
    structure the evaluator parses is exact."""
    stmt = statement_text.rstrip("\n")
    head = "".join(f"{d}\n" for d in directives)
    return (
        f"---- MODULE {task_module_name} ----\n"
        f"EXTENDS {scaffold_module}\n"
        f"{head}"
        f"{stmt}\n"
        f"{BEGIN_AGENT_PROOF}\n"
        f"PROOF OBVIOUS\n"
        f"{END_AGENT_PROOF}\n"
        f"====\n"
    )


def build_prefix_model(sm, source_lines, dump, model_set, target_start):
    """The read-only model layer, truncated at the target theorem.

    `compute_model_set` picks the state machine from the WHOLE file, so building
    one model per source and sharing it across that file's targets hands each
    task everything the module ever declares — including definitions and
    assumptions the source states AFTER the target. That is a scope change, not
    just a layout change: `Voting` states `THEOREM QuorumNonEmpty` on line 10 and
    defines `Ballot` on line 13, so a shared model lets `BY QuorumAssumption DEF
    Ballot` close a task that cannot even name `Ballot` in the source.

    Truncating here restores the original scope exactly. The scaffold already
    stops at the target, and it deletes precisely the model-set operators the
    model keeps, so `model ∪ scaffold` is the source prefix — no more, no less.
    Two targets whose prefixes yield the same model share one file
    (`emit_layered_source` dedupes on the body), so a module whose theorems all
    follow its spec still ships a single model.
    """
    prefix_lines = source_lines[: target_start - 1]
    edits = []
    for t in dump["theorems"]:
        loc, ploc = t["loc"], t.get("proof_loc")
        end = loc["line_end"]
        if ploc and ploc.get("line_start", -1) > 0:
            end = max(end, ploc["line_end"])
        edits.append((loc["line_start"], end, ""))
    for o in dump["operators"]:
        if o["name"] not in model_set:
            edits.append((o["loc"]["line_start"], o["loc"]["line_end"], ""))
    for inst in dump["instances"]:
        if inst.get("name") and inst["name"] not in model_set:
            edits.append((inst["loc"]["line_start"], inst["loc"]["line_end"], ""))
    edits = [edit for edit in edits if edit[1] < target_start]

    # Truncation drops the source's `====`, so the module needs a terminator.
    text = sm.apply_edits(prefix_lines, edits) + "=" * 77 + "\n"
    return sm._sm_tidy(sm._strip_module_directives(sm.strip_comments(text)))


def build_scaffold(sm, source_lines, dump, target_thm, scaffold_module_name, model_module, model_set):
    """The read-only scaffold layer: this target's given definitions and lemmas.

    Keeps every definition the source states ahead of the target (proof
    completion gives the agent the invariants) and admits each preceding
    structured proof as `PROOF OMITTED`. With a shared model the declarations
    and the specification come through `EXTENDS <model_module>` instead.

    The scaffold stops at the target theorem. Nothing after it is a given: TLA+
    requires definition before use, so neither the target nor its proof can name
    anything down there, while hoisting it into a module the task EXTENDS WOULD
    change scoping — BubbleSort states `THEOREM ... \\A A \\in [1..N -> Int]`
    ahead of `VARIABLES A, A0`, and that declaration then shadows the bound name
    and SANY rejects the task.
    """
    use_model = bool(model_set)
    target_start = target_thm["loc"]["line_start"]
    prefix_lines = source_lines[: target_start - 1]

    edits = list(sm._decl_edits(dump)) if use_model else []
    for t in dump["theorems"]:
        loc, ploc = t["loc"], t.get("proof_loc")
        if loc["line_start"] >= target_start:
            continue
        if ploc and ploc.get("line_start", -1) > 0 and _is_structured_proof(sm, t, source_lines):
            edits.append(_proof_edit(source_lines, ploc, "PROOF OMITTED"))
    if use_model:
        for o in dump["operators"]:
            if o["name"] in model_set:
                edits.append((o["loc"]["line_start"], o["loc"]["line_end"], ""))
        for inst in dump["instances"]:
            if inst.get("name") and inst["name"] in model_set:
                edits.append((inst["loc"]["line_start"], inst["loc"]["line_end"], ""))
    edits = [edit for edit in edits if edit[1] < target_start]

    # Truncation drops the source's `====`, so the module needs a terminator.
    text = sm.apply_edits(prefix_lines, edits) + "=" * 77 + "\n"
    text = strip_proof_step_comments(text)
    # `USE`/`HIDE` do not cross EXTENDS and the scaffold proves nothing, so they
    # are dead here; `module_directives_before` re-emits them in the task file.
    text = sm._strip_module_directives(text)
    if use_model:
        text = sm._strip_bare_decls(text)
        text = sm._rewrite_extends_line(text, model_module)
    text = sm._rename_header(text, scaffold_module_name)
    return sm._sm_tidy(text)


def dependency_module_text(sm, dep_path):
    """A local dependency copied as given context: proofs admitted, comments out.

    A dependency's THEOREM statements stay (they are usable givens, exactly like
    the scaffold's preceding lemmas) but every proof becomes `PROOF OMITTED`, so
    no reference proof is handed over. This is the rule the flat generator
    already applied to copied dependencies.
    """
    with open(dep_path, encoding="utf-8") as f:
        dep_lines = f.read().split("\n")
    dep_theorems = parse_theorems(dep_lines)
    text = strip_all_proofs(dep_lines, dep_theorems) if dep_theorems else "\n".join(dep_lines)
    text = sm.strip_comments(text)
    return _BLANK_RUN.sub("\n\n", text)


def write_task_dependencies(sm, dump, source_path, out_dir, subdir, task_module, audit_writer, written):
    """Write each local dependency of `source_path` and return its context paths.

    Dependencies are shared per output directory — the copy is a function of the
    source module alone, so every task in the directory gets the same bytes. If
    two different modules ever claim one basename, the loser gets a private copy
    under `<subdir>/<task>/` rather than silently overwriting the winner.
    """
    instance_names = {i["name"] for i in dump.get("instances", []) if i.get("name")}
    context = []
    for _mod, dep_path in sm.layered_dep_paths(dump, source_path, instance_names):
        base = os.path.basename(dep_path)
        text = dependency_module_text(sm, dep_path)
        shared = os.path.join(out_dir, base)
        previous = written.get(shared)
        if previous is None or previous == text:
            written[shared] = text
            _write_module(shared, text)
            context.append(f"{subdir}/{base}")
            continue
        private = os.path.join(out_dir, task_module, base)
        _write_module(private, text)
        context.append(f"{subdir}/{task_module}/{base}")
        audit_writer.write(
            f"[audit] {subdir}/{task_module}.tla: dependency {base} conflicts with another module of "
            f"that name in {subdir}/ — given a private copy\n"
        )
    return context


def _audit_scaffold(audit_writer, task_key, scaffold_key, scaffold_text, target_name):
    """Flag a scaffold that leaks the target or keeps a real proof."""
    if _STRUCTURED_PROOF_SCAN.search(scaffold_text):
        audit_writer.write(f"[audit] {task_key}: LEAK scaffold {scaffold_key} still contains proof steps\n")
    if not target_name:
        return
    stated = re.search(
        rf"(?m)^[ \t]*(THEOREM|LEMMA|COROLLARY|PROPOSITION)\s+{re.escape(target_name)}\s*==",
        scaffold_text,
    )
    if stated:
        audit_writer.write(f"[audit] {task_key}: LEAK scaffold {scaffold_key} restates the target theorem\n")


def _plan_targets(sm, dump, source_lines, base_module, subdir, reference_task_keys, audit_writer):
    """Choose this source's task targets and their module names, in file order.

    A target is a theorem carrying a structured proof, so every new task has a
    reference proof to validate against. A theorem whose task the dataset
    already ships is kept even without one: dropping it would silently shrink
    the benchmark, and the boundary this issue is about does not depend on where
    the reference proof lives. Naming (including the `_2` suffix for a repeated
    theorem name) follows the flat generator, so regeneration keeps task keys.
    Unnamed targets reuse proof-from-scratch's semantic filename or line-number
    fallback without naming the theorem itself. Reserve named task modules first
    so an unnamed goal cannot steal an existing task's key. Repeated unnamed
    statements keep distinct keys: their preceding context may differ.
    """
    planned = []
    used_names = {}
    reserved = set()
    named_counts = {}
    for theorem in dump["theorems"]:
        if theorem.get("name"):
            module = f"{base_module}_{theorem['name']}"
            count = named_counts.get(module, 0)
            named_module = module if count == 0 else f"{module}_{count}"
            reserved.update((named_module, f"{named_module}Scaffold"))
            named_counts[module] = count + 1
    unnamed_modules = set()
    for target_thm in dump["theorems"]:
        name = target_thm.get("name")
        structured = _is_structured_proof(sm, target_thm, source_lines)
        if name:
            module = f"{base_module}_{name}"
            emitted = used_names.get(module, 0)
            task_module = module if emitted == 0 else f"{module}_{emitted}"
        else:
            if not structured:
                continue
            label, _sanitized = sm.target_theorem_name(target_thm)
            module = f"{base_module}_{label}"
            task_module = module
            suffix = 0
            while {task_module, f"{task_module}Scaffold"} & (reserved | unnamed_modules):
                suffix += 1
                task_module = f"{module}_{suffix}"
            unnamed_modules.update((task_module, f"{task_module}Scaffold"))
        task_key = f"{subdir}/{task_module}.tla"

        if not structured:
            if reference_task_keys is None or task_key not in reference_task_keys:
                continue
            audit_writer.write(
                f"[audit] {task_key}: source states no reference proof — retained for existing-dataset selection\n"
            )
        elif reference_task_keys is not None and task_key not in reference_task_keys:
            # Outside the reviewed selection: a fresh scan finds candidates the
            # curated dataset intentionally excludes, so skip rather than expand
            # the benchmark past what was reviewed.
            audit_writer.write(
                f"[audit] {task_key}: source candidate is outside the existing dataset selection — skipped\n"
            )
            continue

        if name:
            used_names[module] = emitted + 1
        planned.append((target_thm, task_module, task_key))
    return planned


def emit_layered_source(
    sm,
    source_path,
    subdir,
    out_dir,
    audit_writer,
    manifest,
    audit_state,
    reference_task_keys=None,
    source_root=None,
):
    """Emit the layered split + manifest entries for one source file.

    Layout per task (Issue #86 contract):
      <base>Model.tla        benchmark-owned model, truncated
                             at the target theorem, shared by
                             the targets it is identical for  (read-only)
      <task>Scaffold.tla     this target's given scaffolding   (read-only)
      <task>.tla             theorem + markers + PROOF OBVIOUS (editable)
    """
    try:
        dump = sm.dump_sany(source_path)
    except Exception as e:
        # Not survivable: a source we cannot read is a source whose tasks are
        # missing from the dataset, so the run must not go on to write a
        # manifest that quietly omits them.
        audit_writer.write(f"[audit] {source_path}: SANY parse failed — {e}\n")
        audit_state.setdefault("errors", []).append(f"{source_path}: SANY parse failed — {e}")
        return 0

    with open(source_path, encoding="utf-8") as f:
        source_lines = f.readlines()

    base_module = os.path.splitext(os.path.basename(source_path))[0]
    planned = _plan_targets(sm, dump, source_lines, base_module, subdir, reference_task_keys, audit_writer)
    if not planned:
        return 0
    targets = [target for target, _module, _key in planned]
    spec_id = source_spec_id(source_path, source_root or SOURCE_ROOT)

    os.makedirs(out_dir, exist_ok=True)
    written = audit_state.setdefault("written", {})

    model_set, _main_specs = sm.compute_model_set(dump, targets)
    # Model body (pre-rename) -> module name. Keyed on the body so targets whose
    # source prefixes yield the same model share one file; named in file order,
    # so regeneration is reproducible.
    model_variants = {}

    def model_for(target_thm):
        """The model module this target may see, written on first use."""
        if not model_set:
            return None
        body = build_prefix_model(sm, source_lines, dump, model_set, target_thm["loc"]["line_start"])
        if body in model_variants:
            return model_variants[body]
        suffix = "" if not model_variants else f"_{len(model_variants) + 1}"
        model_module = f"{base_module}Model{suffix}"
        model_variants[body] = model_module
        model_text = sm._rename_header(body, model_module)
        model_path = os.path.join(out_dir, f"{model_module}.tla")
        written[model_path] = model_text
        _write_module(model_path, model_text)
        if sm._THEOREM_SCAN.search(model_text):
            audit_writer.write(f"[audit] {source_path}: LEAK model {model_module} contains a THEOREM/LEMMA\n")
        return model_module

    count = 0
    for target_thm, task_module, task_key in planned:
        model_module = model_for(target_thm)
        scaffold_module = f"{task_module}Scaffold"
        scaffold_text = build_scaffold(sm, source_lines, dump, target_thm, scaffold_module, model_module, model_set)
        scaffold_path = os.path.join(out_dir, f"{scaffold_module}.tla")
        written[scaffold_path] = scaffold_text
        _write_module(scaffold_path, scaffold_text)
        _audit_scaffold(
            audit_writer,
            task_key,
            f"{subdir}/{scaffold_module}.tla",
            scaffold_text,
            target_thm["name"],
        )

        statement = target_statement_text(sm, source_lines, target_thm)
        directives = module_directives_before(source_lines, dump, target_thm["loc"]["line_start"])
        task_text = build_task_module(task_module, scaffold_module, statement, directives)
        task_path = os.path.join(out_dir, f"{task_module}.tla")
        written[task_path] = task_text
        _write_module(task_path, task_text)

        # Read the emitted task back through the evaluator's own parser: a task
        # whose marker structure the grader cannot parse must never be written.
        parse_proof_completion_region(task_text)

        context = [f"{subdir}/{scaffold_module}.tla"]
        if model_module:
            context.append(f"{subdir}/{model_module}.tla")
        context += write_task_dependencies(sm, dump, source_path, out_dir, subdir, task_module, audit_writer, written)
        if target_thm.get("name"):
            reference_steps = reference_proof_steps_for_name(source_lines, target_thm["name"])
        else:
            ploc = target_thm["proof_loc"]
            proof_lines = source_lines[ploc["line_start"] - 1 : ploc["line_end"]]
            proof_lines[0] = proof_lines[0][ploc.get("column_start", 1) - 1 :]
            reference_steps = count_reference_proof_steps(proof_lines)
        manifest[task_key] = {
            "spec_id": spec_id,
            "context": sorted(set(context)),
            "reference_proof_steps": reference_steps,
        }
        audit_state.setdefault("scaffold_owner", {}).setdefault(f"{subdir}/{scaffold_module}.tla", []).append(task_key)

        count += 1
        print(f"  generated task: {os.path.relpath(task_path, PROJECT_ROOT)}")

    return count


def load_dataset_task_keys(root):
    """Task keys that define the repository's curated dataset selection.

    Once a layered manifest exists it is the complete dataset index. Scanning the
    tree is only the bootstrap path for a legacy dataset that has no manifest.
    """
    from dataset.sany_audit import is_task_file

    manifest_path = os.path.join(root, MANIFEST_FILENAME)
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            if isinstance(manifest, dict):
                return set(manifest)
        except (OSError, json.JSONDecodeError):
            pass

    flat_keys = set()
    if os.path.isdir(root):
        for current_root, dirs, files in os.walk(root):
            # `.tlacache` holds tlapm's fingerprint history, not dataset tasks.
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".tla"):
                    continue
                path = os.path.join(current_root, fname)
                if is_task_file(path):
                    flat_keys.add(os.path.relpath(path, root).replace(os.sep, "/"))
    return flat_keys


def drop_known_degenerate(output_root, manifest, audit_writer):
    """Drop targets recorded as degenerate that the gate cannot detect reliably.

    The triviality gate's verdict is not reproducible under its own 16-way load
    — see `known_degenerate_targets.json` for the measurements — so a task whose
    placeholder demonstrably verifies can survive it. Dropping the recorded ones
    up front makes the dataset deterministic and stops a no-op submission from
    scoring a PASS, whichever way the gate happens to fall on a given run.

    A recorded target that no longer exists is not an error: it may have been
    dropped by the gate itself on this run, or renamed by a source change.
    """
    with open(_KNOWN_DEGENERATE_PATH, encoding="utf-8") as f:
        recorded = json.load(f)["targets"]

    removed = []
    for entry in recorded:
        task_key = entry["task"]
        if task_key not in manifest:
            continue
        del manifest[task_key]
        path = os.path.join(output_root, task_key)
        if os.path.exists(path):
            os.remove(path)
        removed.append(task_key)
        audit_writer.write(
            f"[audit] {task_key}: recorded as degenerate — dropped — {entry['reason']} ({entry['evidence']})\n"
        )
    if removed:
        print(f"[layered-known-degenerate] dropped {len(removed)} recorded degenerate task(s)")
    return sorted(removed)


def layered_duplicate_gate(output_root, manifest, audit_writer):
    """Drop approved cross-directory duplicates; reject unknown ones (#90).

    Several `source/` groups vendor the same module, so the same target is
    generated twice — `Sets_PigeonHole` under both `Data/` and `Consensus/`.
    The flat gate compares task files byte-for-byte, which a layered task file
    cannot do alone: it is a thin `EXTENDS <Scaffold>` wrapper, so two tasks
    could match on it while resting on different givens. Identity here therefore
    spans the task AND every context module the manifest assigns it — the same
    rule `layered_cross_dir_dedup` uses, and the same conclusion: two tasks are
    the same prompt only when their given semantics match.

    The approved families in `duplicate_task_families.json` say which copy is
    canonical. An unapproved duplicate raises rather than picking a winner, so a
    new collision is a decision someone makes, not one the generator makes.
    """
    import hashlib

    with open(_DUPLICATE_TASK_FAMILIES_PATH, encoding="utf-8") as f:
        families = json.load(f)

    def digest(task_key):
        h = hashlib.sha256()
        for rel in [task_key] + sorted(manifest[task_key]["context"]):
            h.update(os.path.basename(rel).encode())
            try:
                with open(os.path.join(output_root, rel), "rb") as fh:
                    h.update(fh.read())
            except OSError:
                # A context file the manifest names but the tree lacks is a
                # manifest bug, reported with its own message by the validation
                # at the end of finalize. Hashing a marker keeps this gate from
                # masking that with a stack trace, and keeps the two tasks
                # distinct so neither is dropped as the other's duplicate.
                h.update(f"<missing:{rel}>".encode())
        return h.hexdigest()

    groups = {}
    for task_key in manifest:
        groups.setdefault((os.path.basename(task_key), digest(task_key)), []).append(task_key)

    removed, unapproved = [], []
    for (basename, _hash), group in sorted(groups.items()):
        if len(group) < 2:
            continue
        dirs = {key.split("/", 1)[0] for key in group}
        keeper = None
        for family in families:
            if not basename.startswith(family["target_prefix"]):
                continue
            canonical = [key for key in group if key.split("/", 1)[0] == family["canonical"]]
            if len(canonical) == 1 and dirs <= set(family["copies"]) | {family["canonical"]}:
                keeper = canonical[0]
                break
        if keeper is None:
            unapproved.append(sorted(group))
            continue
        for task_key in sorted(group):
            if task_key == keeper:
                continue
            del manifest[task_key]
            path = os.path.join(output_root, task_key)
            if os.path.exists(path):
                os.remove(path)
            removed.append(task_key)
            audit_writer.write(f"[audit] {task_key}: duplicate of {keeper} — removed (approved duplicate family)\n")

    if removed:
        print(f"[layered-duplicate-gate] removed {len(removed)} approved duplicate task(s)")
    return sorted(removed), unapproved


def _finalize_layered(
    sm,
    output_root,
    manifest,
    audit_state,
    audit_writer,
    run_gates=True,
    incremental=False,
    scope=None,
    reference_task_keys=None,
):
    """Gate, audit isolation, sweep, then write and re-validate manifest.json.

    Both gates run against each task's exact manifest context, so their verdict
    matches the grader's. A partial run replaces only the tasks whose source it
    regenerated and leaves the rest untouched.

    Fails closed: a source parse error, a SANY failure, a triviality gate that
    cannot reach a verdict, a run that does not regenerate the reviewed
    selection before the gates, or an empty result all leave the manifest
    unwritten and raise. The audit log is written either way, so the failure is
    diagnosable. The gates may deliberately reduce the final task count.
    """
    existing = sm._load_existing_manifest(output_root) if incremental else {}
    all_bases, processed_bases = scope or ({}, {})
    superseded = sm.tasks_owned_by(existing, all_bases, processed_bases) if incremental else set(existing)
    errors = list(audit_state.get("errors", []))

    def fail_if_errors():
        if not errors:
            return
        for message in errors:
            audit_writer.write(f"[audit] generation error: {message}\n")
        audit_writer.write(f"[audit] generation FAILED with {len(errors)} error(s) — manifest not written\n")
        print(f"\n❌ generation failed with {len(errors)} error(s); manifest not written:", file=sys.stderr)
        for message in errors[:20]:
            print(f"   {message[:200]}", file=sys.stderr)
        if len(errors) > 20:
            print(f"   ... and {len(errors) - 20} more (see the audit log)", file=sys.stderr)
        raise SystemExit(1)

    # Before any gate runs, the generator must reproduce EXACTLY the reviewed
    # selection. This catches source/generation failures without rejecting tasks
    # the later gates deliberately remove as degenerate or duplicate.
    if reference_task_keys is not None:
        if incremental:
            expected = sm.tasks_owned_by(reference_task_keys, all_bases, processed_bases)
            actual = sm.tasks_owned_by(manifest, all_bases, processed_bases)
        else:
            expected = set(reference_task_keys)
            actual = set(manifest)
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
        for key in missing:
            errors.append(f"{key}: reviewed dataset task was not regenerated")
        for key in unexpected:
            errors.append(f"{key}: generated task is not in the reviewed dataset selection")
    fail_if_errors()

    dropped, slow = [], []
    recorded_degenerate = drop_known_degenerate(output_root, manifest, audit_writer)
    duplicates, unapproved = layered_duplicate_gate(output_root, manifest, audit_writer)
    for group in unapproved:
        errors.append(f"unapproved duplicate task group {group} — add it to duplicate_task_families.json or diverge")
    if run_gates:
        for task_key, err in sm.layered_sany_gate(output_root, manifest, audit_writer):
            errors.append(f"{task_key}: failed standalone SANY with its manifest context — {err}")
        # `slow` tasks are kept (they cannot pass on the grader's budget either);
        # `errored` ones the gate could not judge, so they fail the run.
        dropped, slow, errored = sm.layered_triviality_gate(output_root, manifest, audit_writer)
        for task_key in errored:
            errors.append(f"{task_key}: triviality gate could not reach a verdict (see the audit log)")

    for key in sorted(superseded - set(manifest)):
        audit_writer.write(f"[audit] {key}: no longer generated by its source — removed from the manifest\n")
    complete = {k: v for k, v in existing.items() if k not in superseded}
    complete.update(manifest)
    if not complete:
        errors.append("the run produced no tasks at all")

    # The sweep DELETES files; do not let a failing run prune the dataset.
    if not errors:
        sm.sweep_unreferenced_context(output_root, complete, audit_writer)

    owners = audit_state.get("scaffold_owner", {})
    owners = {k: [t for t in v if t in manifest] for k, v in owners.items()}
    for scaffold_key, task_keys in sorted(owners.items()):
        if len(task_keys) > 1:
            audit_writer.write(
                f"[audit] LEAK scaffold {scaffold_key} is shared by multiple tasks {sorted(task_keys)} "
                f"— a target's scaffolding must belong to exactly one task\n"
            )

    fail_if_errors()

    manifest_path = os.path.join(output_root, MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(complete.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Fail closed: what the evaluator will load must validate in full.
    load_proof_completion_manifest(Path(output_root))

    scope_note = f"{len(manifest)} regenerated, {len(complete)} total" if incremental else f"{len(complete)} tasks"
    print(
        f"Manifest: {os.path.relpath(manifest_path, PROJECT_ROOT)} ({scope_note}, {len(duplicates)} duplicates and "
        f"{len(dropped) + len(recorded_degenerate)} degenerate tasks dropped, "
        f"{len(slow)} kept as beyond the grader's budget)"
    )
    return len(complete)


def _seed_staging(source_root, staging_root):
    """Copy the current dataset into `staging_root` so a partial run preserves it.

    Staging starts as a copy of the shipped dataset (manifest and `.tlacache`
    included) and the run overwrites only the files it regenerates.
    """
    import shutil

    for name in os.listdir(source_root):
        src = os.path.join(source_root, name)
        dst = os.path.join(staging_root, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _promote_dataset(staging_root, output_root):
    """Replace `output_root` with `staging_root`, restoring the old one on failure.

    The previous dataset is moved aside first and removed only after the new one
    is in place, so a failed swap leaves it recoverable.
    """
    import shutil

    backup = f"{output_root}.promote-backup-{os.getpid()}"
    if os.path.exists(output_root):
        os.rename(output_root, backup)
    try:
        os.rename(staging_root, output_root)
    except OSError:
        if not os.path.exists(output_root) and os.path.exists(backup):
            os.rename(backup, output_root)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def generate_layered(output_root=None, source_dir=None, filter_substring=None, files=(), run_gates=True):
    """Generate the layered proof-completion dataset and its manifest.

    Generation runs entirely in a private staging directory and is promoted over
    the shipped dataset only after every gate, the sweep, the reviewed-selection
    check, and manifest validation have passed. A run that fails at any step
    leaves the existing dataset byte-for-byte unchanged; only the audit log is
    refreshed at `output_root`, so the failure stays diagnosable. A `--filter`
    or positional run seeds staging from the current dataset first, so the tasks
    it does not regenerate survive untouched.
    """
    import shutil
    import tempfile

    sm = _engine()
    output_root = os.path.abspath(output_root or BENCHMARK_DIR)
    source_dir = os.path.abspath(source_dir or SOURCE_ROOT)
    os.makedirs(output_root, exist_ok=True)

    # Scan unfiltered, then select: a filtered run needs every possible source to
    # tell a regenerated task's source from one it skipped.
    if files:
        all_targets, repository_sources = sm.positional_targets(files, SOURCE_ROOT)
        if not repository_sources and any(subdir is not None for _path, subdir in all_targets):
            raise SystemExit(
                "a layered positional run cannot mix repository source files with external files; "
                "run the two source sets separately"
            )
        ownership_targets = sm.scan_source_targets(SOURCE_ROOT) if repository_sources else all_targets
    else:
        repository_sources = os.path.realpath(source_dir) == os.path.realpath(SOURCE_ROOT)
        all_targets = sm.scan_source_targets(source_dir)
        ownership_targets = all_targets
    targets = [t for t in all_targets if not filter_substring or filter_substring in t[0]]

    # The shipped dataset is the reference selection even when writing elsewhere,
    # so a dry run into a scratch directory still accounts for every task.
    reference_task_keys = None
    if repository_sources:
        keys = load_dataset_task_keys(BENCHMARK_DIR)
        if keys:
            reference_task_keys = keys
            print(f"Using existing proof-completion dataset selection: {len(keys)} tasks")

    incremental = bool(filter_substring or files)
    if incremental:
        reason = sm.incremental_precondition_error(output_root)
        if reason:
            raise SystemExit(
                f"a partial run needs a valid manifest to preserve the tasks it is not regenerating: {reason}"
            )
    scope = (sm.source_bases(ownership_targets), sm.source_bases(targets))

    audit_path = os.path.join(output_root, "audit.log")
    staging_root = tempfile.mkdtemp(
        prefix=f".staging-{os.path.basename(output_root)}-", dir=os.path.dirname(output_root)
    )
    try:
        if incremental:
            _seed_staging(output_root, staging_root)

        manifest = {}
        audit_state = {}
        total = 0
        with open(os.path.join(staging_root, "audit.log"), "w", encoding="utf-8") as audit_writer:
            for path, subdir in targets:
                print(f"\nProcessing {os.path.relpath(path, PROJECT_ROOT)}")
                key = subdir if subdir is not None else os.path.splitext(os.path.basename(path))[0]
                try:
                    total += emit_layered_source(
                        sm,
                        path,
                        key,
                        os.path.join(staging_root, key),
                        audit_writer,
                        manifest,
                        audit_state,
                        reference_task_keys,
                        source_root=SOURCE_ROOT if files else source_dir,
                    )
                except Exception as e:
                    audit_writer.write(f"[audit] {path}: ERROR {e!r}\n")
                    audit_state.setdefault("errors", []).append(f"{path}: {e!r}")
                    print(f"  ERROR: {e}", file=sys.stderr)

            final_count = _finalize_layered(
                sm,
                staging_root,
                manifest,
                audit_state,
                audit_writer,
                run_gates=run_gates,
                incremental=incremental,
                scope=scope,
                reference_task_keys=reference_task_keys,
            )

        # Everything passed: replace the shipped dataset with the staged one.
        _promote_dataset(staging_root, output_root)
        staging_root = None
    finally:
        if staging_root is not None and os.path.isdir(staging_root):
            # A failed run leaves the dataset untouched, but its audit log still
            # has to reach the caller — salvage it to `output_root` before the
            # staging directory (and the half-built dataset in it) is discarded.
            salvaged = os.path.join(staging_root, "audit.log")
            if os.path.isfile(salvaged):
                shutil.copy2(salvaged, audit_path)
            shutil.rmtree(staging_root, ignore_errors=True)

    print(f"\nTotal proof-completion tasks: {final_count} ({total} generated before gates)")
    print(f"Audit log: {os.path.relpath(audit_path, PROJECT_ROOT)}")
    return final_count


def _run_sany_gate(directory):
    """Post-generation input SANY gate over the emitted proof-completion benchmark dir.

    Every task file handed to an agent must parse under standalone tla2sany.
    Flags failures (manifest + stdout); does not drop them. Returns the number of
    degenerate tasks the triviality gate then dropped, so callers can correct the
    printed benchmark count.
    """
    from dataset.sany_audit import gate

    gate(directory, label="sany-gate-l1")
    return _run_triviality_gate(directory)


def _prune_unreferenced_dependencies(directory):
    """Remove generated dependency modules no surviving task can reach.

    Proof-completion dependencies are resolved among sibling files. Walk the
    EXTENDS/INSTANCE closure from every task in each output directory, keep that
    closure, and delete only well-formed non-task modules outside it.
    """
    from dataset.sany_audit import is_task_file

    unused = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        paths = sorted(os.path.join(root, name) for name in files if name.endswith(".tla"))
        if not paths:
            continue

        contents = {}
        modules = {}
        tasks = []
        for path in paths:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            contents[path] = content
            module = os.path.splitext(os.path.basename(path))[0]
            modules.setdefault(module, []).append(path)
            if is_task_file(path):
                tasks.append(path)

        reachable = set(tasks)
        stack = list(tasks)
        while stack:
            path = stack.pop()
            for module in _tla_modules.referenced_modules(contents[path]):
                for dependency in modules.get(module, ()):
                    if dependency not in reachable:
                        reachable.add(dependency)
                        stack.append(dependency)

        unused.extend(path for path in paths if path not in reachable)

    removed = []
    for path in sorted(unused):
        os.remove(path)
        removed.append(path)
        print(f"  [dependency-prune-l1] removed {os.path.relpath(path, directory)} (unreferenced)")

    for root, _dirs, _files in os.walk(directory, topdown=False):
        if root != directory and not os.listdir(root):
            os.rmdir(root)

    if removed:
        print(f"[dependency-prune-l1] removed {len(removed)} unreferenced dependency module(s)")
    return removed


def _run_duplicate_gate(directory):
    """Drop approved exact-byte duplicate targets; reject unknown groups."""
    import hashlib

    from dataset.sany_audit import is_task_file

    with open(_DUPLICATE_TASK_FAMILIES_PATH, encoding="utf-8") as f:
        duplicate_families = json.load(f)

    tasks = sorted(glob.glob(os.path.join(directory, "**", "*.tla"), recursive=True))
    tasks = [path for path in tasks if is_task_file(path)]
    by_hash = {}
    for path in tasks:
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        by_hash.setdefault(digest, []).append(path)

    approved = []
    unknown = []
    for group in (paths for paths in by_hash.values() if len(paths) > 1):
        basenames = {os.path.basename(path) for path in group}
        source_dirs = {os.path.relpath(path, directory).split(os.sep, 1)[0] for path in group}
        keeper = None
        if len(basenames) == 1:
            basename = next(iter(basenames))
            for family in duplicate_families:
                prefix = family["target_prefix"]
                canonical = family["canonical"]
                copies = set(family["copies"])
                keepers = [path for path in group if os.path.relpath(path, directory).split(os.sep, 1)[0] == canonical]
                if basename.startswith(prefix) and len(keepers) == 1 and source_dirs <= copies | {canonical}:
                    keeper = keepers[0]
                    break
        if keeper is None:
            unknown.append(group)
        else:
            approved.append((keeper, group))

    if unknown:
        detail = "\n".join(
            "  - " + "\n    ".join(os.path.relpath(path, directory) for path in group) for group in unknown
        )
        raise RuntimeError(f"duplicate task gate found {len(unknown)} unapproved exact-byte group(s):\n{detail}")

    removed = []
    for keeper, group in approved:
        for path in group:
            if path == keeper:
                continue
            os.remove(path)
            removed.append(path)
            print(
                f"  [duplicate-gate-l1] removed {os.path.relpath(path, directory)} "
                f"(same target as {os.path.relpath(keeper, directory)})"
            )
    print(f"[duplicate-gate-l1] checked {len(tasks)} task(s), removed {len(removed)} approved duplicate(s)")
    _prune_unreferenced_dependencies(directory)
    return removed


def _run_triviality_gate(directory):
    """Post-generation triviality gate: a task whose PROOF OBVIOUS placeholder
    already verifies is degenerate (a no-op submission would PASS grading).
    Drops such tasks so a fresh generation never re-ships them (manifest + stdout
    keep the audit trail). Returns the number of tasks dropped.
    """
    from dataset.triviality_audit import gate

    return len(gate(directory, label="triviality-gate-l1", drop=True))


def _drop_detail(total, duplicate_count, dropped):
    if not duplicate_count and not dropped:
        return ""
    return f" ({total} generated, {duplicate_count} duplicates and {dropped} degenerate tasks dropped)"


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate proof-completion benchmarks.")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use a legacy generator instead of the default layered layout.",
    )
    parser.add_argument(
        "--shared-model",
        action="store_true",
        help="Legacy mode only: emit one proof-free <Module>.tla model per output dir "
        "and have tasks EXTEND it instead of inlining the spec.",
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        help="Skip the SANY and triviality gates for layered generation. "
        "For fast iteration — a shipped dataset must be generated with them.",
    )
    parser.add_argument("--source-dir", default=None, help="Directory of source .tla files (default: source/)")
    parser.add_argument("--filter", default=None, help="Substring limiting which source files are processed")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for layered or legacy shared-model generation (default: benchmark/proof-completion)",
    )
    parser.add_argument("files", nargs="*", help="Specific source .tla files to process")
    args = parser.parse_args()

    if args.shared_model and not args.legacy:
        parser.error("--shared-model requires --legacy; layered generation already performs the model split")
    if args.legacy and args.output_dir is not None and not args.shared_model:
        parser.error("--output-dir requires --shared-model with --legacy")
    if args.legacy and (args.filter is not None or args.files or args.source_dir is not None or args.skip_gates):
        parser.error("--source-dir, --filter, --skip-gates and positional files are unavailable with --legacy")

    if not args.legacy:
        generate_layered(
            output_root=args.output_dir,
            source_dir=args.source_dir,
            filter_substring=args.filter,
            files=args.files,
            run_gates=not args.skip_gates,
        )
        return

    if args.shared_model:
        total = generate_shared_model_l1(output_root=args.output_dir)
        duplicates = _run_duplicate_gate(args.output_dir or BENCHMARK_DIR)
        dropped = _run_sany_gate(args.output_dir or BENCHMARK_DIR)
        _prune_unreferenced_dependencies(args.output_dir or BENCHMARK_DIR)
        detail = _drop_detail(total, len(duplicates), dropped)
        print(f"Total proof-completion benchmarks (shared-model): {total - len(duplicates) - dropped}{detail}")
        return

    # Clean benchmark dir
    if os.path.exists(BENCHMARK_DIR):
        import shutil

        shutil.rmtree(BENCHMARK_DIR)
    os.makedirs(BENCHMARK_DIR, exist_ok=True)

    module_dirs = find_source_dirs()
    total = 0

    for mod_dir in module_dirs:
        print(f"\nProcessing {mod_dir}/")
        count = process_module_dir(mod_dir)
        total += count
        if count:
            print(f"  -> {count} benchmarks")

    duplicates = _run_duplicate_gate(BENCHMARK_DIR)
    dropped = _run_sany_gate(BENCHMARK_DIR)
    _prune_unreferenced_dependencies(BENCHMARK_DIR)
    detail = _drop_detail(total, len(duplicates), dropped)
    print(f"\nTotal benchmarks generated: {total - len(duplicates) - dropped}{detail}")


if __name__ == "__main__":
    main()

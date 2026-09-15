"""Permanent guard: no benchmark file may leak proof content outside a module.

Content after a module's ``====`` terminator is invisible to SANY/tlapm but
readable by an agent — so a generator that fails to truncate the source leaves
the reference proof there as an answer leak (the CRDT contamination bug, which
regressed once unnoticed because nothing asserted against it). This test is that
assertion: it fails if any benchmark `.tla` has a THEOREM/LEMMA/proof step
outside a module body. Keep it green.

Run: PYTHONPATH=src python3 -m pytest tests/dataset/test_benchmark_integrity.py
"""

import os

import pytest

from dataset.integrity import check_dir, iter_leaks

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROOTS = [
    os.path.join(REPO, "source"),  # the origin — a malformed source leaks into every derived task
    os.path.join(REPO, "benchmark", "proof-completion"),
    os.path.join(REPO, "benchmark", "proof-from-scratch"),
    os.path.join(REPO, "benchmark", "proof-from-scratch-module"),
    os.path.join(REPO, "unvalidated-proof-exercises"),
]


def test_clean_module_has_no_leak():
    spec = "---- MODULE M ----\nx == 1\nTHEOREM T == TRUE\n  OBVIOUS\n====\n"
    assert list(iter_leaks(spec)) == []


def test_proof_after_module_end_is_a_leak():
    spec = "---- MODULE M ----\nx == 1\n====\nLEMMA L == TRUE\n  OBVIOUS\n"
    assert list(iter_leaks(spec))  # the LEMMA dangling after ==== is the answer leak


def test_nested_submodule_does_not_false_flag():
    # A theorem after an INNER submodule's ==== is still inside the OUTER module —
    # legitimate, not a leak. Requires module_depth to be a counter, not a flag.
    spec = (
        "---- MODULE Outer ----\n"
        "EXTENDS Naturals\n"
        "---- MODULE Inner ----\n"
        "x == 1\n"
        "====\n"
        "Bar == 2\n"
        "THEOREM Bar = 2 BY DEF Bar\n"
        "====\n"
    )
    assert list(iter_leaks(spec)) == []


def test_leak_after_outer_module_still_flagged_with_nesting():
    # Content after the OUTER terminator (depth back to 0) is still a leak.
    spec = "---- MODULE Outer ----\n---- MODULE Inner ----\n====\n====\nTHEOREM Leaked == TRUE\n  BY DEF X\n"
    assert list(iter_leaks(spec))


@pytest.mark.parametrize("root", ROOTS, ids=lambda r: os.path.basename(r))
def test_no_proof_leak_outside_module(root):
    if not os.path.isdir(root):
        pytest.skip(f"benchmark dir absent: {root}")
    bad = check_dir(root)
    if bad:
        lines = []
        for f, leaks in sorted(bad.items()):
            rel = f.split("benchmark/")[-1]
            lines.append(
                f"  {rel}: {len(leaks)} leaked tokens (first @ line {leaks[0][0]}: {leaks[0][1].strip()[:50]!r})"
            )
        detail = "\n".join(lines)
        pytest.fail(
            f"{len(bad)} benchmark file(s) leak proof/theorem content OUTSIDE a module "
            f"(answer contamination — strip everything after the first `====`):\n{detail}"
        )

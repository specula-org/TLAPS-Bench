"""Focused tests for the strict module-task manifest loader."""

from __future__ import annotations

import copy
import hashlib
import json
import pickle
from pathlib import Path

import pytest

from common.proof_from_scratch_manifest import (
    MANIFEST_FILENAME,
    ModuleTaskManifestError,
    load_module_task_manifest,
)
from common.proof_from_scratch_module import (
    MODULE_TASK_FORMAT_VERSION,
    begin_agent_proof,
    end_agent_proof,
    statement_sha256,
)
from common.task_contract import BEGIN_AGENT_HELPERS, END_AGENT_HELPERS

TASK_ID = "Group/Source.tla"
UNIT_A = "Group/Source_Alpha.tla"
UNIT_B = "Group/Source_Beta.tla"
CONTEXT_ID = "Group/SourceDefs.tla"
CORPUS_BYTES = (
    b'{"Group/Source_Alpha.tla":{"spec_id":"Group/Source.tla","context":[]},'
    b'"Group/Source_Beta.tla":{"spec_id":"Group/Source.tla","context":[]}}\n'
)
STATEMENT_A = "THEOREM Alpha == captured = captured"
STATEMENT_B = "THEOREM Beta == TRUE"


def _task_source(*, statement_a: str = STATEMENT_A, statement_b: str = STATEMENT_B) -> str:
    lines = [
        "---- MODULE Source ----",
        "EXTENDS SourceDefs",
        "",
        BEGIN_AGENT_HELPERS,
        END_AGENT_HELPERS,
        "",
        statement_a,
        begin_agent_proof(UNIT_A),
        "PROOF OMITTED",
        end_agent_proof(UNIT_A),
        "",
        statement_b,
        begin_agent_proof(UNIT_B),
        "PROOF OMITTED",
        end_agent_proof(UNIT_B),
        "====",
        "",
    ]
    return "\n".join(lines)


def _context_source() -> str:
    return "---- MODULE SourceDefs ----\n====\n"


def _entry() -> dict:
    return {
        "spec": {
            "format_version": MODULE_TASK_FORMAT_VERSION,
            "task_id": TASK_ID,
            "source_sha256": hashlib.sha256(b"original Source.tla").hexdigest(),
            "proof_units": [
                {"task_id": UNIT_A, "statement_sha256": statement_sha256(STATEMENT_A)},
                {"task_id": UNIT_B, "statement_sha256": statement_sha256(STATEMENT_B)},
            ],
        },
        "context": [CONTEXT_ID],
        "renamed_bindings": {UNIT_A: {"captured": "captured_renamed"}},
    }


def _document(*, entries: list[dict] | None = None, complete: bool = True, corpus_bytes: bytes = CORPUS_BYTES) -> dict:
    return {
        "format_version": MODULE_TASK_FORMAT_VERSION,
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "complete": complete,
        "module_tasks": [_entry()] if entries is None else entries,
    }


def _write_document(root: Path, document: dict) -> None:
    (root / MANIFEST_FILENAME).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _materialize(
    tmp_path: Path,
    *,
    document: dict | None = None,
    task_source: str | None = None,
    context_source: str | None = None,
    corpus_bytes: bytes = CORPUS_BYTES,
    source_bytes: bytes = b"original Source.tla",
) -> tuple[Path, Path]:
    root = tmp_path / "module-suite"
    root.mkdir()
    document = _document() if document is None else document

    task_path = root / TASK_ID
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(_task_source() if task_source is None else task_source, encoding="utf-8")

    context_path = root / CONTEXT_ID
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(_context_source() if context_source is None else context_source, encoding="utf-8")

    source_path = tmp_path / "source" / TASK_ID
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(source_bytes)

    _write_document(root, document)

    corpus_path = tmp_path / "proof-from-scratch" / MANIFEST_FILENAME
    corpus_path.parent.mkdir()
    corpus_path.write_bytes(corpus_bytes)
    return root, corpus_path


def _load(root: Path, corpus_path: Path):
    return load_module_task_manifest(root, corpus_manifest_path=corpus_path, source_root=root.parent / "source")


def test_loads_a_complete_manifest_strictly(tmp_path):
    root, corpus_path = _materialize(tmp_path)

    manifest = _load(root, corpus_path)

    assert manifest.format_version == MODULE_TASK_FORMAT_VERSION
    assert manifest.proof_unit_ids == (UNIT_A, UNIT_B)
    assert manifest.entries[0].context == (CONTEXT_ID,)
    assert manifest.entries[0].renamed_bindings == ((UNIT_A, (("captured", "captured_renamed"),)),)


def test_rejects_duplicate_module_task_ids(tmp_path):
    entry = _entry()
    root, corpus_path = _materialize(tmp_path, document=_document(entries=[entry, copy.deepcopy(entry)]))

    with pytest.raises(ModuleTaskManifestError, match="repeats task ID"):
        _load(root, corpus_path)


def test_rejects_duplicate_proof_unit_ids_across_tasks(tmp_path):
    first = _entry()
    second = copy.deepcopy(first)
    second["spec"]["task_id"] = "Group/Other.tla"
    root, corpus_path = _materialize(tmp_path, document=_document(entries=[first, second]))

    with pytest.raises(ModuleTaskManifestError, match="more than one module task"):
        _load(root, corpus_path)


def test_rejects_a_forged_proof_unit_id(tmp_path):
    document = _document()
    document["module_tasks"][0]["spec"]["proof_units"][0]["task_id"] = "Group/Forged.tla"
    document["module_tasks"][0]["renamed_bindings"] = {"Group/Forged.tla": {"captured": "captured_renamed"}}
    root, corpus_path = _materialize(tmp_path, document=document)

    with pytest.raises(ModuleTaskManifestError, match="BEGIN"):
        _load(root, corpus_path)


def test_rejects_statement_digest_mismatch(tmp_path):
    root, corpus_path = _materialize(tmp_path, task_source=_task_source(statement_a="THEOREM Alpha == FALSE"))

    with pytest.raises(ModuleTaskManifestError, match="statement digest does not match"):
        _load(root, corpus_path)


def test_rejects_a_source_hash_mismatch(tmp_path):
    root, corpus_path = _materialize(tmp_path, source_bytes=b"changed Source.tla")

    with pytest.raises(ModuleTaskManifestError, match="source_sha256 does not match"):
        _load(root, corpus_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda source: source.replace(f"{end_agent_proof(UNIT_B)}\n", "", 1),
            "exactly one END",
        ),
        (
            lambda source: source.replace(
                "====\n",
                f"{begin_agent_proof('Group/Forged.tla')}\n====\n",
                1,
            ),
            "unknown proof marker",
        ),
    ],
)
def test_rejects_malformed_or_unknown_markers(tmp_path, mutate, message):
    original = _task_source()
    root, corpus_path = _materialize(tmp_path, task_source=mutate(original))

    with pytest.raises(ModuleTaskManifestError, match=message):
        _load(root, corpus_path)


def test_rejects_context_that_is_tampered_to_include_the_task(tmp_path):
    document = _document()
    document["module_tasks"][0]["context"] = [TASK_ID]
    root, corpus_path = _materialize(tmp_path, document=document)

    with pytest.raises(ModuleTaskManifestError, match="also appears in its context"):
        _load(root, corpus_path)


def test_rejects_a_missing_context_file(tmp_path):
    root, corpus_path = _materialize(tmp_path)
    (root / CONTEXT_ID).unlink()

    with pytest.raises(ModuleTaskManifestError, match="context"):
        _load(root, corpus_path)


def test_rejects_proof_artifacts_in_tampered_context(tmp_path):
    context = _context_source() + f"{begin_agent_proof(UNIT_A)}\nPROOF OBVIOUS\n{end_agent_proof(UNIT_A)}\n"
    root, corpus_path = _materialize(tmp_path, context_source=context)

    with pytest.raises(ModuleTaskManifestError, match="context|proof"):
        _load(root, corpus_path)


def test_rejects_a_corpus_digest_mismatch(tmp_path):
    root, corpus_path = _materialize(tmp_path)
    corpus_path.write_bytes(b"a different source corpus\n")

    with pytest.raises(ModuleTaskManifestError, match="different proof-from-scratch corpus"):
        _load(root, corpus_path)


def test_rejects_self_consistent_manifest_that_drops_a_corpus_proof_unit(tmp_path):
    document = _document()
    document["module_tasks"][0]["spec"]["proof_units"] = document["module_tasks"][0]["spec"]["proof_units"][:1]
    source = _task_source()
    second_start = source.index("\n" + STATEMENT_B)
    second_end = source.index("\n====", second_start)
    source = source[:second_start] + source[second_end:]
    root, corpus_path = _materialize(tmp_path, document=document, task_source=source)

    with pytest.raises(ModuleTaskManifestError, match="proof-unit coverage differs"):
        _load(root, corpus_path)


def test_rejects_an_incomplete_manifest(tmp_path):
    root, corpus_path = _materialize(tmp_path, document=_document(complete=False))

    with pytest.raises(ModuleTaskManifestError, match="complete corpus"):
        _load(root, corpus_path)


def test_validated_manifest_is_pickleable(tmp_path):
    root, corpus_path = _materialize(tmp_path)
    manifest = _load(root, corpus_path)

    restored = pickle.loads(pickle.dumps(manifest))

    assert restored == manifest

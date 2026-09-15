"""Portable Agent Skill discovery, snapshotting, and result metadata."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evaluator import runner
from evaluator.agent_skills import discover_agent_skills
from evaluator.backends import get_backend
from evaluator.backends.agentic import AgenticBackend
from evaluator.modes.proof_from_scratch import ProofFromScratch

EXPECTED_SKILLS = {
    "tla-inductive-invariant-validation",
    "tlaps-proof-hints",
}
SUPPORTED_BACKENDS = [
    ("codex", ".agents/skills"),
    ("claude_code", ".claude/skills"),
    ("copilot", ".github/skills"),
    ("cursor", ".agents/skills"),
    ("litellm", ".agents/skills"),
    ("pi", ".agents/skills"),
]
UNSUPPORTED_BACKENDS = ["codex_single_turn", "copilot_oneshot", "litellm_oneshot"]
BENCHMARK = "---- MODULE Task ----\nTHEOREM Goal == TRUE\nPROOF OBVIOUS\n====\n"


def _parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    source = path.read_text(encoding="utf-8")
    assert source.startswith("---\n")
    frontmatter, separator, body = source[4:].partition("\n---\n")
    assert separator
    metadata = {}
    for line in frontmatter.splitlines():
        key, value = line.split(":", 1)
        metadata[key] = value.strip()
    return metadata, body


def _write_catalog(root: Path) -> dict[str, dict[str, bytes]]:
    expected = {
        "zeta-skill": {
            "SKILL.md": b"---\nname: zeta-skill\ndescription: Use when testing zeta.\n---\n\nZeta.\n",
            "references/payload.bin": b"\x00zeta\xff",
        },
        "alpha-skill": {
            "SKILL.md": b"---\nname: alpha-skill\ndescription: Use when testing alpha.\n---\n\nAlpha.\n",
        },
    }
    for skill, files in expected.items():
        for relative, content in files.items():
            path = root / skill / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    (root / "not-a-skill").mkdir()
    (root / "not-a-skill" / "README.md").write_text("ignored")
    nested = root / "container" / "nested-skill"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("---\nname: nested-skill\ndescription: ignored\n---\n")
    (root / "SKILL.md").write_text("---\nname: root-file\ndescription: ignored\n---\n")
    return expected


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class _Mode:
    name = "proof-completion"
    read_only_dependencies = False
    canonical_replay_required = False

    def __init__(self, root: Path):
        self.root = root

    def benchmark_dir(self):
        return str(self.root)

    def get_dependencies(self, benchmark_path):
        return []

    def checker_binary_path(self):
        return "/bin/true"

    def build_prompt(self, basename, tlapm_path, tlapm_lib):
        return "Prove it."


def _work_item(tmp_path: Path, backend) -> runner.WorkItem:
    benchmark_root = tmp_path / "benchmark"
    benchmark = benchmark_root / "Suite" / "Task.tla"
    benchmark.parent.mkdir(parents=True)
    benchmark.write_text(BENCHMARK)
    return runner.WorkItem(
        benchmark_path=str(benchmark),
        output_dir=str(tmp_path / "results"),
        timeout=10,
        check_timeout=10,
        backend=backend,
        mode=_Mode(benchmark_root),  # ty:ignore[invalid-argument-type]
        tlapm_path="/bin/true",
        tlapm_lib="",
        infra_retries=0,
    )


def test_checked_in_skills_have_portable_metadata_and_guidance():
    skills_root = Path(runner.SKILLS_DIR)
    discovered = discover_agent_skills(skills_root)

    assert [skill.name for skill in discovered] == sorted(EXPECTED_SKILLS)
    for skill in discovered:
        skill_file = skill.source_dir / "SKILL.md"
        metadata, body = _parse_frontmatter(skill_file)
        assert set(metadata) == {"name", "description"}
        assert metadata["name"] == skill.name == skill.source_dir.name
        assert metadata["description"] == skill.description
        assert "Use when" in skill.description
        assert body.strip()

    invariant = (skills_root / "tla-inductive-invariant-validation" / "SKILL.md").read_text()
    for retained_guidance in (
        "--init=Init --inv=IndInv --length=0",
        "--init=IndInv --inv=IndInv --length=1",
        "--init=IndInv --inv=Safety --length=0",
        "INIT Init\nNEXT Next\n\nCONSTANT N = 5",
        r"TypeOK /\ H",
        "violation1.tla",
        r"\* @type:",
        "java -cp /opt/sany/lib/tla2tools.jar tlc2.TLC",
        "RandomSubset",
        "check_proof_bin",
    ):
        assert retained_guidance in invariant
    for obsolete_placeholder in ("{benchmark_basename}", "APFoo", "MCFoo", "Foo.tla"):
        assert obsolete_placeholder not in invariant

    hints = (skills_root / "tlaps-proof-hints" / "SKILL.md").read_text()
    assert "BY I!Thm, NA" in hints
    assert "THEOREM Bridge" in hints
    assert "tlaplus/tlapm#279" in hints
    assert not (Path(runner.REPO_ROOT) / "docs" / "hints" / "tlaps-proof-hints.md").exists()


@pytest.mark.parametrize(
    ("directory", "source", "error"),
    [
        ("missing-frontmatter", "# Instructions\n", "missing YAML frontmatter"),
        (
            "unclosed-frontmatter",
            "---\nname: unclosed-frontmatter\ndescription: Use when testing.\n",
            "unclosed YAML frontmatter",
        ),
        (
            "missing-name",
            "---\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "missing required metadata name",
        ),
        (
            "missing-description",
            "---\nname: missing-description\n---\n\nInstructions.\n",
            "missing required metadata description",
        ),
        (
            "duplicate-name",
            "---\nname: duplicate-name\nname: duplicate-name\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "invalid YAML frontmatter",
        ),
        (
            "wrong-directory",
            "---\nname: another-name\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "must match directory",
        ),
        (
            "invalid_name",
            "---\nname: invalid_name\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "invalid Agent Skill name",
        ),
        (
            "empty-body",
            "---\nname: empty-body\ndescription: Use when testing.\n---\n",
            "has no instructions",
        ),
        (
            "invalid-yaml",
            "---\nname: invalid-yaml\ndescription: [unterminated\n---\n\nInstructions.\n",
            "invalid YAML frontmatter",
        ),
        (
            "non-string-name",
            "---\nname: [testing]\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "name must be a string",
        ),
        (
            "non-string-description",
            "---\nname: non-string-description\ndescription: [testing]\n---\n\nInstructions.\n",
            "description must be a string",
        ),
        (
            "boolean-name",
            "---\nname: true\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "name must be a string",
        ),
        (
            "numeric-name",
            "---\nname: 123\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "name must be a string",
        ),
        (
            "null-name",
            "---\nname: null\ndescription: Use when testing.\n---\n\nInstructions.\n",
            "name must be a string",
        ),
        (
            "boolean-description",
            "---\nname: boolean-description\ndescription: true\n---\n\nInstructions.\n",
            "description must be a string",
        ),
        (
            "numeric-description",
            "---\nname: numeric-description\ndescription: 123\n---\n\nInstructions.\n",
            "description must be a string",
        ),
        (
            "exponent-description",
            "---\nname: exponent-description\ndescription: 1e3\n---\n\nInstructions.\n",
            "description must be a string",
        ),
        (
            "leading-zero-description",
            "---\nname: leading-zero-description\ndescription: 08\n---\n\nInstructions.\n",
            "description must be a string",
        ),
        (
            "octal-description",
            "---\nname: octal-description\ndescription: 0o17\n---\n\nInstructions.\n",
            "description must be a string",
        ),
        (
            "null-description",
            "---\nname: null-description\ndescription: null\n---\n\nInstructions.\n",
            "description must be a string",
        ),
    ],
)
def test_shared_discovery_rejects_invalid_skill_metadata(tmp_path, directory, source, error):
    skill_dir = tmp_path / directory
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(source)

    with pytest.raises(ValueError, match=error):
        discover_agent_skills(tmp_path)


def test_shared_discovery_parses_quoted_metadata_and_ignores_non_skills(tmp_path):
    skill_dir = tmp_path / "quoted-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: \"quoted-skill\"\ndescription: 'Use when it''s relevant.' # trigger\n---\n\nInstructions.\n"
    )
    ignored = tmp_path / "not-a-skill"
    ignored.mkdir()
    (ignored / "README.md").write_text("Ignored.")

    skills = discover_agent_skills(tmp_path)
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "quoted-skill"
    assert skill.description == "Use when it's relevant."
    assert skill.source_dir == skill_dir


@pytest.mark.parametrize("description", ("123", "1e3", "08", "0o17"))
def test_shared_discovery_accepts_quoted_yaml_lookalike_scalars(tmp_path, description):
    skill_dir = tmp_path / "true"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(f'---\nname: "true"\ndescription: "{description}"\n---\n\nInstructions.\n')

    skill = discover_agent_skills(tmp_path)[0]

    assert skill.name == "true"
    assert skill.description == description


@pytest.mark.parametrize(
    ("name", "description"),
    (("on", "2026-08-04"), ("off", "="), ("yes", "<<"), ("no", "no")),
)
def test_shared_discovery_uses_yaml12_string_resolution(tmp_path, name, description):
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\nInstructions.\n")

    skill = discover_agent_skills(tmp_path)[0]

    assert skill.name == name
    assert skill.description == description


def test_shared_discovery_accepts_yaml_block_descriptions(tmp_path):
    skill_dir = tmp_path / "block-description"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: block-description\n"
        "description: >\n"
        "  Validates candidate invariants.\n"
        "  Use when developing a safety proof.\n"
        "metadata:\n"
        "  author: benchmark\n"
        "---\n\n"
        "Instructions.\n"
    )

    skill = discover_agent_skills(tmp_path)[0]

    assert skill.description == "Validates candidate invariants. Use when developing a safety proof."


def test_shared_discovery_accepts_spec_length_boundaries(tmp_path):
    name = "a" * 64
    description = "d" * 1024
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\nInstructions.\n")

    skill = discover_agent_skills(tmp_path)[0]

    assert skill.name == name
    assert skill.description == description


@pytest.mark.parametrize(
    ("name", "description", "error"),
    [
        ("a" * 65, "Valid description.", "name must be 1-64 characters"),
        ("valid-name", "d" * 1025, "description must be 1-1024 characters"),
        ("valid-name", "   ", "description must be 1-1024 characters"),
    ],
)
def test_shared_discovery_rejects_metadata_outside_spec_length_limits(tmp_path, name, description, error):
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "{description}"\n---\n\nInstructions.\n')

    with pytest.raises(ValueError, match=error):
        discover_agent_skills(tmp_path)


def test_litellm_container_receives_shared_skill_parser():
    dockerfile = Path("docker/base.Dockerfile").read_text()
    installer = Path("docker/install-scripts/install-litellm.sh").read_text()

    assert "COPY src/evaluator/__init__.py src/evaluator/agent_skills.py /opt/evaluator/" in dockerfile
    assert "litellm pyyaml" in installer


def test_ci_requires_real_pi_skill_discovery():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "bash docker/install-scripts/install-pi.sh" in workflow
    assert 'TLAPS_BENCH_REQUIRE_PI_CLI: "1"' in workflow


@pytest.mark.parametrize(("backend_name", "project_skills_dir"), SUPPORTED_BACKENDS)
def test_supported_backends_receive_byte_exact_skills_in_clean_fresh_workspaces(
    tmp_path, monkeypatch, backend_name, project_skills_dir
):
    catalog = tmp_path / "catalog"
    expected = _write_catalog(catalog)
    monkeypatch.setattr(runner, "SKILLS_DIR", str(catalog))
    backend = get_backend(backend_name)
    snapshot = tmp_path / "input" / "skills"

    assert backend.project_skills_dir == project_skills_dir
    assert runner._snapshot_agent_skills(backend, str(snapshot)) == ["alpha-skill", "zeta-skill"]
    expected_bytes = {
        f"{skill}/{relative}": content for skill, files in expected.items() for relative, content in files.items()
    }
    assert _tree_bytes(snapshot) == expected_bytes

    canonical = runner.CanonicalInputs("Task.tla", BENCHMARK.encode(), ())
    workspaces = []
    try:
        first = Path(
            runner._make_workspace(
                backend.name,
                "Task",
                canonical,
                skills_snapshot_dir=str(snapshot),
                project_skills_dir=backend.project_skills_dir,
            )
        )
        workspaces.append(first)
        installed = first / project_skills_dir
        assert _tree_bytes(installed) == expected_bytes
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=first,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert f"{project_skills_dir}/alpha-skill/SKILL.md" in tracked
        assert f"{project_skills_dir}/zeta-skill/references/payload.bin" in tracked
        assert (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=first,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == ""
        )

        (installed / "alpha-skill" / "SKILL.md").write_text("TAINTED")
        second = Path(
            runner._make_workspace(
                backend.name,
                "Task",
                canonical,
                skills_snapshot_dir=str(snapshot),
                project_skills_dir=backend.project_skills_dir,
            )
        )
        workspaces.append(second)
        assert second != first
        assert _tree_bytes(second / project_skills_dir) == expected_bytes
        assert _tree_bytes(snapshot) == expected_bytes
        assert (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=second,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            == ""
        )
    finally:
        for workspace in workspaces:
            runner.shutil.rmtree(workspace)


def test_agent_skill_snapshot_freezes_bytes_and_has_content_identity(tmp_path):
    catalog = tmp_path / "catalog"
    expected = _write_catalog(catalog)
    backend = get_backend("codex")

    frozen = runner.AgentSkillsSnapshot.capture(backend, catalog)
    (catalog / "zeta-skill" / "references" / "payload.bin").write_bytes(b"changed after capture")
    changed = runner.AgentSkillsSnapshot.capture(backend, catalog)
    destination = tmp_path / "snapshot"
    frozen.materialize(destination)

    assert frozen.digest() != changed.digest()
    assert (destination / "alpha-skill" / "SKILL.md").read_bytes() == expected["alpha-skill"]["SKILL.md"]


@pytest.mark.parametrize("backend_name", UNSUPPORTED_BACKENDS)
def test_unsupported_backends_receive_no_skills_and_report_empty_metadata(tmp_path, monkeypatch, backend_name):
    catalog = tmp_path / "catalog"
    _write_catalog(catalog)
    monkeypatch.setattr(runner, "SKILLS_DIR", str(catalog))
    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *args, **kwargs: False)
    backend = get_backend(backend_name)

    assert backend.project_skills_dir is None
    result = runner.run_single_benchmark(_work_item(tmp_path, backend))

    assert result["agent_skills"] == []
    assert "indinv_check_prompted" not in result
    snapshot = tmp_path / "results" / "Suite" / "Task" / "input" / "skills"
    assert snapshot.is_dir()
    assert list(snapshot.iterdir()) == []

    canonical = runner.CanonicalInputs("Task.tla", BENCHMARK.encode(), ())
    workspace = Path(
        runner._make_workspace(
            backend.name,
            "Task",
            canonical,
            skills_snapshot_dir=str(snapshot),
            project_skills_dir=backend.project_skills_dir,
        )
    )
    try:
        assert not (workspace / ".agents").exists()
        assert not (workspace / ".claude").exists()
        assert not (workspace / ".github").exists()
    finally:
        runner.shutil.rmtree(workspace)


@pytest.mark.parametrize("backend_name", ["codex", "litellm"])
def test_quota_skip_records_sorted_skill_availability(tmp_path, monkeypatch, backend_name):
    catalog = tmp_path / "catalog"
    _write_catalog(catalog)
    monkeypatch.setattr(runner, "SKILLS_DIR", str(catalog))
    monkeypatch.setattr(runner.quota, "wait_for_quota", lambda *args, **kwargs: False)

    result = runner.run_single_benchmark(_work_item(tmp_path, get_backend(backend_name)))

    assert result["agent_skills"] == ["alpha-skill", "zeta-skill"]
    assert "indinv_check_prompted" not in result
    snapshot = tmp_path / "results" / "Suite" / "Task" / "input" / "skills"
    assert sorted(path.name for path in snapshot.iterdir()) == ["alpha-skill", "zeta-skill"]


class _RetryBackend(AgenticBackend):
    name = "copilot"
    project_skills_dir = ".agents/skills"

    def __init__(self):
        self.output_tokens = 0

    def build_command(self, workspace, result_dir):
        return ["fake-agent"]

    def parse_output(self, jsonl_path):
        return "", 0, self.output_tokens


def test_infrastructure_retry_repopulates_skills_from_the_input_snapshot(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    expected = _write_catalog(catalog)
    monkeypatch.setattr(runner, "SKILLS_DIR", str(catalog))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    backend = _RetryBackend()
    item = _work_item(tmp_path, backend)
    item.infra_retries = 1
    seen = []
    workspaces = []

    def fake_agent(
        item_,
        backend_,
        mode,
        workspace,
        agent_dir,
        agent_jsonl,
        prompt,
        result,
        checker_bin,
        canonical_dir=None,
    ):
        attempt = len(seen)
        workspaces.append(workspace)
        skill = Path(workspace) / ".agents" / "skills" / "alpha-skill" / "SKILL.md"
        seen.append(skill.read_bytes())
        with open(agent_jsonl, "w") as stream:
            if attempt:
                stream.write(json.dumps({"type": "result", "exitCode": 0}) + "\n")
        if attempt == 0:
            skill.write_text("TAINTED")
            Path(agent_dir, "stderr.txt").write_text("Error: Failed to load models\n")
            result["agent_exit"] = 1
            backend.output_tokens = 0
        else:
            result["agent_exit"] = 0
            backend.output_tokens = 10

    def fake_grader(item_, workspace, basename, grading_dir, check_result_path, result, canonical_dir=None):
        result["check_verdict"] = "FAIL"

    monkeypatch.setattr(runner, "_run_backend_local", fake_agent)
    monkeypatch.setattr(runner, "_run_grader_local", fake_grader)

    result = runner.run_single_benchmark(item)

    original = expected["alpha-skill"]["SKILL.md"]
    assert seen == [original, original]
    assert workspaces[0] != workspaces[1]
    assert result["agent_skills"] == ["alpha-skill", "zeta-skill"]
    assert result["infra_retries"] == 1
    snapshot = tmp_path / "results" / "Suite" / "Task" / "input" / "skills"
    assert (snapshot / "alpha-skill" / "SKILL.md").read_bytes() == original


def test_agentic_prompt_drops_inline_model_checker_guide_without_skill_pointer(tmp_path):
    mode = ProofFromScratch(str(tmp_path), "/bin/true")

    prompt = mode.build_prompt("Target.tla", "/opt/tlapm", "/opt/tlapm/lib")

    assert "Validating inductive invariant candidates" not in prompt
    assert "apalache-mc" not in prompt
    assert "tlc2.TLC" not in prompt
    assert not EXPECTED_SKILLS.intersection(prompt.split())
    assert "check_proof_bin Target.tla --mode proof-from-scratch" in prompt
    assert "Every helper `LEMMA` or `THEOREM` must be named and fully proved" in prompt
    assert 'SMTT("rN")' in prompt
    assert "temporary wrappers, configs, traces, and other scratch files" in prompt
    assert "the final task must not import or depend on scratch files" in prompt
    assert "Do not modify or replace supplied dependency modules" in prompt

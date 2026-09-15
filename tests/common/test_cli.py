"""Top-level CLI argument routing."""

from tlaps_bench import cli


def test_public_check_enables_strict_proof_from_scratch_default(monkeypatch):
    captured = {}

    def fake_dispatch(prog, module_name, attr, passthrough, *, entry_kwargs=None):
        captured.update(
            prog=prog,
            module_name=module_name,
            attr=attr,
            passthrough=passthrough,
            entry_kwargs=entry_kwargs,
        )
        return 0

    monkeypatch.setattr(cli, "_dispatch", fake_dispatch)

    assert cli.main(["check", "Task.tla", "--mode", "proof-from-scratch"]) == 0
    assert captured == {
        "prog": "tlaps-bench check",
        "module_name": "common.check_proof",
        "attr": "main",
        "passthrough": ["Task.tla", "--mode", "proof-from-scratch"],
        "entry_kwargs": {"require_canonical_for_proof_from_scratch": True},
    }


def test_generate_routes_legacy_shared_model_arguments(monkeypatch, tmp_path):
    captured = {}

    def fake_dispatch(prog, module_name, attr, passthrough, *, entry_kwargs=None):
        captured.update(
            prog=prog,
            module_name=module_name,
            attr=attr,
            passthrough=passthrough,
            entry_kwargs=entry_kwargs,
        )
        return 0

    monkeypatch.setattr(cli, "_dispatch", fake_dispatch)
    output_dir = tmp_path / "shared-model"

    assert (
        cli.main(
            [
                "generate",
                "--mode",
                "proof-completion",
                "--legacy",
                "--shared-model",
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    assert captured == {
        "prog": "tlaps-bench generate --mode proof-completion",
        "module_name": "dataset.proof_completion.generate",
        "attr": "main",
        "passthrough": ["--legacy", "--shared-model", "--output-dir", str(output_dir)],
        "entry_kwargs": None,
    }


def test_generate_proof_from_scratch_routes_to_module_tasks(monkeypatch, tmp_path):
    captured = {}

    def fake_dispatch(prog, module_name, attr, passthrough, *, entry_kwargs=None):
        captured.update(
            prog=prog,
            module_name=module_name,
            attr=attr,
            passthrough=passthrough,
            entry_kwargs=entry_kwargs,
        )
        return 0

    monkeypatch.setattr(cli, "_dispatch", fake_dispatch)
    output_dir = tmp_path / "module-suite"
    source_dir = tmp_path / "source"

    assert (
        cli.main(
            [
                "generate",
                "--mode",
                "proof-from-scratch",
                "--output-dir",
                str(output_dir),
                "--source-dir",
                str(source_dir),
                "--verify",
            ]
        )
        == 0
    )
    assert captured == {
        "prog": "tlaps-bench generate --mode proof-from-scratch",
        "module_name": "dataset.proof_from_scratch.module_tasks",
        "attr": "main",
        "passthrough": [
            "--output-root",
            str(output_dir),
            "--source-root",
            str(source_dir),
            "--verify",
        ],
        "entry_kwargs": None,
    }

    assert (
        cli.main(
            [
                "generate",
                "--mode=proof-from-scratch",
                f"--output-dir={output_dir}",
            ]
        )
        == 0
    )
    assert captured["passthrough"] == [f"--output-root={output_dir}"]

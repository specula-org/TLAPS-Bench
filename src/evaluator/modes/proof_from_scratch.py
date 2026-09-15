"""Manifest-driven module-level proof-from-scratch evaluation."""

import os
from functools import cached_property
from pathlib import Path

from common.proof_from_scratch_manifest import ModuleTaskEntry, ModuleTaskManifest, load_module_task_manifest
from common.proof_from_scratch_module import ModuleTaskSpec

from .base import Mode

MODULE_SUITE = "proof-from-scratch-module"


class ProofFromScratch(Mode):
    name = "proof-from-scratch"
    description = "Proof from scratch — one agent session proves every selected theorem in a module"
    read_only_dependencies = True
    canonical_replay_required = True
    requires_workspace_tools = True

    def benchmark_dir(self) -> str:
        return os.path.join(self._benchmark_root, MODULE_SUITE)

    @cached_property
    def _manifest(self) -> ModuleTaskManifest:
        return load_module_task_manifest(
            Path(self.benchmark_dir()),
            corpus_manifest_path=Path(self._benchmark_root) / "proof-from-scratch" / "manifest.json",
            source_root=Path(self._benchmark_root).parent / "source",
        )

    @cached_property
    def _entries_by_path(self) -> dict[Path, ModuleTaskEntry]:
        root = Path(self.benchmark_dir())
        return {(root / entry.spec.task_id).resolve(): entry for entry in self._manifest.entries}

    def _entry_for_path(self, benchmark_path: str) -> ModuleTaskEntry:
        try:
            resolved = Path(benchmark_path).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"proof-from-scratch module task does not exist: {benchmark_path}") from exc
        entry = self._entries_by_path.get(resolved)
        if entry is None:
            raise ValueError(
                f"proof-from-scratch module task is not declared in {self.benchmark_dir()}/manifest.json: "
                f"{benchmark_path}"
            )
        return entry

    def is_benchmark_file(self, path: str) -> bool:
        """Return whether path is a complete module task declared by the manifest."""

        try:
            resolved = Path(path).resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        return resolved in self._entries_by_path

    def get_benchmark_files(self, filter_pattern: str | None = None) -> list[str]:
        """Discover complete module tasks exclusively from the shipped manifest."""

        entries = self._manifest.entries
        if filter_pattern:
            patterns = [pattern.strip() for pattern in filter_pattern.split(",") if pattern.strip()]
            entries = tuple(entry for entry in entries if any(pattern in entry.spec.task_id for pattern in patterns))
        root = Path(self.benchmark_dir())
        return [str((root / entry.spec.task_id).resolve()) for entry in entries]

    def specification_ids(self) -> dict[str, str]:
        return {entry.spec.task_id: entry.spec.task_id for entry in self._manifest.entries}

    def get_dependencies(self, benchmark_path: str) -> list[str]:
        """Return only the exact context declared for a manifest task."""

        entry = self._entry_for_path(benchmark_path)
        root = Path(self.benchmark_dir())
        return [str((root / relative).resolve()) for relative in entry.context]

    def module_task_spec(self, benchmark_path: str) -> ModuleTaskSpec:
        return self._entry_for_path(benchmark_path).spec

    def module_task_entry(self, benchmark_path: str) -> ModuleTaskEntry:
        return self._entry_for_path(benchmark_path)

    def build_one_shot_prompt(self, benchmark_path: str, dependencies: list[str]) -> str:
        del benchmark_path, dependencies
        raise ValueError("proof-from-scratch requires a backend with workspace tools")

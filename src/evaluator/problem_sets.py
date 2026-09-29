"""Curated proof-from-scratch collections, independent of task file locations."""

import json
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

PROBLEM_SET_NAMES = ("current", "retired", "next")


@dataclass(frozen=True)
class ProblemSet:
    tasks: tuple[str, ...]
    pending: tuple[tuple[str, str], ...] = ()

    def runnable_tasks(self, name: str) -> list[str]:
        if not self.tasks:
            detail = "; ".join(f"{title} ({url})" for title, url in self.pending)
            message = f"PFS problem set {name!r} has no runnable tasks"
            if detail:
                message += f"; pending merge: {detail}"
            raise ValueError(message)
        return list(self.tasks)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate problem-set key: {key!r}")
        result[key] = value
    return result


def load_problem_sets(path: Path, known_task_ids: Collection[str]) -> dict[str, ProblemSet]:
    """Validate explicit, disjoint collections against the complete PFS manifest.

    Unclassified tasks remain available to searches and custom task lists.
    Pending entries describe proposed additions; they never name runnable tasks.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read PFS problem sets {str(path)!r}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"format_version", *PROBLEM_SET_NAMES}
        or type(data["format_version"]) is not int
        or data["format_version"] != 1
    ):
        raise ValueError("PFS problem sets must contain format_version 1 and current, retired, next")

    known = set(known_task_ids)
    seen: set[str] = set()
    collections = {}
    for name in PROBLEM_SET_NAMES:
        entry = data[name]
        allowed_keys = {"tasks", "pending"} if name == "next" else {"tasks"}
        if not isinstance(entry, dict) or "tasks" not in entry or set(entry) - allowed_keys:
            raise ValueError(f"invalid PFS problem set {name!r}")
        tasks = entry["tasks"]
        if not isinstance(tasks, list) or any(not isinstance(task, str) or not task for task in tasks):
            raise ValueError(f"PFS problem set {name!r} must contain a list of task IDs")
        for task in tasks:
            if task in seen:
                raise ValueError(f"duplicate task ID in PFS problem sets: {task!r}")
            if task not in known:
                raise ValueError(f"unknown task ID in PFS problem set {name!r}: {task!r}")
            seen.add(task)
        pending = entry.get("pending", [])
        if not isinstance(pending, list):
            raise ValueError(f"pending entries in PFS problem set {name!r} must be a list")
        for proposal in pending:
            if (
                not isinstance(proposal, dict)
                or set(proposal) != {"name", "pull_request"}
                or any(not isinstance(value, str) or not value.strip() for value in proposal.values())
                or not proposal["pull_request"].startswith("https://")
            ):
                raise ValueError(f"invalid pending entry in PFS problem set {name!r}")
        collections[name] = ProblemSet(tuple(tasks), tuple((p["name"], p["pull_request"]) for p in pending))
    return collections

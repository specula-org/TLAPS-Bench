"""Count agent tool calls and conservatively classify explicit TLA+ checkers.

Backends record different JSONL event vocabularies, but they all reduce to one
entry per dispatched tool call: a shell command for shell tools and ``None`` for
everything else.  This module owns the shared count schema, evidence semantics,
stream-integrity tracking, and shell parsing used by those adapters.

``total`` describes observed agent tool dispatches.  TLAPS, TLC, Apalache, and
``other`` partition that total.  Classification is deliberately conservative:
commands that cannot be resolved statically are ``other``.  Evidence fields are
about whether dispatches were completely enumerated, not whether every Bash
construct could be classified or whether the agent run itself succeeded.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

TLAPS = "tlaps"
TLC = "tlc"
APALACHE = "apalache"
OTHER = "other"
CATEGORIES = (TLAPS, TLC, APALACHE, OTHER)
COUNT_KEYS = ("total", *CATEGORIES)

_BASH_LANGUAGE = Language(tree_sitter_bash.language())
_MAX_SHELL_DEPTH = 8
_SHELL_EXECUTABLES = frozenset({"bash", "dash", "ksh", "sh", "zsh"})

# Wrappers whose remaining operand is itself a command.  Their option grammars
# vary, so this intentionally handles only the common literal shapes emitted by
# agents.  Tree-sitter supplies the command boundary; this loop only peels the
# leading wrapper and simple operands.
_WRAPPERS = frozenset({"command", "env", "exec", "nice", "nohup", "stdbuf", "sudo", "time", "timeout", "xargs"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_TIMEOUT_DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
_WRAPPER_OPTIONS_WITH_VALUE = {
    "env": frozenset({"--argv0", "--chdir", "--split-string", "--unset", "-C", "-S", "-u"}),
    "exec": frozenset({"-a"}),
    "nice": frozenset({"--adjustment", "-n"}),
    "stdbuf": frozenset({"--error", "--input", "--output", "-e", "-i", "-o"}),
    "sudo": frozenset(
        {
            "--chdir",
            "--chroot",
            "--close-from",
            "--command-timeout",
            "--group",
            "--host",
            "--other-user",
            "--prompt",
            "--role",
            "--type",
            "--user",
            "-C",
            "-D",
            "-R",
            "-T",
            "-U",
            "-g",
            "-h",
            "-p",
            "-r",
            "-t",
            "-u",
        }
    ),
    "time": frozenset({"--format", "--output", "-f", "-o"}),
    "timeout": frozenset({"--kill-after", "--signal", "-k", "-s"}),
    "xargs": frozenset(
        {
            "--arg-file",
            "--delimiter",
            "--eof",
            "--max-args",
            "--max-chars",
            "--max-lines",
            "--max-procs",
            "--replace",
            "-E",
            "-I",
            "-L",
            "-P",
            "-a",
            "-d",
            "-n",
            "-s",
        }
    ),
}

_TLAPS_EXECUTABLES = frozenset({"tlapm"})
_CHECK_PROOF_EXECUTABLES = frozenset({"check_proof", "check_proof_bin"})


_TLC_EXECUTABLES = frozenset({"tlc", "tlc2"})
_JAVA_MAIN_CLASS = re.compile(r"^[a-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
_JAVA_OPTIONS_WITH_VALUE = frozenset(
    {
        "--class-path",
        "--add-exports",
        "--add-modules",
        "--add-opens",
        "--add-reads",
        "--enable-native-access",
        "--limit-modules",
        "--module-path",
        "--module-source-path",
        "--patch-module",
        "--source",
        "--upgrade-module-path",
        "-classpath",
        "-cp",
        "-p",
    }
)
_JAVA_TERMINAL_OPTIONS = frozenset(
    {
        "--describe-module",
        "--dry-run",
        "--help",
        "--help-extra",
        "--list-modules",
        "--validate-modules",
        "--version",
        "-?",
        "-X",
        "-d",
        "-h",
        "-help",
        "-version",
    }
)


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class ToolCallSummary:
    """Serializable counts plus evidence about dispatch enumeration."""

    total: int = 0
    tlaps: int = 0
    tlc: int = 0
    apalache: int = 0
    other: int = 0
    available: bool = False
    complete: bool = False
    is_lower_bound: bool = False
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        counts = (self.total, self.tlaps, self.tlc, self.apalache, self.other)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("tool-call counts must be non-negative integers")
        if any(type(value) is not bool for value in (self.available, self.complete, self.is_lower_bound)):
            raise ValueError("tool-call evidence fields must be booleans")
        if type(self.warnings) is not tuple or any(
            not isinstance(warning, str) or not warning for warning in self.warnings
        ):
            raise ValueError("tool-call warnings must be non-empty strings")
        if self.total != self.tlaps + self.tlc + self.apalache + self.other:
            raise ValueError("tool-call categories must partition total")
        if self.complete and not self.available:
            raise ValueError("a complete tool-call summary must be available")
        if self.is_lower_bound != (self.available and not self.complete):
            raise ValueError("tool-call evidence status is inconsistent")
        if not self.available and self.total:
            raise ValueError("an unavailable tool-call summary cannot contain observed calls")

    @classmethod
    def from_commands(
        cls,
        commands: Iterable[str | None],
        *,
        available: bool,
        complete: bool,
        warnings: Iterable[str] = (),
    ) -> ToolCallSummary:
        counts = tally(commands)
        return cls(
            **counts,
            available=available,
            complete=complete,
            is_lower_bound=available and not complete,
            warnings=_unique_strings(warnings),
        )

    @classmethod
    def from_dict(cls, value: object) -> ToolCallSummary:
        """Read recorded data for continuation aggregation, failing closed."""

        if not isinstance(value, Mapping):
            return cls(warnings=("tool-call summary is missing or invalid",))
        counts: dict[str, int] = {}
        for key in COUNT_KEYS:
            raw = value.get(key)
            if type(raw) is not int or raw < 0:
                return cls(warnings=("tool-call summary has invalid counts",))
            counts[key] = raw
        raw_warnings = value.get("warnings", [])
        if not isinstance(raw_warnings, list) or any(not isinstance(item, str) or not item for item in raw_warnings):
            return cls(warnings=("tool-call summary has invalid warnings",))
        for key in ("available", "complete", "is_lower_bound"):
            if type(value.get(key)) is not bool:
                return cls(warnings=("tool-call summary has invalid evidence",))
        warnings = _unique_strings(raw_warnings)
        try:
            return cls(
                **counts,
                available=value["available"],
                complete=value["complete"],
                is_lower_bound=value["is_lower_bound"],
                warnings=warnings,
            )
        except ValueError:
            return cls(warnings=("tool-call summary has inconsistent evidence",))

    def merge(self, other: ToolCallSummary) -> ToolCallSummary:
        """Aggregate two formal rounds while preserving evidence gaps."""

        available = self.available or other.available
        complete = self.complete and other.complete
        return ToolCallSummary(
            total=self.total + other.total,
            tlaps=self.tlaps + other.tlaps,
            tlc=self.tlc + other.tlc,
            apalache=self.apalache + other.apalache,
            other=self.other + other.other,
            available=available,
            complete=complete,
            is_lower_bound=available and not complete,
            warnings=_unique_strings((*self.warnings, *other.warnings)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "tlaps": self.tlaps,
            "tlc": self.tlc,
            "apalache": self.apalache,
            "other": self.other,
            "available": self.available,
            "complete": self.complete,
            "is_lower_bound": self.is_lower_bound,
            "warnings": list(self.warnings),
        }


@dataclass
class EventStreamEvidence:
    """Mutable integrity evidence populated while a JSONL stream is consumed."""

    opened: bool = False
    available: bool = False
    valid: bool = True
    event_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, warning: str) -> None:
        self.valid = False
        if warning not in self.warnings:
            self.warnings.append(warning)

    def final_warnings(self) -> tuple[str, ...]:
        warnings = list(self.warnings)
        if not self.opened:
            warnings.append("tool-call event stream is missing or unreadable")
        elif not self.available:
            warnings.append("tool-call event stream has no JSON object events")
        return _unique_strings(warnings)


def iter_events(jsonl_path: str, evidence: EventStreamEvidence | None = None) -> Iterator[dict[str, Any]]:
    """Stream JSON-object events while retaining malformed/read-error evidence."""

    state = evidence if evidence is not None else EventStreamEvidence()
    try:
        with open(jsonl_path, "rb") as handle:
            state.opened = True
            for raw_bytes in handle:
                try:
                    raw = raw_bytes.decode("utf-8").strip()
                except UnicodeError:
                    state.warn("tool-call event stream contains invalid text encoding")
                    continue
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except (ValueError, RecursionError):
                    state.warn("tool-call event stream contains malformed JSON")
                    continue
                if not isinstance(event, dict):
                    state.warn("tool-call event stream contains a non-object event")
                    continue
                state.available = True
                state.event_count += 1
                if not isinstance(event.get("type"), str):
                    state.warn("tool-call event stream contains an event without a string type")
                    continue
                yield event
    except OSError:
        if state.opened:
            state.warn("tool-call event stream ended with a read error")
        else:
            state.valid = False


def _node_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _commands_in_expansions(node: Node) -> Iterator[Node]:
    if node.type in {"command_substitution", "process_substitution"}:
        yield from _command_nodes(node)
        return
    for child in node.named_children:
        yield from _commands_in_expansions(child)


def _command_nodes(node: Node) -> Iterator[Node]:
    """Yield command nodes, evaluating nested substitutions before their host."""

    # Defining a function does not dispatch anything in its body.  Resolving a
    # later function call would require runtime shell state, which this
    # classifier deliberately does not attempt to model.
    if node.type == "function_definition":
        return
    if node.type == "command":
        command_name = node.child_by_field_name("name")
        for child in node.named_children:
            if (
                child.type == "subshell"
                and command_name is not None
                and command_name.start_byte == node.start_byte
                and command_name.text == b"time"
            ):
                yield from _command_nodes(child)
            else:
                yield from _commands_in_expansions(child)
        yield node
        return
    for child in node.named_children:
        yield from _command_nodes(child)


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _wrapper_operands(executable: str, operands: list[str]) -> list[str] | None:
    options_with_value = _WRAPPER_OPTIONS_WITH_VALUE.get(executable, frozenset())
    while operands:
        arg = operands[0]
        if arg == "--":
            operands = operands[1:]
            break
        option = next(
            (
                candidate
                for candidate in options_with_value
                if arg == candidate
                or (candidate.startswith("--") and arg.startswith(candidate + "="))
                or (candidate.startswith("-") and not candidate.startswith("--") and arg.startswith(candidate))
            ),
            None,
        )
        if option is not None:
            if arg == option:
                if len(operands) < 2:
                    return None
                operands = operands[2:]
            else:
                operands = operands[1:]
            continue
        if arg.startswith("-") or (arg.startswith("+") and len(arg) > 1):
            operands = operands[1:]
            continue
        break
    if executable == "timeout":
        if not operands or not _TIMEOUT_DURATION.fullmatch(operands[0]):
            return None
        operands = operands[1:]
    return operands


def _unwrap_wrapper(tokens: list[str]) -> tuple[str, list[str]] | None:
    while tokens and _ASSIGNMENT.match(tokens[0]):
        tokens = tokens[1:]
    while tokens:
        if not tokens:
            return None
        executable = _basename(tokens[0])
        if executable not in _WRAPPERS:
            return executable, tokens[1:]
        operands = tokens[1:]
        if executable == "command" and any(
            arg.startswith("-") and not arg.startswith("--") and any(flag in arg[1:] for flag in "Vv")
            for arg in operands
        ):
            return None
        operands = _wrapper_operands(executable, operands)
        if operands is None:
            return None
        if executable == "env":
            while operands and _ASSIGNMENT.match(operands[0]):
                operands = operands[1:]
        elif operands and _ASSIGNMENT.match(operands[0]):
            return None
        if not operands:
            return None
        tokens = operands
    return None


def _shell_script(args: list[str]) -> str | None:
    options_with_value = {"--init-file", "--rcfile", "+O", "+o", "-O", "-o"}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return None
        if arg in options_with_value:
            index += 2
            continue
        if arg.startswith("--") or (arg.startswith("+") and len(arg) > 1):
            index += 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            if "c" in arg[1:]:
                script_index = index + 1
                if script_index < len(args) and args[script_index] == "--":
                    script_index += 1
                return args[script_index] if script_index < len(args) else None
            index += 1
            continue
        # The first non-option is a script filename.  Later ``-c`` text is an
        # argument to that script, not an option interpreted by this shell.
        return None
    return None


def _invocations(command: str, *, depth: int = 0) -> Iterator[tuple[str, list[str]]]:
    """Yield explicit executable invocations from a Bash program."""

    if depth >= _MAX_SHELL_DEPTH:
        return
    source = command.encode("utf-8", errors="replace")
    tree = Parser(_BASH_LANGUAGE).parse(source)
    for node in _command_nodes(tree.root_node):
        try:
            tokens = shlex.split(_node_text(source, node))
        except ValueError:
            continue
        invocation = _unwrap_wrapper(tokens)
        if invocation is None:
            continue
        executable, args = invocation
        if executable in _SHELL_EXECUTABLES:
            script = _shell_script(args)
            if script is not None:
                yield from _invocations(script, depth=depth + 1)
            continue
        yield executable, args


def _java_launch_target(args: list[str]) -> tuple[str, str] | None:
    """Return Java's first launch target, before application arguments begin."""

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in _JAVA_TERMINAL_OPTIONS or any(
            option.startswith("--") and arg.startswith(option + "=") for option in _JAVA_TERMINAL_OPTIONS
        ):
            return None
        if arg in _JAVA_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if arg == "-jar":
            return ("jar", args[index + 1]) if index + 1 < len(args) else None
        if arg in {"-m", "--module"}:
            return ("module", args[index + 1]) if index + 1 < len(args) else None
        if arg.startswith("--module="):
            return ("module", arg.partition("=")[2])
        if arg.startswith("-"):
            index += 1
            continue
        return ("class", arg)
    return None


def _java_category(args: list[str]) -> str | None:
    """Resolve the launched main class or ``-jar`` target, without guessing."""

    target = _java_launch_target(args)
    if target is None:
        return None
    target_type, value = target
    if target_type == "module":
        return None
    if target_type == "jar":
        lowered = _basename(value).lower()
        if "apalache" in lowered:
            return APALACHE
        if lowered == "tla2tools.jar":
            return TLC
        return None
    if not _JAVA_MAIN_CLASS.fullmatch(value):
        return None
    lowered = value.lower()
    if "apalache" in lowered:
        return APALACHE
    if "sany" in lowered or lowered.startswith("pcal."):
        return None
    return TLC if lowered.startswith("tlc2.") else None


def _category(executable: str, args: list[str]) -> str | None:
    if executable in _TLAPS_EXECUTABLES:
        return TLAPS
    if executable in _CHECK_PROOF_EXECUTABLES:
        return None if "--sany-only" in args else TLAPS
    if executable.startswith("apalache"):
        return APALACHE
    if executable in _TLC_EXECUTABLES:
        return TLC
    if executable == "java":
        return _java_category(args)
    return None


def blocking_proof_check_command(name: object, arguments: object, namespace: object = None) -> str | None:
    """Classify the known MCP checker just like its underlying CLI command."""
    if not (
        name in ("mcp__tlaps_check__check_proof", "mcp__tlaps_check.check_proof")
        or (namespace == "mcp__tlaps_check" and name == "check_proof")
    ):
        return None
    if not isinstance(arguments, dict) or not isinstance(arguments.get("file"), str):
        return None
    if type(arguments.get("sany_only", False)) is not bool:
        return None
    command = ["check_proof_bin", arguments["file"], "--mode", "proof-from-scratch"]
    if arguments.get("sany_only"):
        command.append("--sany-only")
    return shlex.join(command)


def classify_command(command: str | None) -> str:
    """Classify one agent shell-tool dispatch by its first explicit checker."""

    if not command:
        return OTHER
    try:
        for executable, args in _invocations(command):
            category = _category(executable, args)
            if category is not None:
                return category
    except RecursionError:
        # Deeply generated shell syntax must not make result recording fail.
        # It is classification-ambiguous, so preserve the dispatch as other.
        return OTHER
    return OTHER


def tally(commands: Iterable[str | None]) -> dict[str, int]:
    """Return numeric counts for one entry per observed agent tool dispatch."""

    counts = dict.fromkeys(CATEGORIES, 0)
    total = 0
    for command in commands:
        counts[classify_command(command)] += 1
        total += 1
    return {"total": total, **counts}


def summarize(
    commands: Iterable[str | None],
    evidence: EventStreamEvidence,
    *,
    lifecycle_complete: bool,
    warnings: Iterable[str] = (),
) -> ToolCallSummary:
    """Build one summary from observed calls and backend lifecycle evidence."""

    all_warnings = (*evidence.final_warnings(), *warnings)
    complete = evidence.available and evidence.valid and lifecycle_complete
    return ToolCallSummary.from_commands(
        commands,
        available=evidence.available,
        complete=complete,
        warnings=all_warnings,
    )

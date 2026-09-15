import sys

# (subcommand, one-line help) — order is the order shown in --help.
SUBCOMMANDS = [
    ("run", "Run an evaluator backend on the benchmarks"),
    ("check", "Check a single benchmark proof for correctness and cheating"),
    ("validate", "Batch-validate source proofs with tlapm"),
    ("generate", "Generate benchmarks (--mode proof-completion|proof-from-scratch; default proof-completion)"),
    ("score", "Score results (pass rate, per-module breakdown) from results.json"),
]

PROG = "tlaps-bench"


def _top_help() -> str:
    width = max(len(name) for name, _ in SUBCOMMANDS)
    lines = [
        f"usage: {PROG} <command> [args...]",
        "",
        "A benchmark for evaluating AI's ability to write TLAPS proofs.",
        "",
        "commands:",
    ]
    lines += [f"  {name.ljust(width)}  {desc}" for name, desc in SUBCOMMANDS]
    lines += [
        "",
        f"Run '{PROG} <command> --help' for a command's full flag set.",
    ]
    return "\n".join(lines)


def _dispatch(
    prog: str,
    module_name: str,
    attr: str,
    passthrough: list[str],
    *,
    entry_kwargs: dict[str, object] | None = None,
) -> int:
    """Import ``module_name`` lazily, set argv, and call its entry function.

    Lazy import keeps one tool's import errors from breaking the others, and
    avoids paying for a tool's dependencies when running a different subcommand.
    """
    import importlib

    module = importlib.import_module(module_name)
    entry = getattr(module, attr)
    saved_argv = sys.argv
    sys.argv = [prog, *passthrough]
    try:
        rc = entry(**(entry_kwargs or {}))
    finally:
        sys.argv = saved_argv
    return rc if isinstance(rc, int) else 0


def _extract_mode(args: list[str]) -> tuple[str, list[str]]:

    mode = "proof-completion"
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--mode":
            if i + 1 >= len(args):
                raise SystemExit(f"{PROG} generate: argument --mode: expected one argument")
            mode = args[i + 1]
            i += 2
            continue
        if a.startswith("--mode="):
            mode = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    valid = {"proof-completion", "proof-from-scratch"}
    if mode not in valid:
        raise SystemExit(
            f"{PROG} generate: argument --mode: invalid choice: {mode!r} "
            "(choose proof-completion or proof-from-scratch)"
        )
    return mode, rest


_PROOF_FROM_SCRATCH_GENERATE_DIR_ALIASES = {
    "--output-dir": "--output-root",
    "--source-dir": "--source-root",
}


def _proof_from_scratch_generate_args(args: list[str]) -> list[str]:
    """Map the shared generate directory flags onto the module-task CLI.

    ``tlaps-bench generate`` documents ``--output-dir`` / ``--source-dir``.
    Module-task generation uses ``--output-root`` / ``--source-root`` so it
    cannot be aimed at the frozen 244-task corpus by accident.
    """

    rewritten: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in _PROOF_FROM_SCRATCH_GENERATE_DIR_ALIASES:
            rewritten.append(_PROOF_FROM_SCRATCH_GENERATE_DIR_ALIASES[token])
            index += 1
            continue
        mapped = False
        for old, new in _PROOF_FROM_SCRATCH_GENERATE_DIR_ALIASES.items():
            prefix = f"{old}="
            if token.startswith(prefix):
                rewritten.append(f"{new}={token[len(prefix) :]}")
                mapped = True
                break
        if not mapped:
            rewritten.append(token)
        index += 1
    return rewritten


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    if not argv or argv[0] in ("-h", "--help"):
        print(_top_help())
        return 0

    sub = argv[0]
    rest = argv[1:]
    names = {name for name, _ in SUBCOMMANDS}
    if sub not in names:
        sys.stderr.write(f"{PROG}: unknown command {sub!r}\n\n{_top_help()}\n")
        return 2

    if sub == "run":
        return _dispatch(f"{PROG} run", "evaluator.runner", "main", rest)
    if sub == "check":
        return _dispatch(
            f"{PROG} check",
            "common.check_proof",
            "main",
            rest,
            entry_kwargs={"require_canonical_for_proof_from_scratch": True},
        )
    if sub == "validate":
        return _dispatch(f"{PROG} validate", "common.validate", "main", rest)
    if sub == "generate":
        # --help before --mode: show which modes exist plus the proof-completion flags
        # (the default) — the mode-specific flags then come from that module.
        mode, gen_args = _extract_mode(rest)
        if mode == "proof-completion":
            return _dispatch(
                f"{PROG} generate --mode {mode}",
                "dataset.proof_completion.generate",
                "main",
                gen_args,
            )
        return _dispatch(
            f"{PROG} generate --mode {mode}",
            "dataset.proof_from_scratch.module_tasks",
            "main",
            _proof_from_scratch_generate_args(gen_args),
        )
    if sub == "score":
        return _dispatch(f"{PROG} score", "evaluator.score", "main", rest)

    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())

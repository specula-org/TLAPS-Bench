#!/usr/bin/env python3
"""Generate the dataset breakdown tables from the benchmark tree.

Counts are derived purely from the files under benchmark/, so the tables never
drift from the actual dataset. Emits, to stdout:

  1. the two summary tables (example libraries / systems specifications) for the
     README, and
  2. the full per-example table for docs/DATASET.md.

The unit of a row is a benchmark *group* (one directory under benchmark/<mode>/,
i.e. one coherent example or protocol), not an individual proof module — so a
protocol whose proof spans several modules stays a single row.

Run:  python3 scripts/dataset_table.py
"""

import collections
import glob
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ("proof-completion", "proof-from-scratch")

_GOAL = re.compile(r"^[ \t]*(THEOREM|LEMMA|COROLLARY|PROPOSITION)\b", re.MULTILINE)


def is_task(path):
    """A benchmark task file: name has a theorem suffix and states a goal."""
    name = os.path.splitext(os.path.basename(path))[0]
    if "_" not in name:
        return False
    with open(path, encoding="utf-8", errors="ignore") as f:
        return _GOAL.search(f.read()) is not None


def source_label(group):
    if group.startswith("tlaplus_examples_"):
        return "tlaplus/Examples"
    if group.startswith("ivy_examples_"):
        return "Ivy liveness"
    if group.startswith("apalache_examples_"):
        return "apalache-examples (Konnov)"
    if group.startswith("ZooKeeper"):
        return "ZooKeeper (Remix)"
    if group == "etcd_raft":
        return "etcd (Specula)"
    if group == "OpenAddressing":
        return "OpenAddressing"
    if group == "two_thread_mutex":
        return "two_thread_mutex (Anvil)"
    if group == "MongoDB":
        return "MongoDB distributed transactions"
    return "TLAPS distribution examples"


# Upstream provenance per source (see NOTICE for full attribution).
SOURCE_URL = {
    "tlaplus/Examples": "https://github.com/tlaplus/Examples",
    "TLAPS distribution examples": "https://github.com/tlaplus/tlapm",
    "ZooKeeper (Remix)": "https://arxiv.org/abs/2409.14301",
    "Ivy liveness": "https://github.com/kenmcmil/ivy",
    "apalache-examples (Konnov)": "https://github.com/konnov/apalache-examples",
    "etcd (Specula)": "https://github.com/specula-org",
    "OpenAddressing": "https://github.com/lemmy/Examples",
    "two_thread_mutex (Anvil)": "https://github.com/anvil-verifier/anvil/blob/main/src/tla_demo.rs",
    "MongoDB distributed transactions": "https://github.com/mongodb-labs/vldb25-dist-txns",
}


def linked(label):
    url = SOURCE_URL.get(label)
    return f"[{label}]({url})" if url else label


# Per-example upstream location, verified against the authoritative upstream
# directory listings (gh api on tlaplus/Examples, tlaplus/tlapm, etc.). Groups
# absent here fall back to their corpus repo (see group_url); the residual —
# upstream location unknown or nonexistent — is listed in docs/DATASET.md.
_EX = "https://github.com/tlaplus/Examples/tree/master/specifications"
_TLAPM = "https://github.com/tlaplus/tlapm"
_APALACHE = "https://github.com/konnov/apalache-examples/tree/af360379b7cbcd1e16c1a801ff8ac64eb9aca038"
# TLAPS-distribution groups that are a single file / directory in the current
# tlapm tree. Multi-module groups whose exact public location differs are listed
# explicitly in _GROUP_URL below.
_TLAPM_FILE = {"Allocator", "Bakery", "BubbleSort", "EWD840", "Peterson", "SimpleMutex", "SumAndMax"}
_TLAPM_DIR = {"Cantor": "examples/cantor"}
_GROUP_URL = {
    "Consensus": "https://github.com/tlaplus/tlapm/tree/main/examples_draft/consensus",
    "Data": "https://github.com/tlaplus/tlapm/tree/main/zenon/regression/examples/data",
    # The current tlapm tree no longer keeps every module in these groups
    # together; these public directories are byte-identical to the bundled
    # multi-module sources.
    "Paxos": "https://github.com/hengxin/tlaps-examples/tree/master/Paxos",
    "Euclid": "https://github.com/hengxin/tlaps-examples/tree/master/Euclid",
    "AtomicBakery": "https://github.com/hengxin/tlaps-examples/tree/master/AtomicBakery",
    "Record": "https://github.com/hengxin/tlaps-examples/tree/master/Record",
    "etcd_raft": "https://github.com/specula-org/Specula/blob/main/skills/spec_generation/examples/etcdraft.tla",
    "OpenAddressing": "https://github.com/lemmy/Examples/tree/mku-OA/specifications/TLC",
    "ZooKeeper": "https://github.com/Disalg-ICS-NJU/zookeeper-tla-spec/blob/main/high-level-spec/Zab.tla",
    "ZooKeeper_LowLevel": "https://github.com/Disalg-ICS-NJU/zookeeper-tla-spec/tree/main/low-level-spec/zk-3.7",
    "tlaplus_examples_BlockingQueue": "https://github.com/lemmy/BlockingQueue",
    "tlaplus_examples_GermanProtocol": (
        "https://github.com/tlaplus/Examples/tree/"
        "91c22ea537853196ed1e03e9ad91693ec37642de/"
        "specifications/GermanProtocol"
    ),
    "tlaplus_examples_ewd687a": (
        "https://github.com/tlaplus/Examples/tree/91c22ea537853196ed1e03e9ad91693ec37642de/specifications/ewd687a"
    ),
    "two_thread_mutex": "https://github.com/anvil-verifier/anvil/blob/main/src/tla_demo.rs",
    "MongoDB": (
        "https://github.com/mongodb-labs/vldb25-dist-txns/blob/"
        "74526c1201109405172eb845413154f547a815ee/MultiShardTxn.tla"
    ),
}


def group_url(group):
    """Specific upstream location for one example, or None if unknown."""
    if group in _GROUP_URL:
        return _GROUP_URL[group]
    if group.startswith("ivy_examples_"):
        name = group[len("ivy_examples_") :]
        return f"https://github.com/kenmcmil/ivy/blob/master/examples/liveness/{name}.ivy"
    if group.startswith("apalache_examples_"):
        return f"{_APALACHE}/{group[len('apalache_examples_') :]}"
    if group.startswith("tlaplus_examples_"):
        x = group[len("tlaplus_examples_") :]
        if x.startswith("SpecifyingSystems_"):
            chapter = x[len("SpecifyingSystems_") :]
            return f"{_EX}/SpecifyingSystems/{chapter}"
        return f"{_EX}/{x}"
    if group in _TLAPM_FILE:
        return f"{_TLAPM}/blob/main/examples/{group}.tla"
    if group in _TLAPM_DIR:
        return f"{_TLAPM}/tree/main/{_TLAPM_DIR[group]}"
    return None


def display_name(group):
    """Strip the corpus prefix for a readable example name."""
    for pre in ("tlaplus_examples_", "ivy_examples_", "apalache_examples_"):
        if group.startswith(pre):
            return group[len(pre) :]
    return group


# Sources grouped into two tiers; order within each tier is by total desc.
LIBRARIES = {"tlaplus/Examples", "TLAPS distribution examples"}


def mode_tasks(mode):
    """Suite-root-relative task keys for one mode.

    A layered suite names its tasks in `manifest.json`; its read-only model and
    scaffold layers are context, not tasks, and a scaffold states admitted
    lemmas that the filename heuristic would miscount. Suites without a manifest
    keep the heuristic.
    """
    root = os.path.join(REPO, "benchmark", mode)
    manifest = os.path.join(root, "manifest.json")
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            return sorted(json.load(f))
    files = sorted(glob.glob(os.path.join(root, "**", "*.tla"), recursive=True))
    return [os.path.relpath(f, root) for f in files if is_task(f)]


def collect():
    # (source_label, group) -> [pc, pfs]
    counts = collections.defaultdict(lambda: [0, 0])
    for i, mode in enumerate(MODES):
        for key in mode_tasks(mode):
            group = key.replace(os.sep, "/").split("/")[0]
            counts[(source_label(group), group)][i] += 1
    return counts


def num(n):
    return str(n) if n else "–"


def main():
    counts = collect()

    # aggregate per source
    src = collections.defaultdict(lambda: [0, 0, 0])  # examples, pc, pfs
    for (label, _group), (pc, pfs) in counts.items():
        a = src[label]
        a[0] += 1
        a[1] += pc
        a[2] += pfs

    def tier(labels):
        rows = [(label, *src[label]) for label in labels]
        rows.sort(key=lambda r: -(r[2] + r[3]))
        return rows

    libs = tier([label for label in src if label in LIBRARIES])
    systems = tier([label for label in src if label not in LIBRARIES])

    def render(rows, subtotal_name):
        out = ["| Source | Examples | Proof completion | Proof from scratch | Total |", "|---|--:|--:|--:|--:|"]
        ts = tpc = tpf = 0
        for label, examples, pc, pfs in rows:
            out.append(f"| {linked(label)} | {examples} | {num(pc)} | {num(pfs)} | {pc + pfs} |")
            ts += examples
            tpc += pc
            tpf += pfs
        out.append(f"| **{subtotal_name}** | **{ts}** | **{num(tpc)}** | **{num(tpf)}** | **{tpc + tpf}** |")
        return "\n".join(out), (ts, tpc, tpf)

    lib_md, lib_tot = render(libs, "Subtotal")
    sys_md, sys_tot = render(systems, "Subtotal")

    print("### Example libraries\n")
    print(lib_md)
    print("\n### Systems specifications\n")
    print(sys_md)
    print(f"\n**{lib_tot[0] + sys_tot[0]} examples, {sum(lib_tot[1:]) + sum(sys_tot[1:])} tasks.**")

    # full per-example table
    print("\n\n---- docs/DATASET.md body ----\n")
    print("| Example | Source | Proof completion | Proof from scratch | Total |")
    print("|---|---|--:|--:|--:|")
    for (label, group), (pc, pfs) in sorted(
        counts.items(), key=lambda kv: (kv[0][0], -(kv[1][0] + kv[1][1]), kv[0][1])
    ):
        name = display_name(group)
        url = group_url(group)
        cell = f"[{name}]({url})" if url else name
        print(f"| {cell} | {label} | {num(pc)} | {num(pfs)} | {pc + pfs} |")


if __name__ == "__main__":
    main()

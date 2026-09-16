"""Run one recorded TLC check without changing the specification or its inputs."""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("module")
parser.add_argument("config")
parser.add_argument("tag")
parser.add_argument("--seconds", type=int, default=120)
parser.add_argument("--simulate", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
output = root / "spec/output"
states = output / (args.tag + "-states")
output.mkdir(exist_ok=True)
(root / "tmp").mkdir(exist_ok=True)
states.mkdir(exist_ok=False)
repo_lib = root.parents[1] / "lib"
lib_dir = Path(os.environ.get("STORAGE_LIB_DIR", repo_lib))
community = os.environ.get("STORAGE_COMMUNITY", str(lib_dir / "community"))
stdlib = os.environ.get("STORAGE_TLAPM_STDLIB", str(Path.home() / ".tlapm/lib/tlapm/stdlib"))
jar = os.environ.get("STORAGE_TLA2TOOLS_JAR", str(lib_dir / "tla2tools.jar"))
timeout = os.environ.get("STORAGE_TIMEOUT") or shutil.which("timeout") or shutil.which("gtimeout")
if not timeout or not Path(jar).is_file():
    parser.error("GNU timeout and tla2tools.jar are required; see README.md")
command = [
    timeout,
    str(args.seconds) + "s",
    "java",
    "-XX:-UsePerfData",
    "-Xmx1g",
    "-Djava.io.tmpdir=" + str(root / "tmp"),
    "-DTLA-Library=" + os.pathsep.join([community, stdlib, str(root / "reference")]),
    "-cp",
    jar,
    "tlc2.TLC",
    "-workers",
    "1",
    "-metadir",
    str(states),
    "-config",
    args.config,
    "-dumpTrace",
    "json",
    str(output / (args.tag + "-trace")),
]
if args.simulate:
    command += ["-simulate", "num=999999999", "-depth", "60", "-seed", "20260916"]
command.append(args.module)
started = time.monotonic()
with (output / (args.tag + ".log")).open("wb") as log:
    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
receipt = {
    "tag": args.tag,
    "command": command,
    "exit_code": result.returncode,
    "elapsed_seconds": round(time.monotonic() - started, 3),
    "finished_at": datetime.datetime.now(datetime.UTC).isoformat(),
}
(output / (args.tag + ".json")).write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({k: v for k, v in receipt.items() if k != "command"}))
for line in (output / (args.tag + ".log")).read_text().splitlines():
    if any(
        value in line
        for value in (
            "Error:",
            "states generated",
            "distinct state",
            "Model checking completed",
            "Finished in",
            "Semantic errors",
            "Progress(",
            "traces generated",
        )
    ):
        print(line)
raise SystemExit(result.returncode)

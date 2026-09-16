#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=env.sh
source spec/env.sh
tag="$1"
config="${2:-spec/HistoryEpoch.cfg}"
mkdir -p "spec/output/$tag-states"
cmd=("${STORAGE_TIMEOUT}" 90s java -XX:-UsePerfData -Xmx2g -Djava.io.tmpdir="$PWD/tmp" "-DTLA-Library=${STORAGE_COMMUNITY}" -cp "${STORAGE_TLA2TOOLS_JAR}" tlc2.TLC -workers 2 -metadir "spec/output/$tag-states" -config "$config" -dumpTrace json "spec/output/$tag-trace" StorageHistory)
# The reference module is found via TLA-Library as an additional search directory.
cmd[6]="-DTLA-Library=${STORAGE_COMMUNITY}:$PWD/reference"
printf '%q ' "${cmd[@]}" > "spec/output/$tag.command"
printf '\n' >> "spec/output/$tag.command"
"${cmd[@]}" > "spec/output/$tag.log" 2>&1
result=$?
printf '%s\n' "$result" > "spec/output/$tag.exit"
tail -n 35 "spec/output/$tag.log"
exit "$result"

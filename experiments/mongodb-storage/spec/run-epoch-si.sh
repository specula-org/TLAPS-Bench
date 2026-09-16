#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=env.sh
source spec/env.sh
tag="$1"
mkdir -p "spec/output/$tag-states"
cmd=("${STORAGE_TIMEOUT}" 30s java -XX:-UsePerfData -Xmx1g -Djava.io.tmpdir="$PWD/tmp" "-DTLA-Library=${STORAGE_COMMUNITY}:$PWD/reference" -cp "${STORAGE_TLA2TOOLS_JAR}" tlc2.TLC -workers 1 -metadir "spec/output/$tag-states" -config spec/EpochSI.cfg -dumpTrace json "spec/output/$tag-trace" StorageEpochSI)
printf '%q ' "${cmd[@]}" > "spec/output/$tag.command"
printf '\n' >> "spec/output/$tag.command"
"${cmd[@]}" > "spec/output/$tag.log" 2>&1
result=$?
printf '%s\n' "$result" > "spec/output/$tag.exit"
tail -n 55 "spec/output/$tag.log"
exit "$result"

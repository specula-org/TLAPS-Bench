#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=env.sh
source spec/env.sh
config="$1"
tag="$2"
mkdir -p "spec/output/$tag-states"
cmd=("${STORAGE_TIMEOUT}" 80s java -XX:-UsePerfData -Xmx2g -Djava.io.tmpdir="$PWD/tmp" "-DTLA-Library=${STORAGE_COMMUNITY}" -cp "${STORAGE_TLA2TOOLS_JAR}" tlc2.TLC -workers 2 -metadir "spec/output/$tag-states" -config "$config" -dumpTrace json "spec/output/$tag-trace" StorageCandidates)
printf '%q ' "${cmd[@]}" > "spec/output/$tag.command"
printf '\n' >> "spec/output/$tag.command"
"${cmd[@]}" > "spec/output/$tag.log" 2>&1
result=$?
printf '%s\n' "$result" > "spec/output/$tag.exit"
tail -n 40 "spec/output/$tag.log"
exit "$result"

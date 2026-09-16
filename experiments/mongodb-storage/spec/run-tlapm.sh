#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=env.sh
source spec/env.sh
module="$1"
tag="$2"
mkdir -p "spec/cache/$tag" spec/output
cmd=("${STORAGE_TIMEOUT}" 100s env JAVA_TOOL_OPTIONS=-XX:-UsePerfData "${STORAGE_TLAPM}" --verbose --strict --nofp --threads 1 --cache-dir "spec/cache/$tag" -I "${STORAGE_COMMUNITY}" -I "${STORAGE_TLAPM_LIBRARY}" -I . -I reference "$module")
printf '%q ' "${cmd[@]}" > "spec/output/$tag.command"
printf '\n' >> "spec/output/$tag.command"
"${cmd[@]}" > "spec/output/$tag.log" 2>&1
result=$?
printf '%s\n' "$result" > "spec/output/$tag.exit"
tail -n 65 "spec/output/$tag.log"
exit "$result"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=env.sh
source spec/env.sh
module="$1"
tag="$2"
mkdir -p spec/output tmp
cmd=("${STORAGE_TIMEOUT}" 30s java -XX:-UsePerfData -Xmx512m -Djava.io.tmpdir="$PWD/tmp" "-DTLA-Library=${STORAGE_COMMUNITY}:${STORAGE_TLAPM_STDLIB}:$PWD/reference" -cp "${STORAGE_TLA2TOOLS_JAR}" tla2sany.SANY "$module")
printf '%q ' "${cmd[@]}" > "spec/output/$tag-sany.command"
printf '\n' >> "spec/output/$tag-sany.command"
set +e
"${cmd[@]}" > "spec/output/$tag-sany.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "spec/output/$tag-sany.exit"
if [[ "$rc" -ne 0 ]] || rg -q 'Semantic errors:|\*\*\* Errors:|Parse Error|Fatal errors:|Cannot find source file' "spec/output/$tag-sany.log"; then
  cat "spec/output/$tag-sany.log"
  exit 1
fi

#!/usr/bin/env bash
# Shared tool locations for the standalone experiment's replay scripts.
storage_spec_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
storage_repo_dir="$(cd "$storage_spec_dir/../../.." && pwd)"
export STORAGE_LIB_DIR="${STORAGE_LIB_DIR:-$storage_repo_dir/lib}"
export STORAGE_COMMUNITY="${STORAGE_COMMUNITY:-$STORAGE_LIB_DIR/community}"
export STORAGE_TLAPM_LIBRARY="${STORAGE_TLAPM_LIBRARY:-$STORAGE_LIB_DIR/tlapm}"
export STORAGE_TLAPM="${STORAGE_TLAPM:-$HOME/.tlapm/bin/tlapm}"
export STORAGE_TLAPM_STDLIB="${STORAGE_TLAPM_STDLIB:-$HOME/.tlapm/lib/tlapm/stdlib}"
export STORAGE_TLA2TOOLS_JAR="${STORAGE_TLA2TOOLS_JAR:-$STORAGE_LIB_DIR/tla2tools.jar}"
export STORAGE_TIMEOUT="${STORAGE_TIMEOUT:-$(command -v timeout || command -v gtimeout || true)}"

if [[ -z "$STORAGE_TIMEOUT" || ! -f "$STORAGE_TLA2TOOLS_JAR" || ! -x "$STORAGE_TLAPM" ]]; then
  printf '%s\n' 'Missing GNU timeout, tla2tools.jar, or TLAPM; see README.md.' >&2
  exit 1
fi
mkdir -p tmp spec/output

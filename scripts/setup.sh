#!/usr/bin/env bash
# Prepare a native checkout (Linux x86-64 or macOS arm64) for benchmark
# development and runs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() {
  echo "[setup] $*"
}

die() {
  echo "[setup] ERROR: $*" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  local install_hint="$2"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    die "${command_name} is required. ${install_hint} Then rerun: make setup"
  fi
}

version_major() {
  local version="$1"
  version="${version%%[-+]*}"
  if [[ "${version}" == 1.* ]]; then
    version="${version#1.}"
  fi
  echo "${version%%.*}"
}

check_java() {
  local java_line java_version java_major
  java_line="$(java -version 2>&1 | sed -n '1p')"
  java_version="$(sed -nE 's/.*version "([^"]+)".*/\1/p' <<<"${java_line}")"
  [[ -n "${java_version}" ]] || die "could not determine the Java version from: ${java_line}"
  java_major="$(version_major "${java_version}")"
  [[ "${java_major}" =~ ^[0-9]+$ ]] || die "could not parse the Java version from: ${java_line}"
  (( java_major >= 21 )) || die "Java 21 or newer is required; found ${java_version}. Install a JDK 21+ package, then rerun: make setup"

  local javac_line javac_version javac_major
  javac_line="$(javac -version 2>&1 | sed -n '1p')"
  javac_version="${javac_line#javac }"
  javac_major="$(version_major "${javac_version}")"
  [[ "${javac_major}" =~ ^[0-9]+$ ]] || die "could not parse the javac version from: ${javac_line}"
  (( javac_major >= 21 )) || die "javac 21 or newer is required; found ${javac_version}. Install a JDK 21+ package, then rerun: make setup"

  log "Java ${java_version} and javac ${javac_version}"
}

main() {
  cd "${REPO_ROOT}"

  local host_os host_arch is_macos=0
  host_os="$(uname -s)"
  host_arch="$(uname -m)"
  if [[ "${host_os}" == "Linux" && "${host_arch}" == "x86_64" ]]; then
    : # Linux x86-64: the original, unchanged path.
  elif [[ "${host_os}" == "Darwin" && "${host_arch}" == "arm64" ]]; then
    is_macos=1
  elif [[ "${host_os}" == "Darwin" ]]; then
    die "native setup supports macOS on Apple Silicon (arm64) only; detected ${host_os} ${host_arch}. Upstream tlapm publishes no Intel (x86_64) macOS binary, so Intel Macs are unsupported."
  else
    die "native setup supports Linux x86-64 and macOS arm64 only; detected ${host_os} ${host_arch}."
  fi

  local make_hint curl_hint tar_hint uv_hint jdk_hint
  if (( is_macos )); then
    make_hint="Install Xcode Command Line Tools: xcode-select --install."
    curl_hint="curl ships with macOS; reinstall the Command Line Tools (xcode-select --install) if missing."
    tar_hint="tar ships with macOS; reinstall the Command Line Tools (xcode-select --install) if missing."
    uv_hint="Install uv with: brew install uv (or: curl -LsSf https://astral.sh/uv/install.sh | sh)."
    jdk_hint="Install a JDK 21+ on PATH (java and javac). Homebrew's openjdk is keg-only, so register it after installing, e.g.: brew install openjdk@21 && ln -sfn \$(brew --prefix)/opt/openjdk@21/libexec/openjdk.jdk ~/Library/Java/JavaVirtualMachines/openjdk-21.jdk."
  else
    make_hint="Install GNU Make (Ubuntu/Debian: sudo apt-get install make)."
    curl_hint="Install curl (Ubuntu/Debian: sudo apt-get install curl)."
    tar_hint="Install tar (Ubuntu/Debian: sudo apt-get install tar)."
    uv_hint="Install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh."
    jdk_hint="Install a JDK 21+ package (Ubuntu/Debian: sudo apt-get install openjdk-21-jdk)."
  fi

  require_command make "${make_hint}"
  require_command curl "${curl_hint}"
  require_command tar "${tar_hint}"
  require_command uv "${uv_hint}"
  require_command java "${jdk_hint}"
  require_command javac "A JRE is not sufficient; ${jdk_hint}"
  check_java

  log "syncing the locked Python environment..."
  uv sync --locked

  log "installing pinned TLAPS dependencies..."
  bash "${REPO_ROOT}/scripts/install_deps.sh"

  local sany_source sany_class tla2tools
  sany_source="${REPO_ROOT}/src/dataset/sany-dump/DumpSemantics.java"
  sany_class="${REPO_ROOT}/src/dataset/sany-dump/build/DumpSemantics.class"
  tla2tools="${REPO_ROOT}/lib/tla2tools.jar"
  if [[ ! -f "${sany_class}" || "${sany_source}" -nt "${sany_class}" || "${tla2tools}" -nt "${sany_class}" ]]; then
    log "compiling the SANY semantic dumper..."
    bash "${REPO_ROOT}/src/dataset/sany-dump/build.sh"
  else
    log "SANY semantic dumper is up to date — skipping compilation"
  fi

  if env -u MAKEFLAGS make --no-print-directory --question build; then
    log "check_proof_bin is up to date — skipping build"
  else
    log "building check_proof_bin (the first build can take about a minute)..."
    env -u MAKEFLAGS make --no-print-directory build
  fi

  log "running the SANY smoke test..."
  local smoke_output
  if ! smoke_output="$(
    SANY_RUN_SH="${REPO_ROOT}/src/dataset/sany-dump/run.sh" \
      TLAPS_LIB="${REPO_ROOT}/lib/tlapm" \
      COMMUNITY_LIB="${REPO_ROOT}/lib/community" \
      "${REPO_ROOT}/check_proof_bin" \
      "${REPO_ROOT}/benchmark/proof-completion/Euclid/GCD_GCD3.tla" --no-container --sany-only \
      --benchmark-dir "${REPO_ROOT}/benchmark/proof-completion/Euclid" 2>&1
  )"; then
    echo "${smoke_output}" >&2
    die "the SANY smoke test failed."
  fi
  if [[ "${smoke_output}" != *"SANY OK"* ]]; then
    echo "${smoke_output}" >&2
    die "the SANY smoke test could not run successfully."
  fi

  log "setup complete. Preview the Current problem set with:"
  echo "  uv run tlaps-bench run --dry-run"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi

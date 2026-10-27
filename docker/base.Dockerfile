# syntax=docker/dockerfile:1

# Stage 1: Compile check_proof_bin from source (no source leaks to final image)
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends binutils && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pyinstaller

COPY pyproject.toml /build/pyproject.toml
COPY src/ /build/src/

# Version stamp for the `checker:` header (passed by ensure_image from `git
# describe`; also overwrites any stale locally-generated _build_version.py).
ARG CHECKER_VERSION=dev
RUN printf 'BUILD_VERSION = "%s"\n' "$CHECKER_VERSION" > /build/src/common/_build_version.py

RUN cd /build && pyinstaller --onefile --name check_proof_bin \
        --paths src/common --paths src \
        --collect-submodules tlacheck \
        --collect-submodules tlacore \
        src/common/check_proof.py \
    && mv dist/check_proof_bin /check_proof_bin

# Stage 2: Final image (agent runtime)
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# Layer 1: System packages (rarely changes)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git python3 python3-pip \
    libstdc++6 libgmp10 make \
    default-jdk-headless \
    iptables iproute2 dnsutils libcap2-bin \
    dnsmasq-base ipset \
    && groupadd --system tlaps-dnsmasq \
    && useradd --system --gid tlaps-dnsmasq --home-dir /nonexistent \
        --no-create-home --shell /usr/sbin/nologin tlaps-dnsmasq

# Layer 2: Node.js (rarely changes)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs

# Layer 3: content-locked verification tools (~850MB TLAPM download).
COPY config/verification-toolchain.json /opt/tlaps-bench/config/verification-toolchain.json
COPY src/common/__init__.py src/common/verification_toolchain.py /opt/tlaps-bench/src/common/
RUN --mount=type=cache,target=/tmp/downloads \
    TLAPM_PLATFORM=linux-x86_64 \
    && TLAPM_TAG="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value tlapm tag \
         --platform ${TLAPM_PLATFORM})" \
    && TLAPM_ASSET="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value tlapm asset \
         --platform ${TLAPM_PLATFORM})" \
    && TLAPM_SHA256="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value tlapm sha256 \
         --platform ${TLAPM_PLATFORM})" \
    && TLAPM_URL="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value tlapm url \
         --platform ${TLAPM_PLATFORM})" \
    && TLAPM_CACHE="/tmp/downloads/${TLAPM_SHA256}-${TLAPM_ASSET}" \
    && if [ ! -f "${TLAPM_CACHE}" ]; then \
      curl -fsSL -o "${TLAPM_CACHE}" "${TLAPM_URL}"; \
    fi \
    && PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json verify-artifact tlapm \
         "${TLAPM_CACHE}" --platform ${TLAPM_PLATFORM} \
    && tar -xzf "${TLAPM_CACHE}" -C /opt/ \
    && TLAPM_HELP="$(/opt/tlapm/bin/tlapm --help 2>&1 || true)" \
    && [[ "${TLAPM_HELP}" == *"--strict"* ]] \
    && PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json write-tlapm-marker \
         /opt/tlapm/bin/tlapm /opt/tlapm/.tlaps-bench-toolchain.json \
         --platform ${TLAPM_PLATFORM} \
    && rm -f /opt/tlapm/bin/tlapm_lsp \
    && echo "Installed locked tlapm ${TLAPM_TAG} (${TLAPM_SHA256})"

# Layer 4: tla2tools.jar / SANY (downloaded inside Docker — no host dependency)
RUN --mount=type=cache,target=/tmp/downloads \
    TLATOOLS_TAG="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value sany tag)" \
    && TLATOOLS_ASSET="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value sany asset)" \
    && TLATOOLS_SHA256="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value sany sha256)" \
    && TLATOOLS_URL="$(PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json value sany url)" \
    && TLATOOLS_CACHE="/tmp/downloads/${TLATOOLS_SHA256}-${TLATOOLS_ASSET}" \
    && if [ ! -f "${TLATOOLS_CACHE}" ]; then \
      curl -fsSL -o "${TLATOOLS_CACHE}" "${TLATOOLS_URL}"; \
    fi \
    && PYTHONPATH=/opt/tlaps-bench/src python3 -m common.verification_toolchain \
         --lock /opt/tlaps-bench/config/verification-toolchain.json verify-artifact sany \
         "${TLATOOLS_CACHE}" \
    && mkdir -p /opt/sany/lib \
    && cp "${TLATOOLS_CACHE}" /opt/sany/lib/tla2tools.jar \
    && echo "Installed locked tla2tools ${TLATOOLS_TAG} (${TLATOOLS_SHA256})"

# Layer 5: Audited official proof-library source snapshots.
COPY config/proof-library-sources.json /opt/tlaps-bench/config/proof-library-sources.json
COPY scripts/install_proof_libraries.py /opt/tlaps-bench/scripts/install_proof_libraries.py
RUN python3 /opt/tlaps-bench/scripts/install_proof_libraries.py install \
      --lock /opt/tlaps-bench/config/proof-library-sources.json \
      --root /opt/proof-libraries
ARG TLAPS_BENCH_BUILD_SHA256=unknown
RUN --mount=type=bind,source=src,target=/tmp/tlaps-bench-src,readonly \
    test -n "${TLAPS_BENCH_BUILD_SHA256}" \
    && PYTHONPATH=/tmp/tlaps-bench-src python3 -c \
      "from pathlib import Path; from common.proof_libraries import scan_official_libraries; Path('/opt/proof-libraries/proof-library-catalog.json').write_bytes(scan_official_libraries(source_lock=Path('/opt/tlaps-bench/config/proof-library-sources.json'), tlapm_library=Path('/opt/proof-libraries/tlapm'), community_library=Path('/opt/proof-libraries/community')).to_bytes())"

# Layer 5b: Apalache model checker (downloaded inside Docker — no host
# dependency). Kept in sync with scripts/install_deps.sh (host → ~/.apalache).
# The tgz unpacks to apalache-${APALACHE_VERSION}/ with bin/apalache-mc + lib/;
# symlinked onto PATH so agents can invoke `apalache-mc` directly.
ARG APALACHE_TAG=v0.58.3
ARG APALACHE_VERSION=0.58.3
ARG APALACHE_ASSET=apalache-${APALACHE_VERSION}.tgz
ARG APALACHE_URL=https://github.com/apalache-mc/apalache/releases/download/${APALACHE_TAG}/${APALACHE_ASSET}
RUN --mount=type=cache,target=/tmp/downloads \
    if [ ! -f /tmp/downloads/${APALACHE_ASSET} ]; then \
      curl -fsSL -o /tmp/downloads/${APALACHE_ASSET} "${APALACHE_URL}"; \
    fi \
    && tar -xzf /tmp/downloads/${APALACHE_ASSET} -C /opt/ \
    && mv /opt/apalache-${APALACHE_VERSION} /opt/apalache \
    && test -x /opt/apalache/bin/apalache-mc \
    && ln -s /opt/apalache/bin/apalache-mc /usr/local/bin/apalache-mc

# Layer 6: SANY DumpSemantics compilation (needs tla2tools.jar + JDK)
COPY src/dataset/sany-dump /opt/sany/src/dataset/sany-dump
RUN cp -r /opt/proof-libraries/community /opt/sany/lib/community \
    && cd /opt/sany/src/dataset/sany-dump && bash build.sh

# Layer 7: check_proof_bin (changes when src/ changes)
COPY --from=builder /check_proof_bin /usr/local/bin/check_proof_bin

ENV SANY_RUN_SH=/opt/sany/src/dataset/sany-dump/run.sh \
    TLAPS_LIB=/opt/proof-libraries/tlapm \
    COMMUNITY_LIB=/opt/proof-libraries/community \
    TLAPS_IN_CONTAINER=1

# Layer 8: Provider runners
RUN pip install --no-cache-dir --break-system-packages \
    'mcp>=1.28.1,<2' \
    'tree-sitter>=0.25.2' 'tree-sitter-bash>=0.25.1' 'tree-sitter-javascript>=0.25.0'
COPY src/evaluator/__init__.py src/evaluator/agent_skills.py /opt/evaluator/
COPY src/evaluator/backends/litellm_agent.py /opt/litellm_agent.py
COPY src/evaluator/backends/oneshot_runner.py /opt/oneshot_runner.py
COPY src/evaluator/toolcalls.py /opt/toolcalls.py
COPY src/evaluator/backends/codex_usage_wrapper.py /opt/codex_usage_wrapper.py
COPY src/evaluator/backends/codex_proof_check.py /opt/codex_proof_check.py

# Lock down checker + SANY
RUN chmod 0755 /usr/local/bin/check_proof_bin \
    && chown -R root:root /usr/local/bin/check_proof_bin /opt/sany \
    && chmod -R a-w /opt/sany

# Layer 9: Install scripts + firewall + entrypoint (changes sometimes)
COPY docker/install-scripts /opt/install-scripts
RUN chmod -R +x /opt/install-scripts

COPY docker/firewall.sh /opt/firewall.sh
RUN chmod +x /opt/firewall.sh

COPY docker/base-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

# Invalidate locally cached images when sources or the checker version change.
# Keep this label last so the expensive dependency layers remain cacheable.
LABEL org.specula.tlaps-bench.build-sha256="${TLAPS_BENCH_BUILD_SHA256}"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]

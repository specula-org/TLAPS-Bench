"""Content-locked verification toolchain tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from common.verification_toolchain import (
    VerificationToolchainError,
    artifact_descriptor,
    validate_toolchain_identity,
    verification_toolchain_identity,
    verify_artifact,
    write_tlapm_marker,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _lock(tmp_path, *, tlapm_archive: bytes = b"tlapm archive", sany: bytes = b"sany jar"):
    value = {
        "schema_version": 1,
        "tools": {
            "tlapm": {
                "repository": "tlaplus/tlapm",
                "tag": "1.6.0-pre",
                "platforms": {
                    "darwin-arm64": {"asset": "tlapm-mac.tgz", "sha256": _sha256(b"mac archive")},
                    "linux-x86_64": {"asset": "tlapm-linux.tgz", "sha256": _sha256(tlapm_archive)},
                },
            },
            "sany": {
                "repository": "tlaplus/tlaplus",
                "tag": "v1.8.0",
                "asset": "tla2tools.jar",
                "sha256": _sha256(sany),
            },
        },
    }
    path = tmp_path / "verification-toolchain.json"
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize("mirrored", [False, True])
def test_artifact_descriptor_uses_platform_specific_tlapm_asset(tmp_path, mirrored):
    lock = _lock(tmp_path)
    mirror_url = "https://example.org/releases/tlapm-build-123/tlapm-linux.tgz"
    if mirrored:
        value = json.loads(lock.read_text())
        value["tools"]["tlapm"]["platforms"]["linux-x86_64"]["url"] = mirror_url
        lock.write_text(json.dumps(value))

    descriptor = artifact_descriptor("tlapm", lock_path=lock, platform_key="linux-x86_64")

    assert descriptor["asset"] == "tlapm-linux.tgz"
    if mirrored:
        assert descriptor["url"] == mirror_url
    else:
        assert descriptor["url"].endswith("/1.6.0-pre/tlapm-linux.tgz")
    mac = artifact_descriptor("tlapm", lock_path=lock, platform_key="darwin-arm64")
    assert mac["url"].endswith("/1.6.0-pre/tlapm-mac.tgz")


@pytest.mark.parametrize("tool", ["tlapm", "sany"])
@pytest.mark.parametrize("url", ["", "http://example.org/tool.tgz", "https:///tool.tgz", "file:///tmp/tool.tgz"])
def test_artifact_descriptor_rejects_invalid_download_url(tmp_path, url, tool):
    lock = _lock(tmp_path)
    value = json.loads(lock.read_text())
    artifact = value["tools"]["tlapm"]["platforms"]["linux-x86_64"] if tool == "tlapm" else value["tools"]["sany"]
    artifact["url"] = url
    lock.write_text(json.dumps(value))

    with pytest.raises(VerificationToolchainError):
        artifact_descriptor(tool, lock_path=lock, platform_key="linux-x86_64")


@pytest.mark.parametrize("tool", ["tlapm", "sany"])
def test_mirrored_artifact_still_requires_locked_content(tmp_path, tool):
    lock = _lock(tmp_path)
    value = json.loads(lock.read_text())
    entry = value["tools"]["tlapm"]["platforms"]["linux-x86_64"] if tool == "tlapm" else value["tools"]["sany"]
    entry["url"] = "https://example.org/pinned-tool"
    lock.write_text(json.dumps(value))
    artifact = tmp_path / "pinned-tool"
    artifact.write_bytes(b"tlapm archive" if tool == "tlapm" else b"sany jar")
    descriptor = verify_artifact(tool, artifact, lock_path=lock, platform_key="linux-x86_64")
    assert descriptor["url"] == entry["url"]
    artifact.write_bytes(b"replacement archive")

    with pytest.raises(VerificationToolchainError, match="content drifted"):
        verify_artifact(tool, artifact, lock_path=lock, platform_key="linux-x86_64")


def test_artifact_verification_rejects_same_tag_with_different_bytes(tmp_path):
    lock = _lock(tmp_path)
    artifact = tmp_path / "tla2tools.jar"
    artifact.write_bytes(b"different jar")

    with pytest.raises(VerificationToolchainError, match="content drifted"):
        verify_artifact("sany", artifact, lock_path=lock)


def test_runtime_identity_verifies_tlapm_marker_and_sany_bytes(tmp_path):
    lock = _lock(tmp_path)
    executable = tmp_path / "tlapm"
    executable.write_text("#!/bin/sh\necho build-123\n")
    executable.chmod(0o755)
    marker = tmp_path / ".tlaps-bench-toolchain.json"
    write_tlapm_marker(
        executable,
        marker,
        lock_path=lock,
        platform_key="linux-x86_64",
    )
    sany = tmp_path / "tla2tools.jar"
    sany.write_bytes(b"sany jar")

    identity = verification_toolchain_identity(
        executable,
        sany,
        tlapm_marker=marker,
        lock_path=lock,
        platform_key="linux-x86_64",
    )

    assert identity["tlapm"]["version"] == "build-123"
    assert identity["sany"]["jar_sha256"] == _sha256(b"sany jar")
    assert validate_toolchain_identity(identity) == identity


def test_runtime_identity_rejects_modified_tlapm_after_install(tmp_path):
    lock = _lock(tmp_path)
    executable = tmp_path / "tlapm"
    executable.write_text("#!/bin/sh\necho build-123\n")
    executable.chmod(0o755)
    marker = tmp_path / ".tlaps-bench-toolchain.json"
    write_tlapm_marker(
        executable,
        marker,
        lock_path=lock,
        platform_key="linux-x86_64",
    )
    executable.write_text("#!/bin/sh\necho changed\n")
    sany = tmp_path / "tla2tools.jar"
    sany.write_bytes(b"sany jar")

    with pytest.raises(VerificationToolchainError, match="does not match"):
        verification_toolchain_identity(
            executable,
            sany,
            tlapm_marker=marker,
            lock_path=lock,
            platform_key="linux-x86_64",
        )

"""Content locks and runtime identity for the proof verification toolchain."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLCHAIN_LOCK = _REPO_ROOT / "config" / "verification-toolchain.json"
TLAPM_MARKER_FILENAME = ".tlaps-bench-toolchain.json"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class VerificationToolchainError(ValueError):
    """The locked or installed proof verification toolchain is invalid."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _read_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationToolchainError(f"cannot read {label} {path}: {exc}") from exc


def _require_string(mapping: dict[str, object], key: str, *, label: str) -> str:
    value = mapping.get(key)
    if type(value) is not str or not value:
        raise VerificationToolchainError(f"{label} has invalid {key!r}")
    return value


def _validate_artifact(value: object, *, label: str) -> dict[str, str]:
    required = {"asset", "sha256"}
    if type(value) is not dict or set(value) not in (required, required | {"url"}):
        raise VerificationToolchainError(f"invalid verification toolchain artifact {label}")
    artifact = {key: _require_string(value, key, label=label) for key in ("asset", "sha256")}
    if _SHA256.fullmatch(artifact["sha256"]) is None:
        raise VerificationToolchainError(f"{label} has invalid 'sha256'")
    if "url" in value:
        artifact["url"] = _require_string(value, "url", label=label)
        try:
            url = urlsplit(artifact["url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("expected an HTTPS download URL")
        except ValueError as exc:
            raise VerificationToolchainError(f"{label} has invalid 'url'") from exc
    return artifact


def load_toolchain_lock(path: Path = DEFAULT_TOOLCHAIN_LOCK) -> dict[str, object]:
    """Load and validate the exact TLAPM and SANY release artifacts."""

    value = _read_json(path, label="verification toolchain lock")
    if type(value) is not dict or set(value) != {"schema_version", "tools"}:
        raise VerificationToolchainError(f"invalid verification toolchain lock: {path}")
    if value["schema_version"] != 1 or type(value["tools"]) is not dict:
        raise VerificationToolchainError(f"invalid verification toolchain lock fields: {path}")
    tools = value["tools"]
    if set(tools) != {"tlapm", "sany"}:
        raise VerificationToolchainError("verification toolchain lock must contain tlapm and sany")

    tlapm = tools["tlapm"]
    if type(tlapm) is not dict or set(tlapm) != {"repository", "tag", "platforms"}:
        raise VerificationToolchainError("invalid tlapm verification toolchain entry")
    _require_string(tlapm, "repository", label="tlapm")
    _require_string(tlapm, "tag", label="tlapm")
    platforms = tlapm["platforms"]
    if type(platforms) is not dict or set(platforms) != {"darwin-arm64", "linux-x86_64"}:
        raise VerificationToolchainError("tlapm toolchain entry must contain darwin-arm64 and linux-x86_64")
    for platform_name, artifact in platforms.items():
        _validate_artifact(artifact, label=f"tlapm {platform_name}")

    sany = tools["sany"]
    sany_fields = {"repository", "tag", "asset", "sha256"}
    if type(sany) is not dict or set(sany) not in (sany_fields, sany_fields | {"url"}):
        raise VerificationToolchainError("invalid sany verification toolchain entry")
    _require_string(sany, "repository", label="sany")
    _require_string(sany, "tag", label="sany")
    _validate_artifact({key: sany[key] for key in ("asset", "sha256", "url") if key in sany}, label="sany")
    return value


def current_platform_key(system: str | None = None, machine: str | None = None) -> str:
    """Return the lock key for a supported native platform."""

    system = system or platform.system()
    machine = machine or platform.machine()
    keys = {("Linux", "x86_64"): "linux-x86_64", ("Darwin", "arm64"): "darwin-arm64"}
    try:
        return keys[(system, machine)]
    except KeyError as exc:
        raise VerificationToolchainError(f"unsupported verification toolchain platform: {system} {machine}") from exc


def artifact_descriptor(
    tool: str,
    *,
    lock_path: Path = DEFAULT_TOOLCHAIN_LOCK,
    platform_key: str | None = None,
) -> dict[str, str]:
    """Return the locked release artifact and its immutable content digest."""

    lock = load_toolchain_lock(lock_path)
    tools = lock["tools"]
    if tool == "tlapm":
        entry = tools["tlapm"]
        selected_platform = platform_key or current_platform_key()
        platforms = entry["platforms"]
        if selected_platform not in platforms:
            raise VerificationToolchainError(f"unsupported tlapm platform in toolchain lock: {selected_platform}")
        artifact = platforms[selected_platform]
    elif tool == "sany":
        entry = tools["sany"]
        selected_platform = "platform-independent"
        artifact = entry
    else:
        raise VerificationToolchainError(f"unknown verification tool: {tool}")
    repository = entry["repository"]
    tag = entry["tag"]
    asset = artifact["asset"]
    return {
        "repository": repository,
        "tag": tag,
        "platform": selected_platform,
        "asset": asset,
        "sha256": artifact["sha256"],
        "url": artifact.get("url", f"https://github.com/{repository}/releases/download/{tag}/{asset}"),
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VerificationToolchainError(f"cannot hash verification tool {path}: {exc}") from exc
    return digest.hexdigest()


def verify_artifact(
    tool: str,
    path: Path,
    *,
    lock_path: Path = DEFAULT_TOOLCHAIN_LOCK,
    platform_key: str | None = None,
) -> dict[str, str]:
    descriptor = artifact_descriptor(tool, lock_path=lock_path, platform_key=platform_key)
    actual = file_sha256(path)
    if actual != descriptor["sha256"]:
        raise VerificationToolchainError(
            f"{tool} artifact content drifted: expected {descriptor['sha256']}, got {actual}"
        )
    return descriptor


def _tlapm_version(executable: Path) -> str:
    try:
        result = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerificationToolchainError(f"cannot run tlapm executable {executable}: {exc}") from exc
    version = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
    if not version:
        detail = (result.stderr or result.stdout or "").strip()
        raise VerificationToolchainError(f"tlapm executable did not report a version: {detail or executable}")
    return version


def _tlapm_marker_payload(executable: Path, descriptor: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact": descriptor,
        "version": _tlapm_version(executable),
        "executable_sha256": file_sha256(executable),
    }


def write_tlapm_marker(
    executable: Path,
    marker_path: Path,
    *,
    lock_path: Path = DEFAULT_TOOLCHAIN_LOCK,
    platform_key: str | None = None,
) -> dict[str, object]:
    descriptor = artifact_descriptor("tlapm", lock_path=lock_path, platform_key=platform_key)
    payload = _tlapm_marker_payload(executable, descriptor)
    try:
        marker_path.write_bytes(_canonical_json(payload))
    except OSError as exc:
        raise VerificationToolchainError(f"cannot write tlapm installation marker {marker_path}: {exc}") from exc
    return payload


def verify_tlapm_installation(
    executable: Path,
    marker_path: Path,
    *,
    lock_path: Path = DEFAULT_TOOLCHAIN_LOCK,
    platform_key: str | None = None,
) -> dict[str, object]:
    descriptor = artifact_descriptor("tlapm", lock_path=lock_path, platform_key=platform_key)
    marker = _read_json(marker_path, label="tlapm installation marker")
    expected = _tlapm_marker_payload(executable, descriptor)
    if marker != expected:
        raise VerificationToolchainError("installed tlapm does not match its locked release artifact")
    return marker


def verification_toolchain_identity(
    tlapm_executable: Path,
    sany_jar: Path,
    *,
    tlapm_marker: Path | None = None,
    lock_path: Path = DEFAULT_TOOLCHAIN_LOCK,
    platform_key: str | None = None,
) -> dict[str, object]:
    """Verify the installed tools and return their content-based run identity."""

    selected_platform = platform_key or current_platform_key()
    marker_path = tlapm_marker or tlapm_executable.parents[1] / TLAPM_MARKER_FILENAME
    tlapm = verify_tlapm_installation(
        tlapm_executable,
        marker_path,
        lock_path=lock_path,
        platform_key=selected_platform,
    )
    sany = verify_artifact("sany", sany_jar, lock_path=lock_path)
    lock = load_toolchain_lock(lock_path)
    payload = {
        "schema_version": 1,
        "lock_digest": _digest_payload(lock),
        "platform": selected_platform,
        "tlapm": {
            "tag": tlapm["artifact"]["tag"],
            "asset": tlapm["artifact"]["asset"],
            "archive_sha256": tlapm["artifact"]["sha256"],
            "version": tlapm["version"],
            "executable_sha256": tlapm["executable_sha256"],
        },
        "sany": {
            "tag": sany["tag"],
            "asset": sany["asset"],
            "jar_sha256": sany["sha256"],
        },
    }
    return {**payload, "digest": _digest_payload(payload)}


def validate_toolchain_identity(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "lock_digest",
        "platform",
        "tlapm",
        "sany",
        "digest",
    }:
        raise VerificationToolchainError("invalid verification toolchain identity shape")
    payload = {key: value[key] for key in value if key != "digest"}
    if value["schema_version"] != 1 or value["digest"] != _digest_payload(payload):
        raise VerificationToolchainError("verification toolchain identity digest does not match its content")
    return value


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_TOOLCHAIN_LOCK)
    subparsers = parser.add_subparsers(dest="command", required=True)

    value_parser = subparsers.add_parser("value")
    value_parser.add_argument("tool", choices=("tlapm", "sany"))
    value_parser.add_argument("field", choices=("repository", "tag", "platform", "asset", "sha256", "url"))
    value_parser.add_argument("--platform")

    verify_parser = subparsers.add_parser("verify-artifact")
    verify_parser.add_argument("tool", choices=("tlapm", "sany"))
    verify_parser.add_argument("path", type=Path)
    verify_parser.add_argument("--platform")

    write_parser = subparsers.add_parser("write-tlapm-marker")
    write_parser.add_argument("executable", type=Path)
    write_parser.add_argument("marker", type=Path)
    write_parser.add_argument("--platform")

    installed_parser = subparsers.add_parser("verify-tlapm")
    installed_parser.add_argument("executable", type=Path)
    installed_parser.add_argument("marker", type=Path)
    installed_parser.add_argument("--platform")

    args = parser.parse_args()
    try:
        if args.command == "value":
            print(artifact_descriptor(args.tool, lock_path=args.lock, platform_key=args.platform)[args.field])
        elif args.command == "verify-artifact":
            verify_artifact(args.tool, args.path, lock_path=args.lock, platform_key=args.platform)
        elif args.command == "write-tlapm-marker":
            write_tlapm_marker(
                args.executable,
                args.marker,
                lock_path=args.lock,
                platform_key=args.platform,
            )
        else:
            verify_tlapm_installation(
                args.executable,
                args.marker,
                lock_path=args.lock,
                platform_key=args.platform,
            )
    except VerificationToolchainError as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

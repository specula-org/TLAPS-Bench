"""Validation for machine-readable module checker results."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from common.proof_from_scratch_module import ModuleTaskContractError, compute_trusted_units

MODULE_RESULT_SCHEMA_VERSION = 2
SUPPORTED_MODULE_RESULT_SCHEMA_VERSIONS = frozenset({1, MODULE_RESULT_SCHEMA_VERSION})
MODULE_RESULT_PREFIX = "MODULE-RESULT: "
RAW_VERDICTS = frozenset({"PASS", "FAIL", "UNRESOLVED", "TIMEOUT", "ERROR"})


class ModuleResultError(ValueError):
    """A module checker result is missing or internally inconsistent."""


def _reject_constant(value: str) -> Any:
    raise ModuleResultError(f"module result contains non-standard JSON constant {value}")


def _without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModuleResultError(f"module result contains duplicate JSON key {key!r}")
        result[key] = value
    return result


def _string_list(value: object, *, label: str) -> list[str]:
    if type(value) is not list or any(type(item) is not str or not item for item in value):
        raise ModuleResultError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ModuleResultError(f"{label} must not contain duplicates")
    return value


def validate_module_result(raw: object, expected_unit_ids: Iterable[str]) -> dict[str, object]:
    """Validate checker output and recompute dependency-closed trust."""

    expected = tuple(expected_unit_ids)
    if not expected or len(expected) != len(set(expected)):
        raise ModuleResultError("expected proof-unit IDs must be non-empty and unique")
    if type(raw) is not dict:
        raise ModuleResultError("module result must be an object")
    required = {
        "schema_version",
        "sany_status",
        "proof_unit_ids",
        "units",
        "trusted_unit_ids",
        "trusted_proof_unit_ids",
        "complete",
    }
    allowed = required | {"unused_helper_names", "integrity_issues"}
    if not required <= set(raw) or set(raw) - allowed:
        raise ModuleResultError("module result has missing or unknown fields")
    if type(raw["schema_version"]) is not int or raw["schema_version"] not in SUPPORTED_MODULE_RESULT_SCHEMA_VERSIONS:
        raise ModuleResultError(f"unsupported module result schema_version {raw['schema_version']!r}")
    schema_version = raw["schema_version"]
    if type(raw["sany_status"]) is not str or raw["sany_status"] not in {"valid", "invalid"}:
        raise ModuleResultError("module result sany_status must be valid or invalid")
    if tuple(_string_list(raw["proof_unit_ids"], label="proof_unit_ids")) != expected:
        raise ModuleResultError("module result proof-unit IDs differ from the selected module task")
    if type(raw["complete"]) is not bool:
        raise ModuleResultError("module result complete must be a boolean")
    trusted_ids = _string_list(raw["trusted_unit_ids"], label="trusted_unit_ids")
    trusted_targets = _string_list(raw["trusted_proof_unit_ids"], label="trusted_proof_unit_ids")
    if tuple(unit_id for unit_id in expected if unit_id in trusted_targets) != tuple(trusted_targets):
        raise ModuleResultError("trusted proof-unit IDs must preserve manifest order")
    if not set(trusted_targets) <= set(expected):
        raise ModuleResultError("trusted proof-unit IDs contain an unknown target")

    units = raw["units"]
    if type(units) is not list:
        raise ModuleResultError("module result units must be a list")
    normalized_units: list[dict[str, object]] = []
    dependencies: dict[str, tuple[str, ...]] = {}
    raw_pass: set[str] = set()
    seen: set[str] = set()
    unit_keys = {
        "unit_id",
        "kind",
        "theorem_name",
        "line_start",
        "line_end",
        "dependencies",
        "raw_verdict",
        "tlapm_exit",
        "missing_proofs",
        "obligation_failed",
        "trusted",
    }
    if schema_version >= 2:
        unit_keys.add("obligations")
    for index, value in enumerate(units):
        if type(value) is not dict or set(value) != unit_keys:
            raise ModuleResultError(f"module result unit {index} has an invalid shape")
        unit_id = value["unit_id"]
        if type(unit_id) is not str or not unit_id or unit_id in seen:
            raise ModuleResultError(f"module result unit {index} has an invalid or repeated unit_id")
        seen.add(unit_id)
        kind = value["kind"]
        if type(kind) is not str or kind not in {"target", "helper"}:
            raise ModuleResultError(f"module result unit {unit_id!r} has an invalid kind")
        if kind == "target" and unit_id not in expected:
            raise ModuleResultError(f"module result contains unknown target unit {unit_id!r}")
        if kind == "helper" and not unit_id.startswith("helper:"):
            raise ModuleResultError(f"module result helper {unit_id!r} has an invalid identity")
        theorem_name = value["theorem_name"]
        if theorem_name is not None and (type(theorem_name) is not str or not theorem_name):
            raise ModuleResultError(f"module result unit {unit_id!r} has an invalid theorem_name")
        if any(type(value[field]) is not int or value[field] <= 0 for field in ("line_start", "line_end")):
            raise ModuleResultError(f"module result unit {unit_id!r} has invalid line bounds")
        if value["line_end"] < value["line_start"]:
            raise ModuleResultError(f"module result unit {unit_id!r} has reversed line bounds")
        deps = tuple(_string_list(value["dependencies"], label=f"dependencies for {unit_id!r}"))
        dependencies[unit_id] = deps
        verdict = value["raw_verdict"]
        if type(verdict) is not str or verdict not in RAW_VERDICTS:
            raise ModuleResultError(f"module result unit {unit_id!r} has an invalid raw_verdict")
        tlapm_exit = value["tlapm_exit"]
        if tlapm_exit is not None and (type(tlapm_exit) is not int):
            raise ModuleResultError(f"module result unit {unit_id!r} has an invalid tlapm_exit")
        missing_proofs = value["missing_proofs"]
        if missing_proofs is not None and (type(missing_proofs) is not int or missing_proofs < 0):
            raise ModuleResultError(f"module result unit {unit_id!r} has invalid missing_proofs")
        obligation_failed = value["obligation_failed"]
        if obligation_failed is not None and type(obligation_failed) is not bool:
            raise ModuleResultError(f"module result unit {unit_id!r} has invalid obligation_failed")
        if verdict == "PASS" and (tlapm_exit != 0 or missing_proofs != 0 or obligation_failed is not False):
            raise ModuleResultError(f"module result unit {unit_id!r} has inconsistent PASS evidence")
        if verdict == "FAIL" and (tlapm_exit is None or missing_proofs is None or obligation_failed is None):
            raise ModuleResultError(f"module result unit {unit_id!r} has incomplete FAIL evidence")
        if verdict == "UNRESOLVED" and (
            tlapm_exit is not None or missing_proofs is None or missing_proofs < 1 or obligation_failed is not False
        ):
            raise ModuleResultError(f"module result unit {unit_id!r} has inconsistent UNRESOLVED evidence")
        if verdict in {"TIMEOUT", "ERROR"} and (
            tlapm_exit is not None or missing_proofs is not None or obligation_failed is not None
        ):
            raise ModuleResultError(f"module result unit {unit_id!r} has inconsistent {verdict} evidence")
        if schema_version >= 2:
            obligations = value["obligations"]
            if obligations is not None and (type(obligations) is not int or obligations < 0):
                raise ModuleResultError(f"module result unit {unit_id!r} has invalid obligations")
            if verdict == "UNRESOLVED" and obligations != 0:
                raise ModuleResultError(f"module result unit {unit_id!r} has inconsistent UNRESOLVED obligations")
            if verdict in {"TIMEOUT", "ERROR"} and obligations is not None:
                raise ModuleResultError(f"module result unit {unit_id!r} has inconsistent {verdict} obligations")
        if verdict == "PASS":
            raw_pass.add(unit_id)
        if type(value["trusted"]) is not bool:
            raise ModuleResultError(f"module result unit {unit_id!r} trusted must be a boolean")
        normalized_units.append(dict(value))

    integrity = raw.get("integrity_issues")
    if integrity is not None:
        if type(integrity) is not list or any(
            type(issue) is not dict
            or set(issue) != {"code", "message"}
            or type(issue["code"]) is not str
            or not issue["code"]
            or type(issue["message"]) is not str
            for issue in integrity
        ):
            raise ModuleResultError("module result integrity_issues has an invalid shape")
    unused = raw.get("unused_helper_names", [])
    _string_list(unused, label="unused_helper_names")

    if raw["sany_status"] != "valid" or integrity:
        if units or trusted_ids or trusted_targets or raw["complete"]:
            raise ModuleResultError("an invalid or integrity-failing module result cannot contain trusted proof data")
        return dict(raw)

    target_order = [unit["unit_id"] for unit in normalized_units if unit["kind"] == "target"]
    if target_order != list(expected):
        raise ModuleResultError("module result must contain every target unit in manifest order")
    unknown_dependencies = {dependency for values in dependencies.values() for dependency in values} - set(dependencies)
    if unknown_dependencies:
        raise ModuleResultError(f"module result contains unknown local dependencies: {sorted(unknown_dependencies)}")
    try:
        recomputed = compute_trusted_units(raw_pass, dependencies)
    except ModuleTaskContractError as exc:
        raise ModuleResultError(f"module result dependency graph is invalid: {exc}") from exc
    if set(trusted_ids) != set(recomputed):
        raise ModuleResultError("module result trusted-unit set does not match dependency-closed raw passes")
    if any(value["trusted"] != (value["unit_id"] in recomputed) for value in normalized_units):
        raise ModuleResultError("module result per-unit trust flags do not match the trusted-unit set")
    recomputed_targets = [unit_id for unit_id in expected if unit_id in recomputed]
    if trusted_targets != recomputed_targets:
        raise ModuleResultError("module result trusted proof-unit list does not match the trusted-unit set")
    if raw["complete"] != (len(recomputed_targets) == len(expected)):
        raise ModuleResultError("module result complete flag does not match trusted proof-unit coverage")
    return dict(raw)


def parse_module_result_json(text: str, expected_unit_ids: Iterable[str]) -> dict[str, object]:
    """Parse strict JSON and validate all checker-owned trust fields."""

    if type(text) is not str or not text:
        raise ModuleResultError("module result JSON must be a non-empty string")
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_without_duplicates,
            parse_constant=_reject_constant,
        )
    except ModuleResultError:
        raise
    except json.JSONDecodeError as exc:
        raise ModuleResultError(
            f"invalid module result JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    return validate_module_result(raw, expected_unit_ids)


def module_result_from_result(result: Mapping[str, object]) -> dict[str, object] | None:
    value = result.get("module_result")
    return value if isinstance(value, dict) else None


__all__ = [
    "MODULE_RESULT_SCHEMA_VERSION",
    "MODULE_RESULT_PREFIX",
    "RAW_VERDICTS",
    "SUPPORTED_MODULE_RESULT_SCHEMA_VERSIONS",
    "ModuleResultError",
    "module_result_from_result",
    "parse_module_result_json",
    "validate_module_result",
]

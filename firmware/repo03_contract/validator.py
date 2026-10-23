"""Deterministic, standard-library-only validation for REP-03 profiles.

The validator checks contract scope.  It does not validate physical hardware and
must not be used as evidence of automotive, RF, component, or OEM compliance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from typing import Any


SCHEMA_VERSION = "repo03.variant.schema.v1"
TOOL_VERSION = "repo03-contract-validator/1.0.0"

SOURCE_CLASSIFICATIONS = frozenset(
    {
        "SOURCE_EXPLICIT",
        "DERIVED",
        "ENGINEERING_RULE",
        "ASSUMPTION",
        "UNKNOWN",
        "CONFLICT",
    }
)

RESULT_STATUSES = frozenset({"PASS", "FAIL", "UNKNOWN", "BLOCKED", "NOT_RUN"})

VARIANT_CONTRACTS: dict[str, dict[str, Any]] = {
    "A": {
        "enabled_modules": frozenset({"can", "lin", "gnss"}),
        "module_fields": {
            "can": frozenset({"controller", "transceiver", "events"}),
            "lin": frozenset({"uart", "transceiver", "events"}),
            "gnss": frozenset({"hardware", "data_quality"}),
        },
        "required_paths": (
            ("modules", "can", "controller"),
            ("modules", "can", "transceiver"),
            ("modules", "can", "events"),
            ("modules", "lin", "uart"),
            ("modules", "lin", "transceiver"),
            ("modules", "lin", "events"),
            ("modules", "gnss", "hardware"),
            ("modules", "gnss", "data_quality"),
        ),
    },
    "B": {
        "enabled_modules": frozenset({"automotive_power", "shutdown"}),
        "module_fields": {
            "automotive_power": frozenset({"targets", "events", "profile_type"}),
            "shutdown": frozenset({"events", "host_contract"}),
        },
        "required_paths": (
            ("modules", "automotive_power", "targets"),
            ("modules", "automotive_power", "events"),
            ("modules", "automotive_power", "profile_type"),
            ("modules", "shutdown", "events"),
            ("modules", "shutdown", "host_contract"),
            ("integrations", "rep02"),
        ),
    },
}

ALL_MODULES = frozenset().union(
    *(contract["enabled_modules"] for contract in VARIANT_CONTRACTS.values())
)

ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "variant_id",
        "enabled_modules",
        "source",
        "modules",
        "integrations",
        "claims",
        "hardware",
    }
)

SOURCE_KEYS = frozenset({"classification", "reference", "note"})
RESULT_KEYS = frozenset({"status"})
SOURCE_FIELD_KEYS = frozenset(
    {"value", "source", "result", "rule_id", "reason_code"}
)

GATE_LOCKED_VALUE_PATHS = frozenset(
    {
        ("modules", "can", "controller"),
        ("modules", "can", "transceiver"),
        ("modules", "lin", "uart"),
        ("modules", "lin", "transceiver"),
        ("modules", "gnss", "hardware"),
        ("modules", "automotive_power", "targets"),
        ("modules", "automotive_power", "profile_type"),
        ("modules", "shutdown", "host_contract"),
        ("integrations", "rep02"),
    }
)

SYNTHETIC_ONLY_VALUE_PATHS = frozenset(
    {
        ("modules", "can", "events"),
        ("modules", "lin", "events"),
        ("modules", "gnss", "data_quality"),
        ("modules", "automotive_power", "events"),
        ("modules", "shutdown", "events"),
    }
)

_STATUS_PRIORITY = {"PASS": 0, "UNKNOWN": 1, "BLOCKED": 2, "FAIL": 3}
_SEVERITY_BY_STATUS = {
    "UNKNOWN": "WARNING",
    "BLOCKED": "BLOCKER",
    "FAIL": "ERROR",
}


def _normalise_json_value(value: Any, path: tuple[str, ...] = ()) -> Any:
    """Return a deterministic JSON-compatible representation.

    Module declaration order is not semantically meaningful, so
    ``enabled_modules`` is sorted before hashing.  Other arrays retain order.
    Unsupported Python values are represented by type, never by ``repr`` (which
    can contain process-specific memory addresses).
    """

    if isinstance(value, Mapping):
        return {
            str(key): _normalise_json_value(item, path + (str(key),))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        normalised = [_normalise_json_value(item, path + ("[]",)) for item in value]
        if path and path[-1] == "enabled_modules":
            return sorted(
                normalised,
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
        return normalised
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            label = "NaN"
        elif value > 0:
            label = "Infinity"
        else:
            label = "-Infinity"
        return {"__non_finite_number__": label}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__unsupported_type__": type(value).__name__}


def _non_finite_number_paths(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[tuple[str, ...]]:
    """Return deterministic paths to numbers JSON cannot represent."""

    if isinstance(value, float) and not math.isfinite(value):
        return [path]
    if isinstance(value, Mapping):
        paths: list[tuple[str, ...]] = []
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            paths.extend(_non_finite_number_paths(item, path + (str(key),)))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_non_finite_number_paths(item, path + (str(index),)))
        return paths
    return []


def normalized_profile_hash(profile: Any) -> str:
    """Calculate the SHA-256 of a canonical JSON representation of *profile*."""

    payload = json.dumps(
        _normalise_json_value(profile),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _path_text(path: Sequence[str]) -> str:
    return ".".join(path) if path else "$"


def _read_path(profile: Mapping[str, Any], path: Sequence[str]) -> tuple[bool, Any]:
    current: Any = profile
    for component in path:
        if not isinstance(current, Mapping) or component not in current:
            return False, None
        current = current[component]
    return True, current


def validate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a REP-03 variant profile and return a deterministic report.

    Contract or scope violations produce ``FAIL``.  Missing source-controlled
    fields produce ``BLOCKED``; explicitly unresolved values produce
    ``UNKNOWN`` unless their field result already marks them ``BLOCKED``.
    """

    profile_hash = normalized_profile_hash(profile)
    issues: list[dict[str, str]] = []

    def add_issue(
        status: str,
        rule_id: str,
        reason_code: str,
        path: Sequence[str],
        message: str,
    ) -> None:
        issues.append(
            {
                "severity": _SEVERITY_BY_STATUS[status],
                "status": status,
                "rule_id": rule_id,
                "reason_code": reason_code,
                "path": _path_text(path),
                "message": message,
            }
        )

    if not isinstance(profile, Mapping):
        add_issue(
            "FAIL",
            "REP03-SCHEMA-001",
            "PROFILE_NOT_OBJECT",
            (),
            "Profile must be a JSON object.",
        )
        return _build_report(None, None, profile_hash, issues)

    for non_finite_path in _non_finite_number_paths(profile):
        add_issue(
            "FAIL",
            "REP03-SCHEMA-010",
            "NON_FINITE_NUMBER",
            non_finite_path,
            "JSON numeric values must be finite; NaN and infinity are forbidden.",
        )

    for key in profile:
        if not isinstance(key, str):
            add_issue(
                "FAIL",
                "REP03-SCHEMA-002",
                "NON_STRING_KEY",
                (),
                "All profile object keys must be strings.",
            )
            break

    unknown_top_level = {
        key
        for key in profile
        if isinstance(key, str)
        and key not in ALLOWED_TOP_LEVEL_FIELDS
        and key != "combined_profile"
    }
    if unknown_top_level:
        add_issue(
            "FAIL",
            "REP03-SCHEMA-005",
            "UNKNOWN_TOP_LEVEL_FIELD",
            (),
            "Unknown top-level fields: "
            + ", ".join(sorted(unknown_top_level))
            + ".",
        )

    schema_version = profile.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        add_issue(
            "FAIL",
            "REP03-SCHEMA-003",
            "SCHEMA_VERSION_MISMATCH",
            ("schema_version",),
            f"schema_version must equal {SCHEMA_VERSION!r}.",
        )

    variant_id = profile.get("variant_id")
    if variant_id not in VARIANT_CONTRACTS:
        add_issue(
            "FAIL",
            "REP03-VARIANT-001",
            "VARIANT_ID_INVALID",
            ("variant_id",),
            "variant_id must be 'A' or 'B'.",
        )

    if "combined_profile" in profile:
        add_issue(
            "FAIL",
            "REP03-SCOPE-001",
            "COMBINED_PROFILE_FORBIDDEN",
            ("combined_profile",),
            "A combined A+B profile is outside the approved contract.",
        )

    if "hardware" in profile:
        add_issue(
            "FAIL",
            "REP03-GATE-001",
            "HARDWARE_CONTENT_FORBIDDEN",
            ("hardware",),
            "All hardware content is forbidden before G1/G2, including "
            "exact-part, RF, OEM transient, schematic, and PCB data.",
        )

    enabled_modules = profile.get("enabled_modules")
    declared_modules: set[str] | None = None
    if not isinstance(enabled_modules, list) or not all(
        isinstance(module, str) for module in enabled_modules
    ):
        add_issue(
            "FAIL",
            "REP03-VARIANT-002",
            "ENABLED_MODULES_INVALID",
            ("enabled_modules",),
            "enabled_modules must be an array of module identifiers.",
        )
    else:
        declared_modules = set(enabled_modules)
        if len(declared_modules) != len(enabled_modules):
            add_issue(
                "FAIL",
                "REP03-VARIANT-003",
                "DUPLICATE_MODULE",
                ("enabled_modules",),
                "enabled_modules must not contain duplicates.",
            )
        unknown_modules = declared_modules - ALL_MODULES
        if unknown_modules:
            add_issue(
                "FAIL",
                "REP03-SCOPE-002",
                "UNKNOWN_MODULE",
                ("enabled_modules",),
                "Unknown modules: " + ", ".join(sorted(unknown_modules)) + ".",
            )
        if variant_id in VARIANT_CONTRACTS:
            expected = VARIANT_CONTRACTS[variant_id]["enabled_modules"]
            foreign = (declared_modules & ALL_MODULES) - expected
            if foreign:
                add_issue(
                    "FAIL",
                    "REP03-SCOPE-003",
                    "VARIANT_MODULE_LEAKAGE",
                    ("enabled_modules",),
                    "Modules from the other variant are enabled: "
                    + ", ".join(sorted(foreign))
                    + ".",
                )
            missing = expected - declared_modules
            if missing:
                add_issue(
                    "FAIL",
                    "REP03-VARIANT-004",
                    "REQUIRED_MODULE_MISSING",
                    ("enabled_modules",),
                    "Required modules are missing: " + ", ".join(sorted(missing)) + ".",
                )

    modules = profile.get("modules")
    if not isinstance(modules, Mapping):
        add_issue(
            "FAIL",
            "REP03-SCHEMA-004",
            "MODULES_NOT_OBJECT",
            ("modules",),
            "modules must be an object.",
        )
    else:
        module_keys = {key for key in modules if isinstance(key, str)}
        unknown_module_keys = module_keys - ALL_MODULES
        if unknown_module_keys:
            add_issue(
                "FAIL",
                "REP03-SCOPE-002",
                "UNKNOWN_MODULE",
                ("modules",),
                "Unknown module definitions: "
                + ", ".join(sorted(unknown_module_keys))
                + ".",
            )
        if variant_id in VARIANT_CONTRACTS:
            expected = VARIANT_CONTRACTS[variant_id]["enabled_modules"]
            foreign = (module_keys & ALL_MODULES) - expected
            if foreign:
                add_issue(
                    "FAIL",
                    "REP03-SCOPE-004",
                    "VARIANT_DEFINITION_LEAKAGE",
                    ("modules",),
                    "Module definitions leak from the other variant: "
                    + ", ".join(sorted(foreign))
                    + ".",
                )
            missing_definitions = expected - module_keys
            if missing_definitions:
                add_issue(
                    "FAIL",
                    "REP03-VARIANT-005",
                    "MODULE_DEFINITION_MISSING",
                    ("modules",),
                    "Module definitions are missing: "
                    + ", ".join(sorted(missing_definitions))
                    + ".",
                )
            for module_name in sorted(expected & module_keys):
                if not isinstance(modules[module_name], Mapping):
                    add_issue(
                        "FAIL",
                        "REP03-SCHEMA-006",
                        "MODULE_DEFINITION_NOT_OBJECT",
                        ("modules", module_name),
                        "Each enabled module definition must be an object.",
                    )
                    continue
                expected_fields = VARIANT_CONTRACTS[variant_id]["module_fields"][
                    module_name
                ]
                module_field_keys = set(modules[module_name])
                if not all(isinstance(key, str) for key in module_field_keys):
                    add_issue(
                        "FAIL",
                        "REP03-SCHEMA-008",
                        "NON_STRING_MODULE_FIELD",
                        ("modules", module_name),
                        "Module field names must be strings.",
                    )
                unknown_fields = {
                    key
                    for key in module_field_keys
                    if isinstance(key, str) and key not in expected_fields
                }
                if unknown_fields:
                    add_issue(
                        "FAIL",
                        "REP03-SCOPE-006",
                        "UNKNOWN_MODULE_FIELD",
                        ("modules", module_name),
                        "Unknown module fields: "
                        + ", ".join(sorted(unknown_fields))
                        + ".",
                    )

    if variant_id == "A" and "integrations" in profile:
        add_issue(
            "FAIL",
            "REP03-SCOPE-005",
            "VARIANT_INTEGRATION_LEAKAGE",
            ("integrations",),
            "Variant A must not contain Variant B integrations.",
        )
    elif variant_id == "B" and "integrations" in profile:
        integrations = profile.get("integrations")
        if not isinstance(integrations, Mapping):
            add_issue(
                "FAIL",
                "REP03-SCHEMA-007",
                "INTEGRATIONS_NOT_OBJECT",
                ("integrations",),
                "integrations must be an object for Variant B.",
            )
        else:
            integration_keys = set(integrations)
            if not all(isinstance(key, str) for key in integration_keys):
                add_issue(
                    "FAIL",
                    "REP03-SCHEMA-009",
                    "NON_STRING_INTEGRATION_FIELD",
                    ("integrations",),
                    "Integration field names must be strings.",
                )
            unknown_integrations = {
                key
                for key in integration_keys
                if isinstance(key, str) and key != "rep02"
            }
            if unknown_integrations:
                add_issue(
                    "FAIL",
                    "REP03-SCOPE-007",
                    "UNKNOWN_INTEGRATION_FIELD",
                    ("integrations",),
                    "Unknown integration fields: "
                    + ", ".join(sorted(unknown_integrations))
                    + ".",
                )

    root_source = profile.get("source")
    _validate_source_object(root_source, ("source",), add_issue)

    claims = profile.get("claims")
    if not isinstance(claims, Mapping):
        add_issue(
            "FAIL",
            "REP03-CLAIM-001",
            "CLAIMS_NOT_OBJECT",
            ("claims",),
            "claims must be an object containing validation_level.",
        )
    else:
        unknown_claim_fields = {key for key in claims if key != "validation_level"}
        if unknown_claim_fields:
            add_issue(
                "FAIL",
                "REP03-CLAIM-003",
                "UNKNOWN_CLAIM_FIELD",
                ("claims",),
                "Unknown claim fields are not permitted.",
            )
        if claims.get("validation_level") != "SYNTHETIC":
            add_issue(
                "FAIL",
                "REP03-CLAIM-002",
                "VALIDATION_LEVEL_NOT_SYNTHETIC",
                ("claims", "validation_level"),
                "Only SYNTHETIC validation claims are permitted at this gate.",
            )

    if variant_id in VARIANT_CONTRACTS:
        for required_path in VARIANT_CONTRACTS[variant_id]["required_paths"]:
            present, value = _read_path(profile, required_path)
            if not present:
                add_issue(
                    "FAIL",
                    "REP03-INPUT-001",
                    "REQUIRED_CONTRACT_FIELD_MISSING",
                    required_path,
                    "A required contract field is missing; unresolved inputs must be "
                    "represented explicitly with null plus UNKNOWN/BLOCKED metadata.",
                )
                continue
            _evaluate_field(
                value,
                required_path,
                add_issue,
            )

    return _build_report(schema_version, variant_id, profile_hash, issues)


def _evaluate_classification(
    classification: str,
    path: Sequence[str],
    add_issue: Any,
) -> None:
    if classification not in SOURCE_CLASSIFICATIONS:
        add_issue(
            "FAIL",
            "REP03-SOURCE-002",
            "SOURCE_CLASSIFICATION_INVALID",
            path,
            "Source classification is outside the approved enumeration.",
        )
    elif classification == "CONFLICT":
        add_issue(
            "BLOCKED",
            "REP03-SOURCE-003",
            "SOURCE_CONFLICT",
            path,
            "Conflicting source evidence blocks the input.",
        )
    elif classification in {"UNKNOWN", "ASSUMPTION"}:
        add_issue(
            "UNKNOWN",
            "REP03-SOURCE-004",
            "SOURCE_UNVERIFIED",
            path,
            "The source is unknown or an unverified assumption.",
        )


def _validate_source_object(
    source: Any,
    path: Sequence[str],
    add_issue: Any,
) -> str | None:
    if not isinstance(source, Mapping):
        add_issue(
            "FAIL",
            "REP03-SOURCE-001",
            "SOURCE_METADATA_NOT_OBJECT",
            path,
            "Source metadata must be an object containing classification.",
        )
        return None

    unknown_keys = {key for key in source if key not in SOURCE_KEYS}
    if unknown_keys:
        add_issue(
            "FAIL",
            "REP03-SOURCE-006",
            "UNKNOWN_SOURCE_FIELD",
            path,
            "Unknown source metadata fields are not permitted.",
        )

    classification = source.get("classification")
    if not isinstance(classification, str):
        add_issue(
            "FAIL",
            "REP03-SOURCE-001",
            "SOURCE_CLASSIFICATION_MISSING",
            tuple(path) + ("classification",),
            "Source classification is required and must be a string.",
        )
        classification = None
    else:
        _evaluate_classification(
            classification,
            tuple(path) + ("classification",),
            add_issue,
        )

    if "reference" in source and source["reference"] is not None and not isinstance(
        source["reference"], str
    ):
        add_issue(
            "FAIL",
            "REP03-SOURCE-007",
            "SOURCE_REFERENCE_INVALID",
            tuple(path) + ("reference",),
            "Source reference must be a string or null.",
        )
    if "note" in source and not isinstance(source["note"], str):
        add_issue(
            "FAIL",
            "REP03-SOURCE-008",
            "SOURCE_NOTE_INVALID",
            tuple(path) + ("note",),
            "Source note must be a string.",
        )
    return classification


def _validate_result_object(
    result: Any,
    path: Sequence[str],
    add_issue: Any,
) -> str | None:
    if not isinstance(result, Mapping):
        add_issue(
            "FAIL",
            "REP03-RESULT-005",
            "FIELD_RESULT_NOT_OBJECT",
            path,
            "Field result metadata must be an object containing status.",
        )
        return None

    unknown_keys = {key for key in result if key not in RESULT_KEYS}
    if unknown_keys:
        add_issue(
            "FAIL",
            "REP03-RESULT-006",
            "UNKNOWN_RESULT_FIELD",
            path,
            "Unknown result metadata fields are not permitted.",
        )

    status = result.get("status")
    if not isinstance(status, str) or status not in RESULT_STATUSES:
        add_issue(
            "FAIL",
            "REP03-RESULT-001",
            "RESULT_STATUS_INVALID",
            tuple(path) + ("status",),
            "Field result status is outside the approved enumeration.",
        )
        return None
    return status


def _evaluate_field(
    value: Any,
    path: Sequence[str],
    add_issue: Any,
) -> None:
    if not isinstance(value, Mapping):
        add_issue(
            "FAIL",
            "REP03-INPUT-003",
            "SOURCE_FIELD_NOT_OBJECT",
            path,
            "The source-controlled input must include value, source, and result metadata.",
        )
        return

    unknown_keys = {key for key in value if key not in SOURCE_FIELD_KEYS}
    if unknown_keys:
        add_issue(
            "FAIL",
            "REP03-INPUT-004",
            "UNKNOWN_SOURCE_FIELD_PROPERTY",
            path,
            "Unknown source-field properties are not permitted.",
        )

    for metadata_key in ("value", "source", "result"):
        if metadata_key not in value:
            add_issue(
                "FAIL",
                "REP03-INPUT-005",
                "SOURCE_FIELD_PROPERTY_MISSING",
                tuple(path) + (metadata_key,),
                "Each source-controlled field must include value, source, and result.",
            )

    for text_key in ("rule_id", "reason_code"):
        if text_key in value and (
            not isinstance(value[text_key], str) or not value[text_key]
        ):
            add_issue(
                "FAIL",
                "REP03-INPUT-006",
                "TRACE_FIELD_INVALID",
                tuple(path) + (text_key,),
                "Optional rule_id and reason_code values must be non-empty strings.",
            )

    _validate_source_object(value.get("source"), tuple(path) + ("source",), add_issue)
    status = _validate_result_object(
        value.get("result"), tuple(path) + ("result",), add_issue
    )

    if status == "FAIL":
        add_issue(
            "FAIL",
            "REP03-RESULT-002",
            "SOURCE_INPUT_FAILED",
            path,
            "The source-controlled input reports FAIL.",
        )
    elif status in {"BLOCKED", "NOT_RUN"}:
        add_issue(
            "BLOCKED",
            "REP03-RESULT-003",
            "SOURCE_INPUT_BLOCKED",
            path,
            "The source-controlled input is blocked or has not run.",
        )
    elif status == "UNKNOWN":
        add_issue(
            "UNKNOWN",
            "REP03-RESULT-004",
            "SOURCE_INPUT_UNKNOWN",
            path,
            "The source-controlled input reports UNKNOWN.",
        )

    actual_value = value.get("value")
    path_tuple = tuple(path)
    if path_tuple in GATE_LOCKED_VALUE_PATHS and actual_value is not None:
        add_issue(
            "FAIL",
            "REP03-GATE-003",
            "GATE_LOCKED_VALUE_PRESENT",
            tuple(path) + ("value",),
            "This hardware-sensitive value must remain null until G1/G2 opens.",
        )
    if path_tuple in SYNTHETIC_ONLY_VALUE_PATHS and actual_value not in (
        None,
        "SYNTHETIC_ONLY",
    ):
        add_issue(
            "FAIL",
            "REP03-GATE-004",
            "NON_SYNTHETIC_VALUE_FORBIDDEN",
            tuple(path) + ("value",),
            "This field may contain only null or SYNTHETIC_ONLY at the current gate.",
        )
    if actual_value is None:
        if status == "PASS":
            add_issue(
                "FAIL",
                "REP03-INPUT-007",
                "PASS_WITH_UNRESOLVED_VALUE",
                tuple(path) + ("value",),
                "A null source value cannot report PASS.",
            )
            return
        unresolved_status = (
            "BLOCKED" if status in {"BLOCKED", "NOT_RUN", None} else "UNKNOWN"
        )
        add_issue(
            unresolved_status,
            "REP03-INPUT-002",
            "SOURCE_VALUE_UNRESOLVED",
            tuple(path) + ("value",),
            "The required source value is not yet resolved.",
        )


def _build_report(
    schema_version: Any,
    variant_id: Any,
    profile_hash: str,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    if issues:
        dominant = max(
            issues,
            key=lambda issue: _STATUS_PRIORITY[issue["status"]],
        )
        status = dominant["status"]
        rule_id = dominant["rule_id"]
        reason_code = dominant["reason_code"]
    else:
        status = "PASS"
        rule_id = "REP03-CONTRACT-000"
        reason_code = "CONTRACT_VALID"

    safe_schema_version = schema_version if isinstance(schema_version, str) else None
    safe_variant_id = variant_id if isinstance(variant_id, str) else None

    return {
        "schema_version": safe_schema_version,
        "expected_schema_version": SCHEMA_VERSION,
        "variant_id": safe_variant_id,
        "status": status,
        "result": {"status": status},
        "rule_id": rule_id,
        "reason_code": reason_code,
        "normalized_profile_hash": profile_hash,
        "profile_hash": profile_hash,
        "input_hash": profile_hash,
        "tool_version": TOOL_VERSION,
        "claims": {"validation_level": "SYNTHETIC"},
        "issues": issues,
    }

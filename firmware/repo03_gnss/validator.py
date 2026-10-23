"""Deterministic synthetic GNSS validator for REP-03 WF-03-04.

The validator deliberately separates synthetic fix-data checks from hardware
and RF suitability.  GAP-02 remains visible until an integration guide,
antenna source and RF layout evidence are all traceable.  A synthetic PASS is
therefore never presented as a measured position, antenna result or RF proof.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
from typing import Any


SCHEMA_VERSION = "repo03.gnss.scenario.v1"
TOOL_VERSION = "repo03-gnss-validator/1.0.0"
ENGINE_ID = "repo03-gnss-validator"
MODULE_ID = "gnss"
VARIANT_ID = "A"
VARIANT_CONTRACT_SCHEMA = "repo03.variant.schema.v1"
APPROVED_VARIANT_A_PROFILE_HASH = (
    "f74c42bb2a2519ab563a91cb05cfb6d4e5accd9d6f2570ed89604bbad5e0367e"
)

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
PASS_SOURCE_CLASSIFICATIONS = frozenset(
    {"SOURCE_EXPLICIT", "DERIVED", "ENGINEERING_RULE"}
)
FIX_QUALITIES = frozenset({"NO_FIX", "FIX_2D", "FIX_3D"})
ANTENNA_STATUSES = frozenset({"NOMINAL", "OPEN", "SHORT", "UNKNOWN"})
_STATUS_PRIORITY = {"PASS": 0, "UNKNOWN": 1, "BLOCKED": 2, "FAIL": 3}

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "scenario_id",
        "engine_id",
        "module_id",
        "variant_id",
        "enabled_modules",
        "variant_contract",
        "source",
        "synthetic_data",
        "known_gaps",
        "module_profile",
        "freshness_policy",
        "observation",
    }
)
_SOURCE_KEYS = frozenset({"classification", "reference", "version"})
_CONTRACT_KEYS = frozenset({"schema_version", "profile_hash", "source"})
_MODULE_KEYS = frozenset(
    {
        "profile_id",
        "scope",
        "module_variant",
        "antenna_type",
        "rf_feed",
        "power_profile",
        "integration_guide",
        "rf_layout_evidence",
    }
)
_COMPONENT_KEYS = frozenset({"value", "source"})
_FRESHNESS_KEYS = frozenset({"max_age_ms", "source"})
_OBSERVATION_KEYS = frozenset(
    {
        "fix_quality",
        "timestamp_ms",
        "previous_timestamp_ms",
        "evaluation_timestamp_ms",
        "age_ms",
        "antenna_status",
        "position",
        "source",
    }
)
_POSITION_KEYS = frozenset(
    {"latitude_deg", "longitude_deg", "altitude_m", "synthetic_data"}
)
_FORBIDDEN_CLAIM_KEYS = frozenset(
    {
        "physical_pass",
        "physical_validation",
        "physical_gnss_validation",
        "measured",
        "measurement",
        "measured_value",
        "actual_coordinates",
        "real_fix",
        "real_measurement",
        "rf_pass",
        "rf_validated",
        "rf_suitability",
        "rf_suitability_pass",
        "antenna_validated",
        "antenna_gain",
        "signal_strength",
        "cn0",
        "snr",
        "part_number",
        "exact_part",
        "voltage",
        "current",
        "compliance",
        "certified",
    }
)


def _normalise_json(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalise_json(item, path + (str(key),))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        normalised = [_normalise_json(item, path + ("[]",)) for item in value]
        if path and path[-1] in {"enabled_modules", "known_gaps"}:
            return sorted(
                normalised,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        return normalised
    if isinstance(value, float) and not math.isfinite(value):
        return {"__non_finite_number__": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__unsupported_type__": type(value).__name__}


def normalized_input_hash(scenario: Any) -> str:
    """Return a key-order-independent SHA-256 for any supplied input."""

    payload = json.dumps(
        _normalise_json(scenario),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _issue(
    status: str,
    rule_id: str,
    reason_code: str,
    path: str,
    message: str,
) -> dict[str, str]:
    return {
        "status": status,
        "rule_id": rule_id,
        "reason_code": reason_code,
        "path": path,
        "message": message,
    }


def _dominant(records: list[Mapping[str, Any]]) -> tuple[str, str, str]:
    if not records:
        return "PASS", "REP03-GNSS-FIX-000", "SYNTHETIC_FIX_VALID"
    dominant = max(records, key=lambda record: _STATUS_PRIORITY[record["status"]])
    return (
        str(dominant["status"]),
        str(dominant["rule_id"]),
        str(dominant["reason_code"]),
    )


def _unknown_fields(
    value: Mapping[Any, Any],
    allowed: frozenset[str],
    path: str,
    rule_id: str,
    reason_code: str,
) -> list[dict[str, str]]:
    unknown = {str(key) for key in value if key not in allowed}
    if not unknown:
        return []
    return [
        _issue(
            "FAIL",
            rule_id,
            reason_code,
            path,
            "Unknown fields: " + ", ".join(sorted(unknown)),
        )
    ]


def _find_forbidden_claims(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            lower = key_text.lower()
            if (
                lower in _FORBIDDEN_CLAIM_KEYS
                or lower.startswith("measured_")
                or lower.startswith("physical_")
                or lower.startswith("rf_pass_")
                or lower.endswith("_pass")
                or lower.endswith("_validated")
                or lower.endswith("_suitable")
            ):
                found.append(child_path)
            found.extend(_find_forbidden_claims(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_claims(item, f"{path}[{index}]"))
    return found


def _find_non_finite(value: Any, path: str = "$") -> list[str]:
    if isinstance(value, float) and not math.isfinite(value):
        return [path]
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_find_non_finite(item, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_find_non_finite(item, f"{path}[{index}]"))
    return found


def _source_status(classification: Any) -> tuple[str, str]:
    if classification in PASS_SOURCE_CLASSIFICATIONS:
        return "PASS", "SOURCE_TRACEABLE"
    if classification == "ASSUMPTION":
        return "UNKNOWN", "SOURCE_ASSUMPTION"
    if classification == "CONFLICT":
        return "BLOCKED", "SOURCE_CONFLICT"
    return "BLOCKED", "SOURCE_UNRESOLVED"


def _safe_source(source: Any) -> dict[str, str] | None:
    if not isinstance(source, Mapping) or set(source) != _SOURCE_KEYS:
        return None
    classification = source.get("classification")
    reference = source.get("reference")
    version = source.get("version")
    if (
        not isinstance(classification, str)
        or classification not in SOURCE_CLASSIFICATIONS
        or not isinstance(reference, str)
        or not reference.strip()
        or not isinstance(version, str)
        or not version.strip()
    ):
        return None
    return {
        "classification": classification,
        "reference": reference,
        "version": version,
    }


def _validate_source(
    source: Any,
    path: str,
    issues: list[dict[str, str]],
    *,
    prefix: str,
    gate_classification: bool,
) -> None:
    if source is None:
        issues.append(
            _issue(
                "BLOCKED",
                f"REP03-GNSS-{prefix}-001",
                f"{prefix}_SOURCE_MISSING",
                path,
                "Traceable source metadata is required.",
            )
        )
        return
    if not isinstance(source, Mapping):
        issues.append(
            _issue(
                "FAIL",
                f"REP03-GNSS-{prefix}-002",
                f"{prefix}_SOURCE_INVALID",
                path,
                "Source metadata must be an object.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            source,
            _SOURCE_KEYS,
            path,
            f"REP03-GNSS-{prefix}-003",
            "UNKNOWN_SOURCE_FIELD",
        )
    )
    classification = source.get("classification")
    if (
        not isinstance(classification, str)
        or classification not in SOURCE_CLASSIFICATIONS
    ):
        issues.append(
            _issue(
                "FAIL",
                f"REP03-GNSS-{prefix}-004",
                f"{prefix}_SOURCE_CLASSIFICATION_INVALID",
                f"{path}.classification",
                "Source classification is outside the approved enumeration.",
            )
        )
    elif gate_classification and classification not in PASS_SOURCE_CLASSIFICATIONS:
        status, source_reason = _source_status(classification)
        reason = (
            f"{prefix}_SOURCE_ASSUMPTION"
            if classification == "ASSUMPTION"
            else f"{prefix}_SOURCE_UNRESOLVED"
        )
        if classification == "CONFLICT":
            reason = f"{prefix}_SOURCE_CONFLICT"
        issues.append(
            _issue(
                status,
                f"REP03-GNSS-{prefix}-005",
                reason,
                path,
                f"A {source_reason.lower().replace('_', ' ')} cannot produce PASS.",
            )
        )
    reference = source.get("reference")
    version = source.get("version")
    if not isinstance(reference, str) or not reference.strip():
        issues.append(
            _issue(
                "FAIL",
                f"REP03-GNSS-{prefix}-006",
                f"{prefix}_SOURCE_REFERENCE_INVALID",
                f"{path}.reference",
                "Source reference must be a non-empty string.",
            )
        )
    if not isinstance(version, str) or not version.strip():
        issues.append(
            _issue(
                "FAIL",
                f"REP03-GNSS-{prefix}-007",
                f"{prefix}_SOURCE_VERSION_INVALID",
                f"{path}.version",
                "Source version must be a non-empty string.",
            )
        )


def _validate_variant_contract(
    contract: Any, issues: list[dict[str, str]]
) -> None:
    if contract is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-GNSS-D1-001",
                "VARIANT_CONTRACT_MISSING",
                "variant_contract",
                "The approved D1 Variant A contract is required.",
            )
        )
        return
    if not isinstance(contract, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-D1-002",
                "VARIANT_CONTRACT_INVALID",
                "variant_contract",
                "variant_contract must be an object.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            contract,
            _CONTRACT_KEYS,
            "variant_contract",
            "REP03-GNSS-D1-003",
            "UNKNOWN_VARIANT_CONTRACT_FIELD",
        )
    )
    missing = _CONTRACT_KEYS - set(contract)
    if missing:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-D1-004",
                "VARIANT_CONTRACT_FIELDS_MISSING",
                "variant_contract",
                "Missing fields: " + ", ".join(sorted(missing)),
            )
        )
    if contract.get("schema_version") != VARIANT_CONTRACT_SCHEMA:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-D1-005",
                "VARIANT_CONTRACT_SCHEMA_MISMATCH",
                "variant_contract.schema_version",
                "Variant contract schema does not match D1.",
            )
        )
    if contract.get("profile_hash") != APPROVED_VARIANT_A_PROFILE_HASH:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-D1-006",
                "VARIANT_CONTRACT_HASH_MISMATCH",
                "variant_contract.profile_hash",
                "Scenario is not pinned to the approved Variant A profile hash.",
            )
        )
    _validate_source(
        contract.get("source"),
        "variant_contract.source",
        issues,
        prefix="D1",
        gate_classification=True,
    )


def _validate_component(
    component: Any,
    path: str,
    issues: list[dict[str, str]],
    prefix: str,
) -> None:
    if component is None:
        issues.append(
            _issue(
                "BLOCKED",
                f"REP03-GNSS-{prefix}-001",
                f"{prefix}_MISSING",
                path,
                "Component value and source are unresolved.",
            )
        )
        return
    if not isinstance(component, Mapping):
        issues.append(
            _issue(
                "FAIL",
                f"REP03-GNSS-{prefix}-002",
                f"{prefix}_INVALID",
                path,
                "Component must be an object.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            component,
            _COMPONENT_KEYS,
            path,
            f"REP03-GNSS-{prefix}-003",
            "UNKNOWN_COMPONENT_FIELD",
        )
    )
    value = component.get("value")
    if value is not None and (not isinstance(value, str) or not value.strip()):
        issues.append(
            _issue(
                "FAIL",
                f"REP03-GNSS-{prefix}-004",
                f"{prefix}_VALUE_INVALID",
                f"{path}.value",
                "Component value must be null or a non-empty string.",
            )
        )
    _validate_source(
        component.get("source"),
        f"{path}.source",
        issues,
        prefix=prefix,
        gate_classification=False,
    )


def _validate_module_profile(
    profile: Any, issues: list[dict[str, str]]
) -> None:
    if profile is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-GNSS-MODULE-001",
                "MODULE_PROFILE_MISSING",
                "module_profile",
                "No GNSS module profile is available for synthetic evaluation.",
            )
        )
        return
    if not isinstance(profile, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-MODULE-002",
                "MODULE_PROFILE_INVALID",
                "module_profile",
                "module_profile must be an object or null.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            profile,
            _MODULE_KEYS,
            "module_profile",
            "REP03-GNSS-MODULE-003",
            "UNKNOWN_MODULE_PROFILE_FIELD",
        )
    )
    if not isinstance(profile.get("profile_id"), str) or not profile["profile_id"].strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-MODULE-004",
                "MODULE_PROFILE_ID_INVALID",
                "module_profile.profile_id",
                "profile_id must be a non-empty string.",
            )
        )
    if profile.get("scope") != "SYNTHETIC_CONFIGURATION":
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-SCOPE-002",
                "MODULE_SCOPE_INVALID",
                "module_profile.scope",
                "Only SYNTHETIC_CONFIGURATION profiles are accepted.",
            )
        )
    for name, prefix in (
        ("module_variant", "MODULE-VARIANT"),
        ("antenna_type", "ANTENNA-TYPE"),
        ("rf_feed", "RF-FEED"),
        ("power_profile", "POWER-PROFILE"),
    ):
        _validate_component(profile.get(name), f"module_profile.{name}", issues, prefix)
    for name, prefix in (
        ("integration_guide", "INTEGRATION-GUIDE"),
        ("rf_layout_evidence", "RF-LAYOUT"),
    ):
        _validate_source(
            profile.get(name),
            f"module_profile.{name}",
            issues,
            prefix=prefix,
            gate_classification=False,
        )


def _validate_freshness(
    policy: Any, issues: list[dict[str, str]]
) -> None:
    if policy is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-GNSS-FRESH-001",
                "FRESHNESS_POLICY_MISSING",
                "freshness_policy",
                "A sourced freshness threshold is required.",
            )
        )
        return
    if not isinstance(policy, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-FRESH-002",
                "FRESHNESS_POLICY_INVALID",
                "freshness_policy",
                "freshness_policy must be an object.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            policy,
            _FRESHNESS_KEYS,
            "freshness_policy",
            "REP03-GNSS-FRESH-003",
            "UNKNOWN_FRESHNESS_POLICY_FIELD",
        )
    )
    value = policy.get("max_age_ms")
    if value is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-GNSS-FRESH-004",
                "FRESHNESS_THRESHOLD_UNRESOLVED",
                "freshness_policy.max_age_ms",
                "No default freshness threshold is inferred.",
            )
        )
    elif isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-FRESH-005",
                "FRESHNESS_THRESHOLD_INVALID",
                "freshness_policy.max_age_ms",
                "max_age_ms must be a positive integer.",
            )
        )
    _validate_source(
        policy.get("source"),
        "freshness_policy.source",
        issues,
        prefix="FRESHNESS",
        gate_classification=True,
    )


def _validate_position(
    position: Any, fix_quality: Any, issues: list[dict[str, str]]
) -> None:
    if fix_quality == "NO_FIX":
        if position is not None:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-GNSS-POS-001",
                    "POSITION_WITHOUT_FIX",
                    "observation.position",
                    "NO_FIX observations must not carry coordinates.",
                )
            )
        return
    if position is None:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-POS-002",
                "POSITION_MISSING_FOR_FIX",
                "observation.position",
                "Synthetic coordinates are required for a synthetic fix.",
            )
        )
        return
    if not isinstance(position, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-POS-003",
                "POSITION_INVALID",
                "observation.position",
                "position must be an object.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            position,
            _POSITION_KEYS,
            "observation.position",
            "REP03-GNSS-POS-004",
            "UNKNOWN_POSITION_FIELD",
        )
    )
    latitude = position.get("latitude_deg")
    longitude = position.get("longitude_deg")
    altitude = position.get("altitude_m")
    if (
        isinstance(latitude, bool)
        or not isinstance(latitude, (int, float))
        or not math.isfinite(latitude)
        or not -90 <= latitude <= 90
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-POS-005",
                "LATITUDE_INVALID",
                "observation.position.latitude_deg",
                "latitude_deg must be a finite number from -90 through 90.",
            )
        )
    if (
        isinstance(longitude, bool)
        or not isinstance(longitude, (int, float))
        or not math.isfinite(longitude)
        or not -180 <= longitude <= 180
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-POS-006",
                "LONGITUDE_INVALID",
                "observation.position.longitude_deg",
                "longitude_deg must be a finite number from -180 through 180.",
            )
        )
    if altitude is not None and (
        isinstance(altitude, bool)
        or not isinstance(altitude, (int, float))
        or not math.isfinite(altitude)
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-POS-007",
                "ALTITUDE_INVALID",
                "observation.position.altitude_m",
                "altitude_m must be null or a finite number.",
            )
        )
    if position.get("synthetic_data") is not True:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-SCOPE-003",
                "SYNTHETIC_POSITION_TAG_REQUIRED",
                "observation.position.synthetic_data",
                "Coordinates must be explicitly tagged as synthetic.",
            )
        )


def _validate_observation(
    observation: Any, issues: list[dict[str, str]]
) -> None:
    if observation is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-GNSS-OBS-001",
                "OBSERVATION_MISSING",
                "observation",
                "A synthetic observation is required.",
            )
        )
        return
    if not isinstance(observation, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-OBS-002",
                "OBSERVATION_INVALID",
                "observation",
                "observation must be an object.",
            )
        )
        return
    issues.extend(
        _unknown_fields(
            observation,
            _OBSERVATION_KEYS,
            "observation",
            "REP03-GNSS-OBS-003",
            "UNKNOWN_OBSERVATION_FIELD",
        )
    )
    fix_quality = observation.get("fix_quality")
    if not isinstance(fix_quality, str) or fix_quality not in FIX_QUALITIES:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-FIX-001",
                "FIX_QUALITY_INVALID",
                "observation.fix_quality",
                "fix_quality is outside the supported synthetic enumeration.",
            )
        )
    antenna_status = observation.get("antenna_status")
    if not isinstance(antenna_status, str) or antenna_status not in ANTENNA_STATUSES:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-ANT-001",
                "ANTENNA_STATUS_INVALID",
                "observation.antenna_status",
                "antenna_status is outside the supported synthetic enumeration.",
            )
        )
    for field in ("timestamp_ms", "evaluation_timestamp_ms", "age_ms"):
        value = observation.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-GNSS-TIME-001",
                    "TIMESTAMP_OR_AGE_INVALID",
                    f"observation.{field}",
                    f"{field} must be a non-negative integer.",
                )
            )
    previous = observation.get("previous_timestamp_ms")
    if previous is not None and (
        isinstance(previous, bool) or not isinstance(previous, int) or previous < 0
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-TIME-002",
                "PREVIOUS_TIMESTAMP_INVALID",
                "observation.previous_timestamp_ms",
                "previous_timestamp_ms must be null or a non-negative integer.",
            )
        )
    _validate_position(observation.get("position"), fix_quality, issues)
    _validate_source(
        observation.get("source"),
        "observation.source",
        issues,
        prefix="OBSERVATION",
        gate_classification=True,
    )


def _validate_scenario(scenario: Any) -> list[dict[str, str]]:
    if not isinstance(scenario, Mapping):
        return [
            _issue(
                "FAIL",
                "REP03-GNSS-SCHEMA-001",
                "SCENARIO_NOT_OBJECT",
                "$",
                "Scenario must be a JSON object.",
            )
        ]
    issues: list[dict[str, str]] = []
    forbidden = _find_forbidden_claims(scenario)
    if forbidden:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-SCOPE-001",
                "PHYSICAL_OR_RF_CLAIM_FORBIDDEN",
                forbidden[0],
                "Physical, measured or RF-suitability claims are forbidden inputs.",
            )
        )
    non_finite = _find_non_finite(scenario)
    if non_finite:
        issues.append(
            _issue(
                "FAIL",
                "REP03-GNSS-SCHEMA-002",
                "NON_FINITE_NUMBER",
                non_finite[0],
                "NaN and Infinity are not valid JSON scenario values.",
            )
        )
    issues.extend(
        _unknown_fields(
            scenario,
            _TOP_LEVEL_KEYS,
            "$",
            "REP03-GNSS-SCHEMA-003",
            "UNKNOWN_SCENARIO_FIELD",
        )
    )
    if scenario.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue("FAIL", "REP03-GNSS-SCHEMA-004", "SCHEMA_VERSION_MISMATCH", "schema_version", f"schema_version must equal {SCHEMA_VERSION!r}."))
    if not isinstance(scenario.get("scenario_id"), str) or not scenario["scenario_id"].strip():
        issues.append(_issue("FAIL", "REP03-GNSS-SCHEMA-005", "SCENARIO_ID_INVALID", "scenario_id", "scenario_id must be a non-empty string."))
    for field, expected, rule_id, reason in (
        ("engine_id", ENGINE_ID, "REP03-GNSS-GATE-001", "ENGINE_ID_INVALID"),
        ("module_id", MODULE_ID, "REP03-GNSS-GATE-002", "MODULE_ID_INVALID"),
        ("variant_id", VARIANT_ID, "REP03-GNSS-GATE-003", "VARIANT_A_REQUIRED"),
    ):
        if scenario.get(field) != expected:
            issues.append(_issue("FAIL", rule_id, reason, field, f"{field} must equal {expected!r}."))
    modules = scenario.get("enabled_modules")
    required_modules = {"can", "lin", "gnss"}
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        issues.append(_issue("FAIL", "REP03-GNSS-GATE-004", "ENABLED_MODULES_INVALID", "enabled_modules", "enabled_modules must be a string array."))
    else:
        declared = set(modules)
        if len(declared) != len(modules):
            issues.append(_issue("FAIL", "REP03-GNSS-GATE-005", "DUPLICATE_ENABLED_MODULE", "enabled_modules", "Duplicate modules are forbidden."))
        if "gnss" not in declared:
            issues.append(_issue("FAIL", "REP03-GNSS-GATE-006", "GNSS_MODULE_NOT_ENABLED", "enabled_modules", "GNSS must be enabled."))
        if declared != required_modules:
            reason = "FOREIGN_MODULE_ENABLED" if declared - required_modules else "VARIANT_A_MODULE_SET_MISMATCH"
            issues.append(_issue("FAIL", "REP03-GNSS-GATE-007", reason, "enabled_modules", "Variant A requires exactly can, lin and gnss."))
    if scenario.get("synthetic_data") is not True:
        issues.append(_issue("FAIL", "REP03-GNSS-SCOPE-004", "SYNTHETIC_DATA_REQUIRED", "synthetic_data", "Only explicitly synthetic scenarios are accepted."))
    gaps = scenario.get("known_gaps")
    if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
        issues.append(_issue("FAIL", "REP03-GNSS-GAP-001", "KNOWN_GAPS_INVALID", "known_gaps", "known_gaps must be a string array."))
    elif set(gaps) != {"GAP-02"} or len(gaps) != 1:
        issues.append(_issue("FAIL", "REP03-GNSS-GAP-002", "GAP_02_DECLARATION_REQUIRED", "known_gaps", "GNSS scenarios must declare only GAP-02."))
    _validate_source(scenario.get("source"), "source", issues, prefix="SCENARIO", gate_classification=True)
    _validate_variant_contract(scenario.get("variant_contract"), issues)
    _validate_module_profile(scenario.get("module_profile"), issues)
    _validate_freshness(scenario.get("freshness_policy"), issues)
    _validate_observation(scenario.get("observation"), issues)
    return issues


def _matrix_entry(source: Any, rule_suffix: str) -> dict[str, Any]:
    safe = _safe_source(source)
    if safe is None:
        return {
            "classification": "MISSING",
            "reference": None,
            "version": None,
            "status": "BLOCKED",
            "rule_id": f"REP03-GNSS-MATRIX-{rule_suffix}",
            "reason_code": "SOURCE_METADATA_UNRESOLVED",
        }
    status, reason = _source_status(safe["classification"])
    return {
        **safe,
        "status": status,
        "rule_id": f"REP03-GNSS-MATRIX-{rule_suffix}",
        "reason_code": reason,
    }


def _component_matrix_entry(
    profile: Mapping[Any, Any], name: str, rule_suffix: str
) -> dict[str, Any]:
    component = profile.get(name)
    source = component.get("source") if isinstance(component, Mapping) else None
    entry = _matrix_entry(source, rule_suffix)
    value = component.get("value") if isinstance(component, Mapping) else None
    if value is None or not isinstance(value, str) or not value.strip():
        entry["status"] = "BLOCKED"
        entry["reason_code"] = "COMPONENT_VALUE_UNRESOLVED"
    return entry


def _source_matrix(scenario: Any) -> dict[str, dict[str, Any]]:
    profile = scenario.get("module_profile") if isinstance(scenario, Mapping) else None
    observation = scenario.get("observation") if isinstance(scenario, Mapping) else None
    freshness = scenario.get("freshness_policy") if isinstance(scenario, Mapping) else None
    if not isinstance(profile, Mapping):
        profile = {}

    freshness_source = freshness.get("source") if isinstance(freshness, Mapping) else None
    observation_source = (
        observation.get("source") if isinstance(observation, Mapping) else None
    )
    return {
        "integration_guide": _matrix_entry(profile.get("integration_guide"), "001"),
        "module_variant": _component_matrix_entry(profile, "module_variant", "002"),
        "antenna_type": _component_matrix_entry(profile, "antenna_type", "003"),
        "rf_feed": _component_matrix_entry(profile, "rf_feed", "004"),
        "rf_layout_evidence": _matrix_entry(profile.get("rf_layout_evidence"), "005"),
        "power_profile": _component_matrix_entry(profile, "power_profile", "006"),
        "fix_quality": _matrix_entry(observation_source, "007"),
        "freshness": _matrix_entry(freshness_source, "008"),
        "timestamp": _matrix_entry(observation_source, "009"),
        "age": _matrix_entry(observation_source, "010"),
        "antenna_status": _matrix_entry(observation_source, "011"),
    }


def _safe_observation(observation: Any) -> dict[str, Any]:
    if not isinstance(observation, Mapping):
        return {
            "fix_quality": None,
            "timestamp_ms": None,
            "previous_timestamp_ms": None,
            "evaluation_timestamp_ms": None,
            "age_ms": None,
            "antenna_status": None,
            "position": None,
        }
    position = observation.get("position")
    safe_position = None
    if isinstance(position, Mapping):
        safe_position = {
            "latitude_deg": position.get("latitude_deg") if isinstance(position.get("latitude_deg"), (int, float)) and not isinstance(position.get("latitude_deg"), bool) and math.isfinite(position.get("latitude_deg")) else None,
            "longitude_deg": position.get("longitude_deg") if isinstance(position.get("longitude_deg"), (int, float)) and not isinstance(position.get("longitude_deg"), bool) and math.isfinite(position.get("longitude_deg")) else None,
            "altitude_m": position.get("altitude_m") if (position.get("altitude_m") is None or (isinstance(position.get("altitude_m"), (int, float)) and not isinstance(position.get("altitude_m"), bool) and math.isfinite(position.get("altitude_m")))) else None,
            "synthetic_data": True,
        }
    return {
        "fix_quality": observation.get("fix_quality") if isinstance(observation.get("fix_quality"), str) else None,
        "timestamp_ms": observation.get("timestamp_ms") if isinstance(observation.get("timestamp_ms"), int) and not isinstance(observation.get("timestamp_ms"), bool) else None,
        "previous_timestamp_ms": observation.get("previous_timestamp_ms") if (observation.get("previous_timestamp_ms") is None or (isinstance(observation.get("previous_timestamp_ms"), int) and not isinstance(observation.get("previous_timestamp_ms"), bool))) else None,
        "evaluation_timestamp_ms": observation.get("evaluation_timestamp_ms") if isinstance(observation.get("evaluation_timestamp_ms"), int) and not isinstance(observation.get("evaluation_timestamp_ms"), bool) else None,
        "age_ms": observation.get("age_ms") if isinstance(observation.get("age_ms"), int) and not isinstance(observation.get("age_ms"), bool) else None,
        "antenna_status": observation.get("antenna_status") if isinstance(observation.get("antenna_status"), str) else None,
        "position": safe_position,
    }


def _threshold_trace(policy: Any) -> dict[str, Any]:
    source = policy.get("source") if isinstance(policy, Mapping) else None
    safe = _safe_source(source)
    status, _ = _source_status(safe["classification"] if safe else None)
    value = policy.get("max_age_ms") if isinstance(policy, Mapping) else None
    return {
        "name": "max_age_ms",
        "value_ms": value if isinstance(value, int) and not isinstance(value, bool) else None,
        "classification": safe["classification"] if safe else "MISSING",
        "reference": safe["reference"] if safe else None,
        "version": safe["version"] if safe else None,
        "status": status,
    }


def _trace_row(
    scenario: Any,
    input_hash: str,
    status: str,
    rule_id: str,
    reason_code: str,
    event: str,
) -> dict[str, Any]:
    observation = scenario.get("observation") if isinstance(scenario, Mapping) else None
    safe_obs = _safe_observation(observation)
    source = observation.get("source") if isinstance(observation, Mapping) else None
    safe_source = _safe_source(source)
    policy = scenario.get("freshness_policy") if isinstance(scenario, Mapping) else None
    return {
        "event": event,
        "fix_quality": safe_obs["fix_quality"],
        "timestamp_ms": safe_obs["timestamp_ms"],
        "previous_timestamp_ms": safe_obs["previous_timestamp_ms"],
        "evaluation_timestamp_ms": safe_obs["evaluation_timestamp_ms"],
        "age_ms": safe_obs["age_ms"],
        "antenna_status": safe_obs["antenna_status"],
        "threshold_source": _threshold_trace(policy),
        "status": status,
        "rule_id": rule_id,
        "reason_code": reason_code,
        "input_hash": input_hash,
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "source_reference": safe_source["reference"] if safe_source else None,
        "source_version": safe_source["version"] if safe_source else None,
        "synthetic_data": True,
    }


def _safe_contract(contract: Any) -> dict[str, Any] | None:
    if not isinstance(contract, Mapping) or set(contract) != _CONTRACT_KEYS:
        return None
    source = _safe_source(contract.get("source"))
    if (
        contract.get("schema_version") != VARIANT_CONTRACT_SCHEMA
        or contract.get("profile_hash") != APPROVED_VARIANT_A_PROFILE_HASH
        or source is None
    ):
        return None
    return {
        "schema_version": VARIANT_CONTRACT_SCHEMA,
        "profile_hash": APPROVED_VARIANT_A_PROFILE_HASH,
        "source": source,
    }


def _build_report(
    scenario: Any,
    input_hash: str,
    status: str,
    rule_id: str,
    reason_code: str,
    issues: list[dict[str, str]],
    event: str,
) -> dict[str, Any]:
    matrix = _source_matrix(scenario)
    critical_gap_rows = (
        matrix["integration_guide"],
        matrix["module_variant"],
        matrix["antenna_type"],
        matrix["rf_feed"],
        matrix["rf_layout_evidence"],
    )
    gap_open = any(row["status"] != "PASS" for row in critical_gap_rows)
    profile = scenario.get("module_profile") if isinstance(scenario, Mapping) else None
    observation = scenario.get("observation") if isinstance(scenario, Mapping) else None
    freshness = scenario.get("freshness_policy") if isinstance(scenario, Mapping) else None
    source = scenario.get("source") if isinstance(scenario, Mapping) else None
    safe_scenario_source = _safe_source(source)
    safe_observation_source = _safe_source(
        observation.get("source") if isinstance(observation, Mapping) else None
    )
    safe_freshness_source = _safe_source(
        freshness.get("source") if isinstance(freshness, Mapping) else None
    )
    raw_scenario_id = scenario.get("scenario_id") if isinstance(scenario, Mapping) else None
    scenario_id = raw_scenario_id if isinstance(raw_scenario_id, str) and raw_scenario_id.strip() else None
    profile_id = profile.get("profile_id") if isinstance(profile, Mapping) and isinstance(profile.get("profile_id"), str) else None
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "engine_id": ENGINE_ID,
        "module_id": MODULE_ID,
        "variant_id": VARIANT_ID,
        "status": status,
        "result": {"status": status},
        "rule_id": rule_id,
        "reason_code": reason_code,
        "final_observation": _safe_observation(observation),
        "trace": [_trace_row(scenario, input_hash, status, rule_id, reason_code, event)],
        "issues": issues,
        "input_hash": input_hash,
        "tool_version": TOOL_VERSION,
        "synthetic_data": True,
        "source_versions": {
            "scenario_schema": SCHEMA_VERSION,
            "scenario_source_reference": safe_scenario_source["reference"] if safe_scenario_source else None,
            "scenario_source_version": safe_scenario_source["version"] if safe_scenario_source else None,
            "observation_source_reference": safe_observation_source["reference"] if safe_observation_source else None,
            "observation_source_version": safe_observation_source["version"] if safe_observation_source else None,
            "freshness_source_reference": safe_freshness_source["reference"] if safe_freshness_source else None,
            "freshness_source_version": safe_freshness_source["version"] if safe_freshness_source else None,
            "module_profile_id": profile_id,
            "variant_contract_schema": VARIANT_CONTRACT_SCHEMA,
            "variant_contract_profile_hash": APPROVED_VARIANT_A_PROFILE_HASH,
        },
        "variant_contract": _safe_contract(
            scenario.get("variant_contract") if isinstance(scenario, Mapping) else None
        ),
        "source_matrix": matrix,
        "dependencies": {
            "GAP-02": {
                "status": "BLOCKED" if gap_open else "UNKNOWN",
                "rule_id": "REP03-GNSS-GAP-002",
                "reason_code": "GAP_02_SOURCE_MATRIX_OPEN" if gap_open else "GAP_02_SOURCES_TRACEABLE_NOT_PHYSICALLY_VALIDATED",
            },
            "rf_suitability": {
                "status": "BLOCKED" if gap_open else "UNKNOWN",
                "rule_id": "REP03-GNSS-RF-001",
                "reason_code": "RF_SUITABILITY_BLOCKED_BY_GAP_02" if gap_open else "RF_SUITABILITY_NOT_PHYSICALLY_VALIDATED",
            },
            "physical_gnss": {
                "status": "UNKNOWN",
                "rule_id": "REP03-GNSS-CLAIM-001",
                "reason_code": "SYNTHETIC_FIX_NOT_PHYSICAL_GNSS_EVIDENCE",
            },
        },
        "known_limitations": [
            {
                "gap_id": "GAP-02",
                "status": "BLOCKED" if gap_open else "UNKNOWN",
                "rule_id": "REP03-GNSS-GAP-002",
                "reason_code": "GAP_02_SOURCE_MATRIX_OPEN" if gap_open else "PHYSICAL_RF_VALIDATION_NOT_RUN",
            }
        ],
        "claims": {
            "validation_level": "SYNTHETIC",
            "coordinate_scope": "SYNTHETIC_TEST_VECTOR",
            "coordinates_are_measured": False,
            "physical_gnss_validation": False,
            "rf_suitability_validated": False,
            "antenna_validation": False,
        },
    }


def run_scenario(scenario: Any) -> dict[str, Any]:
    """Validate one closed, synthetic Variant-A GNSS scenario."""

    input_hash = normalized_input_hash(scenario)
    issues = _validate_scenario(scenario)
    if issues:
        status, rule_id, reason_code = _dominant(issues)
        return _build_report(
            scenario,
            input_hash,
            status,
            rule_id,
            reason_code,
            issues,
            "preflight",
        )

    observation = scenario["observation"]
    policy = scenario["freshness_policy"]
    outcome: list[dict[str, str]] = []
    if observation["fix_quality"] == "NO_FIX":
        outcome.append(_issue("FAIL", "REP03-GNSS-FIX-002", "NO_FIX", "observation.fix_quality", "The synthetic receiver has no usable fix."))
    timestamp = observation["timestamp_ms"]
    previous = observation["previous_timestamp_ms"]
    evaluated = observation["evaluation_timestamp_ms"]
    age = observation["age_ms"]
    if previous is not None and timestamp < previous:
        outcome.append(_issue("FAIL", "REP03-GNSS-TIME-003", "TIMESTAMP_ROLLBACK", "observation.timestamp_ms", "Timestamp moved backwards relative to the preceding fix."))
    if evaluated < timestamp:
        outcome.append(_issue("FAIL", "REP03-GNSS-TIME-004", "EVALUATION_BEFORE_FIX", "observation.evaluation_timestamp_ms", "Evaluation time cannot precede the fix timestamp."))
    elif age != evaluated - timestamp:
        outcome.append(_issue("FAIL", "REP03-GNSS-TIME-005", "AGE_TIMESTAMP_MISMATCH", "observation.age_ms", "age_ms must equal evaluation_timestamp_ms minus timestamp_ms."))
    elif age > policy["max_age_ms"]:
        outcome.append(_issue("FAIL", "REP03-GNSS-FRESH-006", "STALE_FIX", "observation.age_ms", "Synthetic fix age exceeded the sourced freshness limit."))
    antenna_status = observation["antenna_status"]
    if antenna_status in {"OPEN", "SHORT"}:
        outcome.append(_issue("FAIL", "REP03-GNSS-ANT-002", "ANTENNA_FAULT", "observation.antenna_status", "Synthetic antenna status reports a fault."))
    elif antenna_status == "UNKNOWN":
        outcome.append(_issue("BLOCKED", "REP03-GNSS-ANT-003", "ANTENNA_STATUS_UNRESOLVED", "observation.antenna_status", "No antenna state is inferred from an UNKNOWN marker."))
    status, rule_id, reason_code = _dominant(outcome)
    return _build_report(
        scenario,
        input_hash,
        status,
        rule_id,
        reason_code,
        outcome,
        "validate-fix",
    )

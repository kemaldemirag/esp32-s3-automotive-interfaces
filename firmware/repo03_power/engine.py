"""Deterministic synthetic automotive-power profile engine for REP-03.

This module is a contract validator, not an electrical simulator.  It records
the versioned 12 V nominal-input and 5.1 V / 5 A output-target requirements,
classifies synthetic automotive input profiles, and validates a file-API
adapter envelope for REP-02.  It deliberately does not import or reproduce the
REP-02 rail-budget or sequencing engines.

Transient magnitudes and durations cannot support PASS unless their source is
a pinned OEM reference.  Exact-part and physical-threshold decisions remain
BLOCKED by GAP-03.  A PASS therefore means only that a synthetic contract is
well formed; it is never physical, regulatory, qualification, or compliance
evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import re
from typing import Any


SCHEMA_VERSION = "repo03.automotive-power.scenario.v1"
TOOL_VERSION = "repo03-power-engine/1.0.0"
ENGINE_ID = "repo03-power-engine"
MODULE_ID = "automotive_power"
VARIANT_ID = "B"
VARIANT_CONTRACT_SCHEMA = "repo03.variant.schema.v1"
APPROVED_VARIANT_B_PROFILE_HASH = (
    "1b82f114d7fb4280f55d3f72a7a61816f38242b7495a23cfa468f17b92d00fcd"
)

REP02_ADAPTER_SCHEMA_VERSION = "repo03.rep02.file-adapter.v1"
REP02_RAIL_BUDGET_SCHEMA_VERSION = "1.0.0"
REP02_RAIL_BUDGET_PACKAGE_VERSION = "0.3.0"
REP02_RAIL_BUDGET_FORMULA_VERSION = "REP02-RB-1.0.0"
REP02_RAIL_BUDGET_RULE_ID = "REP02.RAIL_BUDGET.STATIC"
REP02_RAIL_BUDGET_INPUT_FIELDS = (
    "schema_version",
    "rail",
    "loads",
    "capacity",
    "derating",
    "efficiency",
    "sources",
)
REP02_SEQUENCING_SCHEMA_VERSION = "1.0.0"
REP02_SEQUENCING_ENGINE_VERSION = "0.3.0"
REP02_SEQUENCING_FSM_VERSION = "REP02-SEQ-FSM-1.0.0"
REP02_SEQUENCING_RULE_SET_VERSION = "REP02-SEQ-RULESET-1.0.0"
REP02_SEQUENCING_INPUT_FIELDS = (
    "schema_version",
    "scenario_id",
    "scenario_kind",
    "timing_rules",
    "power_off_rule",
    "events",
    "sources",
    "observation_end_offset",
    "observation_end_at",
    "observation_provenance",
    "observation_source_refs",
    "sorting_policy",
    "simultaneous_policy",
)
REP02_SOURCE_REFERENCE = "power-rail-validation-and-review"
REP02_SOURCE_VERSION = "79ae5ba1a842cf2cc206eed408d71214ff2c43bc"

REQUIREMENT_SOURCE_REFERENCE = "REP-03-WF-03-05-REQUIREMENTS"
REQUIREMENT_SOURCE_VERSION = "1.0.0"

# GAP-03 is open.  A self-declared OEM label is not evidence; only references
# reviewed and pinned here may support a transient-profile contract PASS.
APPROVED_OEM_TRANSIENT_SOURCES: frozenset[tuple[str, str]] = frozenset()

PROFILE_TYPES = frozenset(
    {
        "nominal",
        "cold_crank",
        "load_dump_suppressed",
        "load_dump_unsuppressed",
        "jump_start",
        "brownout",
    }
)
TRANSIENT_PROFILE_TYPES = PROFILE_TYPES - {"nominal"}
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
SOURCE_AUTHORITIES = frozenset({"PROJECT_REQUIREMENT", "OEM", "ENGINEERING"})
RESULT_STATUSES = frozenset({"PASS", "FAIL", "UNKNOWN", "BLOCKED"})
_STATUS_PRIORITY = {"PASS": 0, "UNKNOWN": 1, "BLOCKED": 2, "FAIL": 3}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FLOATING_VERSIONS = frozenset(
    {"latest", "current", "main", "master", "head", "tbd", "unknown", "n/a"}
)

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
        "requirements",
        "rep02_adapter",
        "profile",
        "assessment_scope",
    }
)
_SOURCE_KEYS = frozenset({"classification", "authority", "reference", "version"})
_VARIANT_CONTRACT_KEYS = frozenset({"schema_version", "profile_hash", "source"})
_REQUIREMENTS_KEYS = frozenset(
    {"input_nominal_voltage", "output_target_voltage", "output_target_current"}
)
_QUANTITY_KEYS = frozenset({"value", "unit", "source"})
_PROFILE_KEYS = frozenset(
    {"profile_type", "input_voltage", "duration_ms", "suppression_state", "source"}
)
_ADAPTER_KEYS = frozenset(
    {
        "schema_version",
        "transport",
        "native_api",
        "source",
        "profile_hash",
        "rail_budget",
        "sequencing",
    }
)
_RAIL_ADAPTER_KEYS = frozenset(
    {
        "input_schema_version",
        "package_version",
        "formula_version",
        "rule_id",
        "input_fields",
        "units",
    }
)
_SEQ_ADAPTER_KEYS = frozenset(
    {
        "input_schema_version",
        "engine_version",
        "fsm_version",
        "rule_set_version",
        "input_fields",
        "units",
    }
)
_FORBIDDEN_CLAIM_KEYS = frozenset(
    {
        "measured",
        "measurement",
        "measured_value",
        "measured_voltage",
        "measured_current",
        "physical_pass",
        "hardware_pass",
        "exact_part",
        "part_number",
        "oem_compliance",
        "iso_compliance",
        "aec_qualification",
        "compliance_pass",
        "certified",
        "qualified",
    }
)

_GAP_03 = {
    "gap_id": "GAP-03",
    "status": "UNKNOWN",
    "rule_id": "REP03-POWER-GAP-003",
    "reason_code": "AUTOMOTIVE_POWER_EXACT_PART_AND_THRESHOLDS_UNRESOLVED",
    "description": (
        "Exact component selection, protection topology, OEM transient limits, "
        "and physical pass/fail thresholds have no approved evidence."
    ),
}


def _normalise_json(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalise_json(item, path + (str(key),))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        items = [_normalise_json(item, path + ("[]",)) for item in value]
        if path and path[-1] in {"enabled_modules", "known_gaps"}:
            return sorted(
                items,
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
        return items
    if isinstance(value, float) and not math.isfinite(value):
        return {"__non_finite_number__": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__unsupported_type__": type(value).__name__}


def normalized_input_hash(scenario: Any) -> str:
    """Return a deterministic SHA-256 for JSON-compatible scenario semantics."""

    payload = json.dumps(
        _normalise_json(scenario),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def rep02_adapter_profile_hash(adapter: Any) -> str:
    """Hash the adapter declaration, excluding its self-referential hash field."""

    if not isinstance(adapter, Mapping):
        return normalized_input_hash(adapter)
    content = {key: value for key, value in adapter.items() if key != "profile_hash"}
    return normalized_input_hash(content)


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


def _find_forbidden_claims(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            lowered = key_text.casefold()
            if lowered in _FORBIDDEN_CLAIM_KEYS or lowered.startswith("part_"):
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


def _validate_exact_keys(
    value: Any,
    expected: frozenset[str],
    path: str,
    issues: list[dict[str, str]],
    *,
    missing_status: str = "FAIL",
) -> bool:
    if not isinstance(value, Mapping):
        issues.append(
            _issue(
                missing_status,
                "REP03-POWER-SCHEMA-001",
                "OBJECT_REQUIRED",
                path,
                "A closed JSON object is required.",
            )
        )
        return False
    actual = set(value)
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-SCHEMA-002",
                "UNKNOWN_FIELD",
                path,
                "Unknown fields: " + ", ".join(sorted(map(str, unknown))),
            )
        )
    if missing:
        issues.append(
            _issue(
                missing_status,
                "REP03-POWER-SCHEMA-003",
                "REQUIRED_FIELD_MISSING",
                path,
                "Missing fields: " + ", ".join(sorted(missing)),
            )
        )
    return not unknown and not missing


def _safe_source(source: Any) -> dict[str, str] | None:
    if not isinstance(source, Mapping) or set(source) != _SOURCE_KEYS:
        return None
    if not all(isinstance(source.get(key), str) for key in _SOURCE_KEYS):
        return None
    if source.get("classification") not in SOURCE_CLASSIFICATIONS:
        return None
    if source.get("authority") not in SOURCE_AUTHORITIES:
        return None
    if not source.get("reference", "").strip() or not source.get("version", "").strip():
        return None
    return {key: source[key] for key in ("classification", "authority", "reference", "version")}


def _validate_source(
    source: Any,
    path: str,
    issues: list[dict[str, str]],
    *,
    allow_assumption: bool = True,
    required_authority: str | None = None,
) -> None:
    if source is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-SOURCE-001",
                "SOURCE_MISSING",
                path,
                "A pinned source record is required; no value was inferred.",
            )
        )
        return
    if not isinstance(source, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-SOURCE-002",
                "SOURCE_NOT_OBJECT",
                path,
                "Source metadata must be an object or explicit null.",
            )
        )
        return
    _validate_exact_keys(source, _SOURCE_KEYS, path, issues)
    classification = source.get("classification")
    authority = source.get("authority")
    reference = source.get("reference")
    version = source.get("version")
    if not isinstance(classification, str) or classification not in SOURCE_CLASSIFICATIONS:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-SOURCE-003",
                "SOURCE_CLASSIFICATION_INVALID",
                f"{path}.classification",
                "Source classification is outside the approved enumeration.",
            )
        )
    elif classification in {"UNKNOWN", "CONFLICT"}:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-SOURCE-004",
                "SOURCE_UNRESOLVED",
                path,
                "Unknown or conflicting evidence cannot support evaluation.",
            )
        )
    elif classification in {"ASSUMPTION", "DERIVED"}:
        issues.append(
            _issue(
                "UNKNOWN" if allow_assumption else "BLOCKED",
                "REP03-POWER-SOURCE-005",
                "SOURCE_ASSUMPTION",
                path,
                "Assumed or unverified derived evidence cannot support PASS.",
            )
        )
    if not isinstance(authority, str) or authority not in SOURCE_AUTHORITIES:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-SOURCE-006",
                "SOURCE_AUTHORITY_INVALID",
                f"{path}.authority",
                "Source authority is outside the approved enumeration.",
            )
        )
    elif required_authority is not None and authority != required_authority:
        issues.append(
            _issue(
                "UNKNOWN",
                "REP03-POWER-SOURCE-007",
                "OEM_PROFILE_SOURCE_REQUIRED",
                path,
                "This transient profile lacks a pinned OEM source/version.",
            )
        )
    if not isinstance(reference, str) or not reference.strip():
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-SOURCE-008",
                "SOURCE_REFERENCE_MISSING",
                f"{path}.reference",
                "A non-empty source reference is required.",
            )
        )
    if not isinstance(version, str) or not version.strip():
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-SOURCE-009",
                "SOURCE_VERSION_MISSING",
                f"{path}.version",
                "A pinned non-empty source version is required.",
            )
        )
    elif version.strip().casefold() in _FLOATING_VERSIONS:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-SOURCE-010",
                "SOURCE_VERSION_FLOATING",
                f"{path}.version",
                "Mutable or unresolved source versions are forbidden.",
            )
        )


def _validate_variant_contract(value: Any, issues: list[dict[str, str]]) -> None:
    if not _validate_exact_keys(
        value, _VARIANT_CONTRACT_KEYS, "variant_contract", issues, missing_status="BLOCKED"
    ):
        return
    if value.get("schema_version") != VARIANT_CONTRACT_SCHEMA:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-D1-001",
                "VARIANT_CONTRACT_SCHEMA_MISMATCH",
                "variant_contract.schema_version",
                f"Expected {VARIANT_CONTRACT_SCHEMA!r}.",
            )
        )
    if value.get("profile_hash") != APPROVED_VARIANT_B_PROFILE_HASH:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-D1-002",
                "VARIANT_B_PROFILE_HASH_MISMATCH",
                "variant_contract.profile_hash",
                "Scenario is not pinned to the approved complete Variant B profile.",
            )
        )
    _validate_source(value.get("source"), "variant_contract.source", issues)


def _validate_quantity_requirement(
    value: Any,
    path: str,
    expected_value: float,
    expected_unit: str,
    issues: list[dict[str, str]],
) -> None:
    if not _validate_exact_keys(value, _QUANTITY_KEYS, path, issues, missing_status="BLOCKED"):
        return
    raw_value = value.get("value")
    if (
        not isinstance(raw_value, (int, float))
        or isinstance(raw_value, bool)
        or not math.isfinite(float(raw_value))
        or float(raw_value) != expected_value
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-REQ-001",
                "REQUIREMENT_VALUE_MISMATCH",
                f"{path}.value",
                f"Expected the approved requirement value {expected_value}.",
            )
        )
    if value.get("unit") != expected_unit:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-REQ-002",
                "REQUIREMENT_UNIT_MISMATCH",
                f"{path}.unit",
                f"Expected explicit unit {expected_unit!r}.",
            )
        )
    source = value.get("source")
    _validate_source(
        source,
        f"{path}.source",
        issues,
        allow_assumption=False,
        required_authority="PROJECT_REQUIREMENT",
    )
    if isinstance(source, Mapping) and (
        source.get("classification") != "SOURCE_EXPLICIT"
        or source.get("reference") != REQUIREMENT_SOURCE_REFERENCE
        or source.get("version") != REQUIREMENT_SOURCE_VERSION
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-REQ-003",
                "REQUIREMENT_SOURCE_MISMATCH",
                f"{path}.source",
                "Requirement must be pinned to REP-03-WF-03-05-REQUIREMENTS v1.0.0.",
            )
        )


def _validate_requirements(value: Any, issues: list[dict[str, str]]) -> None:
    if not _validate_exact_keys(
        value, _REQUIREMENTS_KEYS, "requirements", issues, missing_status="BLOCKED"
    ):
        return
    _validate_quantity_requirement(
        value.get("input_nominal_voltage"),
        "requirements.input_nominal_voltage",
        12.0,
        "V",
        issues,
    )
    _validate_quantity_requirement(
        value.get("output_target_voltage"),
        "requirements.output_target_voltage",
        5.1,
        "V",
        issues,
    )
    _validate_quantity_requirement(
        value.get("output_target_current"),
        "requirements.output_target_current",
        5.0,
        "A",
        issues,
    )


def _validate_rep02_adapter(value: Any, issues: list[dict[str, str]]) -> None:
    if not _validate_exact_keys(
        value, _ADAPTER_KEYS, "rep02_adapter", issues, missing_status="BLOCKED"
    ):
        return
    mismatch = False
    if value.get("schema_version") != REP02_ADAPTER_SCHEMA_VERSION:
        mismatch = True
    if value.get("transport") != "FILE_API":
        mismatch = True
    if value.get("native_api") != "JSON_COMPATIBLE_MAPPING":
        mismatch = True
    rail = value.get("rail_budget")
    if not _validate_exact_keys(
        rail, _RAIL_ADAPTER_KEYS, "rep02_adapter.rail_budget", issues, missing_status="BLOCKED"
    ):
        mismatch = True
    elif (
        rail.get("input_schema_version") != REP02_RAIL_BUDGET_SCHEMA_VERSION
        or rail.get("package_version") != REP02_RAIL_BUDGET_PACKAGE_VERSION
        or rail.get("formula_version") != REP02_RAIL_BUDGET_FORMULA_VERSION
        or rail.get("rule_id") != REP02_RAIL_BUDGET_RULE_ID
        or rail.get("input_fields") != list(REP02_RAIL_BUDGET_INPUT_FIELDS)
        or rail.get("units")
        != {"voltage": "V", "current": "A", "factor": "1", "power": "W"}
    ):
        mismatch = True
    sequence = value.get("sequencing")
    if not _validate_exact_keys(
        sequence,
        _SEQ_ADAPTER_KEYS,
        "rep02_adapter.sequencing",
        issues,
        missing_status="BLOCKED",
    ):
        mismatch = True
    elif (
        sequence.get("input_schema_version") != REP02_SEQUENCING_SCHEMA_VERSION
        or sequence.get("engine_version") != REP02_SEQUENCING_ENGINE_VERSION
        or sequence.get("fsm_version") != REP02_SEQUENCING_FSM_VERSION
        or sequence.get("rule_set_version") != REP02_SEQUENCING_RULE_SET_VERSION
        or sequence.get("input_fields") != list(REP02_SEQUENCING_INPUT_FIELDS)
        or sequence.get("units") != {"time": "s"}
    ):
        mismatch = True
    if mismatch:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-REP02-001",
                "REP02_ADAPTER_VERSION_MISMATCH",
                "rep02_adapter",
                "REP-02 file-API versions, rules, or units are incompatible; no engine call was made.",
            )
        )
    adapter_source = value.get("source")
    _validate_source(adapter_source, "rep02_adapter.source", issues, allow_assumption=False)
    if isinstance(adapter_source, Mapping) and (
        adapter_source.get("classification") != "SOURCE_EXPLICIT"
        or adapter_source.get("authority") != "ENGINEERING"
        or adapter_source.get("reference") != REP02_SOURCE_REFERENCE
        or adapter_source.get("version") != REP02_SOURCE_VERSION
    ):
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-REP02-005",
                "REP02_ADAPTER_SOURCE_MISMATCH",
                "rep02_adapter.source",
                "Adapter must be pinned to power-rail-validation-and-review commit "
                "79ae5ba1a842cf2cc206eed408d71214ff2c43bc.",
            )
        )
    declared_hash = value.get("profile_hash")
    calculated_hash = rep02_adapter_profile_hash(value)
    if not isinstance(declared_hash, str) or _SHA256_RE.fullmatch(declared_hash) is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-REP02-002",
                "REP02_ADAPTER_PROFILE_HASH_INVALID",
                "rep02_adapter.profile_hash",
                "Adapter profile_hash must be a lowercase SHA-256 digest.",
            )
        )
    elif declared_hash != calculated_hash:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-REP02-003",
                "REP02_ADAPTER_PROFILE_HASH_MISMATCH",
                "rep02_adapter.profile_hash",
                "Adapter declaration does not match its canonical profile hash.",
            )
        )


def _validate_profile(
    value: Any,
    assessment_scope: Any,
    issues: list[dict[str, str]],
) -> None:
    if not _validate_exact_keys(value, _PROFILE_KEYS, "profile", issues, missing_status="BLOCKED"):
        return
    profile_type = value.get("profile_type")
    if not isinstance(profile_type, str) or profile_type not in PROFILE_TYPES:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-PROFILE-001",
                "PROFILE_TYPE_INVALID",
                "profile.profile_type",
                "Profile type is outside the approved profile set.",
            )
        )
        return
    input_voltage = value.get("input_voltage")
    if (
        not isinstance(input_voltage, (int, float))
        or isinstance(input_voltage, bool)
        or not math.isfinite(float(input_voltage))
        or float(input_voltage) < 0
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-PROFILE-002",
                "PROFILE_AMPLITUDE_INVALID",
                "profile.input_voltage",
                "Synthetic input voltage must be a finite non-negative number in volts.",
            )
        )
    duration = value.get("duration_ms")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(float(duration))
        or float(duration) < 0
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-PROFILE-003",
                "PROFILE_DURATION_INVALID",
                "profile.duration_ms",
                "Synthetic duration must be a finite non-negative number in milliseconds.",
            )
        )
    expected_suppression = {
        "load_dump_suppressed": "SUPPRESSED",
        "load_dump_unsuppressed": "UNSUPPRESSED",
    }.get(profile_type, "NOT_APPLICABLE")
    if value.get("suppression_state") != expected_suppression:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-PROFILE-004",
                "SUPPRESSION_STATE_MISMATCH",
                "profile.suppression_state",
                f"Profile {profile_type!r} requires {expected_suppression!r}.",
            )
        )
    source = value.get("source")
    if profile_type == "nominal":
        _validate_source(source, "profile.source", issues, allow_assumption=False)
        if isinstance(source, Mapping) and (
            source.get("classification") != "SOURCE_EXPLICIT"
            or source.get("authority") != "PROJECT_REQUIREMENT"
            or source.get("reference") != REQUIREMENT_SOURCE_REFERENCE
            or source.get("version") != REQUIREMENT_SOURCE_VERSION
        ):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-POWER-PROFILE-006",
                    "NOMINAL_PROFILE_SOURCE_MISMATCH",
                    "profile.source",
                    "Nominal profile must use the pinned 12 V project requirement source.",
                )
            )
        if isinstance(input_voltage, (int, float)) and not isinstance(input_voltage, bool):
            if math.isfinite(float(input_voltage)) and float(input_voltage) != 12.0:
                issues.append(
                    _issue(
                        "FAIL",
                        "REP03-POWER-PROFILE-005",
                        "NOMINAL_INPUT_REQUIREMENT_MISMATCH",
                        "profile.input_voltage",
                        "Nominal profile must use the approved 12 V requirement.",
                    )
                )
    else:
        _validate_source(
            source,
            "profile.source",
            issues,
            allow_assumption=True,
            required_authority="OEM",
        )
        if (
            isinstance(source, Mapping)
            and source.get("classification") != "SOURCE_EXPLICIT"
        ):
            issues.append(
                _issue(
                    "UNKNOWN",
                    "REP03-POWER-PROFILE-007",
                    "OEM_PROFILE_SOURCE_REQUIRED",
                    "profile.source",
                    "Transient profiles require SOURCE_EXPLICIT OEM evidence; "
                    "an engineering rule cannot support PASS.",
                )
            )
        if (
            isinstance(source, Mapping)
            and source.get("classification") == "SOURCE_EXPLICIT"
            and source.get("authority") == "OEM"
            and isinstance(source.get("reference"), str)
            and isinstance(source.get("version"), str)
            and (source["reference"], source["version"])
            not in APPROVED_OEM_TRANSIENT_SOURCES
        ):
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-POWER-PROFILE-008",
                    "OEM_PROFILE_SOURCE_NOT_APPROVED",
                    "profile.source",
                    "The OEM source label is not present in the reviewed, pinned "
                    "GAP-03 source set; self-declaration cannot support PASS.",
                )
            )
    if assessment_scope == "EXACT_PART_OR_PHYSICAL_THRESHOLD":
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-POWER-GAP-004",
                "EXACT_PART_OR_PHYSICAL_THRESHOLD_BLOCKED",
                "assessment_scope",
                "GAP-03 blocks exact-part and real hardware threshold decisions.",
            )
        )


def _validate_scenario(scenario: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not isinstance(scenario, Mapping):
        return [
            _issue(
                "FAIL",
                "REP03-POWER-SCHEMA-000",
                "SCENARIO_NOT_OBJECT",
                "$",
                "Scenario must be a JSON object.",
            )
        ]
    forbidden = _find_forbidden_claims(scenario)
    if forbidden:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-CLAIM-001",
                "PHYSICAL_OR_COMPLIANCE_CLAIM_FORBIDDEN",
                forbidden[0],
                "Physical, measured, exact-part, qualification, or compliance claims are forbidden.",
            )
        )
    non_finite = _find_non_finite(scenario)
    if non_finite:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-SCHEMA-004",
                "NON_FINITE_NUMBER",
                non_finite[0],
                "NaN and Infinity are not JSON scenario numbers.",
            )
        )
    _validate_exact_keys(scenario, _TOP_LEVEL_KEYS, "$", issues)
    for field, expected, rule_id, reason_code in (
        ("schema_version", SCHEMA_VERSION, "REP03-POWER-GATE-001", "SCHEMA_VERSION_MISMATCH"),
        ("engine_id", ENGINE_ID, "REP03-POWER-GATE-002", "ENGINE_ID_MISMATCH"),
        ("module_id", MODULE_ID, "REP03-POWER-GATE-003", "POWER_MODULE_REQUIRED"),
        ("variant_id", VARIANT_ID, "REP03-POWER-GATE-004", "VARIANT_B_REQUIRED"),
    ):
        if scenario.get(field) != expected:
            issues.append(
                _issue("FAIL", rule_id, reason_code, field, f"{field} must equal {expected!r}.")
            )
    scenario_id = scenario.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-SCHEMA-005",
                "SCENARIO_ID_INVALID",
                "scenario_id",
                "scenario_id must be a non-empty string.",
            )
        )
    modules = scenario.get("enabled_modules")
    if (
        not isinstance(modules, list)
        or not all(isinstance(item, str) for item in modules)
        or len(modules) != 2
        or set(modules) != {"automotive_power", "shutdown"}
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-GATE-005",
                "VARIANT_B_MODULE_SET_INVALID",
                "enabled_modules",
                "Variant B requires exactly automotive_power and shutdown.",
            )
        )
    if scenario.get("synthetic_data") is not True:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-CLAIM-002",
                "SYNTHETIC_DATA_REQUIRED",
                "synthetic_data",
                "Only explicitly synthetic scenarios are accepted.",
            )
        )
    known_gaps = scenario.get("known_gaps")
    if not isinstance(known_gaps, list) or known_gaps != ["GAP-03"]:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-GAP-001",
                "GAP_03_DECLARATION_REQUIRED",
                "known_gaps",
                "known_gaps must contain exactly GAP-03.",
            )
        )
    assessment_scope = scenario.get("assessment_scope")
    if assessment_scope not in {
        "SYNTHETIC_REQUIREMENT_ONLY",
        "EXACT_PART_OR_PHYSICAL_THRESHOLD",
    }:
        issues.append(
            _issue(
                "FAIL",
                "REP03-POWER-CLAIM-003",
                "ASSESSMENT_SCOPE_INVALID",
                "assessment_scope",
                "Assessment scope is outside the closed enumeration.",
            )
        )
    _validate_source(scenario.get("source"), "source", issues, allow_assumption=False)
    _validate_variant_contract(scenario.get("variant_contract"), issues)
    _validate_requirements(scenario.get("requirements"), issues)
    _validate_rep02_adapter(scenario.get("rep02_adapter"), issues)
    _validate_profile(scenario.get("profile"), assessment_scope, issues)
    return issues


def _dominant(issues: list[dict[str, str]]) -> tuple[str, str, str]:
    if not issues:
        return "PASS", "REP03-POWER-PROFILE-000", "SYNTHETIC_PROFILE_CONTRACT_ACCEPTED"
    dominant = max(issues, key=lambda item: _STATUS_PRIORITY[item["status"]])
    return dominant["status"], dominant["rule_id"], dominant["reason_code"]


def _profile_assessment(scenario: Any, status: str) -> dict[str, Any]:
    profile = scenario.get("profile") if isinstance(scenario, Mapping) else None
    if not isinstance(profile, Mapping):
        profile = {}
    source = _safe_source(profile.get("source"))
    profile_type = profile.get("profile_type")
    input_voltage = profile.get("input_voltage")
    duration = profile.get("duration_ms")
    suppression = profile.get("suppression_state")
    return {
        "status": status,
        "profile_type": profile_type if profile_type in PROFILE_TYPES else None,
        "input_voltage": (
            float(input_voltage)
            if isinstance(input_voltage, (int, float))
            and not isinstance(input_voltage, bool)
            and math.isfinite(float(input_voltage))
            else None
        ),
        "input_voltage_unit": "V",
        "duration_ms": (
            float(duration)
            if isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(float(duration))
            else None
        ),
        "suppression_state": (
            suppression
            if suppression in {"NOT_APPLICABLE", "SUPPRESSED", "UNSUPPRESSED"}
            else None
        ),
        "source": source,
    }


def _rep02_dependency(scenario: Any) -> dict[str, Any]:
    adapter = scenario.get("rep02_adapter") if isinstance(scenario, Mapping) else None
    if not isinstance(adapter, Mapping):
        return {
            "status": "BLOCKED",
            "rule_id": "REP03-POWER-REP02-004",
            "reason_code": "REP02_ADAPTER_MISSING",
            "integration_status": "BLOCKED",
            "integration_reason_code": "LIVE_REP02_INTEGRATION_NOT_AUTHORIZED",
            "execution_status": "NOT_RUN",
            "execution_reason_code": "REP02_ENGINE_NOT_EXECUTED",
            "schema_version": None,
            "profile_hash": None,
            "source_reference": None,
            "source_version": None,
            "package_version": None,
            "rail_budget_input_schema_version": None,
            "rail_budget_formula_version": None,
            "rail_budget_rule_id": None,
            "sequencing_input_schema_version": None,
            "sequencing_engine_version": None,
            "sequencing_fsm_version": None,
            "sequencing_rule_set_version": None,
        }
    rail = adapter.get("rail_budget")
    sequence = adapter.get("sequencing")
    source = adapter.get("source")
    valid = (
        set(adapter) == _ADAPTER_KEYS
        and adapter.get("schema_version") == REP02_ADAPTER_SCHEMA_VERSION
        and adapter.get("profile_hash") == rep02_adapter_profile_hash(adapter)
        and adapter.get("transport") == "FILE_API"
        and adapter.get("native_api") == "JSON_COMPATIBLE_MAPPING"
        and isinstance(source, Mapping)
        and set(source) == _SOURCE_KEYS
        and source.get("classification") == "SOURCE_EXPLICIT"
        and source.get("authority") == "ENGINEERING"
        and source.get("reference") == REP02_SOURCE_REFERENCE
        and source.get("version") == REP02_SOURCE_VERSION
        and isinstance(rail, Mapping)
        and set(rail) == _RAIL_ADAPTER_KEYS
        and rail.get("input_schema_version") == REP02_RAIL_BUDGET_SCHEMA_VERSION
        and rail.get("package_version") == REP02_RAIL_BUDGET_PACKAGE_VERSION
        and rail.get("formula_version") == REP02_RAIL_BUDGET_FORMULA_VERSION
        and rail.get("rule_id") == REP02_RAIL_BUDGET_RULE_ID
        and rail.get("input_fields") == list(REP02_RAIL_BUDGET_INPUT_FIELDS)
        and rail.get("units")
        == {"voltage": "V", "current": "A", "factor": "1", "power": "W"}
        and isinstance(sequence, Mapping)
        and set(sequence) == _SEQ_ADAPTER_KEYS
        and sequence.get("input_schema_version") == REP02_SEQUENCING_SCHEMA_VERSION
        and sequence.get("engine_version") == REP02_SEQUENCING_ENGINE_VERSION
        and sequence.get("fsm_version") == REP02_SEQUENCING_FSM_VERSION
        and sequence.get("rule_set_version") == REP02_SEQUENCING_RULE_SET_VERSION
        and sequence.get("input_fields") == list(REP02_SEQUENCING_INPUT_FIELDS)
        and sequence.get("units") == {"time": "s"}
    )
    return {
        "status": "PASS" if valid else "BLOCKED",
        "rule_id": "REP03-POWER-REP02-000" if valid else "REP03-POWER-REP02-001",
        "reason_code": (
            "REP02_FILE_API_ADAPTER_COMPATIBLE"
            if valid
            else "REP02_ADAPTER_VERSION_MISMATCH"
        ),
        "integration_status": "BLOCKED",
        "integration_reason_code": "LIVE_REP02_INTEGRATION_NOT_AUTHORIZED",
        "execution_status": "NOT_RUN",
        "execution_reason_code": "REP02_ENGINE_NOT_EXECUTED",
        "schema_version": (
            adapter.get("schema_version")
            if isinstance(adapter.get("schema_version"), str)
            else None
        ),
        "profile_hash": (
            adapter.get("profile_hash")
            if isinstance(adapter.get("profile_hash"), str)
            and _SHA256_RE.fullmatch(adapter["profile_hash"])
            else None
        ),
        "source_reference": (
            source.get("reference")
            if isinstance(source, Mapping) and isinstance(source.get("reference"), str)
            else None
        ),
        "source_version": (
            source.get("version")
            if isinstance(source, Mapping) and isinstance(source.get("version"), str)
            else None
        ),
        "package_version": (
            rail.get("package_version")
            if isinstance(rail, Mapping) and isinstance(rail.get("package_version"), str)
            else None
        ),
        "rail_budget_input_schema_version": (
            rail.get("input_schema_version")
            if isinstance(rail, Mapping)
            and isinstance(rail.get("input_schema_version"), str)
            else None
        ),
        "rail_budget_formula_version": (
            rail.get("formula_version")
            if isinstance(rail, Mapping) and isinstance(rail.get("formula_version"), str)
            else None
        ),
        "rail_budget_rule_id": (
            rail.get("rule_id")
            if isinstance(rail, Mapping) and isinstance(rail.get("rule_id"), str)
            else None
        ),
        "sequencing_input_schema_version": (
            sequence.get("input_schema_version")
            if isinstance(sequence, Mapping)
            and isinstance(sequence.get("input_schema_version"), str)
            else None
        ),
        "sequencing_engine_version": (
            sequence.get("engine_version")
            if isinstance(sequence, Mapping)
            and isinstance(sequence.get("engine_version"), str)
            else None
        ),
        "sequencing_fsm_version": (
            sequence.get("fsm_version")
            if isinstance(sequence, Mapping) and isinstance(sequence.get("fsm_version"), str)
            else None
        ),
        "sequencing_rule_set_version": (
            sequence.get("rule_set_version")
            if isinstance(sequence, Mapping)
            and isinstance(sequence.get("rule_set_version"), str)
            else None
        ),
    }


def _mapping_row(
    source_path: str,
    target_path: str | None,
    disposition: str,
    reason_code: str,
    value: float | str | None,
    unit: str | None,
) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "target_path": target_path,
        "disposition": disposition,
        "rule_id": "REP03-POWER-REP02-MAP-001",
        "reason_code": reason_code,
        "value": value,
        "unit": unit,
    }


def _rep02_adapter_mapping(
    scenario: Any,
    dependency: Mapping[str, Any],
) -> dict[str, Any]:
    profile = scenario.get("profile") if isinstance(scenario, Mapping) else None
    if not isinstance(profile, Mapping):
        profile = {}
    profile_type = profile.get("profile_type")
    if profile_type not in PROFILE_TYPES:
        profile_type = None
    adapter_compatible = dependency.get("status") == "PASS"
    is_transient = profile_type in TRANSIENT_PROFILE_TYPES
    if not adapter_compatible:
        rail_reason = "REP02_ADAPTER_INCOMPATIBLE"
        sequence_reason = "REP02_ADAPTER_INCOMPATIBLE"
    elif is_transient:
        rail_reason = "REP02_STATIC_RAIL_BUDGET_DOES_NOT_MODEL_TRANSIENT_PROFILE"
        sequence_reason = "REP02_SEQUENCING_PROFILE_KIND_UNSUPPORTED"
    else:
        rail_reason = "REP02_RAIL_BUDGET_INPUT_INCOMPLETE"
        sequence_reason = "REP02_SEQUENCING_NOT_APPLICABLE_TO_STATIC_NOMINAL_PROFILE"

    profile_voltage = profile.get("input_voltage")
    if not (
        isinstance(profile_voltage, (int, float))
        and not isinstance(profile_voltage, bool)
        and math.isfinite(float(profile_voltage))
    ):
        profile_voltage = None
    else:
        profile_voltage = float(profile_voltage)
    duration = profile.get("duration_ms")
    if not (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(float(duration))
    ):
        duration = None
    else:
        duration = float(duration)

    rail_mapping = [
        _mapping_row(
            "requirements.input_nominal_voltage",
            None,
            "UNSUPPORTED",
            "REP02_RAIL_BUDGET_HAS_NO_UPSTREAM_AUTOMOTIVE_INPUT_FIELD",
            12.0,
            "V",
        ),
        _mapping_row(
            "requirements.output_target_voltage",
            "rail.nominal_voltage",
            "MAPPED_REQUIREMENT",
            "OUTPUT_TARGET_MAPS_TO_STATIC_RAIL_NOMINAL_VOLTAGE",
            5.1,
            "V",
        ),
        _mapping_row(
            "requirements.output_target_current",
            None,
            "UNRESOLVED",
            "OUTPUT_TARGET_IS_NOT_A_VERIFIED_COMPONENT_RATING_OR_LOAD_BUDGET",
            5.0,
            "A",
        ),
        _mapping_row(
            "profile.input_voltage",
            None,
            "UNSUPPORTED" if is_transient else "NOT_APPLICABLE",
            (
                "REP02_RAIL_BUDGET_DOES_NOT_MODEL_AUTOMOTIVE_TRANSIENT_AMPLITUDE"
                if is_transient
                else "NOMINAL_UPSTREAM_INPUT_NOT_USED_BY_STATIC_OUTPUT_RAIL_BUDGET"
            ),
            profile_voltage,
            "V",
        ),
        _mapping_row(
            "profile.duration_ms",
            None,
            "UNSUPPORTED" if is_transient else "NOT_APPLICABLE",
            (
                "REP02_RAIL_BUDGET_DOES_NOT_MODEL_TRANSIENT_DURATION"
                if is_transient
                else "STATIC_NOMINAL_PROFILE_HAS_NO_DURATION_MAPPING"
            ),
            duration,
            "ms",
        ),
        _mapping_row(
            "profile.suppression_state",
            None,
            "UNSUPPORTED",
            "REP02_RAIL_BUDGET_HAS_NO_TRANSIENT_SUPPRESSION_FIELD",
            (
                profile.get("suppression_state")
                if isinstance(profile.get("suppression_state"), str)
                else None
            ),
            None,
        ),
        _mapping_row(
            "profile.source",
            None,
            "UNSUPPORTED",
            "PROFILE_SOURCE_REQUIRES_EXPLICIT_REP02_SOURCE_RECORD_TRANSFORMATION",
            None,
            None,
        ),
    ]
    sequencing_mapping = [
        _mapping_row(
            "profile.profile_type",
            "scenario_kind",
            "UNSUPPORTED",
            (
                "AUTOMOTIVE_TRANSIENT_IS_NOT_REP02_STARTUP_OR_POWER_OFF"
                if is_transient
                else "STATIC_NOMINAL_PROFILE_IS_NOT_REP02_STARTUP_OR_POWER_OFF"
            ),
            profile_type,
            None,
        ),
        _mapping_row(
            "profile.suppression_state",
            None,
            "UNSUPPORTED",
            "REP02_SEQUENCING_HAS_NO_AUTOMOTIVE_SUPPRESSION_STATE",
            (
                profile.get("suppression_state")
                if isinstance(profile.get("suppression_state"), str)
                else None
            ),
            None,
        ),
        _mapping_row(
            "profile.source",
            None,
            "UNSUPPORTED",
            "PROFILE_SOURCE_CANNOT_BECOME_A_SEQUENCE_SOURCE_WITHOUT_A_SEQUENCE_RULE",
            None,
            None,
        ),
    ]
    return {
        "profile_type": profile_type,
        "rail_budget": {
            "disposition": "BLOCKED",
            "rule_id": "REP03-POWER-REP02-MAP-RAIL-001",
            "reason_code": rail_reason,
            "target_schema_version": REP02_RAIL_BUDGET_SCHEMA_VERSION,
            "mapping": rail_mapping,
            "unresolved_required_fields": [
                "rail.rail_id",
                "rail.voltage_limits",
                "rail.provenance",
                "rail.source_refs",
                "loads",
                "capacity.regulator_id",
                "capacity.rail_id",
                "capacity.rated_current",
                "capacity.current_limit",
                "capacity.provenance",
                "capacity.source_refs",
                "derating.factor",
                "derating.provenance",
                "derating.source_refs",
                "sources",
            ],
            "rail_budget_input": None,
        },
        "sequencing": {
            "disposition": "NOT_RUN",
            "rule_id": "REP03-POWER-REP02-MAP-SEQ-001",
            "reason_code": sequence_reason,
            "target_schema_version": REP02_SEQUENCING_SCHEMA_VERSION,
            "supported_scenario_kinds": ["STARTUP", "POWER_OFF"],
            "selected_scenario_kind": None,
            "mapping": sequencing_mapping,
            "sequencing_input": None,
        },
    }


def run_scenario(scenario: Any) -> dict[str, Any]:
    """Validate one synthetic automotive-power scenario and return JSON data."""

    input_hash = normalized_input_hash(scenario)
    issues = _validate_scenario(scenario)
    status, rule_id, reason_code = _dominant(issues)
    scenario_id = scenario.get("scenario_id") if isinstance(scenario, Mapping) else None
    if not isinstance(scenario_id, str):
        scenario_id = None
    variant_id = scenario.get("variant_id") if isinstance(scenario, Mapping) else None
    if not isinstance(variant_id, str):
        variant_id = None
    scenario_source = _safe_source(scenario.get("source")) if isinstance(scenario, Mapping) else None
    contract = scenario.get("variant_contract") if isinstance(scenario, Mapping) else None
    contract_source = (
        _safe_source(contract.get("source")) if isinstance(contract, Mapping) else None
    )
    rep02_dependency = _rep02_dependency(scenario)
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "engine_id": ENGINE_ID,
        "module_id": MODULE_ID,
        "variant_id": variant_id,
        "status": status,
        "result": {"status": status},
        "rule_id": rule_id,
        "reason_code": reason_code,
        "input_hash": input_hash,
        "tool_version": TOOL_VERSION,
        "synthetic_data": True,
        "profile_assessment": _profile_assessment(scenario, status),
        "requirements": {
            "input_nominal_voltage": {"value": 12.0, "unit": "V"},
            "output_target_voltage": {"value": 5.1, "unit": "V"},
            "output_target_current": {"value": 5.0, "unit": "A"},
            "source_reference": REQUIREMENT_SOURCE_REFERENCE,
            "source_version": REQUIREMENT_SOURCE_VERSION,
        },
        "source_versions": {
            "scenario_source": scenario_source,
            "variant_contract_source": contract_source,
            "variant_contract_schema": (
                contract.get("schema_version")
                if isinstance(contract, Mapping)
                and isinstance(contract.get("schema_version"), str)
                else None
            ),
            "variant_contract_profile_hash": (
                contract.get("profile_hash")
                if isinstance(contract, Mapping)
                and isinstance(contract.get("profile_hash"), str)
                and _SHA256_RE.fullmatch(contract["profile_hash"])
                else None
            ),
        },
        "adapter_mapping": _rep02_adapter_mapping(scenario, rep02_dependency),
        "dependencies": {
            "GAP-03": dict(_GAP_03),
            "rep02": rep02_dependency,
        },
        "issues": issues,
        "claims": {
            "validation_level": "SYNTHETIC",
            "physical_validation": False,
            "exact_part_decision": False,
            "oem_compliance": False,
            "iso_compliance": False,
            "aec_qualification": False,
            "rep02_execution": False,
        },
    }

"""Deterministic synthetic CAN/TWAI event engine for REP-03 Variant A.

The model keeps the ESP32-S3 TWAI/controller state, the external-transceiver
state, and a synthetic bus-observation marker separate.  It is not a physical
bus model and provides no ISO, AEC, exact-part, voltage, or measured-result
claim.  External-transceiver power-off behaviour stays BLOCKED by GAP-01 until
an approved source is supplied.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import re
from typing import Any


SCHEMA_VERSION = "repo03.can.scenario.v1"
TOOL_VERSION = "repo03-can-engine/1.0.0"
ENGINE_ID = "repo03_can"
VARIANT_ID = "A"
MODULE_ID = "can"
VARIANT_CONTRACT_SCHEMA = "repo03.variant.schema.v1"
APPROVED_VARIANT_A_PROFILE_HASH = (
    "f74c42bb2a2519ab563a91cb05cfb6d4e5accd9d6f2570ed89604bbad5e0367e"
)

CONTROLLER_STATES = frozenset(
    {"ERROR_ACTIVE", "ERROR_WARNING", "ERROR_PASSIVE", "BUS_OFF", "RECOVERY_PENDING"}
)
TRANSCEIVER_STATES = frozenset({"SYNTHETIC_ON", "SYNTHETIC_OFF", "UNKNOWN"})
BUS_OBSERVATIONS = frozenset(
    {"NO_SYNTHETIC_OBSERVATION", "SYNTHETIC_FRAME_OBSERVED", "UNKNOWN"}
)
EVENT_TYPES = frozenset(
    {
        "NORMAL_FRAME",
        "ERROR_COUNTER_UPDATE",
        "BUS_OFF",
        "RECOVERY_REQUEST",
        "RECOVERY_COMPLETE",
        "RECOVERY_TIMEOUT",
        "TRANSCEIVER_OFF",
    }
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

_STATUS_PRIORITY = {"PASS": 0, "UNKNOWN": 1, "BLOCKED": 2, "FAIL": 3}
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "scenario_id",
        "variant_id",
        "enabled_modules",
        "variant_contract",
        "module_id",
        "engine_id",
        "synthetic_data",
        "source",
        "known_gaps",
        "recovery_timeout_ms",
        "threshold_sources",
        "initial_state",
        "events",
    }
)
_INITIAL_STATE_KEYS = frozenset(
    {
        "controller_state",
        "transceiver_state",
        "bus_observation",
        "tx_error_counter",
        "rx_error_counter",
    }
)
_SOURCE_KEYS = frozenset({"classification", "reference", "version"})
_BASE_EVENT_KEYS = frozenset({"type", "timestamp_ms"})
_EVENT_KEYS = {
    "NORMAL_FRAME": _BASE_EVENT_KEYS | {"frame_id", "dlc", "data_hex"},
    "ERROR_COUNTER_UPDATE": _BASE_EVENT_KEYS
    | {"tx_error_counter", "rx_error_counter", "controller_state"},
    "BUS_OFF": _BASE_EVENT_KEYS,
    "RECOVERY_REQUEST": _BASE_EVENT_KEYS,
    "RECOVERY_COMPLETE": _BASE_EVENT_KEYS,
    "RECOVERY_TIMEOUT": _BASE_EVENT_KEYS,
    "TRANSCEIVER_OFF": _BASE_EVENT_KEYS,
}
_FORBIDDEN_PHYSICAL_KEYS = frozenset(
    {
        "physical_pass",
        "measured",
        "measurement",
        "measured_value",
        "part",
        "part_number",
        "exact_part",
        "voltage",
        "iso_compliance",
        "aec_qualification",
    }
)

_GAP_01 = {
    "gap_id": "GAP-01",
    "status": "UNKNOWN",
    "rule_id": "REP03-CAN-GAP-001",
    "reason_code": "EXACT_TRANSCEIVER_BEHAVIOR_UNVERIFIED",
    "description": (
        "External transceiver identity, power control and power-off behaviour "
        "have no approved source; no physical state is inferred."
    ),
}


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


def scenario_input_hash(scenario: Any) -> str:
    """Return a stable SHA-256 for the semantic JSON input."""

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


def _dominant_result(records: list[Mapping[str, Any]]) -> tuple[str, str, str]:
    if not records:
        return "PASS", "REP03-CAN-000", "SCENARIO_COMPLETED"
    dominant = max(records, key=lambda record: _STATUS_PRIORITY[record["status"]])
    return dominant["status"], dominant["rule_id"], dominant["reason_code"]


def _source_copy(source: Any) -> dict[str, str] | None:
    if not isinstance(source, Mapping):
        return None
    return {
        "classification": str(source.get("classification", "")),
        "reference": str(source.get("reference", "")),
        "version": str(source.get("version", "")),
    }


def _validated_report_source(source: Any) -> dict[str, str] | None:
    """Return source metadata only when it conforms to the public report schema."""

    if not isinstance(source, Mapping):
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
        or set(source) != _SOURCE_KEYS
    ):
        return None
    return {
        "classification": classification,
        "reference": reference,
        "version": version,
    }


def _validated_report_variant_contract(contract: Any) -> dict[str, Any] | None:
    if not isinstance(contract, Mapping) or set(contract) != {
        "schema_version",
        "profile_hash",
        "source",
    }:
        return None
    safe_source = _validated_report_source(contract.get("source"))
    if (
        contract.get("schema_version") != VARIANT_CONTRACT_SCHEMA
        or contract.get("profile_hash") != APPROVED_VARIANT_A_PROFILE_HASH
        or safe_source is None
    ):
        return None
    return {
        "schema_version": VARIANT_CONTRACT_SCHEMA,
        "profile_hash": APPROVED_VARIANT_A_PROFILE_HASH,
        "source": safe_source,
    }


def _validate_source(
    source: Any,
    path: str,
    issues: list[dict[str, str]],
) -> None:
    if not isinstance(source, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SOURCE-001",
                "SOURCE_METADATA_INVALID",
                path,
                "Source metadata must be an object.",
            )
        )
        return
    unknown = {key for key in source if key not in _SOURCE_KEYS}
    if unknown:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SOURCE-002",
                "UNKNOWN_SOURCE_FIELD",
                path,
                "Unknown source fields: " + ", ".join(sorted(map(str, unknown))),
            )
        )
    classification = source.get("classification")
    if not isinstance(classification, str) or classification not in SOURCE_CLASSIFICATIONS:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SOURCE-003",
                "SOURCE_CLASSIFICATION_INVALID",
                f"{path}.classification",
                "Source classification is outside the approved enumeration.",
            )
        )
    elif classification == "UNKNOWN":
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-CAN-SOURCE-005",
                "SOURCE_UNRESOLVED",
                path,
                "An UNKNOWN source cannot produce a synthetic PASS.",
            )
        )
    elif classification == "ASSUMPTION":
        issues.append(
            _issue(
                "UNKNOWN",
                "REP03-CAN-SOURCE-009",
                "SOURCE_ASSUMPTION",
                path,
                "An assumed source cannot produce a synthetic PASS.",
            )
        )
    elif classification == "CONFLICT":
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-CAN-SOURCE-006",
                "SOURCE_CONFLICT",
                path,
                "Conflicting source evidence blocks evaluation.",
            )
        )
    reference = source.get("reference")
    version = source.get("version")
    if not isinstance(reference, str) or not reference.strip() or not isinstance(version, str) or not version.strip():
        reason_code = (
            "EXACT_SOURCE_METADATA_INCOMPLETE"
            if classification == "SOURCE_EXPLICIT"
            else "SOURCE_REFERENCE_OR_VERSION_MISSING"
        )
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SOURCE-004",
                reason_code,
                path,
                "Source reference and version must both be non-empty strings.",
            )
        )


def _validate_variant_contract(
    contract: Any,
    issues: list[dict[str, str]],
) -> None:
    if not isinstance(contract, Mapping):
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-CAN-D1-001",
                "VARIANT_CONTRACT_MISSING",
                "variant_contract",
                "The approved D1 Variant A contract reference and hash are required.",
            )
        )
        return
    allowed = {"schema_version", "profile_hash", "source"}
    unknown = {key for key in contract if key not in allowed}
    missing = allowed - set(contract)
    if unknown or missing:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-D1-002",
                "VARIANT_CONTRACT_FIELDS_INVALID",
                "variant_contract",
                "variant_contract must contain only schema_version, profile_hash and source.",
            )
        )
    if contract.get("schema_version") != VARIANT_CONTRACT_SCHEMA:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-D1-003",
                "VARIANT_CONTRACT_SCHEMA_MISMATCH",
                "variant_contract.schema_version",
                f"Variant contract schema must equal {VARIANT_CONTRACT_SCHEMA!r}.",
            )
        )
    profile_hash = contract.get("profile_hash")
    if not isinstance(profile_hash, str) or profile_hash != APPROVED_VARIANT_A_PROFILE_HASH:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-D1-004",
                "VARIANT_CONTRACT_HASH_MISMATCH",
                "variant_contract.profile_hash",
                "Scenario is not pinned to the approved Variant A profile hash.",
            )
        )
    _validate_source(contract.get("source"), "variant_contract.source", issues)


def _find_physical_claim_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            lower = key_text.lower()
            if lower in _FORBIDDEN_PHYSICAL_KEYS or lower.startswith("part_"):
                found.append(child_path)
            found.extend(_find_physical_claim_paths(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_find_physical_claim_paths(item, f"{path}[{index}]"))
    return found


def _find_non_finite_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        return [path]
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_find_non_finite_paths(item, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_find_non_finite_paths(item, f"{path}[{index}]"))
    return found


def _validate_scenario(scenario: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not isinstance(scenario, Mapping):
        return [
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-001",
                "SCENARIO_NOT_OBJECT",
                "$",
                "Scenario must be a JSON object.",
            )
        ]

    physical_paths = _find_physical_claim_paths(scenario)
    if physical_paths:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCOPE-001",
                "PHYSICAL_CLAIM_FORBIDDEN",
                physical_paths[0],
                "Physical, measured, part, voltage, ISO or AEC claims are forbidden.",
            )
        )
    non_finite_paths = _find_non_finite_paths(scenario)
    if non_finite_paths:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-013",
                "NON_FINITE_NUMBER",
                non_finite_paths[0],
                "NaN and Infinity are not valid scenario numbers.",
            )
        )

    unknown_keys = {key for key in scenario if key not in _TOP_LEVEL_KEYS}
    if unknown_keys:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-002",
                "UNKNOWN_SCENARIO_FIELD",
                "$",
                "Unknown scenario fields: " + ", ".join(sorted(map(str, unknown_keys))),
            )
        )
    if scenario.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-003",
                "SCHEMA_VERSION_MISMATCH",
                "schema_version",
                f"schema_version must equal {SCHEMA_VERSION!r}.",
            )
        )
    if not isinstance(scenario.get("scenario_id"), str) or not scenario["scenario_id"].strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-012",
                "SCENARIO_ID_INVALID",
                "scenario_id",
                "scenario_id must be a non-empty string.",
            )
        )
    for field, expected, rule_id, reason_code in (
        ("variant_id", VARIANT_ID, "REP03-CAN-GATE-001", "VARIANT_A_REQUIRED"),
        ("module_id", MODULE_ID, "REP03-CAN-GATE-002", "CAN_MODULE_REQUIRED"),
        ("engine_id", ENGINE_ID, "REP03-CAN-GATE-003", "ENGINE_ID_MISMATCH"),
    ):
        if scenario.get(field) != expected:
            issues.append(
                _issue(
                    "FAIL",
                    rule_id,
                    reason_code,
                    field,
                    f"{field} must equal {expected!r}.",
                )
            )
    enabled_modules = scenario.get("enabled_modules")
    allowed_modules = {"can", "lin", "gnss"}
    if not isinstance(enabled_modules, list) or not all(
        isinstance(module, str) for module in enabled_modules
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-GATE-004",
                "ENABLED_MODULES_INVALID",
                "enabled_modules",
                "enabled_modules must be a string array for Variant A.",
            )
        )
    else:
        declared = set(enabled_modules)
        if len(declared) != len(enabled_modules):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-GATE-005",
                    "DUPLICATE_MODULE",
                    "enabled_modules",
                    "enabled_modules must not contain duplicates.",
                )
            )
        if "can" not in declared:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-GATE-002",
                    "CAN_MODULE_REQUIRED",
                    "enabled_modules",
                    "The CAN module must be enabled for this engine.",
                )
            )
        missing = allowed_modules - declared
        if missing:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-GATE-007",
                    "VARIANT_A_MODULE_SET_INCOMPLETE",
                    "enabled_modules",
                    "Variant A requires exactly can, lin and gnss; missing: "
                    + ", ".join(sorted(missing))
                    + ".",
                )
            )
        foreign = declared - allowed_modules
        if foreign:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-GATE-006",
                    "VARIANT_A_MODULE_LEAKAGE",
                    "enabled_modules",
                    "Modules outside the Variant-A allowlist are forbidden.",
                )
            )
    if scenario.get("synthetic_data") is not True:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCOPE-002",
                "SYNTHETIC_DATA_REQUIRED",
                "synthetic_data",
                "Only explicitly synthetic scenarios are accepted.",
            )
        )
    _validate_source(scenario.get("source"), "source", issues)
    _validate_variant_contract(scenario.get("variant_contract"), issues)

    known_gaps = scenario.get("known_gaps")
    if not isinstance(known_gaps, list) or not all(
        isinstance(gap, str) for gap in known_gaps
    ):
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-GAP-003",
                "KNOWN_GAPS_INVALID",
                "known_gaps",
                "known_gaps must be an array containing only string identifiers.",
            )
        )
    else:
        declared_gaps = set(known_gaps)
        if len(declared_gaps) != len(known_gaps):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-GAP-004",
                    "DUPLICATE_KNOWN_GAP",
                    "known_gaps",
                    "known_gaps must not contain duplicates.",
                )
            )
        unsupported_gaps = declared_gaps - {"GAP-01"}
        if unsupported_gaps:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-GAP-005",
                    "UNKNOWN_KNOWN_GAP",
                    "known_gaps",
                    "Unsupported gap identifiers: "
                    + ", ".join(sorted(unsupported_gaps))
                    + ".",
                )
            )
    if not isinstance(known_gaps, list) or "GAP-01" not in known_gaps:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-GAP-002",
                "GAP_01_DECLARATION_MISSING",
                "known_gaps",
                "GAP-01 must remain explicit until transceiver evidence is approved.",
            )
        )

    timeout_ms = scenario.get("recovery_timeout_ms")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-004",
                "RECOVERY_TIMEOUT_INVALID",
                "recovery_timeout_ms",
                "recovery_timeout_ms must be a positive synthetic integer.",
            )
        )

    threshold_sources = scenario.get("threshold_sources")
    if not isinstance(threshold_sources, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SOURCE-007",
                "THRESHOLD_SOURCES_MISSING",
                "threshold_sources",
                "Error-state and recovery-timeout sources are required.",
            )
        )
    else:
        expected = {"error_state", "recovery_timeout"}
        if set(threshold_sources) != expected:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-SOURCE-008",
                    "THRESHOLD_SOURCE_SET_INVALID",
                    "threshold_sources",
                    "threshold_sources must contain only error_state and recovery_timeout.",
                )
            )
        for name in sorted(expected):
            _validate_source(threshold_sources.get(name), f"threshold_sources.{name}", issues)

    initial = scenario.get("initial_state")
    if not isinstance(initial, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-005",
                "INITIAL_STATE_INVALID",
                "initial_state",
                "initial_state must be an object.",
            )
        )
    else:
        if set(initial) != _INITIAL_STATE_KEYS:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-SCHEMA-006",
                    "INITIAL_STATE_FIELDS_INVALID",
                    "initial_state",
                    "Initial controller, transceiver, bus and both counters are required.",
                )
            )
        controller_state = initial.get("controller_state")
        if not isinstance(controller_state, str) or controller_state not in CONTROLLER_STATES:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-SCHEMA-007",
                    "CONTROLLER_STATE_INVALID",
                    "initial_state.controller_state",
                    "Initial controller state is outside the synthetic enumeration.",
                )
            )
        transceiver_state = initial.get("transceiver_state")
        if not isinstance(transceiver_state, str) or transceiver_state not in TRANSCEIVER_STATES:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-SCHEMA-008",
                    "TRANSCEIVER_STATE_INVALID",
                    "initial_state.transceiver_state",
                    "Initial transceiver state is outside the synthetic enumeration.",
                )
            )
        bus_observation = initial.get("bus_observation")
        if not isinstance(bus_observation, str) or bus_observation not in BUS_OBSERVATIONS:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-CAN-SCHEMA-009",
                    "BUS_OBSERVATION_INVALID",
                    "initial_state.bus_observation",
                    "Initial bus observation is outside the synthetic enumeration.",
                )
            )
        for counter in ("tx_error_counter", "rx_error_counter"):
            value = initial.get(counter)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                issues.append(
                    _issue(
                        "FAIL",
                        "REP03-CAN-SCHEMA-010",
                        "INITIAL_ERROR_COUNTER_INVALID",
                        f"initial_state.{counter}",
                        "Initial synthetic error counters must be integers from 0 through 255.",
                    )
                )

    events = scenario.get("events")
    if not isinstance(events, list) or not events:
        issues.append(
            _issue(
                "FAIL",
                "REP03-CAN-SCHEMA-011",
                "EVENTS_EMPTY_OR_INVALID",
                "events",
                "events must be a non-empty array.",
            )
        )
    return issues


def _event_shape_issue(event: Any, index: int) -> dict[str, str] | None:
    path = f"events[{index}]"
    if not isinstance(event, Mapping):
        return _issue("FAIL", "REP03-CAN-EVENT-001", "EVENT_NOT_OBJECT", path, "Each event must be an object.")
    event_type = event.get("type")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        return _issue(
            "FAIL",
            "REP03-CAN-EVENT-002",
            "EVENT_TYPE_INVALID",
            f"{path}.type",
            "Event type is outside the supported synthetic enumeration.",
        )
    unknown = {key for key in event if key not in _EVENT_KEYS[event_type]}
    if unknown:
        return _issue(
            "FAIL",
            "REP03-CAN-EVENT-003",
            "UNKNOWN_EVENT_FIELD",
            path,
            "Unknown event fields: " + ", ".join(sorted(map(str, unknown))),
        )
    timestamp = event.get("timestamp_ms")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        return _issue(
            "FAIL",
            "REP03-CAN-EVENT-004",
            "EVENT_TIMESTAMP_INVALID",
            f"{path}.timestamp_ms",
            "timestamp_ms must be a non-negative integer.",
        )
    return None


def _normal_frame_issue(event: Mapping[str, Any], index: int) -> dict[str, str] | None:
    path = f"events[{index}]"
    frame_id = event.get("frame_id")
    dlc = event.get("dlc")
    data_hex = event.get("data_hex")
    if isinstance(frame_id, bool) or not isinstance(frame_id, int) or not 0 <= frame_id <= 0x1FFFFFFF:
        return _issue("FAIL", "REP03-CAN-FRAME-001", "FRAME_ID_INVALID", f"{path}.frame_id", "frame_id must be an integer in the synthetic 29-bit range.")
    if isinstance(dlc, bool) or not isinstance(dlc, int) or not 0 <= dlc <= 8:
        return _issue("FAIL", "REP03-CAN-FRAME-002", "DLC_INVALID", f"{path}.dlc", "dlc must be an integer from 0 through 8.")
    if not isinstance(data_hex, str) or len(data_hex) != dlc * 2:
        return _issue("FAIL", "REP03-CAN-FRAME-003", "FRAME_DATA_LENGTH_MISMATCH", f"{path}.data_hex", "data_hex must contain exactly two hexadecimal characters per byte.")
    if re.fullmatch(r"[0-9A-Fa-f]*", data_hex) is None:
        return _issue("FAIL", "REP03-CAN-FRAME-004", "FRAME_DATA_NOT_HEX", f"{path}.data_hex", "data_hex contains a non-hexadecimal character.")
    return None


def _counter_issue(event: Mapping[str, Any], index: int) -> dict[str, str] | None:
    path = f"events[{index}]"
    for field in ("tx_error_counter", "rx_error_counter"):
        value = event.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            return _issue("FAIL", "REP03-CAN-COUNTER-001", "ERROR_COUNTER_INVALID", f"{path}.{field}", "Synthetic error counters must be integers from 0 through 255.")
    controller_state = event.get("controller_state")
    if not isinstance(controller_state, str) or controller_state not in {
        "ERROR_ACTIVE",
        "ERROR_WARNING",
        "ERROR_PASSIVE",
    }:
        return _issue("FAIL", "REP03-CAN-COUNTER-002", "COUNTER_TARGET_STATE_INVALID", f"{path}.controller_state", "Counter updates may target only non-bus-off controller states.")
    return None


def _snapshot(
    controller: str | None,
    transceiver: str | None,
    bus_observation: str | None,
    tx_counter: int | None,
    rx_counter: int | None,
) -> dict[str, Any]:
    return {
        "controller_state": controller,
        "transceiver_state": transceiver,
        "bus_observation": bus_observation,
        "tx_error_counter": tx_counter,
        "rx_error_counter": rx_counter,
    }


def _domain_results(
    event: str,
    status: str,
    rule_id: str,
    reason_code: str,
) -> dict[str, dict[str, str]]:
    gap_01_block = reason_code == "GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED"
    controller_unaffected = event == "TRANSCEIVER_OFF" or (
        event == "NORMAL_FRAME" and gap_01_block
    )
    controller_status = "PASS" if controller_unaffected else status
    controller_reason = "CONTROLLER_STATE_UNCHANGED" if controller_unaffected else reason_code
    transceiver_status = "BLOCKED" if gap_01_block else "UNKNOWN"
    transceiver_reason = (
        "GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED"
        if gap_01_block
        else "PHYSICAL_TRANSCEIVER_NOT_VALIDATED"
    )
    return {
        "controller": {
            "status": controller_status,
            "rule_id": rule_id if not controller_unaffected else "REP03-CAN-STATE-001",
            "reason_code": controller_reason,
        },
        "transceiver": {
            "status": transceiver_status,
            "rule_id": "REP03-CAN-GAP-001",
            "reason_code": transceiver_reason,
        },
        "bus_observation": {
            "status": "UNKNOWN",
            "rule_id": "REP03-CAN-SCOPE-003",
            "reason_code": "PHYSICAL_BUS_NOT_OBSERVED",
        },
    }


def _trace_row(
    sequence: int,
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    event: str,
    elapsed_ms: int | None,
    timeout_ms: int | None,
    threshold_source: dict[str, str] | None,
    status: str,
    rule_id: str,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "previous_state": dict(previous_state),
        "next_state": dict(next_state),
        "previous_controller_state": previous_state.get("controller_state"),
        "new_controller_state": next_state.get("controller_state"),
        "previous_transceiver_state": previous_state.get("transceiver_state"),
        "new_transceiver_state": next_state.get("transceiver_state"),
        "previous_bus_observation": previous_state.get("bus_observation"),
        "new_bus_observation": next_state.get("bus_observation"),
        "previous_error_counters": {
            "tx": previous_state.get("tx_error_counter"),
            "rx": previous_state.get("rx_error_counter"),
        },
        "new_error_counters": {
            "tx": next_state.get("tx_error_counter"),
            "rx": next_state.get("rx_error_counter"),
        },
        "event": event,
        "elapsed_ms": elapsed_ms,
        "timeout_ms": timeout_ms,
        "threshold_source": threshold_source,
        "status": status,
        "rule_id": rule_id,
        "reason_code": reason_code,
        "domain_results": _domain_results(event, status, rule_id, reason_code),
    }


def run_scenario(scenario: Any) -> dict[str, Any]:
    """Execute one synthetic Variant-A/CAN scenario."""

    input_hash = scenario_input_hash(scenario)
    issues = _validate_scenario(scenario)
    trace: list[dict[str, Any]] = []
    initial = scenario.get("initial_state", {}) if isinstance(scenario, Mapping) else {}
    controller = initial.get("controller_state") if isinstance(initial, Mapping) else None
    transceiver = initial.get("transceiver_state") if isinstance(initial, Mapping) else None
    bus_observation = initial.get("bus_observation") if isinstance(initial, Mapping) else None
    tx_counter = initial.get("tx_error_counter") if isinstance(initial, Mapping) else None
    rx_counter = initial.get("rx_error_counter") if isinstance(initial, Mapping) else None
    timeout_ms = scenario.get("recovery_timeout_ms") if isinstance(scenario, Mapping) else None
    events = scenario.get("events", []) if isinstance(scenario, Mapping) else []

    if issues:
        status, rule_id, reason_code = _dominant_result(issues)
        precheck_state = _snapshot(None, None, None, None, None)
        safe_timeout = (
            timeout_ms
            if isinstance(timeout_ms, int)
            and not isinstance(timeout_ms, bool)
            and timeout_ms > 0
            else None
        )
        trace.append(
            _trace_row(
                0,
                precheck_state,
                precheck_state,
                "PRECHECK",
                0,
                safe_timeout,
                None,
                status,
                rule_id,
                reason_code,
            )
        )
        return _build_report(
            scenario,
            input_hash,
            status,
            rule_id,
            reason_code,
            precheck_state,
            trace,
            issues,
        )

    threshold_sources = scenario["threshold_sources"]
    last_timestamp = 0
    recovery_started_ms: int | None = None
    recovery_requested = False
    bus_off_seen = controller == "BUS_OFF"

    for index, event in enumerate(events):
        previous = _snapshot(controller, transceiver, bus_observation, tx_counter, rx_counter)
        shape_issue = _event_shape_issue(event, index)
        event_type = event.get("type", "INVALID_EVENT") if isinstance(event, Mapping) else "INVALID_EVENT"
        display_event = event_type if isinstance(event_type, str) else "INVALID_EVENT"
        timestamp = event.get("timestamp_ms") if isinstance(event, Mapping) else None
        elapsed = timestamp - last_timestamp if isinstance(timestamp, int) else None
        threshold_source = None
        if isinstance(event_type, str):
            if event_type == "ERROR_COUNTER_UPDATE":
                threshold_source = _source_copy(threshold_sources["error_state"])
            elif event_type in {"RECOVERY_REQUEST", "RECOVERY_COMPLETE", "RECOVERY_TIMEOUT"}:
                threshold_source = _source_copy(threshold_sources["recovery_timeout"])

        if shape_issue is None and timestamp < last_timestamp:
            shape_issue = _issue("FAIL", "REP03-CAN-EVENT-005", "EVENT_TIME_NOT_MONOTONIC", f"events[{index}].timestamp_ms", "Event timestamps must be monotonic.")
        if shape_issue is not None:
            issues.append(shape_issue)
            trace.append(_trace_row(index, previous, previous, display_event, elapsed, timeout_ms, threshold_source, shape_issue["status"], shape_issue["rule_id"], shape_issue["reason_code"]))
            continue

        status = "PASS"
        rule_id = "REP03-CAN-EVENT-000"
        reason_code = "EVENT_ACCEPTED"
        event_issue: dict[str, str] | None = None

        if event_type == "NORMAL_FRAME":
            event_issue = _normal_frame_issue(event, index)
            if event_issue is None and controller in {"BUS_OFF", "RECOVERY_PENDING"}:
                event_issue = _issue("FAIL", "REP03-CAN-SEQ-001", "FRAME_WHILE_CONTROLLER_UNAVAILABLE", f"events[{index}]", "A normal frame is invalid while bus-off or recovery-pending.")
            elif event_issue is None and transceiver != "SYNTHETIC_ON":
                event_issue = _issue("BLOCKED", "REP03-CAN-GAP-001", "GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED", f"events[{index}]", "Frame outcome is blocked because transceiver behaviour is unknown.")
            elif event_issue is None:
                bus_observation = "SYNTHETIC_FRAME_OBSERVED"
                rule_id = "REP03-CAN-FRAME-000"
                reason_code = "SYNTHETIC_CONTROLLER_FRAME_ACCEPTED"

        elif event_type == "ERROR_COUNTER_UPDATE":
            event_issue = _counter_issue(event, index)
            if event_issue is None and controller in {"BUS_OFF", "RECOVERY_PENDING"}:
                event_issue = _issue("FAIL", "REP03-CAN-SEQ-002", "COUNTER_UPDATE_WHILE_CONTROLLER_UNAVAILABLE", f"events[{index}]", "Error-counter updates are invalid during bus-off or recovery.")
            elif event_issue is None:
                tx_counter = event["tx_error_counter"]
                rx_counter = event["rx_error_counter"]
                controller = event["controller_state"]
                rule_id = "REP03-CAN-COUNTER-000"
                reason_code = "SYNTHETIC_ERROR_STATE_UPDATED"

        elif event_type == "BUS_OFF":
            if controller in {"BUS_OFF", "RECOVERY_PENDING"}:
                event_issue = _issue("FAIL", "REP03-CAN-SEQ-003", "BUS_OFF_SEQUENCE_INVALID", f"events[{index}]", "BUS_OFF is valid only from an operating controller state.")
            else:
                controller = "BUS_OFF"
                bus_off_seen = True
                recovery_requested = False
                recovery_started_ms = None
                rule_id = "REP03-CAN-BUSOFF-001"
                reason_code = "SYNTHETIC_BUS_OFF_ENTERED"

        elif event_type == "RECOVERY_REQUEST":
            if controller != "BUS_OFF":
                event_issue = _issue("FAIL", "REP03-CAN-SEQ-004", "RECOVERY_REQUEST_WITHOUT_BUS_OFF", f"events[{index}]", "Recovery may be requested only from BUS_OFF.")
            else:
                controller = "RECOVERY_PENDING"
                recovery_requested = True
                recovery_started_ms = timestamp
                rule_id = "REP03-CAN-RECOVERY-001"
                reason_code = "SYNTHETIC_RECOVERY_REQUEST_ACCEPTED"

        elif event_type == "RECOVERY_COMPLETE":
            if controller != "RECOVERY_PENDING" or recovery_started_ms is None:
                event_issue = _issue("FAIL", "REP03-CAN-SEQ-005", "RECOVERY_COMPLETE_WITHOUT_REQUEST", f"events[{index}]", "Recovery cannot complete without a pending request.")
            else:
                elapsed = timestamp - recovery_started_ms
                if elapsed >= timeout_ms:
                    controller = "BUS_OFF"
                    event_issue = _issue("FAIL", "REP03-CAN-RECOVERY-003", "RECOVERY_COMPLETE_AFTER_TIMEOUT", f"events[{index}]", "Recovery completion arrived at or after the synthetic timeout.")
                else:
                    controller = "ERROR_ACTIVE"
                    tx_counter = 0
                    rx_counter = 0
                    recovery_started_ms = None
                    rule_id = "REP03-CAN-RECOVERY-002"
                    reason_code = "SYNTHETIC_RECOVERY_COMPLETED"

        elif event_type == "RECOVERY_TIMEOUT":
            if controller != "RECOVERY_PENDING" or recovery_started_ms is None:
                event_issue = _issue("FAIL", "REP03-CAN-SEQ-006", "RECOVERY_TIMEOUT_WITHOUT_REQUEST", f"events[{index}]", "Recovery timeout is invalid without a pending request.")
            else:
                elapsed = timestamp - recovery_started_ms
                if elapsed < timeout_ms:
                    event_issue = _issue("FAIL", "REP03-CAN-SEQ-007", "RECOVERY_TIMEOUT_NOT_REACHED", f"events[{index}]", "Synthetic recovery timeout has not yet elapsed.")
                else:
                    controller = "BUS_OFF"
                    event_issue = _issue("FAIL", "REP03-CAN-RECOVERY-004", "RECOVERY_TIMEOUT_EXCEEDED", f"events[{index}]", "Recovery did not complete within the sourced synthetic timeout.")

        elif event_type == "TRANSCEIVER_OFF":
            transceiver = "UNKNOWN"
            bus_observation = "UNKNOWN"
            event_issue = _issue("BLOCKED", "REP03-CAN-GAP-001", "GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED", f"events[{index}]", "Exact external-transceiver power-off behaviour is not sourced.")

        if event_issue is not None:
            status = event_issue["status"]
            rule_id = event_issue["rule_id"]
            reason_code = event_issue["reason_code"]
            issues.append(event_issue)
        next_state = _snapshot(controller, transceiver, bus_observation, tx_counter, rx_counter)
        trace.append(_trace_row(index, previous, next_state, event_type, elapsed, timeout_ms, threshold_source, status, rule_id, reason_code))
        last_timestamp = timestamp

    if bus_off_seen and controller == "BUS_OFF" and not recovery_requested:
        final_issue = _issue("FAIL", "REP03-CAN-RECOVERY-005", "RECOVERY_NOT_REQUESTED", "events", "Scenario ended in BUS_OFF without a recovery request.")
        issues.append(final_issue)
        state = _snapshot(controller, transceiver, bus_observation, tx_counter, rx_counter)
        trace.append(_trace_row(len(trace), state, state, "SCENARIO_END", 0, timeout_ms, _source_copy(threshold_sources["recovery_timeout"]), final_issue["status"], final_issue["rule_id"], final_issue["reason_code"]))
    elif controller == "RECOVERY_PENDING":
        final_issue = _issue("FAIL", "REP03-CAN-RECOVERY-006", "RECOVERY_INCOMPLETE", "events", "Scenario ended while recovery remained pending.")
        issues.append(final_issue)
        state = _snapshot(controller, transceiver, bus_observation, tx_counter, rx_counter)
        trace.append(_trace_row(len(trace), state, state, "SCENARIO_END", 0, timeout_ms, _source_copy(threshold_sources["recovery_timeout"]), final_issue["status"], final_issue["rule_id"], final_issue["reason_code"]))

    status, rule_id, reason_code = _dominant_result([*trace, *issues])
    final_state = _snapshot(controller, transceiver, bus_observation, tx_counter, rx_counter)
    return _build_report(scenario, input_hash, status, rule_id, reason_code, final_state, trace, issues)


def _build_report(
    scenario: Any,
    input_hash: str,
    status: str,
    rule_id: str,
    reason_code: str,
    final_state: dict[str, Any],
    trace: list[dict[str, Any]],
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    source = scenario.get("source") if isinstance(scenario, Mapping) else None
    safe_source = _validated_report_source(source)
    safe_variant_contract = _validated_report_variant_contract(
        scenario.get("variant_contract") if isinstance(scenario, Mapping) else None
    )
    raw_scenario_id = scenario.get("scenario_id") if isinstance(scenario, Mapping) else None
    safe_scenario_id = (
        raw_scenario_id
        if isinstance(raw_scenario_id, str) and raw_scenario_id.strip()
        else None
    )
    transceiver_exercised = any(
        issue.get("reason_code") == "GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED"
        for issue in issues
    )
    transceiver_dependency = dict(_GAP_01)
    if transceiver_exercised:
        transceiver_dependency["status"] = "BLOCKED"
        transceiver_dependency["reason_code"] = "GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED"
    return {
        "schema_version": SCHEMA_VERSION,
        "variant_id": VARIANT_ID,
        "module_id": MODULE_ID,
        "engine_id": ENGINE_ID,
        "scenario_id": safe_scenario_id,
        "status": status,
        "rule_id": rule_id,
        "reason_code": reason_code,
        "final_state": final_state,
        "trace": trace,
        "issues": issues,
        "input_hash": input_hash,
        "tool_version": TOOL_VERSION,
        "source": safe_source,
        "source_reference": safe_source["reference"] if safe_source is not None else None,
        "source_version": safe_source["version"] if safe_source is not None else None,
        "variant_contract": safe_variant_contract,
        "expected_variant_contract_profile_hash": APPROVED_VARIANT_A_PROFILE_HASH,
        "synthetic_data": True,
        "dependency_results": {
            "external_transceiver": transceiver_dependency,
            "physical_bus": {
                "status": "UNKNOWN",
                "rule_id": "REP03-CAN-SCOPE-003",
                "reason_code": "PHYSICAL_BUS_NOT_OBSERVED",
            },
        },
        "known_limitations": [dict(_GAP_01)],
        "claims": {
            "validation_level": "SYNTHETIC",
            "physical_can_validation": False,
            "physical_transceiver_validation": False,
            "iso_compliance": False,
            "aec_qualification": False,
        },
    }

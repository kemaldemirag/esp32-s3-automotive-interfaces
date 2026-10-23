"""Deterministic, synthetic-only ignition-shutdown engine for REP-03.

The engine records a proposed event order for Variant B.  It does not notify a
real host, observe a real ACK, shut down an operating system, drive a power
switch, or prove that a restart is safe.  Raspberry Pi model, host protocol,
timeout, grace, debounce, and restart values are deliberately input data: no
default is supplied.  When those sources are unresolved, GAP-04 remains open
and protocol-dependent results fail closed as ``BLOCKED`` or ``UNKNOWN``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from typing import Any


SCHEMA_VERSION = "repo03.shutdown.scenario.v1"
TOOL_VERSION = "repo03-shutdown-engine/1.0.0"
ENGINE_ID = "repo03-shutdown-engine"
MODULE_ID = "shutdown"
VARIANT_ID = "B"
VARIANT_CONTRACT_SCHEMA = "repo03.variant.schema.v1"
APPROVED_VARIANT_B_PROFILE_HASH = (
    "1b82f114d7fb4280f55d3f72a7a61816f38242b7495a23cfa468f17b92d00fcd"
)

STATES = (
    "IGNITION_ON",
    "NOTIFY_PENDING",
    "WAIT_ACK",
    "GRACE_PERIOD",
    "READY_TO_CUT",
    "POWER_CUT",
    "RESTART",
)
EVENTS = ("ignition-off", "host-notify", "ACK", "timeout", "cut", "restart")
VARIANT_B_MODULES = frozenset({"automotive_power", "shutdown"})
TIMING_NAMES = (
    "ack_timeout_ms",
    "grace_period_ms",
    "ignition_debounce_ms",
    "restart_minimum_ms",
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
SOURCE_AUTHORITIES = frozenset(
    {"PROJECT_REQUIREMENT", "HOST_PROTOCOL", "ENGINEERING"}
)
RESULT_STATUSES = frozenset({"PASS", "FAIL", "UNKNOWN", "BLOCKED"})
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
        "host_contract",
        "timing_policy",
        "initial_state",
        "events",
        "assertions",
    }
)
_SOURCE_KEYS = frozenset({"classification", "authority", "reference", "version"})
_VARIANT_CONTRACT_KEYS = frozenset({"schema_version", "profile_hash", "source"})
_HOST_CONTRACT_KEYS = frozenset({"raspberry_pi_model", "protocol_id", "source"})
_TIMING_POLICY_KEYS = frozenset(TIMING_NAMES)
_THRESHOLD_KEYS = frozenset({"value_ms", "source"})
_EVENT_KEYS = frozenset({"event", "elapsed_time"})
_ASSERTION_KEYS = frozenset(
    {"validation_level", "real_os_shutdown", "physical_power_cut"}
)

_GAP_04 = {
    "knowledge_status": "UNKNOWN",
    "blocking_status": "BLOCKED",
    "rule_id": "REP03-SHUTDOWN-GAP-004",
    "reason_code": "HOST_MODEL_AND_SHUTDOWN_PROTOCOL_UNRESOLVED",
    "description": (
        "Raspberry Pi model, approved host shutdown protocol, and sourced "
        "timing limits are unresolved."
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
    """Return a deterministic SHA-256 without raising on malformed values."""

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


def _validate_keys(
    value: Mapping[Any, Any],
    allowed: frozenset[str],
    path: str,
    issues: list[dict[str, str]],
) -> None:
    unknown = [key for key in value if not isinstance(key, str) or key not in allowed]
    if unknown:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SCHEMA-001",
                "UNKNOWN_FIELD",
                path,
                "Unknown fields are not permitted by the closed contract.",
            )
        )


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


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _dominant(items: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    if not items:
        return "PASS", "REP03-SHUTDOWN-RUN-000", "SCENARIO_COMPLETED"
    selected = max(
        enumerate(items),
        key=lambda pair: (
            _STATUS_PRIORITY.get(str(pair[1].get("status")), 3),
            -pair[0],
        ),
    )[1]
    return (
        str(selected.get("status", "FAIL")),
        str(selected.get("rule_id", "REP03-SHUTDOWN-RUN-999")),
        str(selected.get("reason_code", "UNSPECIFIED_FAILURE")),
    )


def _validate_source(
    source: Any,
    path: str,
    issues: list[dict[str, str]],
    *,
    decision_source: bool,
) -> None:
    if source is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-SHUTDOWN-SOURCE-001",
                "SOURCE_MISSING",
                path,
                "A pinned source is required; no default is substituted.",
            )
        )
        return
    if not isinstance(source, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SOURCE-002",
                "SOURCE_INVALID",
                path,
                "Source metadata must be an object or null where allowed.",
            )
        )
        return

    _validate_keys(source, _SOURCE_KEYS, path, issues)
    classification = source.get("classification")
    authority = source.get("authority")
    reference = source.get("reference")
    version = source.get("version")

    if not isinstance(classification, str) or classification not in SOURCE_CLASSIFICATIONS:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SOURCE-003",
                "SOURCE_CLASSIFICATION_INVALID",
                f"{path}.classification",
                "Source classification is outside the approved enumeration.",
            )
        )
    elif classification == "CONFLICT":
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-SHUTDOWN-SOURCE-004",
                "SOURCE_CONFLICT",
                f"{path}.classification",
                "Conflicting evidence blocks the decision.",
            )
        )
    elif classification in {"ASSUMPTION", "UNKNOWN"}:
        issues.append(
            _issue(
                "UNKNOWN",
                "REP03-SHUTDOWN-SOURCE-005",
                "SOURCE_UNRESOLVED",
                f"{path}.classification",
                "An assumption or unknown source cannot prove a protocol decision.",
            )
        )

    if not isinstance(authority, str) or authority not in SOURCE_AUTHORITIES:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SOURCE-006",
                "SOURCE_AUTHORITY_INVALID",
                f"{path}.authority",
                "Source authority is outside the approved enumeration.",
            )
        )
    if not isinstance(reference, str) or not reference.strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SOURCE-007",
                "SOURCE_REFERENCE_INVALID",
                f"{path}.reference",
                "A non-empty source reference is required.",
            )
        )
    if not isinstance(version, str) or not version.strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SOURCE-008",
                "SOURCE_VERSION_INVALID",
                f"{path}.version",
                "A non-empty pinned source version is required.",
            )
        )

    if decision_source and (
        classification != "SOURCE_EXPLICIT"
        or authority not in {"PROJECT_REQUIREMENT", "HOST_PROTOCOL"}
    ):
        issues.append(
            _issue(
                "UNKNOWN",
                "REP03-SHUTDOWN-SOURCE-009",
                "DECISION_SOURCE_NOT_AUTHORITATIVE",
                path,
                "Host and timing decisions need an explicit project or host-protocol source.",
            )
        )


def _source_resolution(source: Any, *, decision_source: bool) -> str:
    if source is None:
        return "BLOCKED"
    if not isinstance(source, Mapping):
        return "FAIL"
    if set(source) != set(_SOURCE_KEYS):
        return "FAIL"
    classification = source.get("classification")
    authority = source.get("authority")
    reference = source.get("reference")
    version = source.get("version")
    if (
        not isinstance(classification, str)
        or classification not in SOURCE_CLASSIFICATIONS
        or not isinstance(authority, str)
        or authority not in SOURCE_AUTHORITIES
        or not isinstance(reference, str)
        or not reference.strip()
        or not isinstance(version, str)
        or not version.strip()
    ):
        return "FAIL"
    if classification == "CONFLICT":
        return "BLOCKED"
    if classification in {"ASSUMPTION", "UNKNOWN"}:
        return "UNKNOWN"
    if decision_source and (
        classification != "SOURCE_EXPLICIT"
        or authority not in {"PROJECT_REQUIREMENT", "HOST_PROTOCOL"}
    ):
        return "UNKNOWN"
    return "PASS"


def _validate_variant_contract(value: Any, issues: list[dict[str, str]]) -> None:
    path = "variant_contract"
    if value is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-SHUTDOWN-D1-001",
                "VARIANT_CONTRACT_MISSING",
                path,
                "The fixed D1 Variant B contract is required.",
            )
        )
        return
    if not isinstance(value, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-D1-002",
                "VARIANT_CONTRACT_INVALID",
                path,
                "Variant contract must be an object.",
            )
        )
        return
    _validate_keys(value, _VARIANT_CONTRACT_KEYS, path, issues)
    if value.get("schema_version") != VARIANT_CONTRACT_SCHEMA:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-D1-003",
                "VARIANT_CONTRACT_SCHEMA_MISMATCH",
                f"{path}.schema_version",
                "Variant contract schema is not the pinned D1 schema.",
            )
        )
    if value.get("profile_hash") != APPROVED_VARIANT_B_PROFILE_HASH:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-D1-004",
                "VARIANT_CONTRACT_HASH_MISMATCH",
                f"{path}.profile_hash",
                "Variant B profile hash does not match the approved D1 contract.",
            )
        )
    _validate_source(value.get("source"), f"{path}.source", issues, decision_source=False)


def _validate_host_contract(value: Any, issues: list[dict[str, str]]) -> None:
    path = "host_contract"
    if value is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-SHUTDOWN-HOST-001",
                "HOST_CONTRACT_MISSING",
                path,
                "GAP-04 remains open until a host contract is supplied.",
            )
        )
        return
    if not isinstance(value, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-HOST-002",
                "HOST_CONTRACT_INVALID",
                path,
                "Host contract must be an object.",
            )
        )
        return
    _validate_keys(value, _HOST_CONTRACT_KEYS, path, issues)
    for field, reason in (
        ("raspberry_pi_model", "HOST_MODEL_UNRESOLVED"),
        ("protocol_id", "HOST_PROTOCOL_UNRESOLVED"),
    ):
        item = value.get(field)
        if item is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-SHUTDOWN-HOST-003",
                    reason,
                    f"{path}.{field}",
                    "The value is unresolved; no model or protocol is invented.",
                )
            )
        elif not isinstance(item, str) or not item.strip():
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-HOST-004",
                    f"{field.upper()}_INVALID",
                    f"{path}.{field}",
                    "A supplied host value must be a non-empty string.",
                )
            )
    _validate_source(value.get("source"), f"{path}.source", issues, decision_source=True)


def _validate_timing_policy(value: Any, issues: list[dict[str, str]]) -> None:
    path = "timing_policy"
    if value is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-SHUTDOWN-TIME-001",
                "TIMING_POLICY_MISSING",
                path,
                "A sourced timing policy is required; no defaults are used.",
            )
        )
        return
    if not isinstance(value, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-TIME-002",
                "TIMING_POLICY_INVALID",
                path,
                "Timing policy must be an object.",
            )
        )
        return
    _validate_keys(value, _TIMING_POLICY_KEYS, path, issues)
    for name in TIMING_NAMES:
        threshold = value.get(name)
        threshold_path = f"{path}.{name}"
        if threshold is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-SHUTDOWN-TIME-003",
                    "THRESHOLD_MISSING",
                    threshold_path,
                    "The threshold is missing and is not defaulted.",
                )
            )
            continue
        if not isinstance(threshold, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-TIME-004",
                    "THRESHOLD_INVALID",
                    threshold_path,
                    "Threshold must be an object.",
                )
            )
            continue
        _validate_keys(threshold, _THRESHOLD_KEYS, threshold_path, issues)
        number = threshold.get("value_ms")
        if number is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-SHUTDOWN-TIME-005",
                    "THRESHOLD_VALUE_UNRESOLVED",
                    f"{threshold_path}.value_ms",
                    "The threshold value is unresolved; no duration is invented.",
                )
            )
        elif not _is_number(number) or number < 0:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-TIME-006",
                    "THRESHOLD_VALUE_INVALID",
                    f"{threshold_path}.value_ms",
                    "Threshold must be a finite non-negative number.",
                )
            )
        _validate_source(
            threshold.get("source"),
            f"{threshold_path}.source",
            issues,
            decision_source=True,
        )


def _validate_events(value: Any, issues: list[dict[str, str]]) -> None:
    if not isinstance(value, list):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-EVENT-001",
                "EVENTS_INVALID",
                "events",
                "Events must be a non-empty array.",
            )
        )
        return
    if not value:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-EVENT-002",
                "EVENTS_EMPTY",
                "events",
                "At least one synthetic event is required.",
            )
        )
    for index, item in enumerate(value):
        path = f"events[{index}]"
        if not isinstance(item, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-EVENT-003",
                    "EVENT_INVALID",
                    path,
                    "Each event must be an object.",
                )
            )
            continue
        _validate_keys(item, _EVENT_KEYS, path, issues)
        event = item.get("event")
        if not isinstance(event, str) or event not in EVENTS:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-EVENT-004",
                    "EVENT_UNKNOWN",
                    f"{path}.event",
                    "Event is outside the closed event enumeration.",
                )
            )
        elapsed = item.get("elapsed_time")
        if not _is_number(elapsed) or elapsed < 0:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-EVENT-005",
                    "ELAPSED_TIME_INVALID",
                    f"{path}.elapsed_time",
                    "Elapsed time must be a finite non-negative number of milliseconds.",
                )
            )


def _validate_assertions(value: Any, issues: list[dict[str, str]]) -> None:
    path = "assertions"
    if not isinstance(value, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-CLAIM-001",
                "ASSERTIONS_INVALID",
                path,
                "Synthetic limitations must be explicit.",
            )
        )
        return
    _validate_keys(value, _ASSERTION_KEYS, path, issues)
    if value.get("validation_level") != "SYNTHETIC":
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-CLAIM-002",
                "VALIDATION_LEVEL_INVALID",
                f"{path}.validation_level",
                "Only synthetic validation is supported.",
            )
        )
    for field in ("real_os_shutdown", "physical_power_cut"):
        if value.get(field) is not False:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-CLAIM-003",
                    "REAL_WORLD_CLAIM_FORBIDDEN",
                    f"{path}.{field}",
                    "The synthetic scenario cannot make a real-world completion claim.",
                )
            )


def _validate_scenario(scenario: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not isinstance(scenario, Mapping):
        return [
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SCHEMA-002",
                "SCENARIO_NOT_OBJECT",
                "$",
                "Scenario must be a JSON-compatible object.",
            )
        ]

    for path in _find_non_finite(scenario):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-SCHEMA-003",
                "NON_FINITE_NUMBER",
                path,
                "NaN and infinity are not permitted.",
            )
        )
    _validate_keys(scenario, _TOP_LEVEL_KEYS, "$", issues)

    expected = {
        "schema_version": SCHEMA_VERSION,
        "engine_id": ENGINE_ID,
        "module_id": MODULE_ID,
        "variant_id": VARIANT_ID,
        "synthetic_data": True,
        "initial_state": "IGNITION_ON",
    }
    for field, expected_value in expected.items():
        if scenario.get(field) != expected_value:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-SHUTDOWN-GATE-001",
                    f"{field.upper()}_MISMATCH",
                    field,
                    f"Expected the pinned value {expected_value!r}.",
                )
            )

    scenario_id = scenario.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-GATE-002",
                "SCENARIO_ID_INVALID",
                "scenario_id",
                "Scenario identifier must be a non-empty string.",
            )
        )

    modules = scenario.get("enabled_modules")
    if not isinstance(modules, list) or any(not isinstance(item, str) for item in modules):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-GATE-003",
                "ENABLED_MODULES_INVALID",
                "enabled_modules",
                "Enabled modules must be a string array.",
            )
        )
    elif len(modules) != len(set(modules)):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-GATE-004",
                "DUPLICATE_ENABLED_MODULE",
                "enabled_modules",
                "Duplicate modules are not permitted.",
            )
        )
    elif set(modules) != set(VARIANT_B_MODULES):
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-GATE-005",
                "VARIANT_B_MODULE_SET_MISMATCH",
                "enabled_modules",
                "Variant B requires exactly automotive_power and shutdown.",
            )
        )

    gaps = scenario.get("known_gaps")
    if gaps != ["GAP-04"]:
        issues.append(
            _issue(
                "FAIL",
                "REP03-SHUTDOWN-GAP-001",
                "GAP_04_DECLARATION_MISMATCH",
                "known_gaps",
                "The open GAP-04 declaration must be explicit and exact.",
            )
        )

    _validate_variant_contract(scenario.get("variant_contract"), issues)
    _validate_source(scenario.get("source"), "source", issues, decision_source=False)
    _validate_host_contract(scenario.get("host_contract"), issues)
    _validate_timing_policy(scenario.get("timing_policy"), issues)
    _validate_events(scenario.get("events"), issues)
    _validate_assertions(scenario.get("assertions"), issues)
    return issues


def _safe_source(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or set(value) != set(_SOURCE_KEYS):
        return None
    if not all(isinstance(value.get(key), str) for key in _SOURCE_KEYS):
        return None
    if (
        value.get("classification") not in SOURCE_CLASSIFICATIONS
        or value.get("authority") not in SOURCE_AUTHORITIES
        or not str(value.get("reference", "")).strip()
        or not str(value.get("version", "")).strip()
    ):
        return None
    return {key: str(value[key]) for key in sorted(_SOURCE_KEYS)}


def _host_status(scenario: Mapping[str, Any]) -> str:
    host = scenario.get("host_contract")
    if not isinstance(host, Mapping):
        return "BLOCKED" if host is None else "FAIL"
    for field in ("raspberry_pi_model", "protocol_id"):
        value = host.get(field)
        if value is None:
            return "BLOCKED"
        if not isinstance(value, str) or not value.strip():
            return "FAIL"
    return _source_resolution(host.get("source"), decision_source=True)


def _threshold_status(scenario: Mapping[str, Any], name: str) -> str:
    policy = scenario.get("timing_policy")
    if not isinstance(policy, Mapping):
        return "BLOCKED" if policy is None else "FAIL"
    threshold = policy.get(name)
    if not isinstance(threshold, Mapping):
        return "BLOCKED" if threshold is None else "FAIL"
    value = threshold.get("value_ms")
    if value is None:
        return "BLOCKED"
    if not _is_number(value) or value < 0:
        return "FAIL"
    return _source_resolution(threshold.get("source"), decision_source=True)


def _not_applicable_threshold() -> dict[str, Any]:
    return {
        "name": None,
        "value_ms": None,
        "source": None,
        "status": "NOT_APPLICABLE",
    }


def _threshold_trace(scenario: Mapping[str, Any], name: str | None) -> dict[str, Any]:
    if name is None:
        return _not_applicable_threshold()
    policy = scenario.get("timing_policy")
    threshold = policy.get(name) if isinstance(policy, Mapping) else None
    if isinstance(threshold, Mapping):
        value = threshold.get("value_ms")
        safe_value = value if _is_number(value) and value >= 0 else None
        source = _safe_source(threshold.get("source"))
    else:
        safe_value = None
        source = None
    return {
        "name": name,
        "value_ms": safe_value,
        "source": source,
        "status": _threshold_status(scenario, name),
    }


class ShutdownStateMachine:
    """Small deterministic FSM; callers provide observations, never I/O."""

    def __init__(self, scenario: Mapping[str, Any]):
        self.scenario = scenario
        self.state = "IGNITION_ON"
        self.ack_window_expired = False
        self.ack_received = False
        self.grace_elapsed = False

    def _protocol_result(self, pass_reason: str, unresolved_reason: str) -> tuple[str, str]:
        status = _host_status(self.scenario)
        return ("PASS", pass_reason) if status == "PASS" else (status, unresolved_reason)

    def apply(self, event: str) -> tuple[str, str, str, str | None]:
        """Return next state, status, reason code, and threshold name."""

        state = self.state
        if event == "cut" and state != "READY_TO_CUT":
            self.state = "POWER_CUT"
            return self.state, "FAIL", "EARLY_POWER_CUT", "grace_period_ms"
        if event == "restart" and state != "POWER_CUT":
            self.state = "RESTART"
            return self.state, "FAIL", "RESTART_BEFORE_POWER_CUT", "restart_minimum_ms"

        if state == "IGNITION_ON" and event == "ignition-off":
            self.state = "NOTIFY_PENDING"
            return self.state, "PASS", "IGNITION_OFF_ACCEPTED", None

        if state == "NOTIFY_PENDING" and event == "ignition-off":
            status = _threshold_status(self.scenario, "ignition_debounce_ms")
            reason = (
                "IGNITION_BOUNCE_DEBOUNCED"
                if status == "PASS"
                else "IGNITION_BOUNCE_DEBOUNCE_UNRESOLVED"
            )
            return self.state, status, reason, "ignition_debounce_ms"

        if state == "NOTIFY_PENDING" and event == "host-notify":
            self.state = "WAIT_ACK"
            status, reason = self._protocol_result(
                "HOST_NOTIFY_RECORDED", "HOST_NOTIFY_PROTOCOL_UNRESOLVED"
            )
            return self.state, status, reason, None

        if state == "WAIT_ACK" and event == "timeout":
            self.ack_window_expired = True
            status = _threshold_status(self.scenario, "ack_timeout_ms")
            if status == "PASS":
                return self.state, "FAIL", "ACK_TIMEOUT", "ack_timeout_ms"
            return self.state, status, "ACK_TIMEOUT_THRESHOLD_UNRESOLVED", "ack_timeout_ms"

        if state == "WAIT_ACK" and event == "ACK":
            if self.ack_window_expired:
                return self.state, "FAIL", "LATE_ACK_REJECTED", "ack_timeout_ms"
            self.ack_received = True
            self.state = "GRACE_PERIOD"
            host_status = _host_status(self.scenario)
            threshold_status = _threshold_status(self.scenario, "ack_timeout_ms")
            status, _, _ = _dominant(
                [
                    {"status": host_status, "rule_id": "", "reason_code": ""},
                    {"status": threshold_status, "rule_id": "", "reason_code": ""},
                ]
            )
            reason = "ACK_ACCEPTED" if status == "PASS" else "ACK_PROTOCOL_UNRESOLVED"
            return self.state, status, reason, "ack_timeout_ms"

        if state == "GRACE_PERIOD" and event == "ACK":
            return self.state, "PASS", "DUPLICATE_ACK_IGNORED", "ack_timeout_ms"

        if state == "GRACE_PERIOD" and event == "timeout":
            self.grace_elapsed = True
            self.state = "READY_TO_CUT"
            status = _threshold_status(self.scenario, "grace_period_ms")
            reason = (
                "GRACE_PERIOD_ELAPSED"
                if status == "PASS"
                else "GRACE_PERIOD_THRESHOLD_UNRESOLVED"
            )
            return self.state, status, reason, "grace_period_ms"

        if state == "READY_TO_CUT" and event == "cut":
            self.state = "POWER_CUT"
            host_status = _host_status(self.scenario)
            grace_status = _threshold_status(self.scenario, "grace_period_ms")
            status, _, _ = _dominant(
                [
                    {"status": host_status, "rule_id": "", "reason_code": ""},
                    {"status": grace_status, "rule_id": "", "reason_code": ""},
                ]
            )
            reason = (
                "SYNTHETIC_POWER_CUT_EVENT_RECORDED"
                if status == "PASS"
                else "POWER_CUT_AUTHORIZATION_UNRESOLVED"
            )
            return self.state, status, reason, "grace_period_ms"

        if state == "POWER_CUT" and event == "restart":
            self.state = "RESTART"
            status = _threshold_status(self.scenario, "restart_minimum_ms")
            reason = (
                "SYNTHETIC_RESTART_EVENT_RECORDED"
                if status == "PASS"
                else "RESTART_THRESHOLD_UNRESOLVED"
            )
            return self.state, status, reason, "restart_minimum_ms"

        if state == "WAIT_ACK" and event == "host-notify":
            status, reason = self._protocol_result(
                "DUPLICATE_HOST_NOTIFY_IGNORED",
                "DUPLICATE_HOST_NOTIFY_PROTOCOL_UNRESOLVED",
            )
            return self.state, status, reason, None

        if state == "POWER_CUT" and event == "cut":
            return self.state, "PASS", "DUPLICATE_CUT_IGNORED", "grace_period_ms"

        return state, "FAIL", "INVALID_EVENT_ORDER", None


def _can_run_fsm(scenario: Any, issues: Sequence[Mapping[str, Any]]) -> bool:
    if not isinstance(scenario, Mapping):
        return False
    events = scenario.get("events")
    if not isinstance(events, list) or not events:
        return False
    if any(item.get("status") == "FAIL" for item in issues):
        return False
    return True


def _run_trace(scenario: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    machine = ShutdownStateMachine(scenario)
    trace: list[dict[str, Any]] = []
    events = scenario.get("events")
    if not isinstance(events, list):
        return trace, machine.state
    for index, item in enumerate(events, start=1):
        if not isinstance(item, Mapping):
            break
        event = item.get("event")
        elapsed = item.get("elapsed_time")
        if not isinstance(event, str) or event not in EVENTS or not _is_number(elapsed):
            break
        previous = machine.state
        next_state, status, reason_code, threshold_name = machine.apply(event)
        trace.append(
            {
                "sequence": index,
                "previous_state": previous,
                "event": event,
                "next_state": next_state,
                "elapsed_time": elapsed,
                "threshold_source": _threshold_trace(scenario, threshold_name),
                "status": status,
                "rule_id": f"REP03-SHUTDOWN-FSM-{index:03d}",
                "reason_code": reason_code,
            }
        )
    return trace, machine.state


def _safe_host_contract(scenario: Any) -> tuple[str | None, str | None, dict[str, str] | None]:
    host = scenario.get("host_contract") if isinstance(scenario, Mapping) else None
    if not isinstance(host, Mapping):
        return None, None, None
    model = host.get("raspberry_pi_model")
    protocol = host.get("protocol_id")
    return (
        model if isinstance(model, str) and model.strip() else None,
        protocol if isinstance(protocol, str) and protocol.strip() else None,
        _safe_source(host.get("source")),
    )


def run_scenario(scenario: Any) -> dict[str, Any]:
    """Validate and execute one synthetic event list as JSON-compatible data."""

    input_hash = normalized_input_hash(scenario)
    issues = _validate_scenario(scenario)
    trace: list[dict[str, Any]] = []
    final_state = "IGNITION_ON"
    if _can_run_fsm(scenario, issues):
        trace, final_state = _run_trace(scenario)

    # ``known_gaps`` is fixed to GAP-04 in this schema version.  Metadata in a
    # scenario cannot self-close that externally owned gap, even when it looks
    # authoritative; therefore it participates in the dominant result.
    gap_gate = {
        "status": "BLOCKED",
        "rule_id": _GAP_04["rule_id"],
        "reason_code": _GAP_04["reason_code"],
    }
    status_inputs: list[Mapping[str, Any]] = list(issues) + list(trace) + [gap_gate]
    status, rule_id, reason_code = _dominant(status_inputs)
    scenario_id = scenario.get("scenario_id") if isinstance(scenario, Mapping) else None
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        scenario_id = None
    variant_id = scenario.get("variant_id") if isinstance(scenario, Mapping) else None
    if not isinstance(variant_id, str):
        variant_id = None
    model, protocol, host_source = _safe_host_contract(scenario)
    host_status = _host_status(scenario) if isinstance(scenario, Mapping) else "FAIL"
    timing_statuses = (
        [_threshold_status(scenario, name) for name in TIMING_NAMES]
        if isinstance(scenario, Mapping)
        else ["FAIL"]
    )
    timing_status, _, _ = _dominant(
        [
            {"status": item, "rule_id": "", "reason_code": ""}
            for item in timing_statuses
        ]
    )
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
        "initial_state": "IGNITION_ON",
        "final_state": final_state,
        "time_unit": "ms",
        "trace": trace,
        "dependencies": {
            "GAP-04": dict(_GAP_04),
            "host_protocol": {
                "status": host_status,
                "rule_id": "REP03-SHUTDOWN-HOST-010",
                "reason_code": (
                    "HOST_PROTOCOL_PINNED"
                    if host_status == "PASS"
                    else "HOST_MODEL_OR_PROTOCOL_UNRESOLVED"
                ),
                "raspberry_pi_model": model,
                "protocol_id": protocol,
                "source": host_source,
            },
            "timing_policy": {
                "status": timing_status,
                "rule_id": "REP03-SHUTDOWN-TIME-010",
                "reason_code": (
                    "TIMING_POLICY_PINNED"
                    if timing_status == "PASS"
                    else "TIMING_POLICY_UNRESOLVED"
                ),
            },
        },
        "issues": issues,
        "claims": {
            "validation_level": "SYNTHETIC",
            "real_os_shutdown": False,
            "physical_power_cut": False,
            "host_protocol_validated": False,
            "raspberry_pi_model_validated": False,
            "safe_shutdown_claim": False,
        },
    }

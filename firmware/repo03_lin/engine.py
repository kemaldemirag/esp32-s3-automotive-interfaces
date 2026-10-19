"""Deterministic, synthetic-only LIN event engine for REP-03.

Responsibilities are intentionally separated:

* :class:`UartPeripheralBoundary` classifies synthetic UART observations.
* :class:`LinTransceiverBoundary` resolves transceiver/profile source data and
  the two thresholds that depend on that profile.
* :class:`LinStateMachine` owns state transitions and has no UART or hardware
  access.
* :class:`ScenarioRunner` validates and coordinates the boundaries.

A successful UART event is only a synthetic peripheral result.  It is never
evidence that a LIN transceiver or physical bus behaved correctly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any


SCHEMA_VERSION = "repo03.lin.scenario.v1"
TOOL_VERSION = "repo03-lin-engine/1.0.0"
ENGINE_ID = "repo03-lin-engine"
MODULE_ID = "lin"
VARIANT_A_MODULES = frozenset({"can", "lin", "gnss"})
VARIANT_CONTRACT_SCHEMA = "repo03.variant.schema.v1"
APPROVED_VARIANT_A_PROFILE_HASH = (
    "f74c42bb2a2519ab563a91cb05cfb6d4e5accd9d6f2570ed89604bbad5e0367e"
)

STATES = frozenset(
    {
        "sleep",
        "wake-request",
        "awake",
        "frame-wait",
        "timeout",
        "stuck-dominant",
        "fault",
    }
)

EVENT_DOMAINS = {
    "wake-request": "state-control",
    "wake-detected": "lin-transceiver",
    "sleep-request": "state-control",
    "frame-request": "state-control",
    "uart-frame-received": "uart-peripheral",
    "wake-timeout": "timer",
    "frame-timeout": "timer",
    "bus-dominant": "lin-bus",
    "bus-recessive": "lin-bus",
    "fault-detected": "lin-transceiver",
    "reset": "state-control",
}

WAKE_SOURCES = {
    "wake-request": "synthetic-control",
    "wake-detected": "synthetic-transceiver-observation",
    "wake-timeout": "synthetic-timer",
}

ALLOWED_TOP_LEVEL_FIELDS = frozenset(
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
        "initial_state",
        "uart_peripheral",
        "lin_transceiver",
        "lin_bus",
        "state_policy",
        "events",
    }
)

_FORBIDDEN_PHYSICAL_KEYS = frozenset(
    {
        "exact_part",
        "part_number",
        "physical_pass",
        "physical_voltage",
        "measured_voltage",
        "bus_voltage",
        "voltage",
        "part",
        "measured",
        "physical",
        "hardware_validated",
    }
)

_FORBIDDEN_PHYSICAL_KEY_FRAGMENTS = (
    "physical_pass",
    "physical_bus",
    "physical_validation",
    "measured",
    "voltage",
    "part_number",
    "exact_part",
    "hardware_validated",
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

_RESOLVED_SOURCES = frozenset(
    {"SOURCE_EXPLICIT", "DERIVED", "ENGINEERING_RULE"}
)
_STATUS_PRIORITY = {"PASS": 0, "UNKNOWN": 1, "BLOCKED": 2, "FAIL": 3}


def _normalise_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalise_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalise_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"__invalid_number__": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return {"__unsupported_type__": type(value).__name__}


def normalized_input_hash(scenario: Any) -> str:
    """Return a deterministic SHA-256 hash of a JSON-compatible scenario."""

    payload = json.dumps(
        _normalise_json_value(scenario),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


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


def _validate_allowed_keys(
    value: Mapping[Any, Any],
    allowed: set[str] | frozenset[str],
    path: str,
    reason_code: str,
    issues: list[dict[str, str]],
) -> None:
    unknown = {key for key in value if not isinstance(key, str) or key not in allowed}
    if unknown:
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-SCHEMA-006",
                reason_code,
                path,
                "Unknown fields are not permitted by the versioned scenario contract.",
            )
        )


def _dominant(items: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    if not items:
        return "PASS", "REP03-LIN-RUN-000", "LIN_SCENARIO_COMPLETED"
    selected = max(
        enumerate(items),
        key=lambda pair: (_STATUS_PRIORITY.get(str(pair[1].get("status")), 3), -pair[0]),
    )[1]
    return (
        str(selected.get("status", "FAIL")),
        str(selected.get("rule_id", "REP03-LIN-RUN-999")),
        str(selected.get("reason_code", "UNSPECIFIED_FAILURE")),
    )


def _not_applicable_threshold() -> dict[str, Any]:
    return {
        "name": None,
        "value_ms": None,
        "classification": "NOT_APPLICABLE",
        "reference": None,
        "version": None,
    }


def _find_forbidden_physical_keys(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[str]:
    """Return input paths that attempt to inject physical/hardware evidence."""

    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = path + (key_text,)
            lowered_key = key_text.lower()
            if (
                lowered_key in _FORBIDDEN_PHYSICAL_KEYS
                or any(fragment in lowered_key for fragment in _FORBIDDEN_PHYSICAL_KEY_FRAGMENTS)
            ):
                found.append(".".join(child_path))
            found.extend(_find_forbidden_physical_keys(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_find_forbidden_physical_keys(item, path + (f"[{index}]",)))
    return found


@dataclass(frozen=True)
class Threshold:
    """A duration and the source used to justify it."""

    name: str
    value_ms: float
    classification: str
    reference: str | None
    version: str

    def as_trace_source(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value_ms": self.value_ms,
            "classification": self.classification,
            "reference": self.reference,
            "version": self.version,
        }


class UartPeripheralBoundary:
    """Validate synthetic UART observations without making LIN bus claims."""

    @staticmethod
    def validate_profile(profile: Any, issues: list[dict[str, str]]) -> None:
        if profile is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-UART-001",
                    "UART_PROFILE_MISSING",
                    "uart_peripheral",
                    "A synthetic UART peripheral profile is required.",
                )
            )
            return
        if not isinstance(profile, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-UART-003",
                    "UART_PROFILE_INVALID",
                    "uart_peripheral",
                    "UART profile is present but is not an object.",
                )
            )
            return
        _validate_allowed_keys(
            profile,
            {"mode", "source"},
            "uart_peripheral",
            "UNKNOWN_UART_PROFILE_FIELD",
            issues,
        )
        mode = profile.get("mode")
        if mode is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-UART-004",
                    "UART_MODE_MISSING",
                    "uart_peripheral.mode",
                    "Synthetic UART mode is required.",
                )
            )
        elif mode != "synthetic":
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-UART-002",
                    "UART_MODE_NOT_SYNTHETIC",
                    "uart_peripheral.mode",
                    "Only synthetic UART observations are permitted at this gate.",
                )
            )
        _validate_source(
            profile.get("source"),
            "uart_peripheral.source",
            "UART_SOURCE",
            issues,
        )

    @staticmethod
    def physical_evidence_claim() -> dict[str, str]:
        return {
            "status": "UNKNOWN",
            "rule_id": "REP03-LIN-CLAIM-001",
            "reason_code": "SYNTHETIC_UART_NOT_PHYSICAL_LIN_EVIDENCE",
        }


class LinBusBoundary:
    """Validate the synthetic bus-observation source independently."""

    @staticmethod
    def validate_profile(profile: Any, issues: list[dict[str, str]]) -> None:
        if profile is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-BUS-004",
                    "BUS_PROFILE_MISSING",
                    "lin_bus",
                    "A sourced synthetic LIN bus observation profile is required.",
                )
            )
            return
        if not isinstance(profile, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-BUS-008",
                    "BUS_PROFILE_INVALID",
                    "lin_bus",
                    "LIN bus profile is present but is not an object.",
                )
            )
            return
        _validate_allowed_keys(
            profile,
            {"mode", "source"},
            "lin_bus",
            "UNKNOWN_BUS_PROFILE_FIELD",
            issues,
        )
        mode = profile.get("mode")
        if mode is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-BUS-009",
                    "BUS_MODE_MISSING",
                    "lin_bus.mode",
                    "Synthetic bus mode is required.",
                )
            )
        elif mode != "synthetic":
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-BUS-005",
                    "BUS_MODE_NOT_SYNTHETIC",
                    "lin_bus.mode",
                    "Only synthetic bus observations are permitted at this gate.",
                )
            )
        _validate_source(
            profile.get("source"),
            "lin_bus.source",
            "BUS_SOURCE",
            issues,
        )


class LinTransceiverBoundary:
    """Resolve the synthetic transceiver profile and sourced thresholds."""

    def __init__(self, profile: Mapping[str, Any], thresholds: Mapping[str, Threshold]):
        self.profile_id = str(profile["profile_id"])
        source = profile["source"]
        self.source_reference = str(source["reference"])
        self.source_version = str(source["version"])
        self.thresholds = dict(thresholds)

    @classmethod
    def build(
        cls,
        profile: Any,
        issues: list[dict[str, str]],
    ) -> LinTransceiverBoundary | None:
        if profile is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-XCVR-001",
                    "TRANSCEIVER_PROFILE_MISSING",
                    "lin_transceiver",
                    "A sourced LIN transceiver behavioural profile is required.",
                )
            )
            return None
        if not isinstance(profile, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-XCVR-005",
                    "TRANSCEIVER_PROFILE_INVALID",
                    "lin_transceiver",
                    "Transceiver profile is present but is not an object.",
                )
            )
            return None

        _validate_allowed_keys(
            profile,
            {
                "profile_id",
                "scope",
                "operational_state",
                "source",
                "wake_timeout_ms",
                "stuck_dominant_ms",
            },
            "lin_transceiver",
            "UNKNOWN_TRANSCEIVER_PROFILE_FIELD",
            issues,
        )

        profile_id = profile.get("profile_id")
        if profile_id is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-XCVR-002",
                    "TRANSCEIVER_PROFILE_ID_MISSING",
                    "lin_transceiver.profile_id",
                    "The transceiver behavioural profile must have an identifier.",
                )
            )
        elif not isinstance(profile_id, str) or not profile_id.strip():
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-XCVR-006",
                    "TRANSCEIVER_PROFILE_ID_INVALID",
                    "lin_transceiver.profile_id",
                    "Transceiver profile identifier must be a non-empty string.",
                )
            )

        operational_state = profile.get("operational_state")
        if operational_state is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-XCVR-003",
                    "TRANSCEIVER_OPERATIONAL_STATE_MISSING",
                    "lin_transceiver.operational_state",
                    "The transceiver operational state is required.",
                )
            )
        elif operational_state == "off":
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-XCVR-003",
                    "TRANSCEIVER_UNAVAILABLE",
                    "lin_transceiver.operational_state",
                    "The sourced synthetic transceiver profile is explicitly off.",
                )
            )
        elif operational_state != "synthetic-enabled":
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-XCVR-007",
                    "TRANSCEIVER_OPERATIONAL_STATE_INVALID",
                    "lin_transceiver.operational_state",
                    "Operational state is outside the approved enumeration.",
                )
            )

        scope = profile.get("scope")
        if scope is None:
            issues.append(
                _issue(
                    "BLOCKED",
                    "REP03-LIN-XCVR-008",
                    "TRANSCEIVER_SCOPE_MISSING",
                    "lin_transceiver.scope",
                    "The transceiver model scope is required.",
                )
            )
        elif scope != "SYNTHETIC_BEHAVIOURAL_MODEL":
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-XCVR-004",
                    "TRANSCEIVER_SCOPE_INVALID",
                    "lin_transceiver.scope",
                    "Only the explicitly synthetic behavioural-model scope is permitted.",
                )
            )

        source_issue_count = len(issues)
        _validate_source(
            profile.get("source"),
            "lin_transceiver.source",
            "TRANSCEIVER_SOURCE",
            issues,
        )
        source_valid = (
            len(issues) == source_issue_count
            and isinstance(profile.get("source"), Mapping)
        )
        thresholds: dict[str, Threshold] = {}
        for name in ("wake_timeout_ms", "stuck_dominant_ms"):
            threshold = _read_threshold(profile.get(name), name, f"lin_transceiver.{name}", issues)
            if threshold is not None:
                thresholds[name] = threshold

        if (
            not isinstance(profile_id, str)
            or not profile_id.strip()
            or operational_state != "synthetic-enabled"
            or scope != "SYNTHETIC_BEHAVIOURAL_MODEL"
            or not source_valid
            or len(thresholds) != 2
        ):
            return None
        return cls(profile, thresholds)


def _validate_source(
    source: Any,
    path: str,
    label: str,
    issues: list[dict[str, str]],
) -> None:
    if source is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-SOURCE-001",
                f"{label}_MISSING",
                path,
                "Source metadata is required.",
            )
        )
        return
    if not isinstance(source, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-SOURCE-008",
                f"{label}_INVALID",
                path,
                "Source metadata is present but is not an object.",
            )
        )
        return

    _validate_allowed_keys(
        source,
        {"classification", "reference", "version", "note"},
        path,
        "UNKNOWN_SOURCE_FIELD",
        issues,
    )

    classification = source.get("classification")
    if classification is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-SOURCE-011",
                f"{label}_CLASSIFICATION_MISSING",
                f"{path}.classification",
                "Source classification is required.",
            )
        )
    elif not isinstance(classification, str) or classification not in SOURCE_CLASSIFICATIONS:
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-SOURCE-002",
                f"{label}_CLASSIFICATION_INVALID",
                f"{path}.classification",
                "Source classification is outside the approved enumeration.",
            )
        )
    elif classification == "CONFLICT":
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-SOURCE-003",
                f"{label}_CONFLICT",
                f"{path}.classification",
                "Conflicting source evidence blocks execution.",
            )
        )
    elif classification not in _RESOLVED_SOURCES:
        issues.append(
            _issue(
                "UNKNOWN",
                "REP03-LIN-SOURCE-004",
                f"{label}_UNKNOWN",
                f"{path}.classification",
                "The source is unknown or only an assumption.",
            )
        )

    reference = source.get("reference")
    version = source.get("version")
    if reference is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-SOURCE-005",
                f"{label}_REFERENCE_MISSING",
                f"{path}.reference",
                "Source metadata needs a non-empty reference.",
            )
        )
    elif not isinstance(reference, str) or not reference.strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-SOURCE-009",
                f"{label}_REFERENCE_INVALID",
                f"{path}.reference",
                "Source reference is present but is not a non-empty string.",
            )
        )
    if version is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-SOURCE-006",
                f"{label}_VERSION_MISSING",
                f"{path}.version",
                "Source metadata needs a non-empty version.",
            )
        )
    elif not isinstance(version, str) or not version.strip():
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-SOURCE-010",
                f"{label}_VERSION_INVALID",
                f"{path}.version",
                "Source version is present but is not a non-empty string.",
            )
        )
    if "note" in source and not isinstance(source["note"], str):
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-SOURCE-007",
                f"{label}_NOTE_INVALID",
                f"{path}.note",
                "Source note must be a string when present.",
            )
        )


def _read_threshold(
    raw: Any,
    name: str,
    path: str,
    issues: list[dict[str, str]],
) -> Threshold | None:
    if raw is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-THRESHOLD-001",
                "THRESHOLD_MISSING",
                path,
                f"{name} and its source are required.",
            )
        )
        return None
    if not isinstance(raw, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-THRESHOLD-003",
                "THRESHOLD_INVALID",
                path,
                f"{name} is present but is not an object.",
            )
        )
        return None

    _validate_allowed_keys(
        raw,
        {"value_ms", "source"},
        path,
        "UNKNOWN_THRESHOLD_FIELD",
        issues,
    )

    value = raw.get("value_ms")
    if value is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-THRESHOLD-002",
                "THRESHOLD_VALUE_UNRESOLVED",
                f"{path}.value_ms",
                "Threshold value must be a finite, non-negative number.",
            )
        )
        value_ok = False
    elif not _is_number(value) or value < 0:
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-THRESHOLD-004",
                "THRESHOLD_VALUE_INVALID",
                f"{path}.value_ms",
                "Threshold value is present but is not a finite, non-negative number.",
            )
        )
        value_ok = False
    else:
        value_ok = True

    source = raw.get("source")
    before = len(issues)
    _validate_source(source, f"{path}.source", "THRESHOLD_SOURCE", issues)
    source_ok = len(issues) == before
    if not value_ok or not source_ok or not isinstance(source, Mapping):
        return None

    return Threshold(
        name=name,
        value_ms=float(value),
        classification=str(source["classification"]),
        reference=(
            str(source["reference"])
            if source.get("reference") is not None
            else None
        ),
        version=str(source["version"]),
    )


def _read_state_policy(
    policy: Any,
    issues: list[dict[str, str]],
) -> dict[str, Threshold]:
    if policy is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-FSM-001",
                "STATE_POLICY_MISSING",
                "state_policy",
                "Sourced synthetic state thresholds are required.",
            )
        )
        return {}
    if not isinstance(policy, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-FSM-002",
                "STATE_POLICY_INVALID",
                "state_policy",
                "State policy is present but is not an object.",
            )
        )
        return {}
    _validate_allowed_keys(
        policy,
        {"frame_timeout_ms", "min_awake_before_sleep_ms"},
        "state_policy",
        "UNKNOWN_STATE_POLICY_FIELD",
        issues,
    )
    result: dict[str, Threshold] = {}
    for name in ("frame_timeout_ms", "min_awake_before_sleep_ms"):
        threshold = _read_threshold(policy.get(name), name, f"state_policy.{name}", issues)
        if threshold is not None:
            result[name] = threshold
    return result


def _validate_variant_contract(
    contract: Any,
    issues: list[dict[str, str]],
) -> None:
    """Pin execution to the approved D1 Variant A contract artifact."""

    if contract is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-D1-001",
                "VARIANT_CONTRACT_MISSING",
                "variant_contract",
                "The approved Variant A contract reference and hash are required.",
            )
        )
        return
    if not isinstance(contract, Mapping):
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-D1-004",
                "VARIANT_CONTRACT_INVALID",
                "variant_contract",
                "Variant contract is present but is not an object.",
            )
        )
        return
    _validate_allowed_keys(
        contract,
        {"schema_version", "profile_hash", "source"},
        "variant_contract",
        "UNKNOWN_VARIANT_CONTRACT_FIELD",
        issues,
    )
    contract_schema = contract.get("schema_version")
    if contract_schema is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-D1-005",
                "VARIANT_CONTRACT_SCHEMA_MISSING",
                "variant_contract.schema_version",
                "Variant contract schema version is required.",
            )
        )
    elif contract_schema != VARIANT_CONTRACT_SCHEMA:
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-D1-002",
                "VARIANT_CONTRACT_SCHEMA_MISMATCH",
                "variant_contract.schema_version",
                f"Variant contract schema must equal {VARIANT_CONTRACT_SCHEMA!r}.",
            )
        )
    profile_hash = contract.get("profile_hash")
    if profile_hash is None:
        issues.append(
            _issue(
                "BLOCKED",
                "REP03-LIN-D1-006",
                "VARIANT_CONTRACT_HASH_MISSING",
                "variant_contract.profile_hash",
                "Approved Variant A profile hash is required.",
            )
        )
    elif not isinstance(profile_hash, str) or profile_hash != APPROVED_VARIANT_A_PROFILE_HASH:
        issues.append(
            _issue(
                "FAIL",
                "REP03-LIN-D1-003",
                "VARIANT_CONTRACT_HASH_MISMATCH",
                "variant_contract.profile_hash",
                "Scenario is not pinned to the approved Variant A profile hash.",
            )
        )
    _validate_source(
        contract.get("source"),
        "variant_contract.source",
        "VARIANT_CONTRACT_SOURCE",
        issues,
    )


@dataclass(frozen=True)
class Transition:
    new_state: str
    status: str
    rule_id: str
    reason_code: str
    threshold: Threshold | None = None


class LinStateMachine:
    """Pure state transition logic; no peripheral or bus access occurs here."""

    def __init__(self, initial_state: str):
        self.state = initial_state
        self.total_elapsed_ms = 0.0
        self.state_elapsed_ms = 0.0
        self.awake_since_ms: float | None = None

    def step(
        self,
        event: str,
        elapsed_time_ms: float,
        thresholds: Mapping[str, Threshold],
        observation_duration_ms: float | None = None,
    ) -> Transition:
        self.total_elapsed_ms += elapsed_time_ms
        self.state_elapsed_ms += elapsed_time_ms
        previous = self.state

        if event == "reset":
            transition = Transition(
                "sleep", "PASS", "REP03-LIN-FSM-009", "RESET_TO_SLEEP"
            )
        elif event == "fault-detected":
            transition = Transition(
                "fault", "FAIL", "REP03-LIN-FSM-008", "FAULT_DETECTED"
            )
        elif event == "bus-dominant":
            threshold = thresholds["stuck_dominant_ms"]
            if (
                observation_duration_ms is not None
                and observation_duration_ms >= threshold.value_ms
            ):
                transition = Transition(
                    "stuck-dominant",
                    "FAIL",
                    "REP03-LIN-BUS-001",
                    "STUCK_DOMINANT",
                    threshold,
                )
            else:
                transition = Transition(
                    previous,
                    "PASS",
                    "REP03-LIN-BUS-002",
                    "BUS_DOMINANT_BELOW_THRESHOLD",
                    threshold,
                )
        elif event == "bus-recessive":
            transition = Transition(
                previous,
                "PASS",
                "REP03-LIN-BUS-003",
                "BUS_RECESSIVE_OBSERVED",
            )
        elif previous == "sleep" and event == "wake-request":
            transition = Transition(
                "wake-request",
                "PASS",
                "REP03-LIN-FSM-010",
                "WAKE_REQUEST_ACCEPTED",
            )
        elif previous == "wake-request" and event == "wake-detected":
            threshold = thresholds["wake_timeout_ms"]
            if self.state_elapsed_ms <= threshold.value_ms:
                transition = Transition(
                    "awake",
                    "PASS",
                    "REP03-LIN-XCVR-010",
                    "WAKE_CONFIRMED",
                    threshold,
                )
            else:
                transition = Transition(
                    "timeout",
                    "FAIL",
                    "REP03-LIN-XCVR-011",
                    "WAKE_TIMEOUT_EXCEEDED",
                    threshold,
                )
        elif previous == "wake-request" and event == "wake-timeout":
            threshold = thresholds["wake_timeout_ms"]
            if self.state_elapsed_ms >= threshold.value_ms:
                transition = Transition(
                    "timeout",
                    "FAIL",
                    "REP03-LIN-XCVR-012",
                    "WAKE_TIMEOUT",
                    threshold,
                )
            else:
                transition = Transition(
                    "fault",
                    "FAIL",
                    "REP03-LIN-XCVR-013",
                    "WAKE_TIMEOUT_BEFORE_THRESHOLD",
                    threshold,
                )
        elif previous == "awake" and event == "frame-request":
            transition = Transition(
                "frame-wait",
                "PASS",
                "REP03-LIN-FSM-020",
                "FRAME_WAIT_ENTERED",
            )
        elif previous == "frame-wait" and event == "uart-frame-received":
            threshold = thresholds["frame_timeout_ms"]
            if self.state_elapsed_ms <= threshold.value_ms:
                transition = Transition(
                    "awake",
                    "PASS",
                    "REP03-LIN-UART-010",
                    "SYNTHETIC_UART_FRAME_ACCEPTED",
                    threshold,
                )
            else:
                transition = Transition(
                    "timeout",
                    "FAIL",
                    "REP03-LIN-UART-011",
                    "FRAME_TIMEOUT_EXCEEDED",
                    threshold,
                )
        elif previous == "frame-wait" and event == "frame-timeout":
            threshold = thresholds["frame_timeout_ms"]
            if self.state_elapsed_ms >= threshold.value_ms:
                transition = Transition(
                    "timeout",
                    "FAIL",
                    "REP03-LIN-UART-012",
                    "FRAME_TIMEOUT",
                    threshold,
                )
            else:
                transition = Transition(
                    "fault",
                    "FAIL",
                    "REP03-LIN-UART-013",
                    "FRAME_TIMEOUT_BEFORE_THRESHOLD",
                    threshold,
                )
        elif previous == "awake" and event == "sleep-request":
            threshold = thresholds["min_awake_before_sleep_ms"]
            awake_elapsed = (
                0.0
                if self.awake_since_ms is None
                else self.total_elapsed_ms - self.awake_since_ms
            )
            if awake_elapsed >= threshold.value_ms:
                transition = Transition(
                    "sleep",
                    "PASS",
                    "REP03-LIN-FSM-030",
                    "SLEEP_CONFIRMED",
                    threshold,
                )
            else:
                transition = Transition(
                    "fault",
                    "FAIL",
                    "REP03-LIN-FSM-031",
                    "RAPID_RE_SLEEP",
                    threshold,
                )
        else:
            transition = Transition(
                "fault",
                "FAIL",
                "REP03-LIN-FSM-099",
                "INVALID_EVENT_ORDER",
            )

        self.state = transition.new_state
        if previous != self.state:
            self.state_elapsed_ms = 0.0
        if previous == "wake-request" and self.state == "awake":
            self.awake_since_ms = self.total_elapsed_ms
        elif self.state in {"sleep", "fault", "timeout", "stuck-dominant"}:
            self.awake_since_ms = None
        return transition


class ScenarioRunner:
    """Validate input and execute the pure FSM with deterministic output."""

    def run(self, scenario: Any) -> dict[str, Any]:
        input_hash = normalized_input_hash(scenario)
        issues: list[dict[str, str]] = []

        if not isinstance(scenario, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCHEMA-001",
                    "SCENARIO_NOT_OBJECT",
                    "$",
                    "Scenario must be a JSON object.",
                )
            )
            return self._preflight_report(scenario, input_hash, "sleep", issues)

        if scenario.get("schema_version") != SCHEMA_VERSION:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCHEMA-002",
                    "SCHEMA_VERSION_MISMATCH",
                    "schema_version",
                    f"schema_version must equal {SCHEMA_VERSION!r}.",
                )
            )
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCHEMA-007",
                    "SCENARIO_ID_INVALID",
                    "scenario_id",
                    "scenario_id must be a non-empty string.",
                )
            )
        if scenario.get("engine_id") != ENGINE_ID:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-003",
                    "ENGINE_ID_INVALID",
                    "engine_id",
                    f"engine_id must equal {ENGINE_ID!r}.",
                )
            )
        if scenario.get("module_id") != MODULE_ID:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-004",
                    "MODULE_ID_INVALID",
                    "module_id",
                    f"module_id must equal {MODULE_ID!r}.",
                )
            )
        _validate_source(
            scenario.get("source"),
            "source",
            "SCENARIO_SOURCE",
            issues,
        )
        unknown_top_level = {
            key
            for key in scenario
            if not isinstance(key, str) or key not in ALLOWED_TOP_LEVEL_FIELDS
        }
        if unknown_top_level:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCHEMA-005",
                    "UNKNOWN_TOP_LEVEL_FIELD",
                    "$",
                    "Unknown top-level fields are not permitted.",
                )
            )
        if scenario.get("variant_id") != "A":
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-001",
                    "VARIANT_A_REQUIRED",
                    "variant_id",
                    "The LIN scenario contract is restricted to REP-03 Variant A.",
                )
            )
        _validate_variant_contract(scenario.get("variant_contract"), issues)
        enabled_modules = scenario.get("enabled_modules")
        if (
            not isinstance(enabled_modules, list)
            or "lin" not in enabled_modules
            or not all(isinstance(module, str) for module in enabled_modules)
        ):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-002",
                    "LIN_MODULE_NOT_ENABLED",
                    "enabled_modules",
                    "Variant A must explicitly enable the LIN module.",
                )
            )
        elif len(enabled_modules) != len(set(enabled_modules)):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-005",
                    "DUPLICATE_ENABLED_MODULE",
                    "enabled_modules",
                    "enabled_modules must not contain duplicates.",
                )
            )
        elif set(enabled_modules) - VARIANT_A_MODULES:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-006",
                    "FOREIGN_MODULE_ENABLED",
                    "enabled_modules",
                    "Variant A scenario enables a module outside can/lin/gnss.",
                )
            )
        elif set(enabled_modules) != VARIANT_A_MODULES:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCOPE-007",
                    "VARIANT_A_MODULE_SET_MISMATCH",
                    "enabled_modules",
                    "Variant A requires exactly can, lin, and gnss modules.",
                )
            )
        forbidden_paths = _find_forbidden_physical_keys(scenario)
        if forbidden_paths:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-CLAIM-003",
                    "PHYSICAL_EVIDENCE_INJECTION_FORBIDDEN",
                    forbidden_paths[0],
                    "Scenario fixtures must not contain physical voltage, part, or PASS claims.",
                )
            )
        if scenario.get("synthetic_data") is not True:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-CLAIM-002",
                    "SYNTHETIC_DATA_REQUIRED",
                    "synthetic_data",
                    "The engine accepts synthetic_data=true only.",
                )
            )

        initial_state = scenario.get("initial_state")
        if not isinstance(initial_state, str) or initial_state not in STATES:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCHEMA-003",
                    "INITIAL_STATE_INVALID",
                    "initial_state",
                    "initial_state is outside the LIN FSM state enumeration.",
                )
            )
            initial_state = "sleep"

        UartPeripheralBoundary.validate_profile(
            scenario.get("uart_peripheral"), issues
        )
        LinBusBoundary.validate_profile(scenario.get("lin_bus"), issues)
        transceiver = LinTransceiverBoundary.build(
            scenario.get("lin_transceiver"), issues
        )
        policy_thresholds = _read_state_policy(scenario.get("state_policy"), issues)
        events = scenario.get("events")
        if not isinstance(events, list):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-SCHEMA-004",
                    "EVENTS_NOT_ARRAY",
                    "events",
                    "events must be an ordered array.",
                )
            )
            events = []
        elif not events:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-EVENT-005",
                    "EVENTS_EMPTY",
                    "events",
                    "At least one ordered synthetic event is required.",
                )
            )

        validated_events: list[dict[str, Any]] = []
        for index, raw_event in enumerate(events):
            validated = self._validate_event(raw_event, index, issues)
            if validated is not None:
                validated_events.append(validated)

        if issues:
            return self._preflight_report(scenario, input_hash, initial_state, issues)
        if transceiver is None or len(policy_thresholds) != 2:
            fallback = _issue(
                "BLOCKED",
                "REP03-LIN-RUN-001",
                "REQUIRED_RUNTIME_INPUT_UNRESOLVED",
                "$",
                "Runtime inputs could not be resolved.",
            )
            return self._preflight_report(
                scenario, input_hash, initial_state, [fallback]
            )

        thresholds = dict(transceiver.thresholds)
        thresholds.update(policy_thresholds)
        machine = LinStateMachine(initial_state)
        trace: list[dict[str, Any]] = []
        runtime_issues: list[dict[str, str]] = []
        uart_state = "idle"
        transceiver_state = "unknown"
        bus_observation = "unknown"

        domain_sources = {
            "state-control": scenario["source"],
            "timer": scenario["source"],
            "uart-peripheral": scenario["uart_peripheral"]["source"],
            "lin-transceiver": scenario["lin_transceiver"]["source"],
            "lin-bus": scenario["lin_bus"]["source"],
        }

        for index, event in enumerate(validated_events):
            previous = machine.state
            transition = machine.step(
                event["event"],
                float(event["elapsed_time_ms"]),
                thresholds,
                (
                    float(event["observation_duration_ms"])
                    if event["observation_duration_ms"] is not None
                    else None
                ),
            )
            if (
                event["domain"] == "uart-peripheral"
                and event["event"] == "uart-frame-received"
            ):
                uart_state = "received"

            if event["domain"] == "lin-transceiver":
                if event["event"] == "wake-detected":
                    transceiver_state = "wake-observed"
                elif event["event"] == "fault-detected":
                    transceiver_state = "fault-observed"

            if event["domain"] == "lin-bus":
                if event["event"] == "bus-dominant":
                    bus_observation = (
                        "stuck-dominant"
                        if transition.new_state == "stuck-dominant"
                        else "dominant"
                    )
                elif event["event"] == "bus-recessive":
                    bus_observation = "recessive"

            event_source = domain_sources[event["domain"]]

            trace_row = {
                "event_index": index,
                "previous_state": previous,
                "new_state": transition.new_state,
                "event": event["event"],
                "elapsed_time_ms": event["elapsed_time_ms"],
                "observation_duration_ms": event["observation_duration_ms"],
                "elapsed_total_ms": machine.total_elapsed_ms,
                "wake_source": event["wake_source"],
                "responsibility": event["domain"],
                "uart_state": uart_state,
                "transceiver_state": transceiver_state,
                "bus_observation": bus_observation,
                "threshold_source": (
                    transition.threshold.as_trace_source()
                    if transition.threshold is not None
                    else _not_applicable_threshold()
                ),
                "status": transition.status,
                "rule_id": transition.rule_id,
                "reason_code": transition.reason_code,
                "input_hash": input_hash,
                "tool_version": TOOL_VERSION,
                "schema_version": SCHEMA_VERSION,
                "source_reference": (
                    transition.threshold.reference
                    if transition.threshold is not None
                    else event_source["reference"]
                ),
                "source_version": (
                    transition.threshold.version
                    if transition.threshold is not None
                    else event_source["version"]
                ),
            }
            trace.append(trace_row)
            if transition.status != "PASS":
                runtime_issues.append(
                    _issue(
                        transition.status,
                        transition.rule_id,
                        transition.reason_code,
                        f"events[{index}]",
                        "The event produced a non-PASS LIN FSM transition.",
                    )
                )

        status, rule_id, reason_code = _dominant(runtime_issues)
        return self._report(
            scenario,
            input_hash,
            initial_state,
            machine.state,
            trace,
            runtime_issues,
            status,
            rule_id,
            reason_code,
        )

    @staticmethod
    def _validate_event(
        raw_event: Any,
        index: int,
        issues: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        path = f"events[{index}]"
        if not isinstance(raw_event, Mapping):
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-EVENT-001",
                    "EVENT_NOT_OBJECT",
                    path,
                    "Every event must be an object.",
                )
            )
            return None

        allowed_fields = {
            "event",
            "domain",
            "elapsed_time_ms",
            "wake_source",
            "observation_duration_ms",
        }
        unknown_fields = set(raw_event) - allowed_fields
        if unknown_fields:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-EVENT-004",
                    "UNKNOWN_EVENT_FIELD",
                    path,
                    "Event object contains a field outside its versioned contract.",
                )
            )

        event = raw_event.get("event")
        event_valid = isinstance(event, str) and event in EVENT_DOMAINS
        if not event_valid:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-EVENT-002",
                    "EVENT_UNKNOWN",
                    f"{path}.event",
                    "Event name is outside the supported enumeration.",
                )
            )
        domain = raw_event.get("domain")
        expected_domain = EVENT_DOMAINS.get(event) if event_valid else None
        if expected_domain is not None and domain != expected_domain:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-BOUNDARY-001",
                    "EVENT_DOMAIN_MISMATCH",
                    f"{path}.domain",
                    f"{event!r} belongs to {expected_domain!r}, not {domain!r}.",
                )
            )

        wake_source = raw_event.get("wake_source")
        wake_source_valid = True
        if event_valid and event in WAKE_SOURCES:
            expected_wake_source = WAKE_SOURCES[event]
            if wake_source != expected_wake_source:
                wake_source_valid = False
                issues.append(
                    _issue(
                        "FAIL",
                        "REP03-LIN-WAKE-001",
                        "WAKE_SOURCE_INVALID",
                        f"{path}.wake_source",
                        f"{event!r} requires wake_source={expected_wake_source!r}.",
                    )
                )
        elif "wake_source" in raw_event:
            wake_source_valid = False
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-WAKE-002",
                    "WAKE_SOURCE_NOT_ALLOWED",
                    f"{path}.wake_source",
                    "wake_source is permitted only on wake events.",
                )
            )

        observation_duration = raw_event.get("observation_duration_ms")
        observation_valid = True
        if event == "bus-dominant":
            if not _is_number(observation_duration) or observation_duration < 0:
                observation_valid = False
                issues.append(
                    _issue(
                        "FAIL",
                        "REP03-LIN-BUS-006",
                        "OBSERVATION_DURATION_INVALID",
                        f"{path}.observation_duration_ms",
                        "bus-dominant requires a finite, non-negative observation duration.",
                    )
                )
        elif "observation_duration_ms" in raw_event:
            observation_valid = False
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-BUS-007",
                    "OBSERVATION_DURATION_NOT_ALLOWED",
                    f"{path}.observation_duration_ms",
                    "observation_duration_ms is permitted only for bus-dominant.",
                )
            )
        elapsed = raw_event.get("elapsed_time_ms")
        if not _is_number(elapsed) or elapsed < 0:
            issues.append(
                _issue(
                    "FAIL",
                    "REP03-LIN-EVENT-003",
                    "ELAPSED_TIME_INVALID",
                    f"{path}.elapsed_time_ms",
                    "elapsed_time_ms must be a finite, non-negative number.",
                )
            )

        if (
            not event_valid
            or domain != expected_domain
            or not _is_number(elapsed)
            or elapsed < 0
            or bool(unknown_fields)
            or not wake_source_valid
            or not observation_valid
        ):
            return None
        return {
            "event": event,
            "domain": domain,
            "elapsed_time_ms": elapsed,
            "wake_source": wake_source if event in WAKE_SOURCES else None,
            "observation_duration_ms": (
                observation_duration if event == "bus-dominant" else None
            ),
        }

    def _preflight_report(
        self,
        scenario: Any,
        input_hash: str,
        initial_state: str,
        issues: list[dict[str, str]],
    ) -> dict[str, Any]:
        status, rule_id, reason_code = _dominant(issues)
        trace = [
            {
                "event_index": None,
                "previous_state": initial_state,
                "new_state": initial_state,
                "event": "preflight",
                "elapsed_time_ms": 0,
                "observation_duration_ms": None,
                "elapsed_total_ms": 0,
                "wake_source": None,
                "responsibility": "scenario-preflight",
                "uart_state": "not-run",
                "transceiver_state": "unknown",
                "bus_observation": "unknown",
                "threshold_source": _not_applicable_threshold(),
                "status": status,
                "rule_id": rule_id,
                "reason_code": reason_code,
                "input_hash": input_hash,
                "tool_version": TOOL_VERSION,
                "schema_version": SCHEMA_VERSION,
                "source_version": (
                    _string_or_none(scenario.get("source", {}).get("version"))
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("source"), Mapping)
                    else None
                ),
                "source_reference": (
                    _string_or_none(scenario.get("source", {}).get("reference"))
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("source"), Mapping)
                    else None
                ),
            }
        ]
        return self._report(
            scenario,
            input_hash,
            initial_state,
            initial_state,
            trace,
            issues,
            status,
            rule_id,
            reason_code,
        )

    @staticmethod
    def _report(
        scenario: Any,
        input_hash: str,
        initial_state: str,
        final_state: str,
        trace: list[dict[str, Any]],
        issues: list[dict[str, str]],
        status: str,
        rule_id: str,
        reason_code: str,
    ) -> dict[str, Any]:
        scenario_id = scenario.get("scenario_id") if isinstance(scenario, Mapping) else None
        return {
            "schema_version": SCHEMA_VERSION,
            "scenario_id": scenario_id,
            "engine_id": ENGINE_ID,
            "module_id": MODULE_ID,
            "variant_id": (
                scenario.get("variant_id") if isinstance(scenario, Mapping) else None
            ),
            "status": status,
            "result": {"status": status},
            "rule_id": rule_id,
            "reason_code": reason_code,
            "initial_state": initial_state,
            "final_state": final_state,
            "trace": trace,
            "issues": issues,
            "input_hash": input_hash,
            "tool_version": TOOL_VERSION,
            "synthetic_data": True,
            "claims": {
                "validation_level": "SYNTHETIC",
                "uart_result_scope": "SYNTHETIC_PERIPHERAL_ONLY",
                "physical_lin_evidence": UartPeripheralBoundary.physical_evidence_claim(),
            },
            "source_versions": {
                "scenario_schema": SCHEMA_VERSION,
                "scenario_source_reference": (
                    _string_or_none(scenario.get("source", {}).get("reference"))
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("source"), Mapping)
                    else None
                ),
                "scenario_source_version": (
                    _string_or_none(scenario.get("source", {}).get("version"))
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("source"), Mapping)
                    else None
                ),
                "transceiver_profile": (
                    _string_or_none(
                        scenario.get("lin_transceiver", {}).get("profile_id")
                    )
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("lin_transceiver"), Mapping)
                    else None
                ),
                "variant_contract_schema": (
                    _string_or_none(
                        scenario.get("variant_contract", {}).get("schema_version")
                    )
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("variant_contract"), Mapping)
                    else None
                ),
                "variant_contract_profile_hash": (
                    _string_or_none(
                        scenario.get("variant_contract", {}).get("profile_hash")
                    )
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("variant_contract"), Mapping)
                    else None
                ),
                "uart_source_reference": (
                    _string_or_none(
                        scenario.get("uart_peripheral", {})
                        .get("source", {})
                        .get("reference")
                    )
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("uart_peripheral"), Mapping)
                    and isinstance(scenario.get("uart_peripheral", {}).get("source"), Mapping)
                    else None
                ),
                "bus_source_reference": (
                    _string_or_none(
                        scenario.get("lin_bus", {}).get("source", {}).get("reference")
                    )
                    if isinstance(scenario, Mapping)
                    and isinstance(scenario.get("lin_bus"), Mapping)
                    and isinstance(scenario.get("lin_bus", {}).get("source"), Mapping)
                    else None
                ),
            },
            "dependencies": {
                "GAP-01": {
                    "status": "UNKNOWN",
                    "rule_id": "REP03-LIN-DEP-001",
                    "reason_code": "EXACT_TRANSCEIVER_NOT_PHYSICALLY_VERIFIED",
                }
            },
        }


def run_scenario(scenario: Any) -> dict[str, Any]:
    """Run a synthetic LIN scenario and return a deterministic report."""

    return ScenarioRunner().run(scenario)

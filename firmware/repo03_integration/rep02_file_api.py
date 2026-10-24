"""Build the minimal INT-02A REP-03 -> REP-02 offline handoff.

This module intentionally has no REP-02 import.  It creates deterministic
artifact bytes and a descriptor that can be evaluated by the separately
installed, hash-pinned REP-02 wheel.  A successful handoff proves descriptor
shape and exact-file integrity only; it is not a live adapter, semantic power
mapping, REP-02 rail-budget execution, or hardware validation.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


DEPENDENCY_FILE_NAME = "rep02_dependency.v1.json"
DESCRIPTOR_FILE_NAME = "rep03-to-rep02.descriptor.json"
ARTIFACT_RELATIVE_PATH = "artifacts/power-nominal-001.report.json"

REPORT_SCHEMA_VERSION = "repo03.automotive-power.scenario.v1"
REPORT_TOOL_VERSION = "repo03-power-engine/1.0.0"
REPORT_VARIANT_ID = "B"
REPORT_MODULE_ID = "automotive_power"
REPORT_SCENARIO_ID = "POWER-NOMINAL-001"
REPORT_INPUT_HASH = "cf78b5cabb6a210c67462e0d10521ab7f070f0fe848900fb70f3b26175ed97c5"
REPORT_ARTIFACT_SHA256 = "283b71938deefb22a2cc89192f2193c2f52967224cd5408d63e8d0cae900c256"

DESCRIPTOR_ID = "INT-02A-REP03-POWER-NOMINAL-001"
CONFIGURATION_ID = "REP03-VARIANT-B"
PROFILE_ID = REPORT_SCENARIO_ID
ARTIFACT_ID = "REP03-POWER-NOMINAL-001-REPORT"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_DEPENDENCY_PATH = Path(__file__).with_name(DEPENDENCY_FILE_NAME)

_COMPATIBILITY = {
    "api_version_match": "EXACT",
    "schema_version_match": "EXACT",
    "incompatible_version_status": "BLOCKED",
    "malformed_json_status": "BLOCKED",
    "hash_mismatch_status": "BLOCKED",
    "missing_artifact_status": "NOT_RUN",
}

_REPORT_ROOT_KEYS = {
    "adapter_mapping",
    "claims",
    "dependencies",
    "engine_id",
    "input_hash",
    "issues",
    "module_id",
    "profile_assessment",
    "reason_code",
    "requirements",
    "result",
    "rule_id",
    "scenario_id",
    "schema_version",
    "source_versions",
    "status",
    "synthetic_data",
    "tool_version",
    "variant_id",
}

_FALSE_CLAIMS = {
    "aec_qualification",
    "exact_part_decision",
    "iso_compliance",
    "oem_compliance",
    "physical_validation",
    "rep02_execution",
}

_CLAIM_KEYS = _FALSE_CLAIMS | {"validation_level"}

_REPORT_BINDING_KEYS = {
    "variant_id",
    "module_id",
    "schema_version",
    "scenario_id",
    "input_hash",
    "embedded_d2_integration_status",
    "embedded_d2_execution_status",
}


class HandoffValidationError(ValueError):
    """Structured fail-closed error raised before a descriptor is written."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(f"{code} at {path}: {message}")
        self.code = code
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {
            "status": "BLOCKED",
            "reason_code": self.code,
            "path": self.path,
            "message": self.message,
        }


class _DuplicateJsonKey(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON token {token!r}")


def _expect_exact_keys(
    value: Any,
    expected: set[str],
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HandoffValidationError("OBJECT_REQUIRED", path, "value must be a JSON object")
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        unknown = sorted(observed - expected)
        detail = f"missing={missing!r}, unknown={unknown!r}"
        raise HandoffValidationError("CLOSED_OBJECT_MISMATCH", path, detail)
    return value


def _check_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HandoffValidationError(
                "NON_FINITE_NUMBER",
                path,
                "non-finite numbers are forbidden in handoff JSON",
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise HandoffValidationError(
                    "NON_STRING_OBJECT_KEY",
                    path,
                    "JSON object keys must be strings",
                )
            _check_json_value(item, f"{path}.{key}")
        return
    raise HandoffValidationError(
        "UNSUPPORTED_JSON_TYPE",
        path,
        f"unsupported JSON value type {type(value).__name__}",
    )


def _canonical_json_bytes(value: Any) -> bytes:
    _check_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    _check_json_value(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def dependency_contract() -> dict[str, Any]:
    """Load and structurally validate the pinned INT-02A dependency record."""

    try:
        document = json.loads(
            _DEPENDENCY_PATH.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise HandoffValidationError(
            "DEPENDENCY_CONTRACT_UNAVAILABLE",
            str(_DEPENDENCY_PATH),
            "dependency contract could not be loaded strictly",
        ) from exc

    root = _expect_exact_keys(
        document,
        {
            "schema_version",
            "integration_id",
            "integration_scope",
            "rep02",
            "claim_limits",
            "provenance_notes",
        },
        "$",
    )
    if root["schema_version"] != "repo03.rep02-dependency.v1":
        raise HandoffValidationError(
            "DEPENDENCY_SCHEMA_VERSION_MISMATCH",
            "$.schema_version",
            "expected repo03.rep02-dependency.v1",
        )
    if root["integration_id"] != "INT-02A":
        raise HandoffValidationError(
            "INTEGRATION_ID_MISMATCH",
            "$.integration_id",
            "expected INT-02A",
        )
    if root["integration_scope"] != "OFFLINE_FILE_INTEGRITY_ONLY":
        raise HandoffValidationError(
            "INTEGRATION_SCOPE_EXPANDED",
            "$.integration_scope",
            "INT-02A is limited to offline descriptor and byte integrity",
        )

    rep02 = _expect_exact_keys(
        root["rep02"],
        {
            "repository_id",
            "repository_name",
            "source_baseline_commit",
            "package_name",
            "package_version",
            "wheel",
            "file_api",
        },
        "$.rep02",
    )
    if rep02["repository_id"] != "REP-02":
        raise HandoffValidationError(
            "REP02_REPOSITORY_ID_MISMATCH",
            "$.rep02.repository_id",
            "expected REP-02",
        )
    wheel = _expect_exact_keys(
        rep02["wheel"],
        {
            "file_name",
            "sha256",
            "size_bytes",
            "build_record_head",
            "build_record_working_tree",
            "build_record_status_entries",
        },
        "$.rep02.wheel",
    )
    file_api = _expect_exact_keys(
        rep02["file_api"],
        {
            "api_version",
            "descriptor_schema_version",
            "engine_version",
            "rule_id",
            "tool_name",
            "contract_source_id",
            "contract_sha256",
        },
        "$.rep02.file_api",
    )
    for path, digest in (
        ("$.rep02.source_baseline_commit", rep02["source_baseline_commit"]),
        ("$.rep02.wheel.build_record_head", wheel["build_record_head"]),
    ):
        if not isinstance(digest, str) or _GIT_SHA1_RE.fullmatch(digest) is None:
            raise HandoffValidationError("GIT_COMMIT_INVALID", path, "expected 40 lowercase hex characters")
    for path, digest in (
        ("$.rep02.wheel.sha256", wheel["sha256"]),
        ("$.rep02.file_api.contract_sha256", file_api["contract_sha256"]),
    ):
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise HandoffValidationError("SHA256_INVALID", path, "expected lowercase SHA-256")
    claims = root["claim_limits"]
    if not isinstance(claims, list) or len(claims) != 5 or len(set(claims)) != 5:
        raise HandoffValidationError(
            "CLAIM_LIMITS_INVALID",
            "$.claim_limits",
            "exactly five unique REP-02 claim limits are required",
        )
    if not all(isinstance(item, str) and item for item in claims):
        raise HandoffValidationError(
            "CLAIM_LIMITS_INVALID",
            "$.claim_limits",
            "claim limits must be non-empty strings",
        )
    _check_json_value(document)
    return document


def canonical_report_bytes(report: Any) -> bytes:
    """Return the one byte representation bound by the artifact SHA-256."""

    return _canonical_json_bytes(report)


def descriptor_input_hash(descriptor: Mapping[str, Any]) -> str:
    """Mirror REP-02's documented canonical hash for descriptor construction."""

    if not isinstance(descriptor, Mapping):
        raise HandoffValidationError(
            "DESCRIPTOR_OBJECT_REQUIRED",
            "$",
            "descriptor must be a JSON object",
        )
    payload = {key: value for key, value in descriptor.items() if key != "input_hash"}
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def validate_report_binding(report: Any) -> dict[str, str]:
    """Validate the narrow Variant B nominal report accepted by INT-02A."""

    if not isinstance(report, Mapping):
        raise HandoffValidationError(
            "REPORT_OBJECT_REQUIRED",
            "$",
            "REP-03 report must be a JSON object",
        )
    report = _expect_exact_keys(report, _REPORT_ROOT_KEYS, "$")
    _check_json_value(report)

    expected = {
        "variant_id": REPORT_VARIANT_ID,
        "module_id": REPORT_MODULE_ID,
        "schema_version": REPORT_SCHEMA_VERSION,
        "scenario_id": REPORT_SCENARIO_ID,
        "tool_version": REPORT_TOOL_VERSION,
        "status": "PASS",
        "input_hash": REPORT_INPUT_HASH,
    }
    for field, target in expected.items():
        if report.get(field) != target:
            code = "VARIANT_B_REQUIRED" if field == "variant_id" else "REPORT_BINDING_MISMATCH"
            raise HandoffValidationError(
                code,
                f"$.{field}",
                f"expected {target!r}",
            )
    if report.get("synthetic_data") is not True:
        raise HandoffValidationError(
            "SYNTHETIC_REPORT_REQUIRED",
            "$.synthetic_data",
            "INT-02A accepts only the pinned synthetic report",
        )
    input_hash = report["input_hash"]

    profile = report.get("profile_assessment")
    if not isinstance(profile, Mapping) or profile.get("profile_type") != "nominal":
        raise HandoffValidationError(
            "NOMINAL_PROFILE_REQUIRED",
            "$.profile_assessment.profile_type",
            "the first INT-02A slice accepts only the nominal profile",
        )
    claims = _expect_exact_keys(report["claims"], _CLAIM_KEYS, "$.claims")
    if claims["validation_level"] != "SYNTHETIC":
        raise HandoffValidationError(
            "SYNTHETIC_CLAIM_BOUNDARY_REQUIRED",
            "$.claims.validation_level",
            "validation level must remain SYNTHETIC",
        )
    for name in sorted(_FALSE_CLAIMS):
        if claims[name] is not False:
            raise HandoffValidationError(
                "REAL_WORLD_CLAIM_FORBIDDEN",
                f"$.claims.{name}",
                "offline handoff requires the claim to be the boolean false",
            )

    dependencies = report.get("dependencies")
    rep02 = dependencies.get("rep02") if isinstance(dependencies, Mapping) else None
    if not isinstance(rep02, Mapping):
        raise HandoffValidationError(
            "D2_BOUNDARY_MISSING",
            "$.dependencies.rep02",
            "historical D2 capability-map boundary must remain explicit",
        )
    if rep02.get("integration_status") != "BLOCKED" or rep02.get("execution_status") != "NOT_RUN":
        raise HandoffValidationError(
            "D2_BOUNDARY_EXPANDED",
            "$.dependencies.rep02",
            "INT-02A must not rewrite the D2 capability map as a live execution",
        )

    return {
        "variant_id": REPORT_VARIANT_ID,
        "module_id": REPORT_MODULE_ID,
        "schema_version": REPORT_SCHEMA_VERSION,
        "scenario_id": REPORT_SCENARIO_ID,
        "input_hash": input_hash,
        "embedded_d2_integration_status": "BLOCKED",
        "embedded_d2_execution_status": "NOT_RUN",
    }


def build_descriptor(artifact_sha256: str, report_binding: Mapping[str, str]) -> dict[str, Any]:
    """Build the closed REP-02 descriptor for one materialized report."""

    if not isinstance(artifact_sha256, str) or _SHA256_RE.fullmatch(artifact_sha256) is None:
        raise HandoffValidationError(
            "ARTIFACT_SHA256_INVALID",
            "$.artifact_sha256",
            "expected lowercase SHA-256",
        )
    if artifact_sha256 != REPORT_ARTIFACT_SHA256:
        raise HandoffValidationError(
            "ARTIFACT_SHA256_MISMATCH",
            "$.artifact_sha256",
            "descriptor construction is limited to the pinned nominal artifact",
        )
    report_binding = _expect_exact_keys(
        report_binding,
        _REPORT_BINDING_KEYS,
        "$.report_binding",
    )
    expected_binding = {
        "variant_id": REPORT_VARIANT_ID,
        "module_id": REPORT_MODULE_ID,
        "schema_version": REPORT_SCHEMA_VERSION,
        "scenario_id": REPORT_SCENARIO_ID,
        "input_hash": REPORT_INPUT_HASH,
        "embedded_d2_integration_status": "BLOCKED",
        "embedded_d2_execution_status": "NOT_RUN",
    }
    for field, expected_value in expected_binding.items():
        if report_binding[field] != expected_value:
            code = "VARIANT_B_REQUIRED" if field == "variant_id" else "REPORT_BINDING_MISMATCH"
            raise HandoffValidationError(
                code,
                f"$.report_binding.{field}",
                f"expected {expected_value!r}",
            )

    dependency = dependency_contract()
    api = dependency["rep02"]["file_api"]
    descriptor: dict[str, Any] = {
        "api_version": api["api_version"],
        "schema_version": api["descriptor_schema_version"],
        "descriptor_id": DESCRIPTOR_ID,
        "producer": {
            "repository_id": "REP-03",
            "api_version": api["api_version"],
            "schema_version": api["descriptor_schema_version"],
        },
        "consumer": {
            "repository_id": "REP-02",
            "api_version": api["api_version"],
            "schema_version": api["descriptor_schema_version"],
        },
        "compatibility": dict(_COMPATIBILITY),
        "configurations": [
            {
                "configuration_id": CONFIGURATION_ID,
                "profile_id": PROFILE_ID,
                "artifacts": [
                    {
                        "artifact_id": ARTIFACT_ID,
                        "role": "ASSESSMENT_INPUT",
                        "file_name": ARTIFACT_RELATIVE_PATH,
                        "media_type": "application/json",
                        "access_status": "AVAILABLE",
                        "sha256": artifact_sha256,
                    }
                ],
                "artifact_gaps": [],
            }
        ],
        "claim_limits": list(dependency["claim_limits"]),
    }
    descriptor["input_hash"] = descriptor_input_hash(descriptor)
    return descriptor


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def materialize_power_handoff(scenario: Any, output_root: str | Path) -> dict[str, Any]:
    """Run the pinned REP-03 power scenario and write one deterministic bundle."""

    from repo03_power import run_scenario

    report = run_scenario(scenario)
    binding = validate_report_binding(report)
    report_bytes = canonical_report_bytes(report)
    artifact_sha256 = hashlib.sha256(report_bytes).hexdigest()
    descriptor = build_descriptor(artifact_sha256, binding)

    root = Path(output_root)
    artifact_path = root.joinpath(*ARTIFACT_RELATIVE_PATH.split("/"))
    descriptor_path = root / DESCRIPTOR_FILE_NAME
    _atomic_write(artifact_path, report_bytes)
    _atomic_write(descriptor_path, _pretty_json_bytes(descriptor))

    return {
        "report": report,
        "report_binding": binding,
        "artifact_path": artifact_path,
        "artifact_size_bytes": len(report_bytes),
        "artifact_sha256": artifact_sha256,
        "descriptor": descriptor,
        "descriptor_path": descriptor_path,
        "descriptor_input_hash": descriptor["input_hash"],
    }

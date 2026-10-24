"""Closed, deterministic aggregate reporting for REP-03 variants.

Only the public APIs exported by the contract and scenario packages are used.
The report is intentionally synthetic and carries no physical-validation or
automotive-compliance claim.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Callable

from repo03_can import run_scenario as run_can
from repo03_contract import validate_profile
from repo03_gnss import run_scenario as run_gnss
from repo03_lin import run_scenario as run_lin
from repo03_power import run_scenario as run_automotive_power
from repo03_shutdown import run_scenario as run_shutdown

from . import __version__


REPORT_SCHEMA_VERSION = "repo03.variant-report.v1"
REPORT_TOOL_VERSION = f"repo03-cli/{__version__}"

_MODULES_BY_VARIANT: dict[str, tuple[str, ...]] = {
    "A": ("can", "lin", "gnss"),
    "B": ("automotive_power", "shutdown"),
}
_RUNNERS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "can": run_can,
    "lin": run_lin,
    "gnss": run_gnss,
    "automotive_power": run_automotive_power,
    "shutdown": run_shutdown,
}
_STATUS_PRIORITY = {
    "PASS": 0,
    "NOT_RUN": 1,
    "UNKNOWN": 2,
    "BLOCKED": 3,
    "FAIL": 4,
}
_CLAIMS = {
    "validation_level": "SYNTHETIC",
    "physical_validation": False,
    "hardware_validation": False,
    "rf_validation": False,
    "automotive_compliance": False,
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _status_of(report: Mapping[str, Any], name: str) -> str:
    status = report.get("status")
    if not isinstance(status, str) or status not in _STATUS_PRIORITY:
        raise RuntimeError(f"{name} returned an unsupported status")
    return status


def _require_variant(value: Mapping[str, Any], variant_id: str, name: str) -> None:
    if value.get("variant_id") != variant_id:
        raise ValueError(f"{name} variant_id must match --variant {variant_id}")


def build_report(
    variant_id: str,
    profile: Mapping[str, Any],
    modules: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Run one isolated variant and return its deterministic aggregate report.

    ``modules`` must contain the complete module set for the selected variant
    and no module from the other variant. Inputs are not echoed into the
    result; they are bound through the canonical ``input_hash`` instead.
    """

    if variant_id not in _MODULES_BY_VARIANT:
        raise ValueError("variant_id must be 'A' or 'B'")
    if not isinstance(profile, Mapping) or not isinstance(modules, Mapping):
        raise ValueError("profile and modules must be objects")

    expected_modules = _MODULES_BY_VARIANT[variant_id]
    if set(modules) != set(expected_modules):
        raise ValueError(
            f"variant {variant_id} requires exactly: {', '.join(expected_modules)}"
        )

    _require_variant(profile, variant_id, "profile")
    for module_name in expected_modules:
        module_input = modules[module_name]
        if not isinstance(module_input, Mapping):
            raise ValueError(f"{module_name} input must be an object")
        _require_variant(module_input, variant_id, module_name)

    reports: dict[str, dict[str, Any]] = {
        "profile": validate_profile(profile),
    }
    for module_name in expected_modules:
        reports[module_name] = _RUNNERS[module_name](modules[module_name])

    statuses = [
        _status_of(report, report_name)
        for report_name, report in reports.items()
    ]
    status = max(statuses, key=_STATUS_PRIORITY.__getitem__)
    hash_envelope = {
        "variant_id": variant_id,
        "inputs": {
            "profile": profile,
            "modules": {name: modules[name] for name in expected_modules},
        },
    }

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": REPORT_TOOL_VERSION,
        "variant_id": variant_id,
        "status": status,
        "rule_id": "REP03-CLI-REPORT-000",
        "reason_code": f"VARIANT_REPORT_{status}",
        "input_hash": hashlib.sha256(_canonical_bytes(hash_envelope)).hexdigest(),
        "reports": reports,
        "claims": dict(_CLAIMS),
    }

"""D1 variant contract tests using only the Python standard library.

The structurally valid A and B fixtures intentionally retain unresolved sources.
They exercise contract isolation without claiming physical validation.
"""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

from repo03_contract.validator import validate_profile


FIXTURES = Path(__file__).resolve().parents[1] / "variants" / "fixtures"
RESULT_STATUSES = {"PASS", "FAIL", "UNKNOWN", "BLOCKED", "NOT_RUN"}


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def result_status(result: dict[str, Any]) -> str:
    """Read the public status while checking the nested compatibility field."""

    status = result["status"]
    nested = result.get("result", {})
    if "status" in nested:
        if nested["status"] != status:
            raise AssertionError("top-level and nested result statuses differ")
    return status


class VariantContractTests(unittest.TestCase):
    def assert_result_envelope(self, result: dict[str, Any]) -> None:
        self.assertIn(result_status(result), RESULT_STATUSES)
        self.assertIsInstance(result.get("issues"), list)
        self.assertTrue(result.get("profile_hash"))
        self.assertTrue(result.get("input_hash"))
        self.assertTrue(result.get("tool_version"))

        for issue in result["issues"]:
            self.assertIn("rule_id", issue)
            self.assertIn("reason_code", issue)
            self.assertIn("status", issue)

    def test_variant_a_is_structurally_valid_and_isolated(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        self.assertEqual(profile["enabled_modules"], ["can", "lin", "gnss"])
        self.assertEqual(set(profile["modules"]), {"can", "lin", "gnss"})
        self.assertNotIn("integrations", profile)

        result = validate_profile(profile)

        self.assert_result_envelope(result)
        self.assertIn(result_status(result), {"UNKNOWN", "BLOCKED"})

    def test_variant_b_is_structurally_valid_and_isolated(self) -> None:
        profile = load_fixture("valid_variant_b.json")
        self.assertEqual(
            profile["enabled_modules"], ["automotive_power", "shutdown"]
        )
        self.assertEqual(set(profile["modules"]), {"automotive_power", "shutdown"})
        self.assertIn("rep02", profile["integrations"])

        result = validate_profile(profile)

        self.assert_result_envelope(result)
        self.assertIn(result_status(result), {"UNKNOWN", "BLOCKED"})

    def test_combined_profile_fails(self) -> None:
        result = validate_profile(load_fixture("invalid_combined.json"))

        self.assert_result_envelope(result)
        self.assertEqual(result_status(result), "FAIL")

    def test_missing_variant_id_fails(self) -> None:
        result = validate_profile(load_fixture("invalid_missing_variant_id.json"))

        self.assert_result_envelope(result)
        self.assertEqual(result_status(result), "FAIL")

    def test_unknown_module_fails(self) -> None:
        result = validate_profile(load_fixture("invalid_unknown_module.json"))

        self.assert_result_envelope(result)
        self.assertEqual(result_status(result), "FAIL")

    def test_missing_source_input_is_blocked_not_pass(self) -> None:
        result = validate_profile(load_fixture("blocked_missing_source_input.json"))

        self.assert_result_envelope(result)
        self.assertEqual(result_status(result), "BLOCKED")
        self.assertTrue(
            any(
                issue.get("status") == "BLOCKED"
                and issue.get("reason_code") == "SOURCE_VALUE_UNRESOLVED"
                and issue.get("path") == "modules.gnss.hardware.value"
                for issue in result["issues"]
            ),
            "unresolved GNSS source value must be explicit and traceable",
        )

    def test_profile_hash_is_deterministic_and_key_order_independent(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        reordered = dict(reversed(list(deepcopy(profile).items())))
        reordered["enabled_modules"] = list(reversed(profile["enabled_modules"]))
        reordered["modules"] = dict(reversed(list(profile["modules"].items())))

        first = validate_profile(profile)
        second = validate_profile(profile)
        reordered_result = validate_profile(reordered)

        self.assertEqual(first["profile_hash"], second["profile_hash"])
        self.assertEqual(first["profile_hash"], reordered_result["profile_hash"])
        self.assertEqual(first["input_hash"], second["input_hash"])

    def test_variant_leakage_reason_codes_are_reported(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        profile["enabled_modules"].append("shutdown")
        profile["modules"]["shutdown"] = {}
        profile["integrations"] = {"rep02": {}}

        result = validate_profile(profile)
        reason_codes = {issue["reason_code"] for issue in result["issues"]}

        self.assertEqual(result_status(result), "FAIL")
        self.assertIn("VARIANT_MODULE_LEAKAGE", reason_codes)
        self.assertIn("VARIANT_DEFINITION_LEAKAGE", reason_codes)
        self.assertIn("VARIANT_INTEGRATION_LEAKAGE", reason_codes)

    def test_unknown_nested_field_fails(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        profile["modules"]["can"]["extra"] = {}

        result = validate_profile(profile)

        self.assertEqual(result_status(result), "FAIL")
        self.assertTrue(
            any(
                issue["reason_code"] == "UNKNOWN_MODULE_FIELD"
                for issue in result["issues"]
            )
        )

    def test_enum_values_are_case_sensitive(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        profile["source"]["classification"] = "engineering_rule"

        result = validate_profile(profile)

        self.assertEqual(result_status(result), "FAIL")
        self.assertTrue(
            any(
                issue["reason_code"] == "SOURCE_CLASSIFICATION_INVALID"
                for issue in result["issues"]
            )
        )

    def test_hardware_content_is_forbidden_before_gates(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        profile["hardware"] = {"exact_part": "UNVERIFIED"}

        result = validate_profile(profile)

        self.assertEqual(result_status(result), "FAIL")
        self.assertTrue(
            any(
                issue["reason_code"] == "HARDWARE_CONTENT_FORBIDDEN"
                for issue in result["issues"]
            )
        )

    def test_hardware_claim_cannot_hide_in_gate_locked_value(self) -> None:
        profile = load_fixture("valid_variant_a.json")
        profile["modules"]["can"]["transceiver"] = {
            "value": {"exact_part": "UNVERIFIED"},
            "source": {"classification": "SOURCE_EXPLICIT"},
            "result": {"status": "PASS"},
        }
        profile["modules"]["gnss"]["hardware"] = {
            "value": {"rf_validated": True},
            "source": {"classification": "SOURCE_EXPLICIT"},
            "result": {"status": "PASS"},
        }

        result = validate_profile(profile)

        self.assertEqual(result_status(result), "FAIL")
        locked_paths = {
            issue["path"]
            for issue in result["issues"]
            if issue["reason_code"] == "GATE_LOCKED_VALUE_PRESENT"
        }
        self.assertIn("modules.can.transceiver.value", locked_paths)
        self.assertIn("modules.gnss.hardware.value", locked_paths)

    def test_oem_profile_cannot_hide_in_synthetic_event_value(self) -> None:
        profile = load_fixture("valid_variant_b.json")
        profile["modules"]["automotive_power"]["events"] = {
            "value": {"load_dump_voltage": "UNVERIFIED"},
            "source": {"classification": "SOURCE_EXPLICIT"},
            "result": {"status": "PASS"},
        }

        result = validate_profile(profile)

        self.assertEqual(result_status(result), "FAIL")
        self.assertTrue(
            any(
                issue["reason_code"] == "NON_SYNTHETIC_VALUE_FORBIDDEN"
                and issue["path"] == "modules.automotive_power.events.value"
                for issue in result["issues"]
            )
        )

    def test_missing_required_contract_field_fails(self) -> None:
        profile = load_fixture("valid_variant_b.json")
        del profile["integrations"]

        result = validate_profile(profile)

        self.assertEqual(result_status(result), "FAIL")
        self.assertTrue(
            any(
                issue["reason_code"] == "REQUIRED_CONTRACT_FIELD_MISSING"
                and issue["path"] == "integrations.rep02"
                for issue in result["issues"]
            )
        )

    def test_schema_version_mismatch_fails(self) -> None:
        result = validate_profile(load_fixture("invalid_schema_version.json"))

        self.assert_result_envelope(result)
        self.assertEqual(result_status(result), "FAIL")


if __name__ == "__main__":
    unittest.main()

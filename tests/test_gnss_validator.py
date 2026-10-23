"""WF-03-04 synthetic GNSS validator tests (Python standard library only)."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware"
if str(FIRMWARE) not in sys.path:
    sys.path.insert(0, str(FIRMWARE))

from repo03_gnss import (  # noqa: E402
    APPROVED_VARIANT_A_PROFILE_HASH,
    ENGINE_ID,
    MODULE_ID,
    SCHEMA_VERSION,
    TOOL_VERSION,
    VARIANT_CONTRACT_SCHEMA,
    normalized_input_hash,
    run_scenario,
)


FIXTURES = ROOT / "variants" / "fixtures" / "gnss"
SCHEMA = ROOT / "variants" / "schema" / "repo03.gnss.scenario.v1.json"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def reason_codes(report: dict[str, Any]) -> set[str]:
    return {str(issue["reason_code"]) for issue in report["issues"]}


class GnssValidatorTests(unittest.TestCase):
    def assert_report_envelope(self, report: dict[str, Any]) -> None:
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["engine_id"], ENGINE_ID)
        self.assertEqual(report["module_id"], MODULE_ID)
        self.assertEqual(report["variant_id"], "A")
        self.assertIn(report["status"], {"PASS", "FAIL", "UNKNOWN", "BLOCKED"})
        self.assertEqual(report["result"]["status"], report["status"])
        self.assertEqual(len(report["input_hash"]), 64)
        self.assertEqual(report["tool_version"], TOOL_VERSION)
        self.assertTrue(report["synthetic_data"])
        self.assertNotIn("generated_at", report)
        self.assertEqual(
            set(report["source_matrix"]),
            {
                "integration_guide",
                "module_variant",
                "antenna_type",
                "rf_feed",
                "rf_layout_evidence",
                "power_profile",
                "fix_quality",
                "freshness",
                "timestamp",
                "age",
                "antenna_status",
            },
        )
        self.assertEqual(
            set(report["dependencies"]),
            {"GAP-02", "rf_suitability", "physical_gnss"},
        )
        self.assertEqual(len(report["trace"]), 1)
        row = report["trace"][0]
        for field in (
            "status",
            "rule_id",
            "reason_code",
            "threshold_source",
            "input_hash",
            "tool_version",
            "synthetic_data",
        ):
            self.assertIn(field, row)
        self.assertEqual(row["input_hash"], report["input_hash"])
        self.assertEqual(row["tool_version"], TOOL_VERSION)
        self.assertTrue(row["synthetic_data"])

    def test_schema_and_required_fixtures_are_valid_json(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["variant_id"]["const"], "A")
        self.assertEqual(schema["properties"]["module_id"]["const"], "gnss")
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["$defs"]["module_profile"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["observation"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["run_report"]["additionalProperties"])

        expected = {
            "valid_synthetic_fix.json",
            "no_fix.json",
            "stale_lower_boundary.json",
            "stale_upper_boundary.json",
            "timestamp_rollback.json",
            "antenna_fault.json",
            "missing_module.json",
        }
        self.assertEqual({path.name for path in FIXTURES.glob("*.json")}, expected)
        for name in expected:
            with self.subTest(name=name):
                scenario = load_fixture(name)
                self.assertEqual(scenario["schema_version"], SCHEMA_VERSION)
                self.assertEqual(set(scenario), set(schema["required"]))
                self.assertEqual(set(scenario["enabled_modules"]), {"can", "lin", "gnss"})
                self.assertEqual(
                    scenario["variant_contract"]["profile_hash"],
                    APPROVED_VARIANT_A_PROFILE_HASH,
                )

    def test_valid_synthetic_fix_passes_but_rf_remains_blocked(self) -> None:
        report = run_scenario(load_fixture("valid_synthetic_fix.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["reason_code"], "SYNTHETIC_FIX_VALID")
        self.assertEqual(report["dependencies"]["GAP-02"]["status"], "BLOCKED")
        self.assertEqual(report["dependencies"]["rf_suitability"]["status"], "BLOCKED")
        self.assertEqual(
            report["dependencies"]["rf_suitability"]["reason_code"],
            "RF_SUITABILITY_BLOCKED_BY_GAP_02",
        )

    def test_coordinate_claims_are_explicitly_synthetic(self) -> None:
        report = run_scenario(load_fixture("valid_synthetic_fix.json"))

        self.assertEqual(report["claims"]["validation_level"], "SYNTHETIC")
        self.assertEqual(report["claims"]["coordinate_scope"], "SYNTHETIC_TEST_VECTOR")
        self.assertFalse(report["claims"]["coordinates_are_measured"])
        self.assertFalse(report["claims"]["physical_gnss_validation"])
        self.assertFalse(report["claims"]["rf_suitability_validated"])
        self.assertFalse(report["claims"]["antenna_validation"])

    def test_source_matrix_is_traceable_and_closed(self) -> None:
        report = run_scenario(load_fixture("valid_synthetic_fix.json"))
        matrix = report["source_matrix"]

        required = {
            "classification",
            "reference",
            "version",
            "status",
            "rule_id",
            "reason_code",
        }
        for name, row in matrix.items():
            with self.subTest(name=name):
                self.assertEqual(set(row), required)
        self.assertEqual(matrix["integration_guide"]["status"], "BLOCKED")
        self.assertEqual(matrix["antenna_type"]["status"], "BLOCKED")
        self.assertEqual(matrix["rf_feed"]["status"], "BLOCKED")
        self.assertEqual(matrix["rf_layout_evidence"]["status"], "BLOCKED")
        self.assertEqual(matrix["power_profile"]["status"], "PASS")
        self.assertEqual(matrix["fix_quality"]["status"], "PASS")
        self.assertEqual(matrix["freshness"]["status"], "PASS")
        self.assertEqual(matrix["timestamp"]["status"], "PASS")
        self.assertEqual(matrix["age"]["status"], "PASS")
        self.assertEqual(matrix["antenna_status"]["status"], "PASS")

    def test_no_fix_fails_without_coordinates(self) -> None:
        report = run_scenario(load_fixture("no_fix.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["reason_code"], "NO_FIX")
        self.assertIsNone(report["final_observation"]["position"])

    def test_freshness_lower_boundary_is_fresh(self) -> None:
        report = run_scenario(load_fixture("stale_lower_boundary.json"))

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["final_observation"]["age_ms"], 1000)
        self.assertEqual(report["trace"][0]["threshold_source"]["value_ms"], 1000)

    def test_freshness_upper_boundary_is_stale(self) -> None:
        report = run_scenario(load_fixture("stale_upper_boundary.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["reason_code"], "STALE_FIX")
        self.assertEqual(report["final_observation"]["age_ms"], 1001)

    def test_timestamp_rollback_fails(self) -> None:
        report = run_scenario(load_fixture("timestamp_rollback.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("TIMESTAMP_ROLLBACK", reason_codes(report))

    def test_antenna_fault_fails(self) -> None:
        report = run_scenario(load_fixture("antenna_fault.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["reason_code"], "ANTENNA_FAULT")

    def test_unknown_antenna_status_is_blocked(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["antenna_status"] = "UNKNOWN"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("ANTENNA_STATUS_UNRESOLVED", reason_codes(report))

    def test_missing_module_is_blocked(self) -> None:
        report = run_scenario(load_fixture("missing_module.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("MODULE_PROFILE_MISSING", reason_codes(report))
        self.assertEqual(report["trace"][0]["event"], "preflight")

    def test_age_must_match_timestamps(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["age_ms"] = 201

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("AGE_TIMESTAMP_MISMATCH", reason_codes(report))

    def test_evaluation_cannot_precede_fix(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["evaluation_timestamp_ms"] = 99999
        scenario["observation"]["age_ms"] = 0

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("EVALUATION_BEFORE_FIX", reason_codes(report))

    def test_assumed_freshness_threshold_cannot_pass(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["freshness_policy"]["source"]["classification"] = "ASSUMPTION"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "UNKNOWN")
        self.assertIn("FRESHNESS_SOURCE_ASSUMPTION", reason_codes(report))
        self.assertEqual(report["trace"][0]["event"], "preflight")

    def test_unknown_freshness_threshold_cannot_pass(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["freshness_policy"]["source"]["classification"] = "UNKNOWN"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("FRESHNESS_SOURCE_UNRESOLVED", reason_codes(report))

    def test_missing_freshness_source_is_blocked_without_default(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["freshness_policy"]["source"] = None

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("FRESHNESS_SOURCE_MISSING", reason_codes(report))

    def test_source_reference_and_version_are_mandatory(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["source"]["reference"] = ""
        scenario["observation"]["source"]["version"] = ""

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("OBSERVATION_SOURCE_REFERENCE_INVALID", reason_codes(report))
        self.assertIn("OBSERVATION_SOURCE_VERSION_INVALID", reason_codes(report))

    def test_variant_contract_hash_is_pinned(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        self.assertEqual(scenario["variant_contract"]["schema_version"], VARIANT_CONTRACT_SCHEMA)
        scenario["variant_contract"]["profile_hash"] = "0" * 64

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("VARIANT_CONTRACT_HASH_MISMATCH", reason_codes(report))

    def test_variant_engine_module_and_full_module_set_gates(self) -> None:
        mutations = {
            "variant": ("variant_id", "B", "VARIANT_A_REQUIRED"),
            "engine": ("engine_id", "other", "ENGINE_ID_INVALID"),
            "module": ("module_id", "can", "MODULE_ID_INVALID"),
            "missing-gnss": ("enabled_modules", ["can", "lin"], "GNSS_MODULE_NOT_ENABLED"),
            "incomplete": ("enabled_modules", ["gnss"], "VARIANT_A_MODULE_SET_MISMATCH"),
            "foreign": ("enabled_modules", ["can", "lin", "gnss", "power"], "FOREIGN_MODULE_ENABLED"),
            "duplicate": ("enabled_modules", ["can", "lin", "gnss", "gnss"], "DUPLICATE_ENABLED_MODULE"),
        }
        for label, (field, value, expected) in mutations.items():
            with self.subTest(label=label):
                scenario = load_fixture("valid_synthetic_fix.json")
                scenario[field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected, reason_codes(report))

    def test_gap_02_declaration_is_exact(self) -> None:
        for gaps in ([], ["GAP-01"], ["GAP-02", "GAP-02"]):
            with self.subTest(gaps=gaps):
                scenario = load_fixture("valid_synthetic_fix.json")
                scenario["known_gaps"] = gaps
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("GAP_02_DECLARATION_REQUIRED", reason_codes(report))

    def test_hash_and_report_are_deterministic_and_key_order_independent(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        reordered = dict(reversed(list(deepcopy(scenario).items())))
        reordered["module_profile"] = dict(
            reversed(list(scenario["module_profile"].items()))
        )

        first = run_scenario(scenario)
        second = run_scenario(deepcopy(scenario))
        third = run_scenario(reordered)

        self.assertEqual(first, second)
        self.assertEqual(first["input_hash"], third["input_hash"])
        self.assertEqual(first["trace"], third["trace"])
        self.assertEqual(first["input_hash"], normalized_input_hash(scenario))

    def test_enabled_module_order_is_semantically_canonical(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        reordered = deepcopy(scenario)
        reordered["enabled_modules"] = ["gnss", "can", "lin"]

        self.assertEqual(
            normalized_input_hash(scenario),
            normalized_input_hash(reordered),
        )

    def test_wrong_nested_types_return_structured_failures(self) -> None:
        mutations = []
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["source"] = []
        mutations.append((scenario, "SCENARIO_SOURCE_INVALID"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["variant_contract"] = []
        mutations.append((scenario, "VARIANT_CONTRACT_INVALID"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["module_profile"] = []
        mutations.append((scenario, "MODULE_PROFILE_INVALID"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["freshness_policy"] = []
        mutations.append((scenario, "FRESHNESS_POLICY_INVALID"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"] = []
        mutations.append((scenario, "OBSERVATION_INVALID"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["module_profile"]["antenna_type"] = []
        mutations.append((scenario, "ANTENNA-TYPE_INVALID"))

        for scenario, expected in mutations:
            with self.subTest(expected=expected):
                report = run_scenario(scenario)
                self.assert_report_envelope(report)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected, reason_codes(report))

    def test_invalid_observation_values_return_structured_failures(self) -> None:
        mutations = {
            "fix": ("fix_quality", [], "FIX_QUALITY_INVALID"),
            "antenna": ("antenna_status", [], "ANTENNA_STATUS_INVALID"),
            "timestamp": ("timestamp_ms", [], "TIMESTAMP_OR_AGE_INVALID"),
            "previous": ("previous_timestamp_ms", [], "PREVIOUS_TIMESTAMP_INVALID"),
            "age": ("age_ms", True, "TIMESTAMP_OR_AGE_INVALID"),
            "position": ("position", [], "POSITION_INVALID"),
        }
        for label, (field, value, expected) in mutations.items():
            with self.subTest(label=label):
                scenario = load_fixture("valid_synthetic_fix.json")
                scenario["observation"][field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected, reason_codes(report))

    def test_non_finite_and_out_of_range_coordinates_fail(self) -> None:
        cases = [
            ("latitude_deg", float("nan"), "NON_FINITE_NUMBER"),
            ("latitude_deg", 90.1, "LATITUDE_INVALID"),
            ("longitude_deg", -180.1, "LONGITUDE_INVALID"),
            ("altitude_m", float("inf"), "NON_FINITE_NUMBER"),
        ]
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                scenario = load_fixture("valid_synthetic_fix.json")
                scenario["observation"]["position"][field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected, reason_codes(report))

    def test_no_fix_cannot_carry_coordinates(self) -> None:
        scenario = load_fixture("no_fix.json")
        scenario["observation"]["position"] = {
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "altitude_m": None,
            "synthetic_data": True,
        }

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("POSITION_WITHOUT_FIX", reason_codes(report))

    def test_synthetic_position_tag_is_mandatory(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["position"]["synthetic_data"] = False

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SYNTHETIC_POSITION_TAG_REQUIRED", reason_codes(report))

    def test_unknown_nested_fields_are_rejected(self) -> None:
        scenarios = []
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["extra"] = True
        scenarios.append((scenario, "UNKNOWN_SCENARIO_FIELD"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["module_profile"]["extra"] = True
        scenarios.append((scenario, "UNKNOWN_MODULE_PROFILE_FIELD"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["module_profile"]["module_variant"]["extra"] = True
        scenarios.append((scenario, "UNKNOWN_COMPONENT_FIELD"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["freshness_policy"]["extra"] = True
        scenarios.append((scenario, "UNKNOWN_FRESHNESS_POLICY_FIELD"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["extra"] = True
        scenarios.append((scenario, "UNKNOWN_OBSERVATION_FIELD"))
        scenario = load_fixture("valid_synthetic_fix.json")
        scenario["observation"]["position"]["extra"] = True
        scenarios.append((scenario, "UNKNOWN_POSITION_FIELD"))

        for scenario, expected in scenarios:
            with self.subTest(expected=expected):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected, reason_codes(report))

    def test_physical_measurement_and_rf_claims_are_rejected(self) -> None:
        forbidden = [
            ("physical_pass", True),
            ("measured", True),
            ("measured_value", 1),
            ("actual_coordinates", [1, 2]),
            ("rf_suitability", "PASS"),
            ("rf_pass", True),
            ("rf_layout_pass", True),
            ("antenna_validated", True),
            ("antenna_gain", 3),
            ("part_number", "UNVERIFIED"),
            ("voltage", 3.3),
        ]
        for field, value in forbidden:
            with self.subTest(field=field):
                scenario = load_fixture("valid_synthetic_fix.json")
                scenario["observation"][field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("PHYSICAL_OR_RF_CLAIM_FORBIDDEN", reason_codes(report))

    def test_trace_carries_threshold_source_and_versions(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        report = run_scenario(scenario)
        row = report["trace"][0]

        self.assertEqual(row["threshold_source"]["name"], "max_age_ms")
        self.assertEqual(row["threshold_source"]["value_ms"], 1000)
        self.assertEqual(
            row["threshold_source"]["reference"],
            scenario["freshness_policy"]["source"]["reference"],
        )
        self.assertEqual(
            row["source_reference"], scenario["observation"]["source"]["reference"]
        )

    def test_all_gap_sources_traceable_changes_dependency_to_unknown_not_pass(self) -> None:
        scenario = load_fixture("valid_synthetic_fix.json")
        explicit = {
            "classification": "SOURCE_EXPLICIT",
            "reference": "approved/source",
            "version": "1.0.0",
        }
        scenario["module_profile"]["integration_guide"] = deepcopy(explicit)
        scenario["module_profile"]["module_variant"]["source"] = deepcopy(explicit)
        scenario["module_profile"]["antenna_type"]["source"] = deepcopy(explicit)
        scenario["module_profile"]["antenna_type"]["value"] = "SYNTHETIC_ANTENNA"
        scenario["module_profile"]["rf_feed"]["source"] = deepcopy(explicit)
        scenario["module_profile"]["rf_feed"]["value"] = "SYNTHETIC_RF_FEED"
        scenario["module_profile"]["rf_layout_evidence"] = deepcopy(explicit)

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["dependencies"]["GAP-02"]["status"], "UNKNOWN")
        self.assertEqual(report["dependencies"]["rf_suitability"]["status"], "UNKNOWN")
        self.assertFalse(report["claims"]["rf_suitability_validated"])

    def test_run_report_matches_closed_schema_envelope(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        report = run_scenario(load_fixture("valid_synthetic_fix.json"))
        report_schema = schema["$defs"]["run_report"]

        self.assertEqual(set(report), set(report_schema["required"]))
        self.assertEqual(set(report), set(report_schema["properties"]))
        self.assertFalse(report_schema["additionalProperties"])
        for key, definition_name in (
            ("source_versions", "source_versions"),
            ("source_matrix", "source_matrix"),
            ("dependencies", "dependencies"),
            ("claims", "claims"),
        ):
            definition = schema["$defs"][definition_name]
            self.assertEqual(set(report[key]), set(definition["required"]))
            self.assertEqual(set(report[key]), set(definition["properties"]))
            self.assertFalse(definition["additionalProperties"])

    def test_non_mapping_and_unsupported_values_are_hashable_failures(self) -> None:
        for value in ([], None, {"scenario_id": object()}):
            with self.subTest(value=type(value).__name__):
                report = run_scenario(value)
                self.assert_report_envelope(report)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(len(report["input_hash"]), 64)


if __name__ == "__main__":
    unittest.main()

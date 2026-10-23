"""WF-03-05 automotive-power synthetic contract tests (standard library only)."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware"
if str(FIRMWARE) not in sys.path:
    sys.path.insert(0, str(FIRMWARE))

from repo03_power import (  # noqa: E402
    APPROVED_VARIANT_B_PROFILE_HASH,
    ENGINE_ID,
    MODULE_ID,
    REP02_ADAPTER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TOOL_VERSION,
    VARIANT_CONTRACT_SCHEMA,
    normalized_input_hash,
    rep02_adapter_profile_hash,
    run_scenario,
)


FIXTURES = ROOT / "variants" / "fixtures" / "automotive_power"
SCHEMA = ROOT / "variants" / "schema" / "repo03.automotive-power.scenario.v1.json"
EXPECTED_FIXTURES = {
    "nominal.json",
    "cold_crank.json",
    "load_dump_suppressed.json",
    "load_dump_unsuppressed.json",
    "jump_start.json",
    "brownout.json",
    "exact_threshold_blocked.json",
    "missing_profile_source.json",
    "rep02_version_mismatch.json",
}


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def reason_codes(report: dict[str, Any]) -> set[str]:
    return {str(issue["reason_code"]) for issue in report["issues"]}


class AutomotivePowerProfileTests(unittest.TestCase):
    maxDiff = None

    def assert_report_envelope(self, report: dict[str, Any]) -> None:
        self.assertEqual(
            set(report),
            {
                "schema_version",
                "scenario_id",
                "engine_id",
                "module_id",
                "variant_id",
                "status",
                "result",
                "rule_id",
                "reason_code",
                "input_hash",
                "tool_version",
                "synthetic_data",
                "profile_assessment",
                "requirements",
                "source_versions",
                "adapter_mapping",
                "dependencies",
                "issues",
                "claims",
            },
        )
        self.assertIn(report["status"], {"PASS", "FAIL", "UNKNOWN", "BLOCKED"})
        self.assertEqual(report["result"]["status"], report["status"])
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["engine_id"], ENGINE_ID)
        self.assertEqual(report["module_id"], MODULE_ID)
        self.assertEqual(report["tool_version"], TOOL_VERSION)
        self.assertEqual(len(report["input_hash"]), 64)
        self.assertTrue(report["synthetic_data"])
        self.assertIn("GAP-03", report["dependencies"])
        self.assertEqual(report["dependencies"]["GAP-03"]["status"], "UNKNOWN")
        self.assertEqual(report["dependencies"]["rep02"]["integration_status"], "BLOCKED")
        self.assertEqual(report["dependencies"]["rep02"]["execution_status"], "NOT_RUN")
        self.assertFalse(report["claims"]["physical_validation"])
        self.assertFalse(report["claims"]["exact_part_decision"])
        self.assertFalse(report["claims"]["oem_compliance"])
        self.assertFalse(report["claims"]["iso_compliance"])
        self.assertFalse(report["claims"]["aec_qualification"])
        self.assertFalse(report["claims"]["rep02_execution"])
        self.assertNotIn("generated_at", report)
        for issue in report["issues"]:
            self.assertEqual(
                set(issue), {"status", "rule_id", "reason_code", "path", "message"}
            )

    def test_schema_and_fixture_inventory_are_closed_json(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["variant_id"]["const"], "B")
        self.assertEqual(schema["properties"]["module_id"]["const"], MODULE_ID)
        self.assertFalse(schema["additionalProperties"])
        for definition in (
            "source",
            "variant_contract",
            "requirements",
            "rep02_adapter",
            "rep02_rail_budget",
            "rep02_sequencing",
            "profile",
            "report",
            "claims",
            "dependencies",
            "adapter_mapping",
            "mapping_row",
            "rail_budget_mapping",
            "sequencing_mapping",
        ):
            self.assertFalse(schema["$defs"][definition]["additionalProperties"])
        self.assertEqual({path.name for path in FIXTURES.glob("*.json")}, EXPECTED_FIXTURES)
        for name in EXPECTED_FIXTURES:
            with self.subTest(name=name):
                fixture = load_fixture(name)
                self.assertEqual(fixture["schema_version"], SCHEMA_VERSION)
                self.assertEqual(set(fixture), set(schema["properties"]))

    def test_nominal_boundary_pass_records_versioned_requirements(self) -> None:
        report = run_scenario(load_fixture("nominal.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["reason_code"], "SYNTHETIC_PROFILE_CONTRACT_ACCEPTED")
        self.assertEqual(report["profile_assessment"]["input_voltage"], 12.0)
        self.assertEqual(report["profile_assessment"]["duration_ms"], 0.0)
        self.assertEqual(
            report["requirements"]["input_nominal_voltage"], {"value": 12.0, "unit": "V"}
        )
        self.assertEqual(
            report["requirements"]["output_target_voltage"], {"value": 5.1, "unit": "V"}
        )
        self.assertEqual(
            report["requirements"]["output_target_current"], {"value": 5.0, "unit": "A"}
        )
        self.assertEqual(
            report["requirements"]["source_reference"],
            "REP-03-WF-03-05-REQUIREMENTS",
        )
        self.assertEqual(report["requirements"]["source_version"], "1.0.0")

    def test_every_required_profile_has_a_separate_fixture(self) -> None:
        names = {
            load_fixture(name)["profile"]["profile_type"]
            for name in EXPECTED_FIXTURES
            if name
            in {
                "nominal.json",
                "cold_crank.json",
                "load_dump_suppressed.json",
                "load_dump_unsuppressed.json",
                "jump_start.json",
                "brownout.json",
            }
        }
        self.assertEqual(
            names,
            {
                "nominal",
                "cold_crank",
                "load_dump_suppressed",
                "load_dump_unsuppressed",
                "jump_start",
                "brownout",
            },
        )

    def test_unsourced_oem_transient_profiles_are_unknown_not_pass(self) -> None:
        for name in (
            "cold_crank.json",
            "load_dump_suppressed.json",
            "load_dump_unsuppressed.json",
            "jump_start.json",
            "brownout.json",
        ):
            with self.subTest(name=name):
                report = run_scenario(load_fixture(name))
                self.assert_report_envelope(report)
                self.assertEqual(report["status"], "UNKNOWN")
                self.assertIn("SOURCE_ASSUMPTION", reason_codes(report))
                self.assertIn("OEM_PROFILE_SOURCE_REQUIRED", reason_codes(report))

    def test_engineering_rule_with_oem_authority_cannot_pass_transient_profiles(self) -> None:
        for name in (
            "cold_crank.json",
            "load_dump_suppressed.json",
            "load_dump_unsuppressed.json",
            "jump_start.json",
            "brownout.json",
        ):
            with self.subTest(name=name):
                scenario = load_fixture(name)
                scenario["profile"]["source"] = {
                    "classification": "ENGINEERING_RULE",
                    "authority": "OEM",
                    "reference": "OEM-X",
                    "version": "1.0",
                }

                report = run_scenario(scenario)

                self.assert_report_envelope(report)
                self.assertEqual(report["status"], "UNKNOWN")
                self.assertEqual(report["rule_id"], "REP03-POWER-PROFILE-007")
                self.assertEqual(report["reason_code"], "OEM_PROFILE_SOURCE_REQUIRED")
                self.assertIn("OEM_PROFILE_SOURCE_REQUIRED", reason_codes(report))

    def test_suppressed_and_unsuppressed_load_dump_are_distinct(self) -> None:
        suppressed = run_scenario(load_fixture("load_dump_suppressed.json"))
        unsuppressed = run_scenario(load_fixture("load_dump_unsuppressed.json"))

        self.assertEqual(
            suppressed["profile_assessment"]["suppression_state"], "SUPPRESSED"
        )
        self.assertEqual(
            unsuppressed["profile_assessment"]["suppression_state"], "UNSUPPRESSED"
        )
        self.assertNotEqual(suppressed["input_hash"], unsuppressed["input_hash"])

    def test_missing_profile_source_is_schema_valid_negative_and_blocked(self) -> None:
        scenario = load_fixture("missing_profile_source.json")
        self.assertIsNone(scenario["profile"]["source"])

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("SOURCE_MISSING", reason_codes(report))
        self.assertIsNone(report["profile_assessment"]["source"])

    def test_rep02_version_mismatch_is_fail_closed_blocked(self) -> None:
        report = run_scenario(load_fixture("rep02_version_mismatch.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("REP02_ADAPTER_VERSION_MISMATCH", reason_codes(report))
        self.assertEqual(report["dependencies"]["rep02"]["status"], "BLOCKED")
        self.assertEqual(
            report["dependencies"]["rep02"]["reason_code"],
            "REP02_ADAPTER_VERSION_MISMATCH",
        )

    def test_rep02_adapter_uses_real_pinned_contract_versions_and_units(self) -> None:
        adapter = load_fixture("nominal.json")["rep02_adapter"]

        self.assertEqual(adapter["schema_version"], REP02_ADAPTER_SCHEMA_VERSION)
        self.assertEqual(adapter["transport"], "FILE_API")
        self.assertEqual(adapter["native_api"], "JSON_COMPATIBLE_MAPPING")
        self.assertEqual(adapter["source"]["reference"], "power-rail-validation-and-review")
        self.assertEqual(
            adapter["source"]["version"],
            "79ae5ba1a842cf2cc206eed408d71214ff2c43bc",
        )
        self.assertEqual(adapter["rail_budget"]["input_schema_version"], "1.0.0")
        self.assertEqual(adapter["rail_budget"]["package_version"], "0.3.0")
        self.assertEqual(adapter["rail_budget"]["formula_version"], "REP02-RB-1.0.0")
        self.assertEqual(adapter["rail_budget"]["rule_id"], "REP02.RAIL_BUDGET.STATIC")
        self.assertEqual(
            adapter["rail_budget"]["input_fields"],
            [
                "schema_version",
                "rail",
                "loads",
                "capacity",
                "derating",
                "efficiency",
                "sources",
            ],
        )
        self.assertEqual(
            adapter["rail_budget"]["units"],
            {"voltage": "V", "current": "A", "factor": "1", "power": "W"},
        )
        self.assertEqual(adapter["sequencing"]["input_schema_version"], "1.0.0")
        self.assertEqual(adapter["sequencing"]["engine_version"], "0.3.0")
        self.assertEqual(adapter["sequencing"]["fsm_version"], "REP02-SEQ-FSM-1.0.0")
        self.assertEqual(
            adapter["sequencing"]["rule_set_version"],
            "REP02-SEQ-RULESET-1.0.0",
        )
        self.assertEqual(
            adapter["sequencing"]["input_fields"],
            [
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
            ],
        )
        self.assertEqual(adapter["sequencing"]["units"], {"time": "s"})
        self.assertEqual(adapter["profile_hash"], rep02_adapter_profile_hash(adapter))

    def test_nominal_mapping_is_explicit_and_fail_closed(self) -> None:
        report = run_scenario(load_fixture("nominal.json"))
        mapping = report["adapter_mapping"]

        self.assertEqual(mapping["profile_type"], "nominal")
        self.assertEqual(mapping["rail_budget"]["disposition"], "BLOCKED")
        self.assertEqual(
            mapping["rail_budget"]["reason_code"],
            "REP02_RAIL_BUDGET_INPUT_INCOMPLETE",
        )
        self.assertIsNone(mapping["rail_budget"]["rail_budget_input"])
        voltage_row = next(
            row
            for row in mapping["rail_budget"]["mapping"]
            if row["source_path"] == "requirements.output_target_voltage"
        )
        self.assertEqual(voltage_row["target_path"], "rail.nominal_voltage")
        self.assertEqual(voltage_row["disposition"], "MAPPED_REQUIREMENT")
        current_row = next(
            row
            for row in mapping["rail_budget"]["mapping"]
            if row["source_path"] == "requirements.output_target_current"
        )
        self.assertIsNone(current_row["target_path"])
        self.assertEqual(current_row["disposition"], "UNRESOLVED")
        self.assertEqual(
            mapping["rail_budget"]["unresolved_required_fields"],
            [
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
        )
        for mapping_name in ("rail_budget", "sequencing"):
            rows = {
                row["source_path"]: row
                for row in mapping[mapping_name]["mapping"]
            }
            for source_path in ("profile.suppression_state", "profile.source"):
                with self.subTest(mapping_name=mapping_name, source_path=source_path):
                    self.assertIn(source_path, rows)
                    self.assertIsNone(rows[source_path]["target_path"])
                    self.assertEqual(rows[source_path]["disposition"], "UNSUPPORTED")
        self.assertEqual(mapping["sequencing"]["disposition"], "NOT_RUN")
        self.assertEqual(
            mapping["sequencing"]["supported_scenario_kinds"],
            ["STARTUP", "POWER_OFF"],
        )
        self.assertIsNone(mapping["sequencing"]["sequencing_input"])

    def test_transients_are_not_blindly_mapped_to_rep02_engines(self) -> None:
        for name in (
            "cold_crank.json",
            "load_dump_suppressed.json",
            "load_dump_unsuppressed.json",
            "jump_start.json",
            "brownout.json",
        ):
            with self.subTest(name=name):
                mapping = run_scenario(load_fixture(name))["adapter_mapping"]
                self.assertEqual(mapping["rail_budget"]["disposition"], "BLOCKED")
                self.assertEqual(
                    mapping["rail_budget"]["reason_code"],
                    "REP02_STATIC_RAIL_BUDGET_DOES_NOT_MODEL_TRANSIENT_PROFILE",
                )
                self.assertIsNone(mapping["rail_budget"]["rail_budget_input"])
                self.assertEqual(mapping["sequencing"]["disposition"], "NOT_RUN")
                self.assertEqual(
                    mapping["sequencing"]["reason_code"],
                    "REP02_SEQUENCING_PROFILE_KIND_UNSUPPORTED",
                )
                self.assertIsNone(mapping["sequencing"]["selected_scenario_kind"])
                self.assertIsNone(mapping["sequencing"]["sequencing_input"])

    def test_rep02_adapter_does_not_execute_or_import_sibling_engine(self) -> None:
        report = run_scenario(load_fixture("nominal.json"))
        source_text = (FIRMWARE / "repo03_power" / "engine.py").read_text(encoding="utf-8")

        self.assertEqual(report["dependencies"]["rep02"]["status"], "PASS")
        self.assertEqual(report["dependencies"]["rep02"]["integration_status"], "BLOCKED")
        self.assertEqual(report["dependencies"]["rep02"]["execution_status"], "NOT_RUN")
        self.assertFalse(report["claims"]["rep02_execution"])
        self.assertNotIn("from power_rail_validation", source_text)
        self.assertNotIn("import power_rail_validation", source_text)

        dependency = report["dependencies"]["rep02"]
        self.assertEqual(dependency["source_version"], "79ae5ba1a842cf2cc206eed408d71214ff2c43bc")
        self.assertEqual(dependency["package_version"], "0.3.0")
        self.assertEqual(dependency["rail_budget_formula_version"], "REP02-RB-1.0.0")
        self.assertEqual(dependency["rail_budget_rule_id"], "REP02.RAIL_BUDGET.STATIC")
        self.assertEqual(dependency["sequencing_engine_version"], "0.3.0")
        self.assertEqual(dependency["sequencing_fsm_version"], "REP02-SEQ-FSM-1.0.0")
        self.assertEqual(
            dependency["sequencing_rule_set_version"],
            "REP02-SEQ-RULESET-1.0.0",
        )

    def test_rep02_adapter_hash_mismatch_is_blocked(self) -> None:
        scenario = load_fixture("nominal.json")
        scenario["rep02_adapter"]["profile_hash"] = "0" * 64

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("REP02_ADAPTER_PROFILE_HASH_MISMATCH", reason_codes(report))

    def test_rep02_adapter_source_must_pin_reviewed_commit(self) -> None:
        scenario = load_fixture("nominal.json")
        scenario["rep02_adapter"]["source"]["version"] = "79ae5bb"
        scenario["rep02_adapter"]["profile_hash"] = rep02_adapter_profile_hash(
            scenario["rep02_adapter"]
        )

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("REP02_ADAPTER_SOURCE_MISMATCH", reason_codes(report))

    def test_rep02_unit_contract_mismatch_is_blocked(self) -> None:
        scenario = load_fixture("nominal.json")
        scenario["rep02_adapter"]["rail_budget"]["units"]["current"] = "mA"
        scenario["rep02_adapter"]["profile_hash"] = rep02_adapter_profile_hash(
            scenario["rep02_adapter"]
        )

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("REP02_ADAPTER_VERSION_MISMATCH", reason_codes(report))

    def test_exact_part_or_real_threshold_decision_is_gap_03_blocked(self) -> None:
        report = run_scenario(load_fixture("exact_threshold_blocked.json"))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn(
            "EXACT_PART_OR_PHYSICAL_THRESHOLD_BLOCKED", reason_codes(report)
        )
        self.assertEqual(
            report["dependencies"]["GAP-03"]["reason_code"],
            "AUTOMOTIVE_POWER_EXACT_PART_AND_THRESHOLDS_UNRESOLVED",
        )

    def test_complete_variant_b_module_set_and_fixed_hash_are_enforced(self) -> None:
        scenario = load_fixture("nominal.json")
        self.assertEqual(set(scenario["enabled_modules"]), {"automotive_power", "shutdown"})
        self.assertEqual(scenario["variant_contract"]["schema_version"], VARIANT_CONTRACT_SCHEMA)
        self.assertEqual(
            scenario["variant_contract"]["profile_hash"],
            APPROVED_VARIANT_B_PROFILE_HASH,
        )

        missing_module = deepcopy(scenario)
        missing_module["enabled_modules"] = ["automotive_power"]
        bad_hash = deepcopy(scenario)
        bad_hash["variant_contract"]["profile_hash"] = "f" * 64

        self.assertEqual(run_scenario(missing_module)["status"], "FAIL")
        self.assertIn(
            "VARIANT_B_MODULE_SET_INVALID", reason_codes(run_scenario(missing_module))
        )
        self.assertEqual(run_scenario(bad_hash)["status"], "FAIL")
        self.assertIn("VARIANT_B_PROFILE_HASH_MISMATCH", reason_codes(run_scenario(bad_hash)))

    def test_requirement_values_and_units_are_fail_closed(self) -> None:
        for path, value, reason in (
            (("output_target_voltage", "value"), 5.0, "REQUIREMENT_VALUE_MISMATCH"),
            (("output_target_current", "unit"), "mA", "REQUIREMENT_UNIT_MISMATCH"),
        ):
            with self.subTest(path=path):
                scenario = load_fixture("nominal.json")
                scenario["requirements"][path[0]][path[1]] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(reason, reason_codes(report))

    def test_requirement_source_must_be_pinned_project_requirement(self) -> None:
        scenario = load_fixture("nominal.json")
        scenario["requirements"]["output_target_voltage"]["source"]["version"] = "latest"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SOURCE_VERSION_FLOATING", reason_codes(report))
        self.assertIn("REQUIREMENT_SOURCE_MISMATCH", reason_codes(report))

    def test_nominal_profile_must_use_the_pinned_requirement_source(self) -> None:
        scenario = load_fixture("nominal.json")
        scenario["profile"]["source"] = {
            "classification": "SOURCE_EXPLICIT",
            "authority": "ENGINEERING",
            "reference": "UNRELATED-SOURCE",
            "version": "1.0.0",
        }

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("NOMINAL_PROFILE_SOURCE_MISMATCH", reason_codes(report))

    def test_physical_measurement_and_compliance_claims_are_rejected(self) -> None:
        for key, value in (
            ("measured_voltage", 5.1),
            ("exact_part", "UNVERIFIED"),
            ("iso_compliance", True),
        ):
            with self.subTest(key=key):
                scenario = load_fixture("nominal.json")
                scenario[key] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(
                    "PHYSICAL_OR_COMPLIANCE_CLAIM_FORBIDDEN", reason_codes(report)
                )

    def test_unknown_fields_are_rejected_at_nested_and_top_levels(self) -> None:
        top = load_fixture("nominal.json")
        top["extra"] = True
        nested = load_fixture("nominal.json")
        nested["profile"]["extra"] = True

        top_report = run_scenario(top)
        nested_report = run_scenario(nested)

        self.assertEqual(top_report["status"], "FAIL")
        self.assertEqual(nested_report["status"], "FAIL")
        self.assertIn("UNKNOWN_FIELD", reason_codes(top_report))
        self.assertIn("UNKNOWN_FIELD", reason_codes(nested_report))

    def test_hash_is_deterministic_and_object_order_independent(self) -> None:
        scenario = load_fixture("nominal.json")
        reordered = dict(reversed(list(deepcopy(scenario).items())))
        reordered["enabled_modules"] = list(reversed(scenario["enabled_modules"]))
        reordered["requirements"] = dict(
            reversed(list(scenario["requirements"].items()))
        )

        first = run_scenario(scenario)
        second = run_scenario(reordered)

        self.assertEqual(first["input_hash"], second["input_hash"])
        self.assertEqual(first["status"], second["status"])
        self.assertEqual(normalized_input_hash(scenario), first["input_hash"])

    def test_meaningful_profile_change_changes_hash(self) -> None:
        scenario = load_fixture("cold_crank.json")
        changed = deepcopy(scenario)
        changed["profile"]["duration_ms"] += 1

        self.assertNotEqual(
            run_scenario(scenario)["input_hash"], run_scenario(changed)["input_hash"]
        )

    def test_non_finite_or_negative_profile_values_fail_without_exception(self) -> None:
        for field, value, reason in (
            ("input_voltage", math.nan, "NON_FINITE_NUMBER"),
            ("duration_ms", -1, "PROFILE_DURATION_INVALID"),
        ):
            with self.subTest(field=field):
                scenario = load_fixture("nominal.json")
                scenario["profile"][field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(reason, reason_codes(report))
                json.dumps(report, allow_nan=False)

    def test_wrong_python_types_return_structured_fail(self) -> None:
        for value in (None, [], "scenario", 7):
            with self.subTest(value=value):
                report = run_scenario(value)
                self.assert_report_envelope(report)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("SCENARIO_NOT_OBJECT", reason_codes(report))
                json.dumps(report, allow_nan=False)

    def test_unregistered_oem_label_cannot_self_authorize_transient_pass(self) -> None:
        scenario = load_fixture("cold_crank.json")
        scenario["profile"]["source"] = {
            "classification": "SOURCE_EXPLICIT",
            "authority": "OEM",
            "reference": "OEM-PROFILE-TEST-REFERENCE",
            "version": "rev-A",
        }

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["rule_id"], "REP03-POWER-PROFILE-008")
        self.assertEqual(report["reason_code"], "OEM_PROFILE_SOURCE_NOT_APPROVED")
        self.assertEqual(report["claims"]["validation_level"], "SYNTHETIC")
        self.assertFalse(report["claims"]["physical_validation"])

    def test_load_dump_suppression_state_is_not_interchangeable(self) -> None:
        scenario = load_fixture("load_dump_suppressed.json")
        scenario["profile"]["suppression_state"] = "UNSUPPRESSED"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("SUPPRESSION_STATE_MISMATCH", reason_codes(report))

    def test_adapter_mismatch_profile_hash_is_internally_coherent(self) -> None:
        adapter = load_fixture("rep02_version_mismatch.json")["rep02_adapter"]
        self.assertEqual(adapter["profile_hash"], rep02_adapter_profile_hash(adapter))


if __name__ == "__main__":
    unittest.main()

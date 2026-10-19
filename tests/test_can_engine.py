"""WF-03-02 synthetic CAN/TWAI engine tests (standard library only)."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from repo03_can.engine import (
    APPROVED_VARIANT_A_PROFILE_HASH,
    SCHEMA_VERSION,
    TOOL_VERSION,
    run_scenario,
)
from repo03_contract.validator import validate_profile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "variants" / "fixtures" / "can"
SCHEMA = ROOT / "variants" / "schema" / "repo03.can.scenario.v1.json"


def load_fixture(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def reason_codes(report: dict) -> set[str]:
    return {issue["reason_code"] for issue in report["issues"]}


class CanEngineTests(unittest.TestCase):
    maxDiff = None

    def assert_trace_contract(self, report: dict) -> None:
        required = {
            "previous_state",
            "next_state",
            "previous_controller_state",
            "new_controller_state",
            "previous_transceiver_state",
            "new_transceiver_state",
            "previous_bus_observation",
            "new_bus_observation",
            "previous_error_counters",
            "new_error_counters",
            "event",
            "elapsed_ms",
            "timeout_ms",
            "threshold_source",
            "status",
            "rule_id",
            "reason_code",
            "domain_results",
        }
        self.assertTrue(report["trace"])
        for row in report["trace"]:
            self.assertTrue(required <= set(row))
            self.assertNotEqual(
                id(row["previous_state"]),
                id(row["next_state"]),
            )

    def test_schema_and_all_fixtures_are_valid_json(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["variant_id"]["const"], "A")
        self.assertFalse(schema["additionalProperties"])
        files = sorted(FIXTURES.glob("*.json"))
        self.assertEqual(len(files), 6)
        for fixture in files:
            self.assertIsInstance(json.loads(fixture.read_text(encoding="utf-8")), dict)

    def test_normal_frame_is_synthetic_controller_pass_only(self) -> None:
        report = run_scenario(load_fixture("normal_frame.json"))

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["final_state"]["controller_state"], "ERROR_ACTIVE")
        self.assertEqual(report["final_state"]["transceiver_state"], "SYNTHETIC_ON")
        self.assertEqual(report["final_state"]["bus_observation"], "SYNTHETIC_FRAME_OBSERVED")
        row = report["trace"][0]
        self.assertEqual(row["domain_results"]["controller"]["status"], "PASS")
        self.assertEqual(row["domain_results"]["transceiver"]["status"], "UNKNOWN")
        self.assertEqual(row["domain_results"]["bus_observation"]["status"], "UNKNOWN")
        self.assertFalse(report["claims"]["physical_can_validation"])
        self.assertFalse(report["claims"]["physical_transceiver_validation"])
        self.assert_trace_contract(report)

    def test_error_escalation_bus_off_and_recovery_success(self) -> None:
        report = run_scenario(load_fixture("error_escalation_recovery_success.json"))

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            [row["new_controller_state"] for row in report["trace"]],
            [
                "ERROR_WARNING",
                "ERROR_PASSIVE",
                "BUS_OFF",
                "RECOVERY_PENDING",
                "ERROR_ACTIVE",
                "ERROR_ACTIVE",
            ],
        )
        self.assertEqual(report["trace"][1]["new_error_counters"], {"tx": 128, "rx": 16})
        self.assertEqual(report["trace"][4]["new_error_counters"], {"tx": 0, "rx": 0})
        self.assertEqual(report["trace"][4]["elapsed_ms"], 500)
        self.assertEqual(report["trace"][4]["timeout_ms"], 1000)
        self.assertEqual(
            report["trace"][4]["threshold_source"]["reference"],
            "WF-03-02 synthetic test timeout; not an OEM or component value",
        )

    def test_recovery_timeout_fails_with_reason_and_elapsed(self) -> None:
        report = run_scenario(load_fixture("recovery_timeout.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("RECOVERY_TIMEOUT_EXCEEDED", reason_codes(report))
        timeout_row = report["trace"][-1]
        self.assertEqual(timeout_row["event"], "RECOVERY_TIMEOUT")
        self.assertEqual(timeout_row["elapsed_ms"], 1000)
        self.assertEqual(timeout_row["timeout_ms"], 1000)
        self.assertEqual(timeout_row["new_controller_state"], "BUS_OFF")
        self.assertEqual(timeout_row["threshold_source"]["version"], "1.0.0")

    def test_missing_recovery_fails_at_scenario_end(self) -> None:
        report = run_scenario(load_fixture("missing_recovery.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["trace"][-1]["event"], "SCENARIO_END")
        self.assertEqual(report["trace"][-1]["reason_code"], "RECOVERY_NOT_REQUESTED")

    def test_transceiver_off_is_gap_01_blocked_not_physical_result(self) -> None:
        report = run_scenario(load_fixture("transceiver_off_unknown.json"))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED", reason_codes(report))
        self.assertEqual(report["final_state"]["transceiver_state"], "UNKNOWN")
        self.assertEqual(report["final_state"]["bus_observation"], "UNKNOWN")
        self.assertEqual(report["final_state"]["controller_state"], "ERROR_ACTIVE")
        self.assertEqual(report["dependency_results"]["external_transceiver"]["gap_id"], "GAP-01")
        self.assertEqual(report["trace"][0]["domain_results"]["controller"]["status"], "PASS")
        self.assertEqual(report["trace"][0]["domain_results"]["transceiver"]["status"], "BLOCKED")

    def test_invalid_recovery_sequence_fails_with_specific_reason(self) -> None:
        report = run_scenario(load_fixture("invalid_sequence.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("RECOVERY_COMPLETE_WITHOUT_REQUEST", reason_codes(report))
        self.assertEqual(report["final_state"]["controller_state"], "ERROR_ACTIVE")

    def test_same_fixture_produces_identical_hash_and_trace(self) -> None:
        scenario = load_fixture("error_escalation_recovery_success.json")

        first = run_scenario(scenario)
        second = run_scenario(deepcopy(scenario))

        self.assertEqual(first["input_hash"], second["input_hash"])
        self.assertEqual(first["trace"], second["trace"])
        self.assertEqual(first, second)

    def test_hash_is_independent_of_object_key_order(self) -> None:
        scenario = load_fixture("normal_frame.json")
        reordered = dict(reversed(list(deepcopy(scenario).items())))
        reordered["initial_state"] = dict(reversed(list(scenario["initial_state"].items())))
        reordered["enabled_modules"] = list(reversed(scenario["enabled_modules"]))

        self.assertEqual(run_scenario(scenario)["input_hash"], run_scenario(reordered)["input_hash"])

    def test_variant_a_can_gate_cannot_be_bypassed(self) -> None:
        base = load_fixture("normal_frame.json")
        cases = (
            ("variant_id", "B", "VARIANT_A_REQUIRED"),
            ("module_id", "lin", "CAN_MODULE_REQUIRED"),
            ("engine_id", "other", "ENGINE_ID_MISMATCH"),
        )
        for field, value, expected_reason in cases:
            with self.subTest(field=field):
                scenario = deepcopy(base)
                scenario[field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_d1_variant_contract_hash_is_pinned_and_reported(self) -> None:
        scenario = load_fixture("normal_frame.json")
        canonical_profile = json.loads(
            (ROOT / "variants" / "fixtures" / "valid_variant_a.json").read_text(
                encoding="utf-8"
            )
        )

        report = run_scenario(scenario)
        profile_report = validate_profile(canonical_profile)

        self.assertEqual(
            profile_report["profile_hash"],
            APPROVED_VARIANT_A_PROFILE_HASH,
        )
        self.assertEqual(
            report["variant_contract"]["profile_hash"],
            APPROVED_VARIANT_A_PROFILE_HASH,
        )
        self.assertEqual(
            report["expected_variant_contract_profile_hash"],
            APPROVED_VARIANT_A_PROFILE_HASH,
        )
        self.assertEqual(
            report["variant_contract"]["source"]["reference"],
            "variants/fixtures/valid_variant_a.json",
        )

    def test_missing_or_mismatched_d1_variant_contract_cannot_run(self) -> None:
        base = load_fixture("normal_frame.json")

        missing = deepcopy(base)
        del missing["variant_contract"]
        missing_report = run_scenario(missing)
        self.assertEqual(missing_report["status"], "BLOCKED")
        self.assertIn("VARIANT_CONTRACT_MISSING", reason_codes(missing_report))
        self.assertIsNone(missing_report["variant_contract"])

        mismatched = deepcopy(base)
        mismatched["variant_contract"]["profile_hash"] = "0" * 64
        mismatch_report = run_scenario(mismatched)
        self.assertEqual(mismatch_report["status"], "FAIL")
        self.assertIn("VARIANT_CONTRACT_HASH_MISMATCH", reason_codes(mismatch_report))
        self.assertIsNone(mismatch_report["variant_contract"])

    def test_enabled_modules_enforce_can_allowlist_and_uniqueness(self) -> None:
        base = load_fixture("normal_frame.json")
        cases = (
            (["lin", "gnss"], "CAN_MODULE_REQUIRED"),
            (["can"], "VARIANT_A_MODULE_SET_INCOMPLETE"),
            (["can", "shutdown"], "VARIANT_A_MODULE_LEAKAGE"),
            (["can", "can"], "DUPLICATE_MODULE"),
        )
        for modules, expected_reason in cases:
            with self.subTest(modules=modules):
                scenario = deepcopy(base)
                scenario["enabled_modules"] = modules
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_known_gaps_runtime_matches_closed_schema_contract(self) -> None:
        base = load_fixture("normal_frame.json")
        cases = (
            (["GAP-01", 123], "KNOWN_GAPS_INVALID"),
            (["GAP-01", "GAP-01"], "DUPLICATE_KNOWN_GAP"),
            ({"gap": "GAP-01"}, "KNOWN_GAPS_INVALID"),
            (["GAP-01", "GAP-99"], "UNKNOWN_KNOWN_GAP"),
            ([], "GAP_01_DECLARATION_MISSING"),
        )
        for gaps, expected_reason in cases:
            with self.subTest(gaps=gaps):
                scenario = deepcopy(base)
                scenario["known_gaps"] = gaps
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_source_explicit_requires_nonempty_reference_and_version(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["source"] = {
            "classification": "SOURCE_EXPLICIT",
            "reference": "",
            "version": "",
        }

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("EXACT_SOURCE_METADATA_INCOMPLETE", reason_codes(report))

    def test_guessed_timeout_without_source_is_rejected(self) -> None:
        scenario = load_fixture("recovery_timeout.json")
        del scenario["threshold_sources"]["recovery_timeout"]

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            {"THRESHOLD_SOURCE_SET_INVALID", "SOURCE_METADATA_INVALID"} <= reason_codes(report)
        )

    def test_unknown_timeout_source_is_blocked_not_pass(self) -> None:
        scenario = load_fixture("recovery_timeout.json")
        scenario["threshold_sources"]["recovery_timeout"] = {
            "classification": "UNKNOWN",
            "reference": "GAP-01 unresolved recovery source",
            "version": "UNRESOLVED",
        }

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("SOURCE_UNRESOLVED", reason_codes(report))

    def test_nested_additional_event_property_is_rejected(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["events"][0]["arbitrary"] = "escape"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("UNKNOWN_EVENT_FIELD", reason_codes(report))

    def test_frame_payload_whitespace_is_rejected_like_schema_regex(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["events"][0]["dlc"] = 2
        scenario["events"][0]["data_hex"] = "AA  "

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("FRAME_DATA_NOT_HEX", reason_codes(report))
        self.assertEqual(report["trace"][0]["reason_code"], "FRAME_DATA_NOT_HEX")

    def test_physical_claim_keys_are_rejected_at_any_depth(self) -> None:
        base = load_fixture("normal_frame.json")
        for key, value in (
            ("physical_pass", True),
            ("measured", True),
            ("part_number", "UNVERIFIED"),
            ("voltage", 12),
        ):
            with self.subTest(key=key):
                scenario = deepcopy(base)
                scenario["events"][0][key] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("PHYSICAL_CLAIM_FORBIDDEN", reason_codes(report))

    def test_normal_frame_does_not_infer_transceiver_on(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["initial_state"]["transceiver_state"] = "UNKNOWN"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["final_state"]["transceiver_state"], "UNKNOWN")
        self.assertEqual(report["final_state"]["bus_observation"], "NO_SYNTHETIC_OBSERVATION")
        self.assertIn("GAP_01_TRANSCEIVER_BEHAVIOR_UNRESOLVED", reason_codes(report))
        row = report["trace"][0]
        self.assertEqual(row["domain_results"]["controller"]["status"], "PASS")
        self.assertEqual(
            row["domain_results"]["controller"]["reason_code"],
            "CONTROLLER_STATE_UNCHANGED",
        )
        self.assertEqual(row["domain_results"]["transceiver"]["status"], "BLOCKED")

    def test_assumption_source_returns_unknown_precheck(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["source"]["classification"] = "ASSUMPTION"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "UNKNOWN")
        self.assertIn("SOURCE_ASSUMPTION", reason_codes(report))
        self.assertEqual(report["trace"][0]["event"], "PRECHECK")
        self.assertEqual(report["source"]["classification"], "ASSUMPTION")

    def test_wrong_type_membership_values_return_structured_fail(self) -> None:
        cases = []

        source_type = load_fixture("normal_frame.json")
        source_type["source"]["classification"] = []
        cases.append(source_type)

        controller_type = load_fixture("normal_frame.json")
        controller_type["initial_state"]["controller_state"] = []
        cases.append(controller_type)

        transceiver_type = load_fixture("normal_frame.json")
        transceiver_type["initial_state"]["transceiver_state"] = {}
        cases.append(transceiver_type)

        bus_type = load_fixture("normal_frame.json")
        bus_type["initial_state"]["bus_observation"] = []
        cases.append(bus_type)

        event_type = load_fixture("normal_frame.json")
        event_type["events"][0]["type"] = []
        cases.append(event_type)

        counter_target = load_fixture("error_escalation_recovery_success.json")
        counter_target["events"][0]["controller_state"] = {}
        cases.append(counter_target)

        for scenario in cases:
            with self.subTest(scenario=scenario["scenario_id"]):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertTrue(report["rule_id"])
                self.assertTrue(report["reason_code"])
                self.assertRegex(report["input_hash"], r"^[0-9a-f]{64}$")
                self.assertTrue(report["trace"])

    def test_invalid_source_is_safely_nullable_in_precheck_report(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["source"] = {
            "classification": [],
            "reference": [],
            "version": {},
        }

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIsNone(report["source"])
        self.assertIsNone(report["source_reference"])
        self.assertIsNone(report["source_version"])
        self.assertEqual(report["trace"][0]["event"], "PRECHECK")
        self.assertEqual(
            set(report["final_state"].values()),
            {None},
        )

    def test_event_scope_physical_claim_has_deterministic_precheck_trace(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["events"][0]["physical_pass"] = True

        first = run_scenario(scenario)
        second = run_scenario(deepcopy(scenario))

        self.assertEqual(first["status"], "FAIL")
        self.assertEqual(first["trace"][0]["event"], "PRECHECK")
        self.assertEqual(first["trace"], second["trace"])
        self.assertEqual(first["input_hash"], second["input_hash"])

    def test_report_schema_is_closed_and_matches_runtime_envelope(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        report_schema = schema["$defs"]["report"]
        report = run_scenario(load_fixture("normal_frame.json"))

        self.assertFalse(report_schema["additionalProperties"])
        self.assertEqual(set(report_schema["required"]), set(report_schema["properties"]))
        self.assertEqual(set(report), set(report_schema["properties"]))

    def test_empty_events_and_blank_scenario_id_fail(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["events"] = []
        scenario["scenario_id"] = ""

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("EVENTS_EMPTY_OR_INVALID", reason_codes(report))
        self.assertIn("SCENARIO_ID_INVALID", reason_codes(report))

    def test_non_monotonic_event_time_fails(self) -> None:
        scenario = load_fixture("error_escalation_recovery_success.json")
        scenario["events"][1]["timestamp_ms"] = 5

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("EVENT_TIME_NOT_MONOTONIC", reason_codes(report))

    def test_non_finite_python_input_returns_fail_report(self) -> None:
        scenario = load_fixture("normal_frame.json")
        scenario["events"][0]["frame_id"] = float("nan")

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("NON_FINITE_NUMBER", reason_codes(report))
        self.assertRegex(report["input_hash"], r"^[0-9a-f]{64}$")

    def test_output_metadata_and_claim_boundaries_are_explicit(self) -> None:
        report = run_scenario(load_fixture("normal_frame.json"))

        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["variant_id"], "A")
        self.assertEqual(report["module_id"], "can")
        self.assertEqual(report["engine_id"], "repo03_can")
        self.assertEqual(report["tool_version"], TOOL_VERSION)
        self.assertEqual(report["source_reference"], "WF-03-02 synthetic CAN/TWAI scenarios")
        self.assertEqual(report["source_version"], "1.0.0")
        self.assertEqual(
            report["expected_variant_contract_profile_hash"],
            APPROVED_VARIANT_A_PROFILE_HASH,
        )
        self.assertTrue(report["synthetic_data"])
        self.assertEqual(report["claims"]["validation_level"], "SYNTHETIC")
        self.assertRegex(report["input_hash"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

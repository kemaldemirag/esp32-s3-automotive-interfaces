"""WF-03-06 synthetic ignition-shutdown contract tests."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from repo03_shutdown import (
    APPROVED_VARIANT_B_PROFILE_HASH,
    EVENTS,
    STATES,
    normalized_input_hash,
    run_scenario,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "variants" / "fixtures" / "shutdown"
SCHEMA_PATH = ROOT / "variants" / "schema" / "repo03.shutdown.scenario.v1.json"
EXPECTED_FIXTURES = {
    "normal_ack.json",
    "missing_ack.json",
    "late_ack.json",
    "early_power_cut.json",
    "duplicate_ack.json",
    "ignition_bounce.json",
    "rapid_restart.json",
    "missing_protocol.json",
}
TRACE_FIELDS = {
    "sequence",
    "previous_state",
    "event",
    "next_state",
    "elapsed_time",
    "threshold_source",
    "status",
    "rule_id",
    "reason_code",
}


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain an object")
    return value


def load_fixture(name: str) -> dict:
    return load_json(FIXTURES / name)


def reason_codes(report: dict) -> set[str]:
    return {str(item["reason_code"]) for item in report["issues"]}


def report_validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/run_report",
        }
    )


class ShutdownEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.input_validator = Draft202012Validator(cls.schema)
        cls.output_validator = report_validator(cls.schema)

    def assert_schema_valid(self, validator: Draft202012Validator, value: object) -> None:
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
        self.assertFalse(
            errors,
            "\n".join(
                f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
                for error in errors
            ),
        )

    def test_schema_is_valid_draft_2020_12_and_closed(self) -> None:
        self.assertEqual(
            self.schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator.check_schema(
            {
                "$schema": self.schema["$schema"],
                "$defs": self.schema["$defs"],
                "$ref": "#/$defs/run_report",
            }
        )
        self.assertFalse(self.schema["additionalProperties"])
        self.assertFalse(self.schema["$defs"]["run_report"]["additionalProperties"])

    def test_fixture_inventory_covers_all_required_categories(self) -> None:
        self.assertEqual({path.name for path in FIXTURES.glob("*.json")}, EXPECTED_FIXTURES)

    def test_every_fixture_and_report_matches_the_closed_schema(self) -> None:
        for name in sorted(EXPECTED_FIXTURES):
            with self.subTest(fixture=name):
                scenario = load_fixture(name)
                self.assert_schema_valid(self.input_validator, scenario)
                self.assert_schema_valid(self.output_validator, run_scenario(scenario))

    def test_current_fixtures_do_not_invent_host_or_timing_values(self) -> None:
        for name in sorted(EXPECTED_FIXTURES):
            with self.subTest(fixture=name):
                scenario = load_fixture(name)
                self.assertIsNone(scenario["host_contract"]["raspberry_pi_model"])
                self.assertIsNone(scenario["host_contract"]["protocol_id"])
                self.assertIsNone(scenario["host_contract"]["source"])
                for threshold in scenario["timing_policy"].values():
                    self.assertIsNone(threshold["value_ms"])
                    self.assertIsNone(threshold["source"])

    def test_normal_ack_path_reaches_synthetic_cut_but_stays_blocked(self) -> None:
        report = run_scenario(load_fixture("normal_ack.json"))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["final_state"], "POWER_CUT")
        self.assertEqual(
            [row["previous_state"] for row in report["trace"]],
            [
                "IGNITION_ON",
                "NOTIFY_PENDING",
                "WAIT_ACK",
                "GRACE_PERIOD",
                "READY_TO_CUT",
            ],
        )
        self.assertEqual(
            [row["next_state"] for row in report["trace"]],
            [
                "NOTIFY_PENDING",
                "WAIT_ACK",
                "GRACE_PERIOD",
                "READY_TO_CUT",
                "POWER_CUT",
            ],
        )
        self.assertEqual(
            set(STATES) - {"RESTART"},
            {"IGNITION_ON", *[row["next_state"] for row in report["trace"]]},
        )
        for row in report["trace"]:
            self.assertEqual(set(row), TRACE_FIELDS)
        self.assertEqual(report["dependencies"]["GAP-04"]["knowledge_status"], "UNKNOWN")
        self.assertEqual(report["dependencies"]["GAP-04"]["blocking_status"], "BLOCKED")

    def test_missing_ack_stays_at_wait_ack_without_cut_authorization(self) -> None:
        report = run_scenario(load_fixture("missing_ack.json"))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["final_state"], "WAIT_ACK")
        self.assertEqual(report["trace"][-1]["event"], "timeout")
        self.assertEqual(
            report["trace"][-1]["reason_code"],
            "ACK_TIMEOUT_THRESHOLD_UNRESOLVED",
        )
        self.assertEqual(
            report["trace"][-1]["threshold_source"]["name"],
            "ack_timeout_ms",
        )

    def test_late_ack_after_timeout_fails_closed(self) -> None:
        report = run_scenario(load_fixture("late_ack.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["final_state"], "WAIT_ACK")
        self.assertEqual(report["trace"][-1]["reason_code"], "LATE_ACK_REJECTED")

    def test_early_power_cut_is_a_failure_not_a_physical_success(self) -> None:
        report = run_scenario(load_fixture("early_power_cut.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["final_state"], "POWER_CUT")
        self.assertEqual(report["trace"][-1]["reason_code"], "EARLY_POWER_CUT")
        self.assertFalse(report["claims"]["physical_power_cut"])
        self.assertFalse(report["claims"]["safe_shutdown_claim"])

    def test_duplicate_ack_is_idempotent_in_grace_period(self) -> None:
        report = run_scenario(load_fixture("duplicate_ack.json"))
        duplicate = report["trace"][3]

        self.assertEqual(duplicate["previous_state"], "GRACE_PERIOD")
        self.assertEqual(duplicate["next_state"], "GRACE_PERIOD")
        self.assertEqual(duplicate["reason_code"], "DUPLICATE_ACK_IGNORED")

    def test_ignition_bounce_requires_a_sourced_debounce_threshold(self) -> None:
        report = run_scenario(load_fixture("ignition_bounce.json"))
        bounce = report["trace"][1]

        self.assertEqual(bounce["status"], "BLOCKED")
        self.assertEqual(bounce["previous_state"], "NOTIFY_PENDING")
        self.assertEqual(bounce["next_state"], "NOTIFY_PENDING")
        self.assertEqual(bounce["reason_code"], "IGNITION_BOUNCE_DEBOUNCE_UNRESOLVED")
        self.assertEqual(bounce["threshold_source"]["name"], "ignition_debounce_ms")

    def test_rapid_restart_remains_unresolved_without_a_pinned_minimum(self) -> None:
        report = run_scenario(load_fixture("rapid_restart.json"))
        restart = report["trace"][-1]

        self.assertEqual(restart["previous_state"], "POWER_CUT")
        self.assertEqual(restart["next_state"], "RESTART")
        self.assertEqual(restart["status"], "BLOCKED")
        self.assertEqual(restart["reason_code"], "RESTART_THRESHOLD_UNRESOLVED")

    def test_missing_protocol_is_explicitly_gap_04_blocked(self) -> None:
        report = run_scenario(load_fixture("missing_protocol.json"))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("HOST_MODEL_UNRESOLVED", reason_codes(report))
        self.assertIn("HOST_PROTOCOL_UNRESOLVED", reason_codes(report))
        self.assertEqual(report["dependencies"]["host_protocol"]["status"], "BLOCKED")
        self.assertIsNone(report["dependencies"]["host_protocol"]["raspberry_pi_model"])
        self.assertIsNone(report["dependencies"]["host_protocol"]["protocol_id"])

    def test_scenario_metadata_cannot_self_close_gap_04(self) -> None:
        scenario = load_fixture("normal_ack.json")
        test_source = {
            "classification": "SOURCE_EXPLICIT",
            "authority": "HOST_PROTOCOL",
            "reference": "TEST-ONLY-NOT-A-GAP-CLOSURE-SOURCE",
            "version": "test-vector",
        }
        scenario["host_contract"] = {
            "raspberry_pi_model": "TEST-ONLY-MODEL",
            "protocol_id": "TEST-ONLY-PROTOCOL",
            "source": test_source,
        }
        for threshold in scenario["timing_policy"].values():
            threshold["value_ms"] = 0
            threshold["source"] = test_source

        report = run_scenario(scenario)

        self.assertEqual(report["dependencies"]["host_protocol"]["status"], "PASS")
        self.assertEqual(report["dependencies"]["timing_policy"]["status"], "PASS")
        self.assertEqual(report["dependencies"]["GAP-04"]["blocking_status"], "BLOCKED")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(
            report["reason_code"],
            "HOST_MODEL_AND_SHUTDOWN_PROTOCOL_UNRESOLVED",
        )
        self.assertFalse(report["claims"]["host_protocol_validated"])

    def test_report_never_claims_real_shutdown_or_physical_cut(self) -> None:
        for name in sorted(EXPECTED_FIXTURES):
            with self.subTest(fixture=name):
                claims = run_scenario(load_fixture(name))["claims"]
                self.assertEqual(claims["validation_level"], "SYNTHETIC")
                self.assertFalse(claims["real_os_shutdown"])
                self.assertFalse(claims["physical_power_cut"])
                self.assertFalse(claims["host_protocol_validated"])
                self.assertFalse(claims["raspberry_pi_model_validated"])
                self.assertFalse(claims["safe_shutdown_claim"])

    def test_report_schema_rejects_gap_04_validation_claims(self) -> None:
        report = run_scenario(load_fixture("normal_ack.json"))
        for field in ("host_protocol_validated", "raspberry_pi_model_validated"):
            with self.subTest(field=field):
                mutated = deepcopy(report)
                mutated["claims"][field] = True
                self.assertTrue(list(self.output_validator.iter_errors(mutated)))

    def test_fixed_variant_b_hash_and_module_gate_fail_closed(self) -> None:
        mutations = []
        bad_hash = load_fixture("normal_ack.json")
        bad_hash["variant_contract"]["profile_hash"] = "0" * 64
        mutations.append((bad_hash, "VARIANT_CONTRACT_HASH_MISMATCH"))
        bad_variant = load_fixture("normal_ack.json")
        bad_variant["variant_id"] = "A"
        mutations.append((bad_variant, "VARIANT_ID_MISMATCH"))
        bad_modules = load_fixture("normal_ack.json")
        bad_modules["enabled_modules"] = ["shutdown"]
        mutations.append((bad_modules, "VARIANT_B_MODULE_SET_MISMATCH"))

        self.assertEqual(
            load_fixture("normal_ack.json")["variant_contract"]["profile_hash"],
            APPROVED_VARIANT_B_PROFILE_HASH,
        )
        for scenario, expected_reason in mutations:
            with self.subTest(expected_reason=expected_reason):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_unknown_fields_fail_runtime_and_schema_validation(self) -> None:
        mutations = []
        root = load_fixture("normal_ack.json")
        root["unexpected"] = True
        mutations.append(root)
        source = load_fixture("normal_ack.json")
        source["source"]["unexpected"] = True
        mutations.append(source)
        threshold = load_fixture("normal_ack.json")
        threshold["timing_policy"]["ack_timeout_ms"]["unexpected"] = True
        mutations.append(threshold)
        event = load_fixture("normal_ack.json")
        event["events"][0]["unexpected"] = True
        mutations.append(event)

        for scenario in mutations:
            with self.subTest(keys=list(scenario)):
                self.assertTrue(list(self.input_validator.iter_errors(scenario)))
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("UNKNOWN_FIELD", reason_codes(report))

    def test_non_finite_numbers_return_structured_failures_and_stable_hashes(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                scenario = load_fixture("normal_ack.json")
                scenario["events"][0]["elapsed_time"] = value
                first = run_scenario(scenario)
                second = run_scenario(deepcopy(scenario))
                self.assertEqual(first["status"], "FAIL")
                self.assertIn("NON_FINITE_NUMBER", reason_codes(first))
                self.assertEqual(first["input_hash"], second["input_hash"])
                self.assertEqual(len(first["input_hash"]), 64)
                with self.assertRaises(ValueError):
                    json.dumps(scenario, allow_nan=False)

    def test_wrong_nested_types_return_closed_structured_reports(self) -> None:
        mutations = []
        classification = load_fixture("normal_ack.json")
        classification["source"]["classification"] = []
        mutations.append((classification, "SOURCE_CLASSIFICATION_INVALID"))
        authority = load_fixture("normal_ack.json")
        authority["variant_contract"]["source"]["authority"] = {}
        mutations.append((authority, "SOURCE_AUTHORITY_INVALID"))
        host_authority = load_fixture("normal_ack.json")
        host_authority["host_contract"]["source"] = {
            "classification": "SOURCE_EXPLICIT",
            "authority": "NOT_ALLOWED",
            "reference": "TEST-ONLY",
            "version": "test",
        }
        mutations.append((host_authority, "SOURCE_AUTHORITY_INVALID"))
        host_reference = load_fixture("normal_ack.json")
        host_reference["host_contract"]["source"] = {
            "classification": "SOURCE_EXPLICIT",
            "authority": "HOST_PROTOCOL",
            "reference": "",
            "version": "test",
        }
        mutations.append((host_reference, "SOURCE_REFERENCE_INVALID"))
        threshold = load_fixture("normal_ack.json")
        threshold["timing_policy"]["ack_timeout_ms"]["value_ms"] = []
        mutations.append((threshold, "THRESHOLD_VALUE_INVALID"))
        blank_id = load_fixture("normal_ack.json")
        blank_id["scenario_id"] = ""
        mutations.append((blank_id, "SCENARIO_ID_INVALID"))

        for scenario, expected_reason in mutations:
            with self.subTest(expected_reason=expected_reason):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))
                self.assert_schema_valid(self.output_validator, report)

    def test_hash_and_report_are_deterministic_and_key_order_independent(self) -> None:
        scenario = load_fixture("normal_ack.json")
        reordered = dict(reversed(list(deepcopy(scenario).items())))
        reordered["host_contract"] = dict(
            reversed(list(scenario["host_contract"].items()))
        )

        first = run_scenario(scenario)
        second = run_scenario(deepcopy(scenario))
        third = run_scenario(reordered)
        self.assertEqual(first, second)
        self.assertEqual(first["input_hash"], third["input_hash"])
        self.assertEqual(first["trace"], third["trace"])
        self.assertEqual(normalized_input_hash(scenario), first["input_hash"])

    def test_event_and_state_enumerations_are_exact(self) -> None:
        self.assertEqual(
            set(EVENTS),
            {"ignition-off", "host-notify", "ACK", "timeout", "cut", "restart"},
        )
        self.assertEqual(
            set(STATES),
            {
                "IGNITION_ON",
                "NOTIFY_PENDING",
                "WAIT_ACK",
                "GRACE_PERIOD",
                "READY_TO_CUT",
                "POWER_CUT",
                "RESTART",
            },
        )

    def test_real_world_claim_injection_is_rejected(self) -> None:
        for field in ("real_os_shutdown", "physical_power_cut"):
            with self.subTest(field=field):
                scenario = load_fixture("normal_ack.json")
                scenario["assertions"][field] = True
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("REAL_WORLD_CLAIM_FORBIDDEN", reason_codes(report))


if __name__ == "__main__":
    unittest.main()

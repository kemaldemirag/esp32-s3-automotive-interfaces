"""WF-03-03 synthetic LIN FSM tests (Python standard library only)."""

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

from repo03_lin import (  # noqa: E402
    APPROVED_VARIANT_A_PROFILE_HASH,
    ENGINE_ID,
    MODULE_ID,
    SCHEMA_VERSION,
    TOOL_VERSION,
    VARIANT_CONTRACT_SCHEMA,
    run_scenario,
)


FIXTURES = ROOT / "variants" / "fixtures" / "lin"
SCHEMA = ROOT / "variants" / "schema" / "repo03.lin.scenario.v1.json"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def reason_codes(report: dict[str, Any]) -> set[str]:
    return {str(issue["reason_code"]) for issue in report["issues"]}


class LinEngineTests(unittest.TestCase):
    def assert_report_envelope(self, report: dict[str, Any]) -> None:
        self.assertIn(report["status"], {"PASS", "FAIL", "UNKNOWN", "BLOCKED"})
        self.assertEqual(report["result"]["status"], report["status"])
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertEqual(report["engine_id"], ENGINE_ID)
        self.assertEqual(report["module_id"], MODULE_ID)
        self.assertTrue(report["synthetic_data"])
        self.assertEqual(len(report["input_hash"]), 64)
        self.assertEqual(report["tool_version"], TOOL_VERSION)
        self.assertNotIn("generated_at", report)
        self.assertIn("GAP-01", report["dependencies"])

        required_trace_fields = {
            "previous_state",
            "new_state",
            "event",
            "elapsed_time_ms",
            "observation_duration_ms",
            "wake_source",
            "threshold_source",
            "status",
            "rule_id",
            "reason_code",
            "responsibility",
            "uart_state",
            "transceiver_state",
            "bus_observation",
            "input_hash",
            "tool_version",
            "schema_version",
            "source_reference",
            "source_version",
        }
        for row in report["trace"]:
            self.assertTrue(required_trace_fields <= set(row))
            self.assertEqual(row["input_hash"], report["input_hash"])
            self.assertEqual(row["tool_version"], TOOL_VERSION)
            self.assertEqual(row["schema_version"], SCHEMA_VERSION)
            self.assertIn("classification", row["threshold_source"])
            self.assertIn("reference", row["threshold_source"])
            self.assertIn("version", row["threshold_source"])

    def test_schema_and_all_fixtures_are_valid_json(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["variant_id"]["const"], "A")
        self.assertEqual(schema["properties"]["module_id"]["const"], "lin")
        self.assertFalse(schema["$defs"]["event"]["additionalProperties"])
        self.assertNotIn("lin_transceiver", schema["required"])
        self.assertIn(
            "off",
            schema["$defs"]["lin_transceiver"]["properties"][
                "operational_state"
            ]["enum"],
        )
        self.assertFalse(schema["$defs"]["run_report"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["claims"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["dependencies"]["additionalProperties"])

        names = {
            "normal_wake_sleep.json",
            "wake_timeout.json",
            "stuck_dominant.json",
            "missing_transceiver_profile.json",
            "rapid_re_sleep.json",
            "invalid_order.json",
            "off_transceiver.json",
        }
        self.assertEqual({path.name for path in FIXTURES.glob("*.json")}, names)
        for name in names:
            with self.subTest(name=name):
                fixture = load_fixture(name)
                self.assertEqual(fixture["schema_version"], SCHEMA_VERSION)
                self.assertEqual(fixture["variant_id"], "A")
                self.assertEqual(set(fixture["enabled_modules"]), {"can", "lin", "gnss"})
                self.assertTrue(set(schema["required"]) <= set(fixture))
                self.assertTrue(set(fixture) <= set(schema["properties"]))
                self.assertEqual(
                    fixture["variant_contract"]["profile_hash"],
                    APPROVED_VARIANT_A_PROFILE_HASH,
                )
                for event in fixture["events"]:
                    self.assertTrue(
                        set(event) <= set(schema["$defs"]["event"]["properties"])
                    )
                    if event["event"].startswith("wake-"):
                        self.assertIn("wake_source", event)
                    else:
                        self.assertNotIn("wake_source", event)
                    if event["event"] == "bus-dominant":
                        self.assertIn("observation_duration_ms", event)
                    else:
                        self.assertNotIn("observation_duration_ms", event)

        missing = load_fixture("missing_transceiver_profile.json")
        self.assertNotIn("lin_transceiver", missing)
        off = load_fixture("off_transceiver.json")
        self.assertEqual(off["lin_transceiver"]["operational_state"], "off")

    def test_normal_wake_frame_and_sleep(self) -> None:
        report = run_scenario(load_fixture("normal_wake_sleep.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["final_state"], "sleep")
        self.assertEqual(
            [(row["previous_state"], row["new_state"]) for row in report["trace"]],
            [
                ("sleep", "wake-request"),
                ("wake-request", "awake"),
                ("awake", "frame-wait"),
                ("frame-wait", "awake"),
                ("awake", "sleep"),
            ],
        )
        self.assertTrue(
            all(row["source_reference"] and row["source_version"] for row in report["trace"])
        )

    def test_uart_success_is_not_physical_lin_evidence(self) -> None:
        report = run_scenario(load_fixture("normal_wake_sleep.json"))
        uart_row = next(
            row for row in report["trace"] if row["event"] == "uart-frame-received"
        )

        self.assertEqual(uart_row["status"], "PASS")
        self.assertEqual(uart_row["responsibility"], "uart-peripheral")
        self.assertEqual(uart_row["bus_observation"], "unknown")
        self.assertEqual(
            report["claims"]["physical_lin_evidence"]["status"], "UNKNOWN"
        )
        self.assertEqual(
            report["claims"]["physical_lin_evidence"]["reason_code"],
            "SYNTHETIC_UART_NOT_PHYSICAL_LIN_EVIDENCE",
        )

    def test_trace_boundaries_change_only_on_their_own_domain(self) -> None:
        report = run_scenario(load_fixture("normal_wake_sleep.json"))
        wake_request, wake_observed, frame_request, uart_received, sleep_request = (
            report["trace"]
        )

        self.assertEqual(wake_request["responsibility"], "state-control")
        self.assertEqual(wake_request["transceiver_state"], "unknown")
        self.assertEqual(wake_request["uart_state"], "idle")
        self.assertEqual(wake_request["bus_observation"], "unknown")
        self.assertEqual(wake_request["wake_source"], "synthetic-control")

        self.assertEqual(wake_observed["responsibility"], "lin-transceiver")
        self.assertEqual(wake_observed["transceiver_state"], "wake-observed")
        self.assertEqual(
            wake_observed["wake_source"], "synthetic-transceiver-observation"
        )

        self.assertEqual(frame_request["responsibility"], "state-control")
        self.assertEqual(frame_request["transceiver_state"], "wake-observed")
        self.assertEqual(frame_request["uart_state"], "idle")
        self.assertEqual(frame_request["bus_observation"], "unknown")

        self.assertEqual(uart_received["responsibility"], "uart-peripheral")
        self.assertEqual(uart_received["uart_state"], "received")
        self.assertEqual(uart_received["transceiver_state"], "wake-observed")
        self.assertEqual(uart_received["bus_observation"], "unknown")

        self.assertEqual(sleep_request["responsibility"], "state-control")
        self.assertEqual(sleep_request["transceiver_state"], "wake-observed")
        self.assertEqual(sleep_request["uart_state"], "received")
        self.assertEqual(sleep_request["bus_observation"], "unknown")

        timeout_report = run_scenario(load_fixture("wake_timeout.json"))
        self.assertEqual(timeout_report["trace"][-1]["responsibility"], "timer")
        self.assertEqual(timeout_report["trace"][-1]["transceiver_state"], "unknown")
        self.assertEqual(timeout_report["trace"][-1]["bus_observation"], "unknown")

    def test_wake_timeout_reaches_timeout_with_reason_code(self) -> None:
        report = run_scenario(load_fixture("wake_timeout.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["final_state"], "timeout")
        self.assertEqual(report["reason_code"], "WAKE_TIMEOUT")
        self.assertEqual(report["trace"][-1]["threshold_source"]["name"], "wake_timeout_ms")

    def test_stuck_dominant_is_bus_failure(self) -> None:
        report = run_scenario(load_fixture("stuck_dominant.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["final_state"], "stuck-dominant")
        self.assertEqual(report["reason_code"], "STUCK_DOMINANT")
        self.assertEqual(report["trace"][-1]["responsibility"], "lin-bus")
        self.assertEqual(report["trace"][-1]["bus_observation"], "stuck-dominant")
        self.assertEqual(report["trace"][-1]["elapsed_time_ms"], 1)
        self.assertEqual(report["trace"][-1]["observation_duration_ms"], 20)
        self.assertEqual(report["trace"][-1]["transceiver_state"], "wake-observed")

    def test_missing_transceiver_profile_blocks_wake_success(self) -> None:
        report = run_scenario(load_fixture("missing_transceiver_profile.json"))

        self.assert_report_envelope(report)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["final_state"], "sleep")
        self.assertIn("TRANSCEIVER_PROFILE_MISSING", reason_codes(report))
        self.assertEqual(report["trace"][0]["event"], "preflight")

    def test_rapid_re_sleep_enters_fault(self) -> None:
        report = run_scenario(load_fixture("rapid_re_sleep.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["final_state"], "fault")
        self.assertEqual(report["reason_code"], "RAPID_RE_SLEEP")
        self.assertEqual(
            report["trace"][-1]["threshold_source"]["name"],
            "min_awake_before_sleep_ms",
        )

    def test_invalid_event_order_enters_fault(self) -> None:
        report = run_scenario(load_fixture("invalid_order.json"))

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["final_state"], "fault")
        self.assertEqual(report["reason_code"], "INVALID_EVENT_ORDER")

    def test_hash_and_trace_are_deterministic_and_key_order_independent(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        reordered = dict(reversed(list(deepcopy(scenario).items())))
        reordered["lin_transceiver"] = dict(
            reversed(list(scenario["lin_transceiver"].items()))
        )

        first = run_scenario(scenario)
        second = run_scenario(deepcopy(scenario))
        reordered_report = run_scenario(reordered)

        self.assertEqual(first, second)
        self.assertEqual(first["input_hash"], reordered_report["input_hash"])
        self.assertEqual(first["trace"], reordered_report["trace"])

    def test_assumed_threshold_cannot_produce_overall_pass(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        scenario["lin_transceiver"]["wake_timeout_ms"]["source"][
            "classification"
        ] = "ASSUMPTION"

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "UNKNOWN")
        self.assertIn("THRESHOLD_SOURCE_UNKNOWN", reason_codes(report))
        self.assertEqual(report["trace"][0]["event"], "preflight")

    def test_missing_threshold_source_blocks_without_default(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        del scenario["state_policy"]["min_awake_before_sleep_ms"]["source"]

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("THRESHOLD_SOURCE_MISSING", reason_codes(report))

    def test_source_reference_and_version_are_mandatory(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        scenario["lin_transceiver"]["wake_timeout_ms"]["source"]["reference"] = ""
        scenario["lin_transceiver"]["wake_timeout_ms"]["source"]["version"] = ""

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("THRESHOLD_SOURCE_REFERENCE_INVALID", reason_codes(report))
        self.assertIn("THRESHOLD_SOURCE_VERSION_INVALID", reason_codes(report))

    def test_missing_transceiver_source_blocks_without_exception(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        del scenario["lin_transceiver"]["source"]

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("TRANSCEIVER_SOURCE_MISSING", reason_codes(report))

    def test_variant_engine_and_module_gates_cannot_be_bypassed(self) -> None:
        mutations = {
            "variant": ("variant_id", "B", "VARIANT_A_REQUIRED"),
            "engine": ("engine_id", "other-engine", "ENGINE_ID_INVALID"),
            "module": ("module_id", "can", "MODULE_ID_INVALID"),
            "lin-disabled": ("enabled_modules", ["can"], "LIN_MODULE_NOT_ENABLED"),
        }
        for label, (field, value, expected_reason) in mutations.items():
            with self.subTest(label=label):
                scenario = load_fixture("normal_wake_sleep.json")
                scenario[field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_foreign_and_duplicate_enabled_modules_fail(self) -> None:
        cases = [
            (["lin", "shutdown"], "FOREIGN_MODULE_ENABLED"),
            (["lin", "lin"], "DUPLICATE_ENABLED_MODULE"),
            (["lin"], "VARIANT_A_MODULE_SET_MISMATCH"),
        ]
        for modules, expected_reason in cases:
            with self.subTest(modules=modules):
                scenario = load_fixture("normal_wake_sleep.json")
                scenario["enabled_modules"] = modules
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_nonempty_scenario_id_and_event_list_are_required(self) -> None:
        cases = [
            ("scenario_id", "", "SCENARIO_ID_INVALID"),
            ("events", [], "EVENTS_EMPTY"),
        ]
        for field, value, expected_reason in cases:
            with self.subTest(field=field):
                scenario = load_fixture("normal_wake_sleep.json")
                scenario[field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_nested_additional_properties_fail_runtime_validation(self) -> None:
        scenarios = []
        uart = load_fixture("normal_wake_sleep.json")
        uart["uart_peripheral"]["extra"] = True
        scenarios.append((uart, "UNKNOWN_UART_PROFILE_FIELD"))

        transceiver = load_fixture("normal_wake_sleep.json")
        transceiver["lin_transceiver"]["extra"] = True
        scenarios.append((transceiver, "UNKNOWN_TRANSCEIVER_PROFILE_FIELD"))

        policy = load_fixture("normal_wake_sleep.json")
        policy["state_policy"]["extra"] = True
        scenarios.append((policy, "UNKNOWN_STATE_POLICY_FIELD"))

        threshold = load_fixture("normal_wake_sleep.json")
        threshold["state_policy"]["frame_timeout_ms"]["extra"] = True
        scenarios.append((threshold, "UNKNOWN_THRESHOLD_FIELD"))

        source = load_fixture("normal_wake_sleep.json")
        source["source"]["extra"] = True
        scenarios.append((source, "UNKNOWN_SOURCE_FIELD"))

        bus = load_fixture("normal_wake_sleep.json")
        bus["lin_bus"]["extra"] = True
        scenarios.append((bus, "UNKNOWN_BUS_PROFILE_FIELD"))

        contract = load_fixture("normal_wake_sleep.json")
        contract["variant_contract"]["extra"] = True
        scenarios.append((contract, "UNKNOWN_VARIANT_CONTRACT_FIELD"))

        for scenario, expected_reason in scenarios:
            with self.subTest(expected_reason=expected_reason):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))

    def test_wake_source_is_required_and_event_specific(self) -> None:
        cases = []
        missing = load_fixture("normal_wake_sleep.json")
        del missing["events"][0]["wake_source"]
        cases.append(missing)

        wrong = load_fixture("normal_wake_sleep.json")
        wrong["events"][1]["wake_source"] = "synthetic-control"
        cases.append(wrong)

        for scenario in cases:
            with self.subTest(scenario=scenario["scenario_id"]):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("WAKE_SOURCE_INVALID", reason_codes(report))

    def test_stuck_decision_uses_observation_duration_not_event_delta(self) -> None:
        scenario = load_fixture("stuck_dominant.json")
        scenario["events"][-1]["elapsed_time_ms"] = 100
        scenario["events"][-1]["observation_duration_ms"] = 1

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["final_state"], "awake")
        self.assertEqual(
            report["trace"][-1]["reason_code"],
            "BUS_DOMINANT_BELOW_THRESHOLD",
        )

    def test_bus_observation_duration_is_mandatory_and_bus_only(self) -> None:
        missing = load_fixture("stuck_dominant.json")
        del missing["events"][-1]["observation_duration_ms"]
        missing_report = run_scenario(missing)
        self.assertEqual(missing_report["status"], "FAIL")
        self.assertIn("OBSERVATION_DURATION_INVALID", reason_codes(missing_report))

        extra = load_fixture("normal_wake_sleep.json")
        extra["events"][0]["observation_duration_ms"] = 5
        extra_report = run_scenario(extra)
        self.assertEqual(extra_report["status"], "FAIL")
        self.assertIn("OBSERVATION_DURATION_NOT_ALLOWED", reason_codes(extra_report))

    def test_threshold_free_event_uses_its_domain_source(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        scenario["events"].insert(
            2,
            {"event": "bus-recessive", "domain": "lin-bus", "elapsed_time_ms": 1},
        )

        report = run_scenario(scenario)
        wake_request = report["trace"][0]
        bus_event = report["trace"][2]

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            wake_request["source_reference"],
            scenario["source"]["reference"],
        )
        self.assertEqual(
            bus_event["source_reference"],
            scenario["lin_bus"]["source"]["reference"],
        )
        self.assertEqual(
            bus_event["threshold_source"]["classification"], "NOT_APPLICABLE"
        )

    def test_variant_contract_hash_is_pinned(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        self.assertEqual(
            scenario["variant_contract"]["schema_version"],
            VARIANT_CONTRACT_SCHEMA,
        )
        scenario["variant_contract"]["profile_hash"] = "0" * 64

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("VARIANT_CONTRACT_HASH_MISMATCH", reason_codes(report))

    def test_run_report_matches_closed_schema_envelope(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        report = run_scenario(load_fixture("normal_wake_sleep.json"))
        report_schema = schema["$defs"]["run_report"]

        self.assertEqual(set(report), set(report_schema["required"]))
        self.assertEqual(set(report), set(report_schema["properties"]))
        self.assertFalse(report_schema["additionalProperties"])
        for key, definition_name in (
            ("claims", "claims"),
            ("source_versions", "source_versions"),
            ("dependencies", "dependencies"),
        ):
            definition = schema["$defs"][definition_name]
            self.assertEqual(set(report[key]), set(definition["required"]))
            self.assertEqual(set(report[key]), set(definition["properties"]))
            self.assertFalse(definition["additionalProperties"])

    def test_unhashable_json_values_return_structured_failures(self) -> None:
        scenarios = []
        classification = load_fixture("normal_wake_sleep.json")
        classification["source"]["classification"] = []
        scenarios.append((classification, "SCENARIO_SOURCE_CLASSIFICATION_INVALID"))

        initial_state = load_fixture("normal_wake_sleep.json")
        initial_state["initial_state"] = []
        scenarios.append((initial_state, "INITIAL_STATE_INVALID"))

        event_name = load_fixture("normal_wake_sleep.json")
        event_name["events"][0]["event"] = []
        scenarios.append((event_name, "EVENT_UNKNOWN"))

        for scenario, expected_reason in scenarios:
            with self.subTest(expected_reason=expected_reason):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(len(report["input_hash"]), 64)
                self.assertIn(expected_reason, reason_codes(report))

    def test_present_wrong_nested_types_are_fail_not_blocked(self) -> None:
        scenarios = []

        source = load_fixture("normal_wake_sleep.json")
        source["source"] = []
        scenarios.append((source, "SCENARIO_SOURCE_INVALID"))

        contract = load_fixture("normal_wake_sleep.json")
        contract["variant_contract"] = []
        scenarios.append((contract, "VARIANT_CONTRACT_INVALID"))

        uart = load_fixture("normal_wake_sleep.json")
        uart["uart_peripheral"] = []
        scenarios.append((uart, "UART_PROFILE_INVALID"))

        bus = load_fixture("normal_wake_sleep.json")
        bus["lin_bus"] = []
        scenarios.append((bus, "BUS_PROFILE_INVALID"))

        transceiver = load_fixture("normal_wake_sleep.json")
        transceiver["lin_transceiver"] = []
        scenarios.append((transceiver, "TRANSCEIVER_PROFILE_INVALID"))

        operational_state = load_fixture("normal_wake_sleep.json")
        operational_state["lin_transceiver"]["operational_state"] = []
        scenarios.append(
            (operational_state, "TRANSCEIVER_OPERATIONAL_STATE_INVALID")
        )

        threshold = load_fixture("normal_wake_sleep.json")
        threshold["lin_transceiver"]["wake_timeout_ms"] = []
        scenarios.append((threshold, "THRESHOLD_INVALID"))

        threshold_value = load_fixture("normal_wake_sleep.json")
        threshold_value["lin_transceiver"]["wake_timeout_ms"]["value_ms"] = []
        scenarios.append((threshold_value, "THRESHOLD_VALUE_INVALID"))

        state_policy = load_fixture("normal_wake_sleep.json")
        state_policy["state_policy"] = []
        scenarios.append((state_policy, "STATE_POLICY_INVALID"))

        for scenario, expected_reason in scenarios:
            with self.subTest(expected_reason=expected_reason):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(expected_reason, reason_codes(report))
                self.assertEqual(len(report["input_hash"]), 64)

    def test_absent_or_null_nested_inputs_are_blocked(self) -> None:
        scenarios = []

        source = load_fixture("normal_wake_sleep.json")
        source["source"] = None
        scenarios.append((source, "SCENARIO_SOURCE_MISSING"))

        contract = load_fixture("normal_wake_sleep.json")
        contract["variant_contract"] = None
        scenarios.append((contract, "VARIANT_CONTRACT_MISSING"))

        uart = load_fixture("normal_wake_sleep.json")
        uart["uart_peripheral"] = None
        scenarios.append((uart, "UART_PROFILE_MISSING"))

        bus = load_fixture("normal_wake_sleep.json")
        bus["lin_bus"] = None
        scenarios.append((bus, "BUS_PROFILE_MISSING"))

        transceiver = load_fixture("normal_wake_sleep.json")
        transceiver["lin_transceiver"] = None
        scenarios.append((transceiver, "TRANSCEIVER_PROFILE_MISSING"))

        operational_state = load_fixture("normal_wake_sleep.json")
        operational_state["lin_transceiver"]["operational_state"] = None
        scenarios.append(
            (operational_state, "TRANSCEIVER_OPERATIONAL_STATE_MISSING")
        )

        threshold = load_fixture("normal_wake_sleep.json")
        threshold["lin_transceiver"]["wake_timeout_ms"] = None
        scenarios.append((threshold, "THRESHOLD_MISSING"))

        threshold_value = load_fixture("normal_wake_sleep.json")
        threshold_value["lin_transceiver"]["wake_timeout_ms"]["value_ms"] = None
        scenarios.append((threshold_value, "THRESHOLD_VALUE_UNRESOLVED"))

        state_policy = load_fixture("normal_wake_sleep.json")
        state_policy["state_policy"] = None
        scenarios.append((state_policy, "STATE_POLICY_MISSING"))

        for scenario, expected_reason in scenarios:
            with self.subTest(expected_reason=expected_reason):
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "BLOCKED")
                self.assertIn(expected_reason, reason_codes(report))

    def test_event_domain_and_extra_fields_fail_preflight(self) -> None:
        scenario = load_fixture("normal_wake_sleep.json")
        scenario["events"][3]["domain"] = "lin-bus"
        scenario["events"][3]["loopback_pass"] = True

        report = run_scenario(scenario)

        self.assertEqual(report["status"], "FAIL")
        self.assertIn("EVENT_DOMAIN_MISMATCH", reason_codes(report))
        self.assertIn("UNKNOWN_EVENT_FIELD", reason_codes(report))

    def test_physical_part_voltage_and_pass_claims_are_rejected(self) -> None:
        forbidden = [
            ("physical_pass", True),
            ("physical_bus_pass", True),
            ("part_number", "UNVERIFIED"),
            ("voltage", 12.0),
            ("bus_voltage_v", 12.0),
            ("measured", {"value": 1}),
            ("measured_value", 1),
        ]
        for field, value in forbidden:
            with self.subTest(field=field):
                scenario = load_fixture("normal_wake_sleep.json")
                scenario["events"][0][field] = value
                report = run_scenario(scenario)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn(
                    "PHYSICAL_EVIDENCE_INJECTION_FORBIDDEN", reason_codes(report)
                )

    def test_disabled_transceiver_is_blocked(self) -> None:
        report = run_scenario(load_fixture("off_transceiver.json"))

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("TRANSCEIVER_UNAVAILABLE", reason_codes(report))


if __name__ == "__main__":
    unittest.main()

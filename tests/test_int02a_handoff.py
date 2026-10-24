from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = REPO_ROOT / "firmware"
if str(FIRMWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_ROOT))

from repo03_integration import (  # noqa: E402
    ARTIFACT_RELATIVE_PATH,
    DESCRIPTOR_FILE_NAME,
    HandoffValidationError,
    build_descriptor,
    canonical_report_bytes,
    dependency_contract,
    descriptor_input_hash,
    materialize_power_handoff,
    validate_report_binding,
)
from repo03_power import run_scenario  # noqa: E402


FIXTURE = REPO_ROOT / "variants" / "fixtures" / "automotive_power" / "nominal.json"
DEPENDENCY = FIRMWARE_ROOT / "repo03_integration" / "rep02_dependency.v1.json"
EVIDENCE_ROOT = REPO_ROOT / "evidence" / "INT-02A"

EXPECTED_ARTIFACT_SIZE = 6036
EXPECTED_ARTIFACT_SHA256 = "283b71938deefb22a2cc89192f2193c2f52967224cd5408d63e8d0cae900c256"
EXPECTED_DESCRIPTOR_HASH = "d4eb1b548689adf7cf7e217310ec1ea631c7a8ec9e4dc01233d2525890d39336"
EXPECTED_DEPENDENCY_SHA256 = "423c728d505ad8660f5eb51e54a23bb61842979bac43f445d4487803d44b406f"


def load_scenario() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def nominal_report() -> dict:
    return run_scenario(load_scenario())


class Int02aDeterministicVectorTests(unittest.TestCase):
    def test_nominal_report_bytes_match_pinned_vector(self) -> None:
        payload = canonical_report_bytes(nominal_report())
        self.assertEqual(EXPECTED_ARTIFACT_SIZE, len(payload))
        self.assertEqual(EXPECTED_ARTIFACT_SHA256, hashlib.sha256(payload).hexdigest())
        self.assertNotIn(b"\n", payload)
        json.loads(payload.decode("utf-8"))

    def test_descriptor_matches_pinned_vector_and_closed_claim_boundary(self) -> None:
        report = nominal_report()
        binding = validate_report_binding(report)
        descriptor = build_descriptor(EXPECTED_ARTIFACT_SHA256, binding)
        self.assertEqual(EXPECTED_DESCRIPTOR_HASH, descriptor["input_hash"])
        self.assertEqual(EXPECTED_DESCRIPTOR_HASH, descriptor_input_hash(descriptor))
        self.assertEqual("INT-02A-REP03-POWER-NOMINAL-001", descriptor["descriptor_id"])
        self.assertEqual("REP-03", descriptor["producer"]["repository_id"])
        self.assertEqual("REP-02", descriptor["consumer"]["repository_id"])
        self.assertEqual("REP03-VARIANT-B", descriptor["configurations"][0]["configuration_id"])
        self.assertEqual("POWER-NOMINAL-001", descriptor["configurations"][0]["profile_id"])
        self.assertEqual(5, len(descriptor["claim_limits"]))
        self.assertIn("LIVE_ADAPTERS_NOT_RUN", descriptor["claim_limits"])
        self.assertIn("NO_HARDWARE_COMPLIANCE_CLAIM", descriptor["claim_limits"])

    def test_two_materializations_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            first = materialize_power_handoff(load_scenario(), root / "first")
            second = materialize_power_handoff(load_scenario(), root / "second")
            first_artifact = first["artifact_path"].read_bytes()
            second_artifact = second["artifact_path"].read_bytes()
            first_descriptor = first["descriptor_path"].read_bytes()
            second_descriptor = second["descriptor_path"].read_bytes()
        self.assertEqual(first_artifact, second_artifact)
        self.assertEqual(first_descriptor, second_descriptor)
        self.assertEqual(EXPECTED_ARTIFACT_SHA256, hashlib.sha256(first_artifact).hexdigest())
        self.assertEqual(EXPECTED_DESCRIPTOR_HASH, first["descriptor_input_hash"])

    def test_materialized_paths_are_fixed_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            result = materialize_power_handoff(load_scenario(), root)
            self.assertEqual(root / DESCRIPTOR_FILE_NAME, result["descriptor_path"])
            self.assertEqual(
                root.joinpath(*ARTIFACT_RELATIVE_PATH.split("/")),
                result["artifact_path"],
            )


class Int02aFailClosedBindingTests(unittest.TestCase):
    def assert_error(self, report: dict, expected_code: str) -> None:
        with self.assertRaises(HandoffValidationError) as raised:
            validate_report_binding(report)
        self.assertEqual(expected_code, raised.exception.code)
        self.assertEqual("BLOCKED", raised.exception.as_dict()["status"])

    def test_variant_a_and_combined_variant_are_rejected(self) -> None:
        for variant in ("A", "A+B"):
            report = nominal_report()
            report["variant_id"] = variant
            with self.subTest(variant=variant):
                self.assert_error(report, "VARIANT_B_REQUIRED")

    def test_wrong_module_schema_or_tool_identity_is_rejected(self) -> None:
        mutations = {
            "module_id": "can",
            "schema_version": "repo03.can.scenario.v1",
            "tool_version": "repo03-power-engine/latest",
            "input_hash": "0" * 64,
        }
        for field, value in mutations.items():
            report = nominal_report()
            report[field] = value
            with self.subTest(field=field):
                self.assert_error(report, "REPORT_BINDING_MISMATCH")
        report = nominal_report()
        report["unexpected"] = "field"
        self.assert_error(report, "CLOSED_OBJECT_MISMATCH")

    def test_nonfinite_report_is_rejected_before_hashing_or_writing(self) -> None:
        report = nominal_report()
        report["profile_assessment"]["input_voltage"] = math.nan
        self.assert_error(report, "NON_FINITE_NUMBER")
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as temporary:
            root = Path(temporary)
            scenario = load_scenario()
            scenario["profile"]["input_voltage"] = math.inf
            with self.assertRaises(HandoffValidationError):
                materialize_power_handoff(scenario, root)
            self.assertFalse((root / DESCRIPTOR_FILE_NAME).exists())

    def test_true_real_world_claim_is_rejected(self) -> None:
        for value in (True, 1, "true", None):
            report = nominal_report()
            report["claims"]["physical_validation"] = value
            with self.subTest(value=value):
                self.assert_error(report, "REAL_WORLD_CLAIM_FORBIDDEN")
        report = nominal_report()
        del report["claims"]["physical_validation"]
        self.assert_error(report, "CLOSED_OBJECT_MISMATCH")
        report = nominal_report()
        report["claims"]["unexpected_claim"] = False
        self.assert_error(report, "CLOSED_OBJECT_MISMATCH")

    def test_historical_d2_capability_boundary_cannot_be_rewritten(self) -> None:
        for field, value in (("integration_status", "PASS"), ("execution_status", "PASS")):
            report = nominal_report()
            report["dependencies"]["rep02"][field] = value
            with self.subTest(field=field):
                self.assert_error(report, "D2_BOUNDARY_EXPANDED")

    def test_invalid_artifact_digest_is_rejected(self) -> None:
        binding = validate_report_binding(nominal_report())
        with self.assertRaises(HandoffValidationError) as raised:
            build_descriptor("0" * 63, binding)
        self.assertEqual("ARTIFACT_SHA256_INVALID", raised.exception.code)
        with self.assertRaises(HandoffValidationError) as raised:
            build_descriptor("0" * 64, binding)
        self.assertEqual("ARTIFACT_SHA256_MISMATCH", raised.exception.code)
        with self.assertRaises(HandoffValidationError) as raised:
            build_descriptor(EXPECTED_ARTIFACT_SHA256, {"variant_id": "B"})
        self.assertEqual("CLOSED_OBJECT_MISMATCH", raised.exception.code)


class Int02aDependencyPinTests(unittest.TestCase):
    def test_dependency_contract_pins_reviewed_wheel_and_file_api(self) -> None:
        value = dependency_contract()
        rep02 = value["rep02"]
        self.assertEqual("0.5.0", rep02["package_version"])
        self.assertEqual(
            "000c88499a8848fcc83dfbdc9352a9f0a0dea3a9",
            rep02["source_baseline_commit"],
        )
        self.assertEqual(
            "27ba10f6e14345c39f70241e56abd67469eb7e8130dc6a0abfdb37ca1a8c5027",
            rep02["wheel"]["sha256"],
        )
        self.assertEqual("DIRTY", rep02["wheel"]["build_record_working_tree"])
        self.assertEqual("1.0.0", rep02["file_api"]["api_version"])
        self.assertEqual(
            "e1a40ffd49fb126152a89e37e173ca8aeb87c76f9dc6477540a4b0708c2857da",
            rep02["file_api"]["contract_sha256"],
        )

    def test_dependency_record_bytes_are_pinned(self) -> None:
        self.assertEqual(
            EXPECTED_DEPENDENCY_SHA256,
            hashlib.sha256(DEPENDENCY.read_bytes()).hexdigest(),
        )

    def test_report_binding_does_not_use_historical_adapter_mapping_as_evidence(self) -> None:
        report = nominal_report()
        first = validate_report_binding(report)
        modified = copy.deepcopy(report)
        modified["adapter_mapping"] = {
            "untrusted": "this field is not descriptor material"
        }
        second = validate_report_binding(modified)
        self.assertEqual(first, second)
        first_descriptor = build_descriptor(EXPECTED_ARTIFACT_SHA256, first)
        second_descriptor = build_descriptor(EXPECTED_ARTIFACT_SHA256, second)
        self.assertEqual(first_descriptor, second_descriptor)


class Int02aEvidenceIntegrityTests(unittest.TestCase):
    def test_detached_manifest_checksum_matches(self) -> None:
        manifest_path = EVIDENCE_ROOT / "manifest.json"
        checksum = (EVIDENCE_ROOT / "manifest.json.sha256").read_text(
            encoding="ascii"
        ).strip()
        expected = checksum.split()[0]
        self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), expected)

    def test_manifest_inventory_matches_current_bytes(self) -> None:
        manifest = json.loads((EVIDENCE_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("PASS", manifest["status"])
        self.assertEqual(8, manifest["negative_case_count"])
        expected_paths = {
            ".gitattributes",
            "evidence/INT-02A/handoff/artifacts/power-nominal-001.report.json",
            "evidence/INT-02A/handoff/rep03-to-rep02.descriptor.json",
            "evidence/INT-02A/negative-results.json",
            "evidence/INT-02A/verification-record.md",
            "evidence/INT-02A/verification-result.json",
            "firmware/repo03_integration/__init__.py",
            "firmware/repo03_integration/rep02_dependency.v1.json",
            "firmware/repo03_integration/rep02_file_api.py",
            "scripts/verify_int02a_wheel.py",
            "tests/test_int02a_handoff.py",
        }
        observed_paths = {record["path"] for record in manifest["files"]}
        self.assertEqual(expected_paths, observed_paths)
        for record in manifest["files"]:
            with self.subTest(path=record["path"]):
                path = REPO_ROOT / record["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(record["size_bytes"], path.stat().st_size)
                self.assertEqual(record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

        scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
        canonical_scenario = json.dumps(
            scenario,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(canonical_scenario).hexdigest(),
            manifest["scenario"]["canonical_sha256"],
        )
        self.assertEqual("CANONICAL_JSON_SHA256", manifest["scenario"]["identity"])
        self.assertEqual(
            "variants/fixtures/automotive_power/nominal.json",
            manifest["scenario"]["path"],
        )

    def test_positive_result_preserves_offline_claim_boundary(self) -> None:
        value = json.loads(
            (EVIDENCE_ROOT / "verification-result.json").read_text(encoding="utf-8")
        )
        self.assertEqual("PASS", value["status"])
        self.assertEqual("OFFLINE_FILE_INTEGRITY_ONLY", value["scope"])
        self.assertEqual("PASS", value["rep02_validation"]["status"])
        self.assertEqual(
            "FILE_API_DESCRIPTOR_VALID",
            value["rep02_validation"]["reason_code"],
        )
        self.assertEqual(
            {"NOT_RUN"},
            {item["status"] for item in value["rep02_validation"]["adapter_results"]},
        )
        self.assertTrue(value["claim_boundary"]["descriptor_and_exact_bytes"])
        for field in (
            "semantic_power_mapping",
            "live_adapter_execution",
            "rep02_power_engine_execution",
            "physical_or_compliance_validation",
        ):
            self.assertFalse(value["claim_boundary"][field])

    def test_handoff_descriptor_and_artifact_hashes_replay(self) -> None:
        descriptor = json.loads(
            (EVIDENCE_ROOT / "handoff" / DESCRIPTOR_FILE_NAME).read_text(encoding="utf-8")
        )
        artifact = EVIDENCE_ROOT / "handoff"
        artifact = artifact.joinpath(*ARTIFACT_RELATIVE_PATH.split("/"))
        declared = descriptor["configurations"][0]["artifacts"][0]["sha256"]
        self.assertEqual(EXPECTED_ARTIFACT_SHA256, declared)
        self.assertEqual(declared, hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertEqual(EXPECTED_DESCRIPTOR_HASH, descriptor["input_hash"])
        self.assertEqual(descriptor["input_hash"], descriptor_input_hash(descriptor))
        self.assertEqual(canonical_report_bytes(json.loads(artifact.read_text(encoding="utf-8"))), artifact.read_bytes())


if __name__ == "__main__":
    unittest.main()

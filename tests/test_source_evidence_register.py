"""Closed, fail-closed checks for the REP-03 source/evidence register."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "evidence" / "source_evidence_register.v1.json"
REVIEW_DATE = "2026-10-24"

ROOT_KEYS = {
    "schema_version",
    "register_id",
    "register_version",
    "project",
    "review",
    "policy",
    "sources",
    "gaps",
}
PROJECT_KEYS = {"project_id", "repository", "baseline_commit", "register_purpose"}
REVIEW_KEYS = {"last_reviewed", "evidence_cutoff", "review_scope"}
POLICY_KEYS = {
    "structure",
    "unknown_properties",
    "gap_status_vocabulary",
    "missing_or_unverified_evidence",
    "conflicting_evidence",
    "remote_source_without_content_hash",
    "closure_rule",
    "invalid_or_unknown_status_behavior",
    "physical_claim_default",
}
SOURCE_KEYS = {
    "source_id",
    "title",
    "source_role",
    "owner",
    "authority",
    "source_status",
    "reference",
    "version",
    "sha256",
    "reviewed_on",
    "can_close_gap",
    "applies_to",
    "limitation",
}
GAP_KEYS = {
    "gap_id",
    "title",
    "variant_scope",
    "status",
    "status_reason",
    "source_owner",
    "required_authorities",
    "current_source_ids",
    "required_source_ids",
    "affected_contracts",
    "closure_criteria",
    "last_reviewed",
    "physical_claim_limit",
}
CONTRACT_KEYS = {"kind", "reference"}
CRITERION_KEYS = {"criterion_id", "requirement", "current_result", "evidence_rule"}
CLAIM_LIMIT_KEYS = {"physical_claims_allowed", "allowed_claim_level", "statement"}

SOURCE_ROLES = {
    "PROJECT_CONTRACT_GUIDANCE",
    "RESEARCH_GUIDANCE",
    "REQUIRED_CLOSURE_EVIDENCE",
}
SOURCE_STATUSES = {
    "VERIFIED_LOCAL",
    "REMOTE_REFERENCE_REVIEWED",
    "MISSING_REQUIRED_SOURCE",
    "AVAILABLE_VERIFIED",
}
CRITERION_RESULTS = {"BLOCKED", "PASS"}
GAP_IDS = {"GAP-01", "GAP-02", "GAP-03", "GAP-04"}
EXPECTED_REQUIRED_SOURCE_AUTHORITY = {
    "GAP-01": "APPROVED_BOM_AND_COMPONENT_MANUFACTURER",
    "GAP-02": "APPROVED_BOM_COMPONENT_MANUFACTURER_AND_RF_REVIEW",
    "GAP-03": "APPROVED_OEM_REQUIREMENT_AND_COMPONENT_MANUFACTURER",
    "GAP-04": "APPROVED_CLIENT_REQUIREMENT_AND_PLATFORM_MANUFACTURER",
}


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_register() -> dict:
    with REGISTER_PATH.open(encoding="utf-8") as source:
        return json.load(source, object_pairs_hook=reject_duplicate_keys)


class SourceEvidenceRegisterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.register = load_register()
        cls.sources = {
            item["source_id"]: item for item in cls.register["sources"]
        }

    def assert_exact_keys(self, value: dict, expected: set[str], label: str) -> None:
        self.assertIs(type(value), dict, label)
        self.assertEqual(set(value), expected, label)

    def test_root_and_policy_are_closed_and_fail_closed(self) -> None:
        self.assert_exact_keys(self.register, ROOT_KEYS, "register")
        self.assert_exact_keys(self.register["project"], PROJECT_KEYS, "project")
        self.assert_exact_keys(self.register["review"], REVIEW_KEYS, "review")
        self.assert_exact_keys(self.register["policy"], POLICY_KEYS, "policy")

        self.assertEqual(
            self.register["schema_version"],
            "repo03.source-evidence-register.v1",
        )
        self.assertEqual(self.register["register_version"], "1.0.0")
        self.assertEqual(self.register["review"]["last_reviewed"], REVIEW_DATE)
        self.assertEqual(self.register["review"]["evidence_cutoff"], REVIEW_DATE)

        policy = self.register["policy"]
        self.assertEqual(policy["structure"], "CLOSED_TEST_ENFORCED")
        self.assertEqual(policy["unknown_properties"], "REJECT")
        self.assertEqual(policy["gap_status_vocabulary"], ["BLOCKED", "CLOSED"])
        self.assertEqual(policy["missing_or_unverified_evidence"], "BLOCKED")
        self.assertEqual(policy["conflicting_evidence"], "BLOCKED")
        self.assertEqual(policy["remote_source_without_content_hash"], "RESEARCH_ONLY")
        self.assertEqual(
            policy["invalid_or_unknown_status_behavior"],
            "REJECT_REGISTER_AND_KEEP_G1_BLOCKED",
        )
        self.assertEqual(policy["physical_claim_default"], "PROHIBITED")

    def test_source_records_are_closed_traceable_and_role_limited(self) -> None:
        source_ids = [item["source_id"] for item in self.register["sources"]]
        self.assertEqual(len(source_ids), len(set(source_ids)), "duplicate source_id")
        self.assertGreaterEqual(len(source_ids), 9)

        for source in self.register["sources"]:
            with self.subTest(source_id=source["source_id"]):
                self.assert_exact_keys(source, SOURCE_KEYS, source["source_id"])
                self.assertIn(source["source_role"], SOURCE_ROLES)
                self.assertIn(source["source_status"], SOURCE_STATUSES)
                self.assertEqual(source["reviewed_on"], REVIEW_DATE)
                self.assertIs(type(source["can_close_gap"]), bool)
                self.assertIs(type(source["applies_to"]), list)
                self.assertTrue(set(source["applies_to"]).issubset(GAP_IDS))
                self.assertTrue(source["title"].strip())
                self.assertTrue(source["owner"].strip())
                self.assertTrue(source["authority"].strip())
                self.assertTrue(source["limitation"].strip())

                if source["source_role"] in {
                    "RESEARCH_GUIDANCE",
                    "PROJECT_CONTRACT_GUIDANCE",
                }:
                    self.assertFalse(source["can_close_gap"])

                if source["source_status"] == "MISSING_REQUIRED_SOURCE":
                    self.assertIsNone(source["reference"])
                    self.assertIsNone(source["version"])
                    self.assertIsNone(source["sha256"])
                    self.assertFalse(source["can_close_gap"])

                if source["sha256"] is not None:
                    self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")

                if source["source_status"] == "REMOTE_REFERENCE_REVIEWED":
                    self.assertTrue(source["reference"].startswith("https://"))
                    self.assertIsNone(source["sha256"])
                    self.assertEqual(source["source_role"], "RESEARCH_GUIDANCE")
                    self.assertFalse(source["can_close_gap"])

    def test_local_task_plan_hash_is_pinned_and_not_gap_closing(self) -> None:
        source = self.sources["SRC-PLAN-WF-03-06-V1"]
        plan_path = ROOT / source["reference"]
        self.assertTrue(plan_path.is_file())
        digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        self.assertEqual(digest, source["sha256"])
        self.assertEqual(source["source_role"], "PROJECT_CONTRACT_GUIDANCE")
        self.assertEqual(source["authority"], "PROJECT_PLAN")
        self.assertFalse(source["can_close_gap"])

    def test_all_four_gap_records_are_closed_and_currently_blocked(self) -> None:
        gaps = self.register["gaps"]
        self.assertEqual({item["gap_id"] for item in gaps}, GAP_IDS)
        self.assertEqual(len(gaps), len(GAP_IDS))

        for gap in gaps:
            with self.subTest(gap_id=gap["gap_id"]):
                self.assert_exact_keys(gap, GAP_KEYS, gap["gap_id"])
                self.assertIn(gap["status"], self.register["policy"]["gap_status_vocabulary"])
                self.assertEqual(gap["status"], "BLOCKED")
                self.assertEqual(gap["last_reviewed"], REVIEW_DATE)
                self.assertTrue(gap["status_reason"].strip())
                self.assertTrue(gap["source_owner"].strip())
                self.assertTrue(gap["required_authorities"])
                self.assertTrue(gap["current_source_ids"])
                self.assertTrue(gap["required_source_ids"])
                self.assertTrue(set(gap["required_source_ids"]).issubset(gap["current_source_ids"]))
                self.assertTrue(set(gap["current_source_ids"]).issubset(self.sources))

                for contract in gap["affected_contracts"]:
                    self.assert_exact_keys(contract, CONTRACT_KEYS, gap["gap_id"])
                    self.assertIn(contract["kind"], {"FILE", "PLANNED_CONTRACT"})
                    self.assertTrue(contract["reference"].strip())
                    if contract["kind"] == "FILE":
                        self.assertTrue((ROOT / contract["reference"]).is_file())

                expected_prefix = gap["gap_id"] + "-C"
                self.assertTrue(gap["closure_criteria"])
                for criterion in gap["closure_criteria"]:
                    self.assert_exact_keys(criterion, CRITERION_KEYS, criterion.get("criterion_id", "criterion"))
                    self.assertTrue(criterion["criterion_id"].startswith(expected_prefix))
                    self.assertIn(criterion["current_result"], CRITERION_RESULTS)
                    self.assertTrue(criterion["requirement"].strip())
                    self.assertTrue(criterion["evidence_rule"].strip())

                limit = gap["physical_claim_limit"]
                self.assert_exact_keys(limit, CLAIM_LIMIT_KEYS, gap["gap_id"])
                self.assertIs(limit["physical_claims_allowed"], False)
                self.assertEqual(limit["allowed_claim_level"], "SYNTHETIC_ONLY")
                self.assertTrue(limit["statement"].strip())

    def test_gap_closure_invariant_is_fail_closed(self) -> None:
        for gap in self.register["gaps"]:
            required_sources = [self.sources[item] for item in gap["required_source_ids"]]
            sources_ready = all(
                item["source_status"] == "AVAILABLE_VERIFIED"
                and item["can_close_gap"]
                and item["reference"]
                and item["version"]
                and item["sha256"]
                and item["authority"]
                == EXPECTED_REQUIRED_SOURCE_AUTHORITY[gap["gap_id"]]
                and item["applies_to"] == [gap["gap_id"]]
                for item in required_sources
            )
            criteria_pass = all(
                item["current_result"] == "PASS"
                for item in gap["closure_criteria"]
            )
            expected_status = "CLOSED" if sources_ready and criteria_pass else "BLOCKED"
            with self.subTest(gap_id=gap["gap_id"]):
                self.assertEqual(gap["status"], expected_status)

    def test_research_and_task_plan_cannot_satisfy_required_sources(self) -> None:
        forbidden_roles = {"RESEARCH_GUIDANCE", "PROJECT_CONTRACT_GUIDANCE"}
        for gap in self.register["gaps"]:
            required = [self.sources[item] for item in gap["required_source_ids"]]
            with self.subTest(gap_id=gap["gap_id"]):
                self.assertTrue(
                    all(item["source_role"] == "REQUIRED_CLOSURE_EVIDENCE" for item in required)
                )
                self.assertTrue(
                    all(item["source_role"] not in forbidden_roles for item in required)
                )


if __name__ == "__main__":
    unittest.main()

"""D4 command-line and aggregate-report acceptance tests."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from repo03_cli import __version__
from repo03_cli import cli


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "variants" / "fixtures"
TEST_TEMP_ROOT = ROOT / "build" / "test-cli"


class CliTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def invoke(
        self, arguments: list[str], stdin: str = ""
    ) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("sys.stdin", StringIO(stdin)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def fixture(self, *parts: str) -> str:
        return str(FIXTURES.joinpath(*parts))

    def report_a_arguments(self) -> list[str]:
        return [
            "report",
            "--variant",
            "A",
            "--profile",
            self.fixture("valid_variant_a.json"),
            "--can",
            self.fixture("can", "normal_frame.json"),
            "--lin",
            self.fixture("lin", "normal_wake_sleep.json"),
            "--gnss",
            self.fixture("gnss", "valid_synthetic_fix.json"),
        ]

    def test_version_and_help_are_successful(self) -> None:
        code, stdout, stderr = self.invoke(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, f"repo03 {__version__}\n")
        self.assertEqual(stderr, "")

        code, stdout, stderr = self.invoke(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("{validate,can,lin,gnss,automotive-power,shutdown,report}", stdout)
        self.assertEqual(stderr, "")

    def test_engine_stdout_is_canonical_json_with_status_exit(self) -> None:
        code, stdout, stderr = self.invoke(
            [
                "can",
                "--variant",
                "A",
                self.fixture("can", "normal_frame.json"),
            ]
        )

        report = json.loads(stdout)
        expected = json.dumps(
            report,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(stdout, expected)
        self.assertEqual(stderr, "")

    def test_all_report_statuses_map_to_documented_exit_codes(self) -> None:
        expected = {
            "PASS": 0,
            "FAIL": 10,
            "UNKNOWN": 11,
            "BLOCKED": 12,
            "NOT_RUN": 13,
        }
        for status, exit_code in expected.items():
            with self.subTest(status=status):
                runner = lambda _scenario, value=status: {"status": value}
                with patch.dict(cli._ENGINE_COMMANDS, {"can": ("A", runner)}):
                    code, stdout, stderr = self.invoke(
                        [
                            "can",
                            "--variant",
                            "A",
                            self.fixture("can", "normal_frame.json"),
                        ]
                    )
                self.assertEqual(code, exit_code)
                self.assertEqual(json.loads(stdout), {"status": status})
                self.assertEqual(stderr, "")

    def test_validate_combined_profile_is_a_validator_failure(self) -> None:
        code, stdout, stderr = self.invoke(
            [
                "validate",
                "--variant",
                "A",
                self.fixture("invalid_combined.json"),
            ]
        )

        self.assertEqual(code, 10)
        self.assertEqual(json.loads(stdout)["status"], "FAIL")
        self.assertEqual(stderr, "")

    def test_variant_gate_precedes_engine_input_and_rejects_payload_mismatch(self) -> None:
        code, stdout, stderr = self.invoke(
            ["can", "--variant", "B", "file-that-must-not-be-opened.json"]
        )
        self.assertEqual(code, 64)
        self.assertEqual(stdout, "")
        self.assertIn("can requires --variant A", stderr)

        code, stdout, stderr = self.invoke(
            [
                "can",
                "--variant",
                "A",
                self.fixture("automotive_power", "nominal.json"),
            ]
        )
        self.assertEqual(code, 64)
        self.assertEqual(stdout, "")
        self.assertIn("variant_id must match --variant A", stderr)

    def test_stdin_and_atomic_output_are_supported(self) -> None:
        source = Path(self.fixture("can", "normal_frame.json")).read_text(
            encoding="utf-8"
        )
        code, stdin_stdout, stderr = self.invoke(
            ["can", "--variant", "A", "-"], stdin=source
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdin_stdout)["status"], "PASS")
        self.assertEqual(stderr, "")

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            output = Path(directory) / "report.json"
            code, stdout, stderr = self.invoke(
                [
                    "can",
                    "--variant",
                    "A",
                    self.fixture("can", "normal_frame.json"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            payload = output.read_bytes()
            self.assertTrue(payload.endswith(b"\n"))
            self.assertEqual(payload, stdin_stdout.encode("utf-8"))
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_strict_json_rejects_duplicates_nonfinite_and_nonobject_roots(self) -> None:
        bad_documents = {
            "duplicate": '{"variant_id":"A","variant_id":"A"}',
            "nan": '{"variant_id":"A","value":NaN}',
            "overflow": '{"variant_id":"A","value":1e400}',
            "root": "[]",
        }
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            for name, document in bad_documents.items():
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.json"
                    path.write_text(document, encoding="utf-8")
                    code, stdout, stderr = self.invoke(
                        ["validate", "--variant", "A", str(path)]
                    )
                    self.assertEqual(code, 65)
                    self.assertEqual(stdout, "")
                    self.assertTrue(stderr.startswith("repo03: error:"))

            invalid_utf8 = Path(directory) / "invalid-utf8.json"
            invalid_utf8.write_bytes(b'{"variant_id":"A","x":"\xff"}')
            code, stdout, stderr = self.invoke(
                ["validate", "--variant", "A", str(invalid_utf8)]
            )
            self.assertEqual(code, 65)
            self.assertEqual(stdout, "")
            self.assertIn("not valid UTF-8", stderr)

    def test_input_output_and_internal_errors_have_stable_codes(self) -> None:
        code, stdout, stderr = self.invoke(
            ["validate", "--variant", "A", "missing-input.json"]
        )
        self.assertEqual(code, 66)
        self.assertEqual(stdout, "")
        self.assertIn("cannot read", stderr)

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as directory:
            output = Path(directory) / "missing-parent" / "result.json"
            code, stdout, stderr = self.invoke(
                [
                    "can",
                    "--variant",
                    "A",
                    self.fixture("can", "normal_frame.json"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 73)
            self.assertEqual(stdout, "")
            self.assertIn("cannot write", stderr)

        def broken(_scenario: object) -> dict[str, object]:
            raise RuntimeError("controlled test failure")

        with patch.dict(cli._ENGINE_COMMANDS, {"can": ("A", broken)}):
            code, stdout, stderr = self.invoke(
                [
                    "can",
                    "--variant",
                    "A",
                    self.fixture("can", "normal_frame.json"),
                ]
            )
        self.assertEqual(code, 70)
        self.assertEqual(stdout, "")
        self.assertIn("internal error", stderr)

    def test_variant_a_report_is_exact_closed_and_deterministic(self) -> None:
        first_code, first_stdout, first_stderr = self.invoke(
            self.report_a_arguments()
        )
        second_code, second_stdout, second_stderr = self.invoke(
            self.report_a_arguments()
        )
        report = json.loads(first_stdout)

        self.assertEqual(first_code, second_code)
        self.assertEqual(first_code, 12)
        self.assertEqual(first_stdout, second_stdout)
        self.assertEqual(first_stderr, second_stderr)
        self.assertEqual(first_stderr, "")
        self.assertEqual(
            set(report),
            {
                "schema_version",
                "tool_version",
                "variant_id",
                "status",
                "rule_id",
                "reason_code",
                "input_hash",
                "reports",
                "claims",
            },
        )
        self.assertEqual(set(report["reports"]), {"profile", "can", "lin", "gnss"})
        self.assertEqual(report["variant_id"], "A")
        self.assertEqual(report["schema_version"], "repo03.variant-report.v1")
        self.assertEqual(report["tool_version"], f"repo03-cli/{__version__}")
        self.assertEqual(report["rule_id"], "REP03-CLI-REPORT-000")
        self.assertEqual(report["reason_code"], f"VARIANT_REPORT_{report['status']}")
        self.assertRegex(report["input_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            report["claims"],
            {
                "validation_level": "SYNTHETIC",
                "physical_validation": False,
                "hardware_validation": False,
                "rf_validation": False,
                "automotive_compliance": False,
            },
        )

    def test_variant_b_report_has_only_variant_b_modules(self) -> None:
        code, stdout, stderr = self.invoke(
            [
                "report",
                "--variant",
                "B",
                "--profile",
                self.fixture("valid_variant_b.json"),
                "--automotive-power",
                self.fixture("automotive_power", "nominal.json"),
                "--shutdown",
                self.fixture("shutdown", "normal_ack.json"),
            ]
        )
        report = json.loads(stdout)

        self.assertEqual(code, 12)
        self.assertEqual(stderr, "")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["variant_id"], "B")
        self.assertEqual(
            set(report["reports"]),
            {"profile", "automotive_power", "shutdown"},
        )

    def test_report_rejects_missing_cross_variant_and_repeated_stdin_inputs(self) -> None:
        missing = self.report_a_arguments()
        del missing[-2:]
        code, stdout, stderr = self.invoke(missing)
        self.assertEqual(code, 64)
        self.assertEqual(stdout, "")
        self.assertIn("--gnss", stderr)

        leaked = self.report_a_arguments() + [
            "--shutdown",
            self.fixture("shutdown", "normal_ack.json"),
        ]
        code, stdout, stderr = self.invoke(leaked)
        self.assertEqual(code, 64)
        self.assertEqual(stdout, "")
        self.assertIn("forbids: --shutdown", stderr)

        repeated_stdin = self.report_a_arguments()
        repeated_stdin[repeated_stdin.index(self.fixture("valid_variant_a.json"))] = "-"
        repeated_stdin[repeated_stdin.index(self.fixture("can", "normal_frame.json"))] = "-"
        code, stdout, stderr = self.invoke(repeated_stdin, stdin="{}")
        self.assertEqual(code, 64)
        self.assertEqual(stdout, "")
        self.assertIn("only one report input", stderr)

    def test_combined_profile_cannot_expand_aggregate_report_set(self) -> None:
        arguments = self.report_a_arguments()
        arguments[arguments.index(self.fixture("valid_variant_a.json"))] = self.fixture(
            "invalid_combined.json"
        )
        code, stdout, stderr = self.invoke(arguments)
        report = json.loads(stdout)

        self.assertEqual(code, 10)
        self.assertEqual(stderr, "")
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(set(report["reports"]), {"profile", "can", "lin", "gnss"})
        self.assertNotIn("automotive_power", report["reports"])
        self.assertNotIn("shutdown", report["reports"])


if __name__ == "__main__":
    unittest.main()

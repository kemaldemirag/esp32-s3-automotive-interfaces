"""Draft 2020-12 regression checks for every REP-03 JSON fixture.

``jsonschema`` is deliberately a test-only dependency.  Install
``requirements-test.txt`` before running the suite; the firmware packages do
not import it at runtime.
"""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from repo03_can import run_scenario as run_can_scenario
from repo03_contract import validate_profile
from repo03_gnss import run_scenario as run_gnss_scenario
from repo03_lin import run_scenario as run_lin_scenario
from repo03_power import run_scenario as run_power_scenario
from repo03_shutdown import run_scenario as run_shutdown_scenario


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "variants" / "fixtures"
SCHEMAS = ROOT / "variants" / "schema"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
EXPECTED_FIXTURE_COUNT = 44


@dataclass(frozen=True)
class ContractFamily:
    name: str
    schema_file: str
    fixture_dir: Path
    report_definition: str
    runner: Callable[[dict[str, Any]], dict[str, Any]]
    invalid_input_prefix: str | None = None


CONTRACT_FAMILIES = (
    ContractFamily(
        name="variant",
        schema_file="repo03.variant.schema.v1.json",
        fixture_dir=FIXTURES,
        report_definition="validation_report",
        runner=validate_profile,
        invalid_input_prefix="invalid_",
    ),
    ContractFamily(
        name="can",
        schema_file="repo03.can.scenario.v1.json",
        fixture_dir=FIXTURES / "can",
        report_definition="report",
        runner=run_can_scenario,
    ),
    ContractFamily(
        name="lin",
        schema_file="repo03.lin.scenario.v1.json",
        fixture_dir=FIXTURES / "lin",
        report_definition="run_report",
        runner=run_lin_scenario,
    ),
    ContractFamily(
        name="gnss",
        schema_file="repo03.gnss.scenario.v1.json",
        fixture_dir=FIXTURES / "gnss",
        report_definition="run_report",
        runner=run_gnss_scenario,
    ),
    ContractFamily(
        name="automotive_power",
        schema_file="repo03.automotive-power.scenario.v1.json",
        fixture_dir=FIXTURES / "automotive_power",
        report_definition="report",
        runner=run_power_scenario,
    ),
    ContractFamily(
        name="shutdown",
        schema_file="repo03.shutdown.scenario.v1.json",
        fixture_dir=FIXTURES / "shutdown",
        report_definition="run_report",
        runner=run_shutdown_scenario,
    ),
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def fixture_paths(family: ContractFamily) -> list[Path]:
    paths = sorted(family.fixture_dir.glob("*.json"))
    if not paths:
        raise AssertionError(f"no fixtures found for {family.name}")
    return paths


def report_schema(schema: dict[str, Any], definition: str) -> dict[str, Any]:
    """Build an isolated schema view for a report stored below ``$defs``."""

    definitions = schema.get("$defs", {})
    if definition not in definitions:
        raise AssertionError(f"missing report definition: $defs.{definition}")
    return {
        "$schema": DRAFT_2020_12,
        "$defs": definitions,
        "$ref": f"#/$defs/{definition}",
    }


def validation_errors(
    validator: Draft202012Validator, instance: Any
) -> list[ValidationError]:
    return sorted(
        validator.iter_errors(instance),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            str(error.validator),
            error.message,
        ),
    )


def error_summary(errors: list[ValidationError]) -> str:
    if not errors:
        return ""
    return "\n".join(
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: "
        f"[{error.validator}] {error.message}"
        for error in errors
    )


def has_validator(errors: list[ValidationError], validator_name: str) -> bool:
    """Search an error and its ``anyOf``/``oneOf`` child contexts."""

    pending = list(errors)
    while pending:
        error = pending.pop()
        if error.validator == validator_name:
            return True
        pending.extend(error.context)
    return False


class Draft202012SchemaRegressionTests(unittest.TestCase):
    def test_contract_family_inventory_matches_schema_directory(self) -> None:
        declared = {family.schema_file for family in CONTRACT_FAMILIES}
        present = {path.name for path in SCHEMAS.glob("*.json")}
        self.assertEqual(
            declared,
            present,
            "every schema file must have an explicit regression-test family",
        )

    def test_schema_documents_are_valid_draft_2020_12(self) -> None:
        for family in CONTRACT_FAMILIES:
            with self.subTest(family=family.name):
                schema = load_json(SCHEMAS / family.schema_file)
                self.assertEqual(schema.get("$schema"), DRAFT_2020_12)
                Draft202012Validator.check_schema(schema)
                Draft202012Validator.check_schema(
                    report_schema(schema, family.report_definition)
                )

    def test_every_fixture_input_matches_its_declared_schema_expectation(self) -> None:
        checked = 0
        for family in CONTRACT_FAMILIES:
            schema = load_json(SCHEMAS / family.schema_file)
            validator = Draft202012Validator(schema)
            for path in fixture_paths(family):
                checked += 1
                with self.subTest(family=family.name, fixture=path.name):
                    errors = validation_errors(validator, load_json(path))
                    expected_invalid = bool(
                        family.invalid_input_prefix
                        and path.name.startswith(family.invalid_input_prefix)
                    )
                    if expected_invalid:
                        self.assertTrue(
                            errors,
                            f"{path.name} is an intentionally invalid fixture",
                        )
                    else:
                        self.assertFalse(errors, error_summary(errors))
        self.assertEqual(
            checked,
            EXPECTED_FIXTURE_COUNT,
            "fixture inventory changed; review its contract",
        )

    def test_every_engine_report_matches_its_report_definition(self) -> None:
        checked = 0
        for family in CONTRACT_FAMILIES:
            schema = load_json(SCHEMAS / family.schema_file)
            validator = Draft202012Validator(
                report_schema(schema, family.report_definition)
            )
            for path in fixture_paths(family):
                checked += 1
                with self.subTest(family=family.name, fixture=path.name):
                    report = family.runner(load_json(path))
                    json.dumps(report, allow_nan=False)
                    errors = validation_errors(validator, report)
                    self.assertFalse(errors, error_summary(errors))
        self.assertEqual(
            checked,
            EXPECTED_FIXTURE_COUNT,
            "fixture inventory changed; review its contract",
        )

    def test_unknown_fields_are_rejected_in_inputs_and_nested_sources(self) -> None:
        for family in CONTRACT_FAMILIES:
            schema = load_json(SCHEMAS / family.schema_file)
            validator = Draft202012Validator(schema)
            seed_path = next(
                path
                for path in fixture_paths(family)
                if not (
                    family.invalid_input_prefix
                    and path.name.startswith(family.invalid_input_prefix)
                )
            )
            seed = load_json(seed_path)

            for location in ("root", "source"):
                mutated = deepcopy(seed)
                if location == "root":
                    mutated["unexpected_schema_regression_field"] = True
                else:
                    source = mutated.get("source")
                    self.assertIsInstance(source, dict)
                    source["unexpected_schema_regression_field"] = True

                with self.subTest(family=family.name, location=location):
                    errors = validation_errors(validator, mutated)
                    self.assertTrue(errors, "closed object accepted an unknown field")
                    self.assertTrue(
                        has_validator(errors, "additionalProperties"),
                        error_summary(errors),
                    )

    def test_unknown_fields_are_rejected_in_reports_and_nested_objects(self) -> None:
        for family in CONTRACT_FAMILIES:
            schema = load_json(SCHEMAS / family.schema_file)
            validator = Draft202012Validator(
                report_schema(schema, family.report_definition)
            )
            seed_path = next(
                path
                for path in fixture_paths(family)
                if not (
                    family.invalid_input_prefix
                    and path.name.startswith(family.invalid_input_prefix)
                )
            )
            report = family.runner(load_json(seed_path))

            nested_field = (
                "source" if isinstance(report.get("source"), dict) else "result"
            )
            for location in ("root", nested_field):
                mutated = deepcopy(report)
                if location == "root":
                    mutated["unexpected_schema_regression_field"] = True
                else:
                    nested_object = mutated.get(location)
                    self.assertIsInstance(nested_object, dict)
                    nested_object["unexpected_schema_regression_field"] = True

                with self.subTest(family=family.name, location=location):
                    errors = validation_errors(validator, mutated)
                    self.assertTrue(errors, "closed report accepted an unknown field")
                    self.assertTrue(
                        has_validator(errors, "additionalProperties"),
                        error_summary(errors),
                    )


if __name__ == "__main__":
    unittest.main()

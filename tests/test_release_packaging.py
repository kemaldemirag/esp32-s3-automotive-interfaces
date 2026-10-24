"""Static release-packaging policy checks for D4.

These tests deliberately avoid building a wheel inside the normal unit suite.
The separate release verifier owns the slower clean-install smoke test.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = REPO_ROOT / "firmware"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
DEPENDENCY_CONTRACT = (
    FIRMWARE_ROOT / "repo03_integration" / "rep02_dependency.v1.json"
)
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_PACKAGES = {
    "repo03_can",
    "repo03_cli",
    "repo03_contract",
    "repo03_gnss",
    "repo03_integration",
    "repo03_lin",
    "repo03_power",
    "repo03_shutdown",
}

EXPECTED_PYPROJECT = """[build-system]
requires = [
  "setuptools==84.0.0",
  "wheel==0.48.0",
]
build-backend = "setuptools.build_meta"

[project]
name = "esp32-s3-automotive-interfaces"
dynamic = ["version"]
description = "Deterministic offline validation tools for the REP-03 automotive interface variants"
readme = { file = "README.md", content-type = "text/markdown" }
requires-python = ">=3.10"
dependencies = []

[project.scripts]
repo03 = "repo03_cli.cli:main"

[tool.setuptools]
package-dir = { "" = "firmware" }
include-package-data = true

[tool.setuptools.dynamic]
version = { attr = "repo03_cli.__version__" }

[tool.setuptools.packages.find]
where = ["firmware"]
include = ["repo03_*"]
namespaces = false

[tool.setuptools.package-data]
repo03_integration = ["rep02_dependency.v1.json"]
"""


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_metadata_is_an_exact_closed_allowlist(self) -> None:
        # Exact text keeps this policy test Python 3.10 compatible without a
        # test-only TOML dependency. It also makes additions (especially a
        # runtime dependency, package, entry point, or guessed license) fail
        # visibly until this allowlist is reviewed.
        self.assertEqual(
            EXPECTED_PYPROJECT,
            PYPROJECT_PATH.read_text(encoding="utf-8"),
        )

    def test_discovered_packages_match_the_release_allowlist(self) -> None:

        discovered = {
            package_dir.name
            for package_dir in FIRMWARE_ROOT.glob("repo03_*")
            if package_dir.is_dir() and (package_dir / "__init__.py").is_file()
        }
        self.assertEqual(EXPECTED_PACKAGES, discovered)

    def test_only_pinned_integration_contract_is_declared_as_package_data(self) -> None:
        self.assertTrue(DEPENDENCY_CONTRACT.is_file())
        contract = json.loads(DEPENDENCY_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual("REP-02", contract["rep02"]["repository_id"])
        self.assertEqual("0.5.0", contract["rep02"]["package_version"])

    def test_ci_is_read_only_pinned_and_has_no_publish_path(self) -> None:
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read\n", workflow)
        self.assertIn("pull_request:\n", workflow)
        self.assertIn("workflow_dispatch:\n", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("--no-deps --no-build-isolation", workflow)
        self.assertIn("scripts/verify_d4_release.py", workflow)

        uses = re.findall(r"^\s+uses:\s+([^\s#]+)", workflow, flags=re.MULTILINE)
        self.assertEqual(4, len(uses))
        for action in uses:
            self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")

        forbidden = (
            "pypa/gh-action-pypi-publish",
            "twine upload",
            "contents: write",
            "id-token: write",
        )
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, workflow)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Verify a REP-03 wheel in a clean environment outside the checkout.

The verifier writes no evidence files. Its only output is one JSON document on
stdout so callers can decide where (or whether) to persist the local result.
"""

from __future__ import annotations

import argparse
import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "repo03.d4-local-verification.v1"
PACKAGE_NAME = "esp32-s3-automotive-interfaces"
PACKAGE_VERSION = "0.1.0"
SUBPROCESS_TIMEOUT_SECONDS = 180
REP02_PACKAGE_VERSION = "0.5.0"
REP02_WHEEL_SHA256 = "27ba10f6e14345c39f70241e56abd67469eb7e8130dc6a0abfdb37ca1a8c5027"
EXPECTED_PACKAGES = [
    "repo03_can",
    "repo03_cli",
    "repo03_contract",
    "repo03_gnss",
    "repo03_integration",
    "repo03_lin",
    "repo03_power",
    "repo03_shutdown",
]
EXPECTED_PYTHON_MEMBERS = {
    "repo03_can/__init__.py",
    "repo03_can/engine.py",
    "repo03_cli/__init__.py",
    "repo03_cli/__main__.py",
    "repo03_cli/cli.py",
    "repo03_cli/report.py",
    "repo03_contract/__init__.py",
    "repo03_contract/validator.py",
    "repo03_gnss/__init__.py",
    "repo03_gnss/validator.py",
    "repo03_integration/__init__.py",
    "repo03_integration/rep02_file_api.py",
    "repo03_lin/__init__.py",
    "repo03_lin/engine.py",
    "repo03_power/__init__.py",
    "repo03_power/engine.py",
    "repo03_shutdown/__init__.py",
    "repo03_shutdown/engine.py",
}
PACKAGE_DATA_MEMBER = "repo03_integration/rep02_dependency.v1.json"
DIST_INFO_DIRECTORY = (
    f"esp32_s3_automotive_interfaces-{PACKAGE_VERSION}.dist-info"
)
DIST_INFO_FILES = {
    "METADATA",
    "RECORD",
    "WHEEL",
    "entry_points.txt",
    "top_level.txt",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

FIXTURE_SOURCES = {
    "profile_a": "variants/fixtures/valid_variant_a.json",
    "profile_b": "variants/fixtures/valid_variant_b.json",
    "combined": "variants/fixtures/invalid_combined.json",
    "can_normal": "variants/fixtures/can/normal_frame.json",
    "lin_normal": "variants/fixtures/lin/normal_wake_sleep.json",
    "gnss_valid": "variants/fixtures/gnss/valid_synthetic_fix.json",
    "power_nominal": "variants/fixtures/automotive_power/nominal.json",
    "shutdown_normal": "variants/fixtures/shutdown/normal_ack.json",
}

EXPECTED_CASES = {
    "validate_a": {
        "arguments": ["validate", "--variant", "A", "@profile_a"],
        "variant": "A",
        "status": "BLOCKED",
        "reason_code": "SOURCE_INPUT_BLOCKED",
        "exit_code": 12,
    },
    "validate_b": {
        "arguments": ["validate", "--variant", "B", "@profile_b"],
        "variant": "B",
        "status": "BLOCKED",
        "reason_code": "SOURCE_INPUT_BLOCKED",
        "exit_code": 12,
    },
    "combined_profile": {
        "arguments": ["validate", "--variant", "A", "@combined"],
        "variant": "A",
        "status": "FAIL",
        "reason_code": "COMBINED_PROFILE_FORBIDDEN",
        "exit_code": 10,
    },
    "can": {
        "arguments": ["can", "--variant", "A", "@can_normal"],
        "variant": "A",
        "status": "PASS",
        "reason_code": "SYNTHETIC_CONTROLLER_FRAME_ACCEPTED",
        "exit_code": 0,
    },
    "lin": {
        "arguments": ["lin", "--variant", "A", "@lin_normal"],
        "variant": "A",
        "status": "PASS",
        "reason_code": "LIN_SCENARIO_COMPLETED",
        "exit_code": 0,
    },
    "gnss": {
        "arguments": ["gnss", "--variant", "A", "@gnss_valid"],
        "variant": "A",
        "status": "PASS",
        "reason_code": "SYNTHETIC_FIX_VALID",
        "exit_code": 0,
    },
    "automotive_power": {
        "arguments": [
            "automotive-power",
            "--variant",
            "B",
            "@power_nominal",
        ],
        "variant": "B",
        "status": "PASS",
        "reason_code": "SYNTHETIC_PROFILE_CONTRACT_ACCEPTED",
        "exit_code": 0,
    },
    "shutdown": {
        "arguments": ["shutdown", "--variant", "B", "@shutdown_normal"],
        "variant": "B",
        "status": "BLOCKED",
        "reason_code": "HOST_MODEL_UNRESOLVED",
        "exit_code": 12,
    },
    "report_a": {
        "arguments": [
            "report",
            "--variant",
            "A",
            "--profile",
            "@profile_a",
            "--can",
            "@can_normal",
            "--lin",
            "@lin_normal",
            "--gnss",
            "@gnss_valid",
        ],
        "variant": "A",
        "status": "BLOCKED",
        "reason_code": "VARIANT_REPORT_BLOCKED",
        "exit_code": 12,
    },
    "report_b": {
        "arguments": [
            "report",
            "--variant",
            "B",
            "--profile",
            "@profile_b",
            "--automotive-power",
            "@power_nominal",
            "--shutdown",
            "@shutdown_normal",
        ],
        "variant": "B",
        "status": "BLOCKED",
        "reason_code": "VARIANT_REPORT_BLOCKED",
        "exit_code": 12,
    },
}


class VerificationError(RuntimeError):
    """A bounded, machine-readable verification failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _VerifierArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise VerificationError("USAGE_ERROR", message)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _default_temporary_root() -> Path:
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "Temp" / "repo03-d4"
    return Path(tempfile.gettempdir()) / "repo03-d4"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_package_members() -> dict[str, Path]:
    firmware_root = (REPO_ROOT / "firmware").resolve(strict=True)
    discovered_python: dict[str, Path] = {}
    for package_name in EXPECTED_PACKAGES:
        package_root = firmware_root / package_name
        if not (package_root / "__init__.py").is_file():
            raise VerificationError(
                "PACKAGE_SOURCE_MISSING",
                f"package allowlist member {package_name} has no __init__.py",
            )
        for source in package_root.rglob("*.py"):
            resolved_source = source.resolve(strict=True)
            if source.is_symlink() or not _is_within(resolved_source, firmware_root):
                raise VerificationError(
                    "PACKAGE_SOURCE_INVALID",
                    f"package source escaped firmware root: {source}",
                )
            member = source.relative_to(firmware_root).as_posix()
            discovered_python[member] = source

    if set(discovered_python) != EXPECTED_PYTHON_MEMBERS:
        missing = sorted(EXPECTED_PYTHON_MEMBERS - set(discovered_python))
        extra = sorted(set(discovered_python) - EXPECTED_PYTHON_MEMBERS)
        raise VerificationError(
            "PACKAGE_SOURCE_ALLOWLIST_MISMATCH",
            f"missing={missing!r}; extra={extra!r}",
        )

    package_data = firmware_root / PurePosixPath(PACKAGE_DATA_MEMBER)
    if not package_data.is_file() or package_data.is_symlink():
        raise VerificationError(
            "PACKAGE_DATA_MISSING",
            f"required package data is unavailable: {PACKAGE_DATA_MEMBER}",
        )
    discovered_python[PACKAGE_DATA_MEMBER] = package_data
    return discovered_python


def _verify_wheel_archive(wheel_path: Path) -> dict[str, Any]:
    expected_sources = _expected_package_members()
    expected_dist_info = {
        f"{DIST_INFO_DIRECTORY}/{file_name}" for file_name in DIST_INFO_FILES
    }
    expected_members = set(expected_sources) | expected_dist_info
    record_member = f"{DIST_INFO_DIRECTORY}/RECORD"

    try:
        with zipfile.ZipFile(wheel_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise VerificationError(
                    "DUPLICATE_WHEEL_MEMBER",
                    "wheel contains duplicate ZIP member names",
                )

            for info in infos:
                name = info.filename
                parts = name.split("/")
                if (
                    not name
                    or "\\" in name
                    or "\x00" in name
                    or name.startswith("/")
                    or any(part in {"", ".", ".."} for part in parts)
                    or PurePosixPath(name).is_absolute()
                    or PurePosixPath(name).as_posix() != name
                ):
                    raise VerificationError(
                        "UNSAFE_WHEEL_MEMBER_PATH",
                        f"wheel member path is unsafe: {name!r}",
                    )
                if info.is_dir():
                    raise VerificationError(
                        "UNEXPECTED_WHEEL_DIRECTORY_ENTRY",
                        f"wheel contains an explicit directory entry: {name}",
                    )
                unix_mode = info.external_attr >> 16
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise VerificationError(
                        "WHEEL_SYMLINK_FORBIDDEN",
                        f"wheel member is a symbolic link: {name}",
                    )
                if info.flag_bits & 0x1:
                    raise VerificationError(
                        "ENCRYPTED_WHEEL_MEMBER",
                        f"wheel member is encrypted: {name}",
                    )

            observed_members = set(names)
            if observed_members != expected_members:
                missing = sorted(expected_members - observed_members)
                extra = sorted(observed_members - expected_members)
                raise VerificationError(
                    "WHEEL_MEMBER_ALLOWLIST_MISMATCH",
                    f"missing={missing!r}; extra={extra!r}",
                )

            observed_packages = {
                name.split("/", 1)[0]
                for name in names
                if not name.startswith(f"{DIST_INFO_DIRECTORY}/")
            }
            if observed_packages != set(EXPECTED_PACKAGES):
                raise VerificationError(
                    "PACKAGE_ALLOWLIST_MISMATCH",
                    "wheel top-level packages do not match EXPECTED_PACKAGES",
                )

            for member, source in expected_sources.items():
                if archive.read(member) != source.read_bytes():
                    raise VerificationError(
                        "WHEEL_SOURCE_MISMATCH",
                        f"wheel member differs from checkout source: {member}",
                    )

            top_level = archive.read(
                f"{DIST_INFO_DIRECTORY}/top_level.txt"
            ).decode("utf-8", errors="strict").splitlines()
            if len(top_level) != len(set(top_level)) or set(top_level) != set(
                EXPECTED_PACKAGES
            ):
                raise VerificationError(
                    "TOP_LEVEL_METADATA_MISMATCH",
                    "top_level.txt does not match the package allowlist",
                )

            entry_points = archive.read(
                f"{DIST_INFO_DIRECTORY}/entry_points.txt"
            )
            if entry_points != b"[console_scripts]\nrepo03 = repo03_cli.cli:main\n":
                raise VerificationError(
                    "ENTRYPOINT_METADATA_MISMATCH",
                    "wheel console entry point metadata is not exact",
                )

            wheel_metadata = archive.read(
                f"{DIST_INFO_DIRECTORY}/WHEEL"
            ).decode("utf-8", errors="strict")
            for required_line in (
                "Wheel-Version: 1.0",
                "Root-Is-Purelib: true",
                "Tag: py3-none-any",
            ):
                if required_line not in wheel_metadata.splitlines():
                    raise VerificationError(
                        "WHEEL_METADATA_MISMATCH",
                        f"WHEEL metadata lacks {required_line!r}",
                    )

            metadata_bytes = archive.read(f"{DIST_INFO_DIRECTORY}/METADATA")
            if b"\r\n\r\n" in metadata_bytes:
                _, readme_payload = metadata_bytes.split(b"\r\n\r\n", 1)
            elif b"\n\n" in metadata_bytes:
                _, readme_payload = metadata_bytes.split(b"\n\n", 1)
            else:
                raise VerificationError(
                    "CORE_METADATA_MALFORMED",
                    "METADATA has no header/body separator",
                )
            if readme_payload != (REPO_ROOT / "README.md").read_bytes():
                raise VerificationError(
                    "README_PAYLOAD_MISMATCH",
                    "wheel METADATA body is not the current README.md bytes",
                )

            metadata = BytesParser(policy=policy.default).parsebytes(metadata_bytes)
            if (
                metadata.get("Name") != PACKAGE_NAME
                or metadata.get("Version") != PACKAGE_VERSION
                or metadata.get("Requires-Python") != ">=3.10"
                or metadata.get("Description-Content-Type") != "text/markdown"
                or metadata.get_all("Requires-Dist", []) != []
            ):
                raise VerificationError(
                    "CORE_METADATA_MISMATCH",
                    "wheel name, version, Python floor, or dependency set is unexpected",
                )
            if (
                metadata.get("License")
                or metadata.get("License-Expression")
                or any(
                    value.startswith("License ::")
                    for value in metadata.get_all("Classifier", [])
                )
            ):
                raise VerificationError(
                    "UNAPPROVED_LICENSE_METADATA",
                    "wheel contains license metadata before the owner decision",
                )

            record_bytes = archive.read(record_member)
            reader = csv.reader(
                io.StringIO(
                    record_bytes.decode("utf-8", errors="strict"),
                    newline="",
                ),
                strict=True,
            )
            record_entries: dict[str, tuple[str, str]] = {}
            for row in reader:
                if len(row) != 3:
                    raise VerificationError(
                        "INVALID_WHEEL_RECORD",
                        "every RECORD row must contain exactly three fields",
                    )
                member, hash_field, size_field = row
                if member in record_entries:
                    raise VerificationError(
                        "DUPLICATE_WHEEL_RECORD_ENTRY",
                        f"duplicate RECORD path: {member}",
                    )
                record_entries[member] = (hash_field, size_field)

            if set(record_entries) != observed_members:
                raise VerificationError(
                    "WHEEL_RECORD_MEMBER_MISMATCH",
                    "RECORD paths do not exactly match ZIP members",
                )
            for member in names:
                hash_field, size_field = record_entries[member]
                if member == record_member:
                    if hash_field or size_field:
                        raise VerificationError(
                            "INVALID_WHEEL_RECORD",
                            "RECORD must leave its own hash and size empty",
                        )
                    continue
                payload = archive.read(member)
                expected_hash = "sha256=" + base64.urlsafe_b64encode(
                    hashlib.sha256(payload).digest()
                ).rstrip(b"=").decode("ascii")
                if hash_field != expected_hash or size_field != str(len(payload)):
                    raise VerificationError(
                        "WHEEL_RECORD_HASH_MISMATCH",
                        f"RECORD hash or size mismatch: {member}",
                    )

            return {
                "member_count": len(names),
                "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            }
    except VerificationError:
        raise
    except (csv.Error, KeyError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise VerificationError(
            "INVALID_WHEEL_ARCHIVE",
            f"wheel archive could not be validated: {exc}",
        ) from exc


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    expected_codes: set[int],
    step: str,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError(
            "SUBPROCESS_TIMEOUT",
            f"{step} exceeded {SUBPROCESS_TIMEOUT_SECONDS} seconds",
        ) from exc
    if completed.returncode not in expected_codes:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()[:1200]
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()[:1200]
        raise VerificationError(
            "SUBPROCESS_EXIT_MISMATCH",
            f"{step} returned {completed.returncode}; stdout={stdout!r}; stderr={stderr!r}",
        )
    return completed


def _strict_json_object(payload: bytes, step: str) -> dict[str, Any]:
    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite token {token}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            payload.decode("utf-8", errors="strict"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise VerificationError(
            "INVALID_JSON_OUTPUT",
            f"{step} did not emit one strict JSON document: {exc}",
        ) from exc
    if not isinstance(decoded, dict):
        raise VerificationError(
            "INVALID_JSON_OUTPUT",
            f"{step} emitted {type(decoded).__name__}, expected object",
        )
    return decoded


def _venv_paths(venv_root: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return (
            venv_root / "Scripts" / "python.exe",
            venv_root / "Scripts" / "repo03.exe",
        )
    return venv_root / "bin" / "python", venv_root / "bin" / "repo03"


def _copy_smoke_fixtures(destination: Path) -> dict[str, Path]:
    destination.mkdir()
    copied: dict[str, Path] = {}
    repo_root = REPO_ROOT.resolve(strict=True)
    for fixture_id, relative_path in FIXTURE_SOURCES.items():
        source = (repo_root / relative_path).resolve(strict=True)
        if not _is_within(source, repo_root) or not source.is_file():
            raise VerificationError(
                "FIXTURE_SOURCE_INVALID",
                f"{fixture_id} is not a regular repository fixture",
            )
        target = destination / f"{fixture_id}.json"
        shutil.copyfile(source, target)
        if _sha256(target) != _sha256(source):
            raise VerificationError(
                "FIXTURE_COPY_MISMATCH",
                f"scratch copy for {fixture_id} changed bytes",
            )
        copied[fixture_id] = target.resolve(strict=True)
    return copied


def _probe_installed_packages(
    python_path: Path,
    *,
    cwd: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    probe = r"""
import json
import os
from importlib.metadata import requires, version
from pathlib import Path

import repo03_can
import repo03_cli
import repo03_contract
import repo03_gnss
import repo03_integration
import repo03_lin
import repo03_power
import repo03_shutdown
from repo03_integration import dependency_contract

checkout = Path(os.environ["REPO03_FORBIDDEN_CHECKOUT"]).resolve()
modules = {
    "repo03_can": repo03_can,
    "repo03_cli": repo03_cli,
    "repo03_contract": repo03_contract,
    "repo03_gnss": repo03_gnss,
    "repo03_integration": repo03_integration,
    "repo03_lin": repo03_lin,
    "repo03_power": repo03_power,
    "repo03_shutdown": repo03_shutdown,
}
for name, module in modules.items():
    origin = Path(module.__file__).resolve()
    if origin == checkout or checkout in origin.parents:
        raise RuntimeError(f"{name} imported from checkout: {origin}")

contract = dependency_contract()
print(json.dumps({
    "distribution_version": version("esp32-s3-automotive-interfaces"),
    "runtime_dependencies": requires("esp32-s3-automotive-interfaces") or [],
    "module_version": repo03_cli.__version__,
    "imported_packages": sorted(modules),
    "dependency_contract": {
        "schema_version": contract["schema_version"],
        "integration_id": contract["integration_id"],
        "integration_scope": contract["integration_scope"],
        "rep02_package_version": contract["rep02"]["package_version"],
        "rep02_wheel_sha256": contract["rep02"]["wheel"]["sha256"],
    },
}, sort_keys=True, separators=(",", ":")))
"""
    completed = _run(
        [str(python_path), "-I", "-B", "-c", probe],
        cwd=cwd,
        environment=environment,
        expected_codes={0},
        step="installed-package probe",
    )
    if completed.stderr:
        raise VerificationError(
            "UNEXPECTED_STDERR",
            "installed-package probe wrote to stderr",
        )
    result = _strict_json_object(completed.stdout, "installed-package probe")
    if result.get("distribution_version") != PACKAGE_VERSION:
        raise VerificationError(
            "DISTRIBUTION_VERSION_MISMATCH",
            f"expected {PACKAGE_VERSION}, got {result.get('distribution_version')!r}",
        )
    if result.get("module_version") != PACKAGE_VERSION:
        raise VerificationError(
            "MODULE_VERSION_MISMATCH",
            f"expected {PACKAGE_VERSION}, got {result.get('module_version')!r}",
        )
    if result.get("runtime_dependencies") != []:
        raise VerificationError(
            "RUNTIME_DEPENDENCY_MISMATCH",
            "the wheel declares an unexpected runtime dependency",
        )
    if result.get("imported_packages") != EXPECTED_PACKAGES:
        raise VerificationError(
            "PACKAGE_ALLOWLIST_MISMATCH",
            "the clean import probe did not match the package allowlist",
        )
    contract = result.get("dependency_contract")
    if not isinstance(contract, dict):
        raise VerificationError(
            "DEPENDENCY_CONTRACT_MISSING",
            "installed package did not return its dependency contract",
        )
    if contract.get("schema_version") != "repo03.rep02-dependency.v1":
        raise VerificationError(
            "DEPENDENCY_CONTRACT_MISMATCH",
            "installed package returned an unexpected dependency schema",
        )
    if contract.get("integration_id") != "INT-02A":
        raise VerificationError(
            "DEPENDENCY_CONTRACT_MISMATCH",
            "installed package returned an unexpected integration identity",
        )
    if contract.get("integration_scope") != "OFFLINE_FILE_INTEGRITY_ONLY":
        raise VerificationError(
            "INTEGRATION_SCOPE_EXPANDED",
            "installed dependency contract exceeds the INT-02A scope",
        )
    if contract.get("rep02_package_version") != REP02_PACKAGE_VERSION:
        raise VerificationError(
            "DEPENDENCY_CONTRACT_MISMATCH",
            "installed package returned an unexpected REP-02 package version",
        )
    if contract.get("rep02_wheel_sha256") != REP02_WHEEL_SHA256:
        raise VerificationError(
            "DEPENDENCY_CONTRACT_MISMATCH",
            "installed package returned an unexpected REP-02 wheel hash",
        )
    return result


def _run_cli_case(
    executable: Path,
    case_id: str,
    case: dict[str, Any],
    *,
    fixture_paths: dict[str, Path],
    cwd: Path,
    environment: dict[str, str],
) -> tuple[dict[str, Any], bytes]:
    arguments: list[str] = []
    for token in case["arguments"]:
        if token.startswith("@"):
            fixture_id = token[1:]
            if fixture_id not in fixture_paths:
                raise VerificationError(
                    "FIXTURE_REFERENCE_UNKNOWN",
                    f"CLI case {case_id} references unknown fixture {fixture_id}",
                )
            arguments.append(str(fixture_paths[fixture_id]))
        else:
            arguments.append(token)
    completed = _run(
        [str(executable), *arguments],
        cwd=cwd,
        environment=environment,
        expected_codes={case["exit_code"]},
        step=f"CLI case {case_id}",
    )
    if completed.stderr:
        raise VerificationError(
            "UNEXPECTED_STDERR",
            f"CLI case {case_id} wrote to stderr",
        )
    result = _strict_json_object(completed.stdout, f"CLI case {case_id}")
    if result.get("status") != case["status"]:
        raise VerificationError(
            "CLI_STATUS_MISMATCH",
            f"{case_id} expected {case['status']}, got {result.get('status')!r}",
        )
    if result.get("variant_id") != case["variant"]:
        raise VerificationError(
            "CLI_VARIANT_MISMATCH",
            f"{case_id} expected variant {case['variant']}",
        )
    if result.get("reason_code") != case["reason_code"]:
        raise VerificationError(
            "CLI_REASON_CODE_MISMATCH",
            f"{case_id} expected reason_code {case['reason_code']}",
        )
    input_hash = result.get("input_hash")
    if not isinstance(input_hash, str) or not _SHA256_RE.fullmatch(input_hash):
        raise VerificationError(
            "CLI_INPUT_HASH_INVALID",
            f"{case_id} did not emit a lowercase SHA-256 input_hash",
        )
    return result, completed.stdout


def verify(wheel_path: Path, temporary_root: Path) -> dict[str, Any]:
    wheel_path = wheel_path.resolve(strict=True)
    if not wheel_path.is_file() or wheel_path.suffix != ".whl":
        raise VerificationError("WHEEL_REQUIRED", "--wheel must identify one .whl file")
    wheel_file_name = wheel_path.name
    source_wheel_sha256 = _sha256(wheel_path)
    source_wheel_size = wheel_path.stat().st_size

    repo_root = REPO_ROOT.resolve(strict=True)
    temporary_candidate = temporary_root.resolve(strict=False)
    if _is_within(temporary_candidate, repo_root):
        raise VerificationError(
            "TEMPORARY_ROOT_INSIDE_CHECKOUT",
            "clean-install work must be outside the repository checkout",
        )
    temporary_candidate.mkdir(parents=True, exist_ok=True)
    temporary_root = temporary_candidate.resolve(strict=True)
    if _is_within(temporary_root, repo_root):
        raise VerificationError(
            "TEMPORARY_ROOT_INSIDE_CHECKOUT",
            "clean-install work resolved inside the repository checkout",
        )

    scratch_path = Path(tempfile.mkdtemp(prefix="verify-", dir=temporary_root))
    try:
        scratch_path = scratch_path.resolve(strict=True)
        if _is_within(scratch_path, repo_root):
            raise VerificationError(
                "SCRATCH_INSIDE_CHECKOUT",
                "clean-install scratch unexpectedly resolved inside the checkout",
            )
        venv_root = scratch_path / "venv"
        smoke_cwd = scratch_path / "cwd"
        process_temp = scratch_path / "process-temp"
        fixture_root = scratch_path / "fixtures"
        staged_wheel_root = scratch_path / "wheel"
        smoke_cwd.mkdir()
        process_temp.mkdir()
        staged_wheel_root.mkdir()
        staged_wheel = staged_wheel_root / wheel_file_name
        shutil.copyfile(wheel_path, staged_wheel)
        if (
            staged_wheel.stat().st_size != source_wheel_size
            or _sha256(staged_wheel) != source_wheel_sha256
        ):
            raise VerificationError(
                "WHEEL_COPY_MISMATCH",
                "source wheel changed while it was copied into verification scratch",
            )
        archive_result = _verify_wheel_archive(staged_wheel)
        fixture_paths = _copy_smoke_fixtures(fixture_root)

        base_environment = os.environ.copy()
        base_environment.pop("PYTHONPATH", None)
        base_environment.pop("PYTHONHOME", None)
        base_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        base_environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        base_environment["REPO03_FORBIDDEN_CHECKOUT"] = str(repo_root)
        base_environment["TEMP"] = str(process_temp)
        base_environment["TMP"] = str(process_temp)
        base_environment["TMPDIR"] = str(process_temp)

        _run(
            [sys.executable, "-I", "-B", "-m", "venv", str(venv_root)],
            cwd=smoke_cwd,
            environment=base_environment,
            expected_codes={0},
            step="virtual-environment creation",
        )
        python_path, cli_path = _venv_paths(venv_root)
        _run(
            [
                str(python_path),
                "-I",
                "-B",
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(staged_wheel),
            ],
            cwd=smoke_cwd,
            environment=base_environment,
            expected_codes={0},
            step="wheel installation",
        )
        pip_check = _run(
            [str(python_path), "-I", "-B", "-m", "pip", "check"],
            cwd=smoke_cwd,
            environment=base_environment,
            expected_codes={0},
            step="installed dependency check",
        )
        if pip_check.stderr:
            raise VerificationError(
                "UNEXPECTED_STDERR",
                "pip check wrote to stderr",
            )
        if not cli_path.is_file():
            raise VerificationError(
                "ENTRYPOINT_MISSING",
                "installed wheel did not create the repo03 console entry point",
            )

        package_probe = _probe_installed_packages(
            python_path,
            cwd=smoke_cwd,
            environment=base_environment,
        )

        version_result = _run(
            [str(cli_path), "--version"],
            cwd=smoke_cwd,
            environment=base_environment,
            expected_codes={0},
            step="CLI version probe",
        )
        expected_version_lines = {
            f"repo03 {PACKAGE_VERSION}\n".encode("ascii"),
            f"repo03 {PACKAGE_VERSION}\r\n".encode("ascii"),
        }
        if version_result.stderr or version_result.stdout not in expected_version_lines:
            raise VerificationError(
                "CLI_VERSION_MISMATCH",
                "repo03 --version did not report the packaged version cleanly",
            )

        case_results: dict[str, dict[str, Any]] = {}
        case_bytes: dict[str, bytes] = {}
        for case_id, case in EXPECTED_CASES.items():
            result, raw = _run_cli_case(
                cli_path,
                case_id,
                case,
                fixture_paths=fixture_paths,
                cwd=smoke_cwd,
                environment=base_environment,
            )
            case_results[case_id] = {
                "status": result["status"],
                "exit_code": case["exit_code"],
                "input_hash": result.get("input_hash"),
                "reason_code": result["reason_code"],
                "output_sha256": hashlib.sha256(raw).hexdigest(),
            }
            case_bytes[case_id] = raw

        _, repeated_report_a = _run_cli_case(
            cli_path,
            "report_a_repeat",
            EXPECTED_CASES["report_a"],
            fixture_paths=fixture_paths,
            cwd=smoke_cwd,
            environment=base_environment,
        )
        if repeated_report_a != case_bytes["report_a"]:
            raise VerificationError(
                "NONDETERMINISTIC_CLI_OUTPUT",
                "two identical Variant A report invocations emitted different bytes",
            )
        if (
            staged_wheel.stat().st_size != source_wheel_size
            or _sha256(staged_wheel) != source_wheel_sha256
        ):
            raise VerificationError(
                "STAGED_WHEEL_MUTATED",
                "the staged wheel changed during clean-install verification",
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "verification_status": "PASS",
            "release_status": "BLOCKED",
            "release_blockers": [
                "LICENSE_DECISION_REQUIRED",
                "REMOTE_CI_NOT_RUN",
            ],
            "wheel": {
                "file_name": wheel_file_name,
                "sha256": source_wheel_sha256,
                "size_bytes": source_wheel_size,
                "archive_member_count": archive_result["member_count"],
                "record_sha256": archive_result["record_sha256"],
            },
            "package": {
                "distribution_name": PACKAGE_NAME,
                "version": package_probe["distribution_version"],
                "runtime_dependencies": package_probe["runtime_dependencies"],
            },
            "checks": {
                "clean_install_no_index_no_deps": "PASS",
                "staged_wheel_identity": "PASS",
                "wheel_member_allowlist": "PASS",
                "wheel_record_integrity": "PASS",
                "wheel_readme_metadata_binding": "PASS",
                "pip_check": "PASS",
                "checkout_independent_imports": "PASS",
                "checkout_independent_fixtures": "PASS",
                "packaged_dependency_contract": "PASS",
                "console_entrypoint": "PASS",
                "all_seven_commands": "PASS",
                "variant_a_report_determinism": "PASS",
            },
            "cli_cases": case_results,
            "claim_limits": [
                "LOCAL_VERIFICATION_ONLY",
                "NO_REMOTE_CI_PASS_CLAIM",
                "NO_RELEASE_PUBLISH_CLAIM",
                "NO_HARDWARE_VALIDATION_CLAIM",
            ],
        }
    finally:
        shutil.rmtree(scratch_path, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = _VerifierArgumentParser(
        description="Verify a locally built REP-03 wheel without writing evidence.",
    )
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument(
        "--temporary-root",
        type=Path,
        default=_default_temporary_root(),
        help="scratch parent outside the repository (default: platform local temp)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        result = verify(arguments.wheel, arguments.temporary_root)
    except Exception as exc:
        if isinstance(exc, VerificationError):
            code = exc.code
            detail = exc.detail
        elif isinstance(exc, (OSError, UnicodeError)):
            code = "VERIFIER_IO_ERROR"
            detail = str(exc)
        else:
            code = "VERIFIER_INTERNAL_ERROR"
            detail = f"{type(exc).__name__}: {exc}"
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "verification_status": "FAIL",
                    "error": {"code": code, "detail": detail},
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

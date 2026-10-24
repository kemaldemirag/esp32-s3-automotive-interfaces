#!/usr/bin/env python3
"""Record reproducible, local-only D4 release evidence.

The recorder runs the complete unittest suite, delegates clean-wheel and CLI
verification to ``verify_d4_release.py``, and publishes an atomic evidence set.
The detached manifest checksum is the acceptance marker and is always written
last. Bytecode caches are deliberately excluded from the source inventory.
"""

from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import (
    PackageNotFoundError,
    distributions,
    version as distribution_version,
)
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = REPO_ROOT / "firmware"
VERIFIER_PATH = REPO_ROOT / "scripts" / "verify_d4_release.py"
RECORDER_PATH = Path(__file__).resolve()
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evidence" / "D4"
REQUIREMENTS_PATH = REPO_ROOT / "requirements-test.txt"

SCHEMA_VERSION = "repo03.d4.release-evidence.v1"
MANIFEST_SCHEMA_VERSION = "repo03.d4.release-manifest.v1"
PACKAGE_NAME = "esp32-s3-automotive-interfaces"
PACKAGE_VERSION = "0.1.0"
SOURCE_STATE = "UNCOMMITTED_D4_WORKTREE"
RELEASE_BLOCKERS = ["LICENSE_DECISION_REQUIRED", "REMOTE_CI_NOT_RUN"]
EXPECTED_CLI_CASES = {
    "automotive_power",
    "can",
    "combined_profile",
    "gnss",
    "lin",
    "report_a",
    "report_b",
    "shutdown",
    "validate_a",
    "validate_b",
}
EXPECTED_WHEEL_MEMBER_COUNT = 24
EXPECTED_UNIT_TEST_COUNT = 207
EXPECTED_RELEASE_CHECKS = {
    "all_seven_commands",
    "checkout_independent_fixtures",
    "checkout_independent_imports",
    "clean_install_no_index_no_deps",
    "console_entrypoint",
    "packaged_dependency_contract",
    "pip_check",
    "staged_wheel_identity",
    "variant_a_report_determinism",
    "wheel_member_allowlist",
    "wheel_readme_metadata_binding",
    "wheel_record_integrity",
}
EXPECTED_CLAIM_LIMITS = {
    "LOCAL_VERIFICATION_ONLY",
    "NO_HARDWARE_VALIDATION_CLAIM",
    "NO_RELEASE_PUBLISH_CLAIM",
    "NO_REMOTE_CI_PASS_CLAIM",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)$"
)
UNIT_TEST_BOOTSTRAP = "\n".join(
    (
        "import os, runpy, sys",
        "sys.path[:0] = [",
        "    os.environ['REPO03_TEST_FIRMWARE'],",
        "    os.environ['REPO03_TEST_DEPENDENCIES'],",
        "]",
        "sys.pycache_prefix = os.environ['REPO03_TEST_PYCACHE_PREFIX']",
        "sys.argv = ['unittest', 'discover', '-s', 'tests', '-q']",
        "runpy.run_module('unittest', run_name='__main__')",
    )
)
OPEN_GAPS = [
    {"gap_id": "GAP-01", "status": "BLOCKED"},
    {"gap_id": "GAP-02", "status": "BLOCKED"},
    {"gap_id": "GAP-03", "status": "BLOCKED"},
    {"gap_id": "GAP-04", "status": "BLOCKED"},
]
NOT_RUN_CHECKS = [
    {"check_id": "PHYSICAL_VALIDATION", "status": "NOT_RUN"},
    {"check_id": "RF_VALIDATION", "status": "NOT_RUN"},
    {"check_id": "EMC_VALIDATION", "status": "NOT_RUN"},
    {"check_id": "AEC_QUALIFICATION", "status": "NOT_RUN"},
    {"check_id": "ISO_COMPLIANCE_VALIDATION", "status": "NOT_RUN"},
    {"check_id": "REAL_HOST_SHUTDOWN", "status": "NOT_RUN"},
    {"check_id": "LIVE_ADAPTER_EXECUTION", "status": "NOT_RUN"},
    {"check_id": "REMOTE_CI", "status": "NOT_RUN"},
]


class EvidenceError(RuntimeError):
    """A bounded recorder failure suitable for machine-readable output."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise EvidenceError("ARGUMENT_ERROR", message)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _environment_record() -> dict[str, Any]:
    tools: dict[str, str | None] = {}
    for distribution in ("setuptools", "wheel"):
        try:
            tools[distribution] = distribution_version(distribution)
        except PackageNotFoundError:
            tools[distribution] = None
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "build_tools": tools,
    }


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _strict_json_object(payload: bytes, step: str) -> dict[str, Any]:
    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite token {token!r}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceError(
            "INVALID_JSON_OUTPUT",
            f"{step} did not emit one strict JSON object: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise EvidenceError(
            "INVALID_JSON_OUTPUT",
            f"{step} emitted {type(value).__name__}, expected object",
        )
    return value


def _write_bytes(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _publish_bytes(output_dir: Path, path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output = output_dir.resolve(strict=True)
    resolved_parent = path.parent.resolve(strict=True)
    if not _is_within(resolved_parent, resolved_output):
        raise EvidenceError(
            "PUBLISH_PATH_ESCAPE",
            f"publish path escapes the evidence directory: {path}",
        )
    if path.exists() and path.is_dir():
        raise EvidenceError("PUBLISH_TARGET_IS_DIRECTORY", str(path))
    _write_bytes(path, payload)


def _resolve_output_dir(value: Path) -> Path:
    repo_root = REPO_ROOT.resolve(strict=True)
    evidence_root = (REPO_ROOT / "evidence").resolve(strict=True)
    candidate = value if value.is_absolute() else REPO_ROOT / value
    resolved = candidate.resolve(strict=False)
    if resolved == evidence_root or not _is_within(resolved, evidence_root):
        raise EvidenceError(
            "OUTPUT_OUTSIDE_REPOSITORY",
            "--output-dir must be a child directory inside REP-03 evidence/",
        )
    if resolved.exists() and not resolved.is_dir():
        raise EvidenceError("OUTPUT_NOT_DIRECTORY", str(resolved))
    return resolved


def _invalidate_acceptance_marker(output_dir: Path) -> None:
    marker = output_dir / "release-manifest.json.sha256"
    if marker.is_file() or marker.is_symlink():
        marker.unlink()


def _repository_record(path: Path) -> dict[str, Any]:
    repo_root = REPO_ROOT.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not path.is_file() or not _is_within(resolved, repo_root):
        raise EvidenceError(
            "SOURCE_PATH_INVALID",
            f"source must be a regular in-repository file: {path}",
        )
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _input_record(path: Path) -> dict[str, Any]:
    repo_root = REPO_ROOT.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix != ".whl":
        raise EvidenceError("WHEEL_REQUIRED", "--wheel must identify one .whl file")
    if _is_within(resolved, repo_root):
        display_path = resolved.relative_to(repo_root).as_posix()
        scope = "REPOSITORY_RELATIVE"
    else:
        display_path = resolved.name
        scope = "INPUT_BASENAME"
    return {
        "path": display_path,
        "path_scope": scope,
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _payload_record(path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": len(payload),
        "sha256": _sha256_bytes(payload),
    }


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _is_linklike(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        attributes = 0
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return (
        path.is_symlink()
        or bool(is_junction and is_junction())
        or bool(attributes & reparse_flag)
    )


def _required_test_distributions() -> dict[str, dict[str, str]]:
    required: dict[str, dict[str, str]] = {}
    try:
        lines = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EvidenceError("TEST_REQUIREMENTS_UNREADABLE", str(exc)) from exc
    if not lines:
        raise EvidenceError("TEST_REQUIREMENTS_EMPTY", "requirements-test.txt is empty")
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        match = _REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise EvidenceError(
                "TEST_REQUIREMENT_NOT_EXACT",
                f"requirements-test.txt:{line_number} must use exact name==version syntax",
            )
        declared_name = match.group("name")
        canonical_name = _canonical_distribution_name(declared_name)
        if canonical_name in required:
            raise EvidenceError(
                "DUPLICATE_TEST_REQUIREMENT",
                f"duplicate test requirement {canonical_name}",
            )
        required[canonical_name] = {
            "declared_name": declared_name,
            "version": match.group("version"),
        }
    return required


def _dependency_record_target(
    dependency_root: Path,
    record_member: str,
) -> tuple[Path, str]:
    if record_member.startswith("../../bin/"):
        script_name = record_member.removeprefix("../../bin/")
        script_path = PurePosixPath(script_name)
        if (
            not script_name
            or "\\" in script_name
            or script_path.is_absolute()
            or len(script_path.parts) != 1
            or script_path.parts[0] in {".", ".."}
        ):
            raise EvidenceError(
                "TEST_DEPENDENCY_RECORD_PATH_INVALID",
                f"unsafe script RECORD path {record_member!r}",
            )
        relative = PurePosixPath("bin") / script_path
    else:
        relative = PurePosixPath(record_member)
        if (
            not record_member
            or "\\" in record_member
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != record_member
        ):
            raise EvidenceError(
                "TEST_DEPENDENCY_RECORD_PATH_INVALID",
                f"unsafe RECORD path {record_member!r}",
            )
    target = dependency_root.joinpath(*relative.parts)
    return target, relative.as_posix()


def _test_dependency_inventory(test_dependency_path: Path | None) -> dict[str, Any]:
    if test_dependency_path is None:
        raise EvidenceError(
            "TEST_DEPENDENCY_PATH_REQUIRED",
            "--test-dependency-path is required for isolated D4 evidence",
        )
    dependency_root = test_dependency_path.resolve(strict=True)
    if not dependency_root.is_dir() or _is_linklike(test_dependency_path):
        raise EvidenceError(
            "TEST_DEPENDENCY_PATH_INVALID",
            "--test-dependency-path must identify a regular directory",
        )
    for candidate in dependency_root.rglob("*"):
        if _is_linklike(candidate):
            raise EvidenceError(
                "TEST_DEPENDENCY_LINK_FORBIDDEN",
                candidate.relative_to(dependency_root).as_posix(),
            )

    required = _required_test_distributions()
    discovered: dict[str, Any] = {}
    for distribution in distributions(path=[str(dependency_root)]):
        raw_name = distribution.metadata.get("Name")
        if not isinstance(raw_name, str) or not raw_name:
            raise EvidenceError(
                "TEST_DEPENDENCY_METADATA_INVALID",
                "a test distribution has no Name metadata",
            )
        canonical_name = _canonical_distribution_name(raw_name)
        if canonical_name in discovered:
            raise EvidenceError(
                "DUPLICATE_TEST_DISTRIBUTION",
                f"multiple installed distributions normalize to {canonical_name}",
            )
        discovered[canonical_name] = distribution

    if set(discovered) != set(required):
        missing = sorted(set(required) - set(discovered))
        extra = sorted(set(discovered) - set(required))
        raise EvidenceError(
            "TEST_DEPENDENCY_ALLOWLIST_MISMATCH",
            f"missing={missing!r}; extra={extra!r}",
        )

    expected_files: set[str] = set()
    package_records: list[dict[str, Any]] = []
    for canonical_name in sorted(required):
        distribution = discovered[canonical_name]
        expected_version = required[canonical_name]["version"]
        if distribution.version != expected_version:
            raise EvidenceError(
                "TEST_DEPENDENCY_VERSION_MISMATCH",
                f"{canonical_name}: expected {expected_version}, got {distribution.version}",
            )
        dist_info = Path(distribution._path)
        resolved_dist_info = dist_info.resolve(strict=True)
        if (
            _is_linklike(dist_info)
            or not resolved_dist_info.is_dir()
            or not _is_within(resolved_dist_info, dependency_root)
        ):
            raise EvidenceError(
                "TEST_DEPENDENCY_METADATA_PATH_INVALID",
                f"invalid dist-info path for {canonical_name}",
            )
        record_path = dist_info / "RECORD"
        if not record_path.is_file() or record_path.is_symlink():
            raise EvidenceError(
                "TEST_DEPENDENCY_RECORD_MISSING",
                f"{canonical_name} has no regular RECORD file",
            )
        record_bytes = record_path.read_bytes()
        try:
            rows = list(
                csv.reader(
                    io.StringIO(
                        record_bytes.decode("utf-8", errors="strict"),
                        newline="",
                    ),
                    strict=True,
                )
            )
        except (csv.Error, UnicodeError) as exc:
            raise EvidenceError(
                "TEST_DEPENDENCY_RECORD_INVALID",
                f"{canonical_name}: {exc}",
            ) from exc
        if not rows:
            raise EvidenceError(
                "TEST_DEPENDENCY_RECORD_EMPTY",
                canonical_name,
            )
        observed_record_members: set[str] = set()
        own_record = record_path.relative_to(dependency_root).as_posix()
        for row in rows:
            if len(row) != 3:
                raise EvidenceError(
                    "TEST_DEPENDENCY_RECORD_INVALID",
                    f"{canonical_name}: every RECORD row must contain three fields",
                )
            member, hash_field, size_field = row
            if member in observed_record_members:
                raise EvidenceError(
                    "TEST_DEPENDENCY_RECORD_DUPLICATE",
                    f"{canonical_name}: duplicate {member!r}",
                )
            observed_record_members.add(member)
            target, normalized_member = _dependency_record_target(
                dependency_root,
                member,
            )
            is_bytecode = "__pycache__" in PurePosixPath(normalized_member).parts or (
                PurePosixPath(normalized_member).suffix == ".pyc"
            )
            if is_bytecode:
                if hash_field or size_field:
                    raise EvidenceError(
                        "TEST_DEPENDENCY_BYTECODE_RECORD_INVALID",
                        f"{canonical_name}: generated bytecode must be unhashed",
                    )
                continue
            try:
                resolved_target = target.resolve(strict=True)
            except OSError as exc:
                raise EvidenceError(
                    "TEST_DEPENDENCY_FILE_MISSING",
                    normalized_member,
                ) from exc
            if (
                _is_linklike(target)
                or not resolved_target.is_file()
                or not _is_within(resolved_target, dependency_root)
            ):
                raise EvidenceError(
                    "TEST_DEPENDENCY_FILE_INVALID",
                    normalized_member,
                )
            expected_files.add(normalized_member)
            if normalized_member == own_record:
                if hash_field or size_field:
                    raise EvidenceError(
                        "TEST_DEPENDENCY_RECORD_INVALID",
                        f"{canonical_name}: RECORD must not hash itself",
                    )
                continue
            if not hash_field.startswith("sha256=") or not size_field.isdigit():
                raise EvidenceError(
                    "TEST_DEPENDENCY_HASH_MISSING",
                    f"{canonical_name}: {normalized_member}",
                )
            expected_hash = base64.urlsafe_b64encode(
                hashlib.sha256(target.read_bytes()).digest()
            ).rstrip(b"=").decode("ascii")
            if (
                hash_field.removeprefix("sha256=") != expected_hash
                or int(size_field) != target.stat().st_size
            ):
                raise EvidenceError(
                    "TEST_DEPENDENCY_HASH_MISMATCH",
                    f"{canonical_name}: {normalized_member}",
                )
        if own_record not in {
            _dependency_record_target(dependency_root, member)[1]
            for member in observed_record_members
        }:
            raise EvidenceError(
                "TEST_DEPENDENCY_RECORD_SELF_ENTRY_MISSING",
                canonical_name,
            )
        package_records.append(
            {
                "name": canonical_name,
                "version": distribution.version,
                "record_entry_count": len(rows),
                "record_sha256": _sha256_bytes(record_bytes),
            }
        )

    actual_files: set[str] = set()
    excluded_bytecode_count = 0
    for path in dependency_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(dependency_root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            excluded_bytecode_count += 1
            continue
        if _is_linklike(path) or not _is_within(path.resolve(strict=True), dependency_root):
            raise EvidenceError("TEST_DEPENDENCY_FILE_INVALID", relative.as_posix())
        actual_files.add(relative.as_posix())
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise EvidenceError(
            "TEST_DEPENDENCY_TREE_MISMATCH",
            f"missing={missing!r}; extra={extra!r}",
        )

    tree_records = [
        {
            "path": relative,
            "size_bytes": (dependency_root / PurePosixPath(relative)).stat().st_size,
            "sha256": _sha256(dependency_root / PurePosixPath(relative)),
        }
        for relative in sorted(actual_files)
    ]
    repo_root = REPO_ROOT.resolve(strict=True)
    if _is_within(dependency_root, repo_root):
        display_path = dependency_root.relative_to(repo_root).as_posix()
        path_scope = "REPOSITORY_RELATIVE_IGNORED_INPUT"
    else:
        display_path = dependency_root.name
        path_scope = "INPUT_BASENAME"
    return {
        "status": "PASS",
        "path": display_path,
        "path_scope": path_scope,
        "requirements_file": REQUIREMENTS_PATH.relative_to(REPO_ROOT).as_posix(),
        "requirements_sha256": _sha256(REQUIREMENTS_PATH),
        "packages": package_records,
        "file_count": len(tree_records),
        "excluded_untrusted_bytecode_count": excluded_bytecode_count,
        "tree_manifest_sha256": _sha256_bytes(_json_bytes(tree_records)),
    }


def _source_paths() -> list[Path]:
    paths: set[Path] = set()

    package_roots = sorted(FIRMWARE_ROOT.glob("repo03_*"))
    if not package_roots:
        raise EvidenceError("SOURCE_INVENTORY_EMPTY", "no firmware/repo03_* package")
    for package_root in package_roots:
        if not package_root.is_dir():
            continue
        for path in package_root.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            ):
                paths.add(path)

    groups: list[tuple[str, Iterable[Path]]] = [
        ("tests/test_*.py", (REPO_ROOT / "tests").glob("test_*.py")),
        ("variants/**/*.json", (REPO_ROOT / "variants").rglob("*.json")),
        (
            ".github/workflows/*.yml",
            (REPO_ROOT / ".github" / "workflows").glob("*.yml"),
        ),
        ("scripts/verify_*.py", (REPO_ROOT / "scripts").glob("verify_*.py")),
    ]
    for label, candidates in groups:
        group = [path for path in candidates if path.is_file()]
        if not group:
            raise EvidenceError("SOURCE_INVENTORY_EMPTY", f"no files matched {label}")
        paths.update(group)

    required = [
        RECORDER_PATH,
        REPO_ROOT / ".gitattributes",
        REPO_ROOT / ".gitignore",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "requirements-test.txt",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "README.md",
        REPO_ROOT / "evidence" / "README.md",
        REPO_ROOT / "firmware" / "README.md",
        REPO_ROOT / "tests" / "README.md",
        REPO_ROOT / "variants" / "README.md",
        REPO_ROOT / "evidence" / "source_evidence_register.v1.json",
        REPO_ROOT / "evidence" / "INT-02A" / "manifest.json",
        REPO_ROOT / "evidence" / "INT-02A" / "manifest.json.sha256",
    ]
    for path in required:
        if not path.is_file():
            raise EvidenceError(
                "REQUIRED_SOURCE_MISSING",
                path.relative_to(REPO_ROOT).as_posix(),
            )
        paths.add(path)

    return sorted(paths, key=lambda item: item.relative_to(REPO_ROOT).as_posix())


def _snapshot(paths: Iterable[Path]) -> dict[Path, dict[str, Any]]:
    return {path: _repository_record(path) for path in paths}


def _assert_snapshot(snapshot: Mapping[Path, Mapping[str, Any]]) -> None:
    current_paths = _source_paths()
    if current_paths != list(snapshot):
        missing = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in set(snapshot) - set(current_paths)
        )
        extra = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in set(current_paths) - set(snapshot)
        )
        raise EvidenceError(
            "SOURCE_INVENTORY_CHANGED_DURING_RUN",
            f"missing={missing!r}; extra={extra!r}",
        )
    for path, expected in snapshot.items():
        if _repository_record(path) != dict(expected):
            raise EvidenceError(
                "SOURCE_CHANGED_DURING_RUN",
                path.relative_to(REPO_ROOT).as_posix(),
            )


def _run_git(arguments: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError("GIT_COMMAND_TIMEOUT", "git command exceeded 30 seconds") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceError("GIT_COMMAND_FAILED", detail or "git command failed")
    return completed.stdout


def _git_head() -> str:
    try:
        value = _run_git(["rev-parse", "HEAD"]).decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise EvidenceError("INVALID_GIT_HEAD", "HEAD is not ASCII") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise EvidenceError("INVALID_GIT_HEAD", value)
    return value


def _porcelain_entry_count(payload: bytes) -> int:
    records = payload.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    count = 0
    index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 3:
            raise EvidenceError("INVALID_GIT_STATUS", "short porcelain record")
        status = record[:2]
        count += 1
        index += 1
        if b"R" in status or b"C" in status:
            if index >= len(records):
                raise EvidenceError("INVALID_GIT_STATUS", "rename source path missing")
            index += 1
    return count


def _git_status(output_dir: Path) -> tuple[dict[str, Any], bytes]:
    relative_output = output_dir.relative_to(REPO_ROOT).as_posix()
    payload = _run_git(
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            ".",
            f":(exclude,literal){relative_output}",
            f":(exclude,glob){relative_output}/**",
        ]
    )
    return (
        {
            "entry_count": _porcelain_entry_count(payload),
            "format": "git-status-porcelain-v1-z",
            "output_path_excluded": relative_output,
            "sha256": _sha256_bytes(payload),
        },
        payload,
    )


def _dependency_inventory_identity(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: inventory[key]
        for key in (
            "status",
            "requirements_file",
            "requirements_sha256",
            "packages",
            "file_count",
            "tree_manifest_sha256",
        )
    }


def _copy_sanitized_test_dependencies(source: Path, destination: Path) -> None:
    destination.mkdir()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if _is_linklike(path) or not _is_within(path.resolve(strict=True), source):
            raise EvidenceError(
                "TEST_DEPENDENCY_FILE_INVALID",
                relative.as_posix(),
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if target.stat().st_size != path.stat().st_size or _sha256(target) != _sha256(path):
            raise EvidenceError(
                "TEST_DEPENDENCY_COPY_MISMATCH",
                relative.as_posix(),
            )


def _test_dependency_scratch_root() -> Path:
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "Temp" / "repo03-d4-tests"
    return Path(tempfile.gettempdir()) / "repo03-d4-tests"


def _assert_test_source_import_safety() -> None:
    for root in (FIRMWARE_ROOT, REPO_ROOT / "tests"):
        if _is_linklike(root) or not root.is_dir():
            raise EvidenceError("TEST_SOURCE_ROOT_INVALID", str(root))
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if _is_linklike(path):
                raise EvidenceError(
                    "TEST_SOURCE_LINK_FORBIDDEN",
                    f"{root.name}/{relative.as_posix()}",
                )
            if (
                path.is_file()
                and path.suffix == ".pyc"
                and "__pycache__" not in relative.parts
            ):
                raise EvidenceError(
                    "LEGACY_SOURCE_BYTECODE_FORBIDDEN",
                    f"{root.name}/{relative.as_posix()}",
                )


def _run_unit_tests(
    test_dependency_path: Path,
    expected_dependency_inventory: Mapping[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    dependency = test_dependency_path.resolve(strict=True)
    _assert_test_source_import_safety()
    scratch_parent = _test_dependency_scratch_root()
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="run-", dir=scratch_parent)).resolve(
        strict=True
    )
    try:
        sanitized_dependency = scratch / "site-packages"
        _copy_sanitized_test_dependencies(dependency, sanitized_dependency)
        sanitized_inventory = _test_dependency_inventory(sanitized_dependency)
        if _dependency_inventory_identity(sanitized_inventory) != (
            _dependency_inventory_identity(expected_dependency_inventory)
        ):
            raise EvidenceError(
                "SANITIZED_TEST_DEPENDENCY_MISMATCH",
                "the bytecode-free dependency copy changed the verified inventory",
            )
        if sanitized_inventory["excluded_untrusted_bytecode_count"] != 0:
            raise EvidenceError(
                "SANITIZED_TEST_DEPENDENCY_HAS_BYTECODE",
                "the sanitized dependency copy contains bytecode",
            )

        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["PYTHONUTF8"] = "1"
        environment["REPO03_TEST_FIRMWARE"] = str(FIRMWARE_ROOT.resolve(strict=True))
        environment["REPO03_TEST_DEPENDENCIES"] = str(sanitized_dependency)
        environment["REPO03_TEST_PYCACHE_PREFIX"] = str(scratch / "pycache")
        command = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            UNIT_TEST_BOOTSTRAP,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise EvidenceError(
                "UNIT_TESTS_TIMEOUT", "unittest suite exceeded 300 seconds"
            ) from exc
        final_sanitized_inventory = _test_dependency_inventory(sanitized_dependency)
        if final_sanitized_inventory != sanitized_inventory:
            raise EvidenceError(
                "SANITIZED_TEST_DEPENDENCIES_CHANGED",
                "test execution changed the sanitized dependency tree",
            )
        _assert_test_source_import_safety()
        try:
            combined = completed.stdout.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise EvidenceError("UNIT_TEST_LOG_NOT_UTF8", str(exc)) from exc
        combined = combined.replace("\r\n", "\n").replace("\r", "\n")
        run_matches = re.findall(
            r"(?m)^Ran ([0-9]+) tests? in ([0-9]+(?:\.[0-9]+)?)s$", combined
        )
        ok_matches = re.findall(r"(?m)^OK(?: \([^\n]+\))?$", combined)
        if completed.returncode != 0:
            raise EvidenceError(
                "UNIT_TESTS_FAILED",
                f"unittest returned {completed.returncode}",
            )
        if len(run_matches) != 1 or len(ok_matches) != 1:
            raise EvidenceError(
                "UNIT_TEST_SUMMARY_INVALID",
                "expected exactly one 'Ran N tests' line and one successful OK line",
            )
        test_count = int(run_matches[0][0])
        if test_count != EXPECTED_UNIT_TEST_COUNT:
            raise EvidenceError(
                "UNIT_TEST_COUNT_MISMATCH",
                f"expected {EXPECTED_UNIT_TEST_COUNT}, discovered {test_count}",
            )
        normalized = re.sub(
            r"(?m)^Ran ([0-9]+) tests? in [0-9]+(?:\.[0-9]+)?s$",
            lambda match: f"Ran {match.group(1)} tests in <elapsed>s",
            combined,
            count=1,
        )
        if not normalized.endswith("\n"):
            normalized += "\n"
        return normalized.encode("utf-8"), {
            "status": "PASS",
            "test_count": test_count,
            "command": [
                "python",
                "-I",
                "-S",
                "-B",
                "-c",
                UNIT_TEST_BOOTSTRAP,
            ],
            "combined_log_encoding": "UTF-8",
            "elapsed_time_in_log": "NORMALIZED",
            "isolation": {
                "ignore_python_environment": True,
                "skip_site_initialization": True,
                "user_site_disabled": True,
                "bytecode_writes_disabled": True,
                "sanitized_dependency_copy": True,
                "untrusted_input_bytecode_executed": False,
            },
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run_release_verifier(
    wheel_path: Path,
    wheel_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                str(VERIFIER_PATH),
                "--wheel",
                str(wheel_path),
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError(
            "D4_RELEASE_VERIFIER_TIMEOUT",
            "verify_d4_release.py exceeded 300 seconds",
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if not detail:
            detail = completed.stdout.decode("utf-8", errors="replace").strip()
        raise EvidenceError(
            "D4_RELEASE_VERIFIER_FAILED",
            detail[:1600] or f"verifier returned {completed.returncode}",
        )
    if completed.stderr:
        raise EvidenceError(
            "D4_RELEASE_VERIFIER_STDERR",
            completed.stderr.decode("utf-8", errors="replace").strip()[:1600],
        )
    result = _strict_json_object(completed.stdout, "verify_d4_release.py")
    _validate_release_result(result, wheel_path, wheel_snapshot)
    return result


def _validate_release_result(
    result: Mapping[str, Any],
    wheel_path: Path,
    wheel_snapshot: Mapping[str, Any],
) -> None:
    if result.get("schema_version") != "repo03.d4-local-verification.v1":
        raise EvidenceError(
            "D4_VERIFIER_SCHEMA_MISMATCH", repr(result.get("schema_version"))
        )
    if result.get("verification_status") != "PASS":
        raise EvidenceError(
            "D4_LOCAL_VERIFICATION_NOT_PASS", repr(result.get("verification_status"))
        )
    if result.get("release_status") != "BLOCKED":
        raise EvidenceError(
            "D4_RELEASE_STATUS_INVALID", repr(result.get("release_status"))
        )
    blockers = result.get("release_blockers")
    if not isinstance(blockers, list) or sorted(blockers) != sorted(RELEASE_BLOCKERS):
        raise EvidenceError("D4_RELEASE_BLOCKERS_INVALID", repr(blockers))

    observed_wheel = result.get("wheel")
    expected_wheel_keys = {
        "file_name",
        "sha256",
        "size_bytes",
        "archive_member_count",
        "record_sha256",
    }
    if not isinstance(observed_wheel, dict) or set(observed_wheel) != expected_wheel_keys:
        raise EvidenceError("D4_WHEEL_BINDING_MISMATCH", repr(observed_wheel))
    if (
        observed_wheel.get("file_name") != wheel_path.name
        or observed_wheel.get("sha256") != wheel_snapshot.get("sha256")
        or observed_wheel.get("size_bytes") != wheel_snapshot.get("size_bytes")
        or observed_wheel.get("archive_member_count") != EXPECTED_WHEEL_MEMBER_COUNT
        or not isinstance(observed_wheel.get("record_sha256"), str)
        or not _SHA256_RE.fullmatch(observed_wheel["record_sha256"])
    ):
        raise EvidenceError("D4_WHEEL_BINDING_MISMATCH", repr(observed_wheel))

    package = result.get("package")
    if (
        not isinstance(package, dict)
        or package.get("distribution_name") != PACKAGE_NAME
        or package.get("version") != PACKAGE_VERSION
        or package.get("runtime_dependencies") != []
    ):
        raise EvidenceError("D4_PACKAGE_METADATA_INVALID", repr(package))
    checks = result.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != EXPECTED_RELEASE_CHECKS
        or set(checks.values()) != {"PASS"}
    ):
        raise EvidenceError("D4_CHECK_SET_NOT_PASS", repr(checks))
    cli_cases = result.get("cli_cases")
    if not isinstance(cli_cases, dict) or set(cli_cases) != EXPECTED_CLI_CASES:
        raise EvidenceError("D4_CLI_CASE_SET_INVALID", repr(cli_cases))
    claim_limits = result.get("claim_limits")
    if (
        not isinstance(claim_limits, list)
        or len(claim_limits) != len(set(claim_limits))
        or set(claim_limits) != EXPECTED_CLAIM_LIMITS
    ):
        raise EvidenceError("D4_CLAIM_LIMITS_INVALID", repr(claim_limits))


def _verification_record(
    *,
    recorded_at_utc: str,
    baseline: str,
    test_count: int,
    test_dependencies: Mapping[str, Any],
    package_version: str,
    wheel_record: Mapping[str, Any],
    source_count: int,
    git_status: Mapping[str, Any],
) -> str:
    return f"""# D4 yerel sürüm doğrulama kaydı

## Sonuç

- Yerel doğrulama: `PASS`
- Kayıt zamanı (UTC): `{recorded_at_utc}`
- Sürüm durumu: `BLOCKED`
- Engeller: `LICENSE_DECISION_REQUIRED`, `REMOTE_CI_NOT_RUN`
- Paket: `{PACKAGE_NAME}=={package_version}`
- Wheel: `{wheel_record['path']}`
- Wheel SHA-256: `{wheel_record['sha256']}`
- Tam unittest paketi: `{test_count}` test, `PASS`
- Test bağımlılıkları: `{len(test_dependencies['packages'])}` paket / `{test_dependencies['tree_manifest_sha256']}`
- Kaynak envanteri: `{source_count}` dosya
- Git tabanı: `{baseline}`
- Git durum kaydı: `{git_status['entry_count']}` girdi / `{git_status['sha256']}`

Yerel kapı; tam test paketini `python -I -S -B` ile ambient ve user
site-packages alanlarından yalıtır. Exact `requirements-test.txt` dağıtım
sürümleri ve kurulu dosya hashleri ayrıca doğrulanır. Wheel'in ağsız ve
bağımlılıksız temiz kurulumunu, paket
içe aktarmalarını, `repo03` konsol girişini, yedi komut yolunu ve Variant A
raporunun aynı girdide byte-deterministik olmasını doğrular. Bu sonuç uzak
GitHub Actions koşusunun gerçekleştiği veya bir sürümün yayımlandığı anlamına
gelmez.

## Açık kapılar ve iddia sınırı

`GAP-01`, `GAP-02`, `GAP-03` ve `GAP-04` `BLOCKED` kalır. Fiziksel doğrulama,
RF, EMC, AEC yeterliliği, ISO uygunluğu, gerçek Raspberry Pi kapanışı, canlı
adaptör yürütmesi ve uzak CI `NOT_RUN` durumundadır. Sentetik test ve temiz
kurulum sonuçları bu alanlarda donanım, araç veya uygunluk iddiası oluşturmaz.

## Yeniden üretim

Depo kökünden, exact `requirements-test.txt` içeriğinin ayrı bir hedef dizine
kurulduğu yolu zorunlu seçenek olarak vererek çalıştırın:

```powershell
python -m pip install --disable-pip-version-check --no-deps `
  --target <test-dependency-directory> -r requirements-test.txt
python -B scripts/record_d4_evidence.py `
  --wheel <esp32_s3_automotive_interfaces-0.1.0-py3-none-any.whl> `
  --test-dependency-path <test-dependency-directory>
```

`release-manifest.json.sha256` kabul işaretidir ve yalnız kaynaklar koşu boyunca
değişmediyse en son yazılır.
"""


def record(
    wheel_path: Path,
    test_dependency_path: Path | None,
    output_value: Path,
) -> dict[str, Any]:
    output_dir = _resolve_output_dir(output_value)
    try:
        recorded_at_utc = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        wheel_path = wheel_path.resolve(strict=True)
        wheel_snapshot = _input_record(wheel_path)
        wheel_record = dict(wheel_snapshot)
        source_paths = _source_paths()
        if any(_is_within(path.resolve(strict=True), output_dir) for path in source_paths):
            raise EvidenceError(
                "OUTPUT_OVERLAPS_SOURCE_INVENTORY",
                "--output-dir contains one or more source-inventory files",
            )
        source_snapshot = _snapshot(source_paths)
        test_dependency_snapshot = _test_dependency_inventory(test_dependency_path)
        baseline = _git_head()
        git_status, git_status_bytes = _git_status(output_dir)

        if test_dependency_path is None:
            raise EvidenceError(
                "TEST_DEPENDENCY_PATH_REQUIRED",
                "--test-dependency-path is required for isolated D4 evidence",
            )
        unit_log_payload, unit_result = _run_unit_tests(
            test_dependency_path,
            test_dependency_snapshot,
        )
        verifier_result = _run_release_verifier(wheel_path, wheel_snapshot)

        cli_smoke = {
            "schema_version": "repo03.d4.cli-smoke-results.v1",
            "recorded_at_utc": recorded_at_utc,
            "status": "PASS",
            "release_status": "BLOCKED",
            "package": verifier_result["package"],
            "wheel": verifier_result["wheel"],
            "checks": verifier_result["checks"],
            "cli_cases": verifier_result["cli_cases"],
            "claim_limits": verifier_result.get("claim_limits", []),
        }
        verification_result = {
            "schema_version": SCHEMA_VERSION,
            "recorded_at_utc": recorded_at_utc,
            "status": "PASS",
            "reason_code": "D4_LOCAL_TEST_AND_CLEAN_INSTALL_PASS",
            "release_status": "BLOCKED",
            "release_blockers": RELEASE_BLOCKERS,
            "environment": _environment_record(),
            "test_dependencies": test_dependency_snapshot,
            "unit_tests": unit_result,
            "clean_install_and_cli": verifier_result,
            "open_gaps": OPEN_GAPS,
            "not_run_checks": NOT_RUN_CHECKS,
        }

        cli_payload = _json_bytes(cli_smoke)
        verification_payload = _json_bytes(verification_result)
        record_payload = _verification_record(
            recorded_at_utc=recorded_at_utc,
            baseline=baseline,
            test_count=unit_result["test_count"],
            test_dependencies=test_dependency_snapshot,
            package_version=verifier_result["package"]["version"],
            wheel_record=wheel_record,
            source_count=len(source_snapshot),
            git_status=git_status,
        ).encode("utf-8")

        generated_payloads = {
            output_dir / "unit-test.log": unit_log_payload,
            output_dir / "cli-smoke-results.json": cli_payload,
            output_dir / "verification-result.json": verification_payload,
            output_dir / "verification-record.md": record_payload,
        }
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "release_gate_id": "D4",
            "recorded_at_utc": recorded_at_utc,
            "local_verification_status": "PASS",
            "release_status": "BLOCKED",
            "release_blockers": RELEASE_BLOCKERS,
            "environment": _environment_record(),
            "test_dependencies": test_dependency_snapshot,
            "license": {
                "status": "BLOCKED_CLIENT_DECISION",
                "spdx_expression": None,
                "file": None,
            },
            "remote_ci": {"status": "NOT_RUN", "run_url": None},
            "repository": {
                "baseline_git_head": baseline,
                "source_state": SOURCE_STATE,
                "git_status": git_status,
            },
            "package": verifier_result["package"],
            "wheel": wheel_record,
            "unit_tests": {
                "status": "PASS",
                "test_count": unit_result["test_count"],
            },
            "open_gaps": OPEN_GAPS,
            "not_run_checks": NOT_RUN_CHECKS,
            "source_files": [dict(source_snapshot[path]) for path in source_paths],
            "generated_files": [
                _payload_record(path, payload)
                for path, payload in sorted(
                    generated_payloads.items(),
                    key=lambda item: item[0].relative_to(REPO_ROOT).as_posix(),
                )
            ],
        }
        manifest_payload = _json_bytes(manifest)
        manifest_path = output_dir / "release-manifest.json"
        checksum_path = output_dir / "release-manifest.json.sha256"
        manifest_hash = _sha256_bytes(manifest_payload)
        checksum_payload = f"{manifest_hash}  release-manifest.json\n".encode("ascii")

        _assert_snapshot(source_snapshot)
        if _git_head() != baseline:
            raise EvidenceError("GIT_HEAD_CHANGED_DURING_RUN", baseline)
        if _input_record(wheel_path) != wheel_snapshot:
            raise EvidenceError("WHEEL_CHANGED_DURING_RUN", wheel_path.name)
        if _test_dependency_inventory(test_dependency_path) != test_dependency_snapshot:
            raise EvidenceError(
                "TEST_DEPENDENCIES_CHANGED_DURING_RUN",
                test_dependency_snapshot["path"],
            )
        final_git_status, final_git_status_bytes = _git_status(output_dir)
        if final_git_status != git_status or final_git_status_bytes != git_status_bytes:
            raise EvidenceError(
                "WORKTREE_CHANGED_DURING_RUN",
                "git status changed while D4 evidence was being produced",
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        if output_dir.resolve(strict=True) != output_dir:
            raise EvidenceError("OUTPUT_PATH_CHANGED", str(output_dir))
        _invalidate_acceptance_marker(output_dir)
        for path, payload in generated_payloads.items():
            _publish_bytes(output_dir, path, payload)
        _publish_bytes(output_dir, manifest_path, manifest_payload)

        _assert_snapshot(source_snapshot)
        if _git_head() != baseline:
            raise EvidenceError("GIT_HEAD_CHANGED_DURING_PUBLISH", baseline)
        if _input_record(wheel_path) != wheel_snapshot:
            raise EvidenceError("WHEEL_CHANGED_DURING_RUN", wheel_path.name)
        if _test_dependency_inventory(test_dependency_path) != test_dependency_snapshot:
            raise EvidenceError(
                "TEST_DEPENDENCIES_CHANGED_DURING_PUBLISH",
                test_dependency_snapshot["path"],
            )
        final_git_status, final_git_status_bytes = _git_status(output_dir)
        if final_git_status != git_status or final_git_status_bytes != git_status_bytes:
            raise EvidenceError(
                "WORKTREE_CHANGED_DURING_PUBLISH",
                "git status changed before the D4 acceptance marker was written",
            )
        _publish_bytes(output_dir, checksum_path, checksum_payload)

        return {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "recorded_at_utc": recorded_at_utc,
            "release_status": "BLOCKED",
            "release_blockers": RELEASE_BLOCKERS,
            "test_count": unit_result["test_count"],
            "manifest_sha256": manifest_hash,
            "output_dir": output_dir.relative_to(REPO_ROOT).as_posix(),
            "wheel_sha256": wheel_record["sha256"],
        }
    except BaseException:
        _invalidate_acceptance_marker(output_dir)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Run and record local-only REP-03 D4 release evidence."
    )
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--test-dependency-path", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = build_parser().parse_args(argv)
        result = record(
            arguments.wheel,
            arguments.test_dependency_path,
            arguments.output_dir,
        )
    except Exception as exc:
        if isinstance(exc, EvidenceError):
            code = exc.code
            detail = exc.detail
        else:
            code = "D4_EVIDENCE_RECORDER_ERROR"
            detail = str(exc)
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "release_status": "BLOCKED",
            "error": {"code": code, "detail": detail},
        }
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

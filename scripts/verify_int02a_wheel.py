"""Verify INT-02A against the exact, pinned REP-02 wheel.

The normal REP-03 unit suite intentionally has no REP-02 dependency.  This
separate acceptance gate verifies the wheel SHA-256, installs it into a
temporary environment with no index and no dependencies, calls the public
``validate_file_api_file`` API, executes fail-closed negative cases, and writes
deterministic evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_ROOT = REPO_ROOT / "firmware"
if str(FIRMWARE_ROOT) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_ROOT))

from repo03_integration import (  # noqa: E402
    ARTIFACT_RELATIVE_PATH,
    DESCRIPTOR_FILE_NAME,
    HandoffValidationError,
    REPORT_INPUT_HASH,
    dependency_contract,
    descriptor_input_hash,
    materialize_power_handoff,
    validate_report_binding,
)


SCENARIO_PATH = REPO_ROOT / "variants" / "fixtures" / "automotive_power" / "nominal.json"
DEPENDENCY_PATH = FIRMWARE_ROOT / "repo03_integration" / "rep02_dependency.v1.json"
INTEGRATION_INIT_PATH = FIRMWARE_ROOT / "repo03_integration" / "__init__.py"
HANDOFF_MODULE_PATH = FIRMWARE_ROOT / "repo03_integration" / "rep02_file_api.py"
TEST_PATH = REPO_ROOT / "tests" / "test_int02a_handoff.py"
SCRIPT_PATH = Path(__file__).resolve()
ATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"
if os.name == "nt":
    DEFAULT_TEMPORARY_ROOT = Path.home() / "AppData" / "Local" / "Temp" / "repo03-int02a"
else:
    DEFAULT_TEMPORARY_ROOT = Path(tempfile.gettempdir()) / "repo03-int02a"

SOURCE_EVIDENCE_PATHS = (
    ATTRIBUTES_PATH,
    DEPENDENCY_PATH,
    INTEGRATION_INIT_PATH,
    HANDOFF_MODULE_PATH,
    TEST_PATH,
    SCRIPT_PATH,
)


class VerificationError(RuntimeError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key in nominal scenario: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(token: str) -> None:
    raise VerificationError(f"non-finite JSON token in nominal scenario: {token!r}")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _write_json(path: Path, value: Any) -> None:
    _write_bytes(path, _json_bytes(value))


def _publish_bytes(output_root: Path, path: Path, payload: bytes) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_root = output_root.resolve(strict=True)
    resolved_parent = path.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise VerificationError(
            f"publish path escapes the evidence directory: {path}"
        ) from exc
    if path.exists() and path.is_dir():
        raise VerificationError(f"publish target is a directory: {path}")
    _write_bytes(path, payload)


def _run(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    environment: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(environment) if environment is not None else None,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or f"exit {completed.returncode}"
        raise VerificationError(f"command failed: {command[0]}: {detail}")
    return completed


def _git_head() -> str:
    return _run(["git", "rev-parse", "HEAD"]).stdout.strip()


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _verify_wheel(path: Path, dependency: Mapping[str, Any]) -> dict[str, Any]:
    wheel = dependency["rep02"]["wheel"]
    if not path.is_file():
        raise VerificationError(f"pinned REP-02 wheel is unavailable: {path}")
    observed_size = path.stat().st_size
    observed_hash = _sha256(path)
    if path.name != wheel["file_name"]:
        raise VerificationError(
            f"wheel filename mismatch: expected {wheel['file_name']!r}, observed {path.name!r}"
        )
    if observed_size != wheel["size_bytes"]:
        raise VerificationError(
            f"wheel size mismatch: expected {wheel['size_bytes']}, observed {observed_size}"
        )
    if observed_hash != wheel["sha256"]:
        raise VerificationError(
            f"wheel SHA-256 mismatch: expected {wheel['sha256']}, observed {observed_hash}"
        )
    return {
        "file_name": path.name,
        "size_bytes": observed_size,
        "sha256": observed_hash,
        "status": "PASS",
        "reason_code": "PINNED_WHEEL_BYTES_VERIFIED",
    }


_HELPER = r"""
import json
from pathlib import Path
import sys

import power_rail_validation
from power_rail_validation.integration import (
    API_VERSION,
    DESCRIPTOR_SCHEMA_VERSION,
    ENGINE_VERSION,
    RULE_ID,
    SPEC_SHA256,
    SPEC_SOURCE_ID,
    TOOL_NAME,
    validate_file_api_file,
)

result = validate_file_api_file(Path(sys.argv[1]))
payload = {
    "runtime": {
        "package_version": power_rail_validation.__version__,
        "api_version": API_VERSION,
        "descriptor_schema_version": DESCRIPTOR_SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "rule_id": RULE_ID,
        "tool_name": TOOL_NAME,
        "contract_source_id": SPEC_SOURCE_ID,
        "contract_sha256": SPEC_SHA256,
    },
    "result": result,
}
sys.stdout.write(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True))
"""


def _call_rep02(
    python: Path,
    descriptor: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    completed = _run(
        [str(python), "-I", "-B", "-c", _HELPER, str(descriptor)],
        environment=environment,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("installed REP-02 helper did not return strict JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("result"), dict):
        raise VerificationError("installed REP-02 helper returned an invalid envelope")
    return value


def _verify_runtime(observed: Mapping[str, Any], dependency: Mapping[str, Any]) -> None:
    expected_api = dependency["rep02"]["file_api"]
    expected = {
        "package_version": dependency["rep02"]["package_version"],
        "api_version": expected_api["api_version"],
        "descriptor_schema_version": expected_api["descriptor_schema_version"],
        "engine_version": expected_api["engine_version"],
        "rule_id": expected_api["rule_id"],
        "tool_name": expected_api["tool_name"],
        "contract_source_id": expected_api["contract_source_id"],
        "contract_sha256": expected_api["contract_sha256"],
    }
    if dict(observed) != expected:
        raise VerificationError(
            "installed REP-02 runtime metadata differs from the dependency contract"
        )


def _issue_codes(result: Mapping[str, Any]) -> list[str]:
    issues = result.get("issues")
    if not isinstance(issues, list):
        return []
    return sorted(
        {
            item.get("reason_code")
            for item in issues
            if isinstance(item, Mapping) and isinstance(item.get("reason_code"), str)
        }
    )


def _assert_positive(result: Mapping[str, Any], artifact_hash: str) -> None:
    if result.get("status") != "PASS" or result.get("reason_code") != "FILE_API_DESCRIPTOR_VALID":
        raise VerificationError("positive descriptor did not pass the installed REP-02 API")
    artifacts = result.get("artifact_results")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise VerificationError("positive descriptor did not return exactly one artifact result")
    artifact = artifacts[0]
    if (
        artifact.get("status") != "PASS"
        or artifact.get("reason_code") != "ARTIFACT_BYTES_VERIFIED"
        or artifact.get("expected_sha256") != artifact_hash
        or artifact.get("observed_sha256") != artifact_hash
    ):
        raise VerificationError("REP-02 did not verify the exact artifact bytes")
    adapters = result.get("adapter_results")
    if not isinstance(adapters, list) or not adapters:
        raise VerificationError("REP-02 adapter status boundary is absent")
    if {item.get("status") for item in adapters if isinstance(item, Mapping)} != {"NOT_RUN"}:
        raise VerificationError("offline validation incorrectly reported a live adapter execution")


def _negative_descriptor_case(
    python: Path,
    environment: Mapping[str, str],
    temporary_root: Path,
    case_id: str,
    descriptor: Mapping[str, Any],
    artifact_source: Path,
    mutate: Any,
    expected_code: str,
) -> dict[str, Any]:
    case_root = temporary_root / case_id
    artifact_target = case_root.joinpath(*ARTIFACT_RELATIVE_PATH.split("/"))
    artifact_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(artifact_source, artifact_target)
    value = copy.deepcopy(descriptor)
    mutate(value)
    value["input_hash"] = descriptor_input_hash(value)
    descriptor_path = case_root / DESCRIPTOR_FILE_NAME
    _write_json(descriptor_path, value)
    envelope = _call_rep02(python, descriptor_path, environment)
    result = envelope["result"]
    codes = _issue_codes(result)
    accepted = result.get("status") == "BLOCKED" and expected_code in codes
    if not accepted:
        raise VerificationError(
            f"negative case {case_id!r} did not block with {expected_code!r}: "
            f"status={result.get('status')!r}, codes={codes!r}"
        )
    return {
        "case_id": case_id,
        "expected_status": "BLOCKED",
        "observed_status": result.get("status"),
        "expected_reason_code": expected_code,
        "observed_reason_codes": codes,
        "accepted": True,
    }


def _malformed_json_case(
    python: Path,
    environment: Mapping[str, str],
    temporary_root: Path,
) -> dict[str, Any]:
    case_root = temporary_root / "malformed_json"
    case_root.mkdir(parents=True, exist_ok=True)
    descriptor_path = case_root / DESCRIPTOR_FILE_NAME
    _write_bytes(descriptor_path, b'{"api_version":')
    result = _call_rep02(python, descriptor_path, environment)["result"]
    codes = _issue_codes(result)
    accepted = result.get("status") == "BLOCKED" and "MALFORMED_JSON" in codes
    if not accepted:
        raise VerificationError("malformed descriptor did not produce BLOCKED/MALFORMED_JSON")
    return {
        "case_id": "malformed_json",
        "expected_status": "BLOCKED",
        "observed_status": result.get("status"),
        "expected_reason_code": "MALFORMED_JSON",
        "observed_reason_codes": codes,
        "accepted": True,
    }


def _local_guard_cases(
    report: Mapping[str, Any],
    wheel: Path,
    dependency: Mapping[str, Any],
    temporary_root: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    observed_variant_codes: list[str] = []
    for variant_id in ("A", "A+B"):
        wrong_variant = copy.deepcopy(report)
        wrong_variant["variant_id"] = variant_id
        try:
            validate_report_binding(wrong_variant)
        except HandoffValidationError as exc:
            if exc.code != "VARIANT_B_REQUIRED":
                raise VerificationError(
                    f"variant guard returned an unexpected code for {variant_id!r}"
                ) from exc
            observed_variant_codes.append(exc.code)
        else:
            raise VerificationError(
                f"variant {variant_id!r} was accepted by the INT-02A binding"
            )
    results.append(
        {
            "case_id": "variant_a_and_combined_profile",
            "tested_variant_ids": ["A", "A+B"],
            "expected_status": "BLOCKED",
            "observed_status": "BLOCKED",
            "expected_reason_code": "VARIANT_B_REQUIRED",
            "observed_reason_codes": sorted(set(observed_variant_codes)),
            "accepted": True,
        }
    )

    case_root = temporary_root / "wrong_wheel_sha256"
    case_root.mkdir(parents=True, exist_ok=True)
    corrupted_wheel = case_root / wheel.name
    corrupted_bytes = bytearray(wheel.read_bytes())
    if not corrupted_bytes:
        raise VerificationError("pinned wheel is unexpectedly empty")
    corrupted_bytes[-1] ^= 0x01
    _write_bytes(corrupted_wheel, bytes(corrupted_bytes))
    try:
        _verify_wheel(corrupted_wheel, dependency)
    except VerificationError as exc:
        accepted = str(exc).startswith("wheel SHA-256 mismatch:")
        if not accepted:
            raise VerificationError(
                "corrupted wheel was rejected for a reason other than SHA-256 mismatch"
            ) from exc
    else:
        raise VerificationError("corrupted wheel passed the pinned wheel gate")
    results.append(
        {
            "case_id": "wrong_wheel_sha256",
            "expected_status": "BLOCKED",
            "observed_status": "BLOCKED",
            "expected_reason_code": "WHEEL_SHA256_MISMATCH",
            "observed_reason_codes": ["WHEEL_SHA256_MISMATCH"],
            "accepted": True,
        }
    )
    return results


def _verification_record(
    wheel: Mapping[str, Any],
    handoff: Mapping[str, Any],
    positive: Mapping[str, Any],
    negative: Mapping[str, Any],
    repo03_head: str,
) -> str:
    cases = negative["cases"]
    case_rows = "\n".join(
        f"| `{item['case_id']}` | `{item['observed_status']}` | "
        f"`{item['expected_reason_code']}` | `PASS` |"
        for item in cases
    )
    return f"""# INT-02A REP-03 → REP-02 offline file-API doğrulama kaydı

## Sonuç

INT-02A, hash'i sabit REP-02 `0.5.0` wheel'i geçici bir ortama yalnız yerel
wheel kullanılarak (`--no-index --no-deps`) kurulmuş ve gerçek
`validate_file_api_file()` public
API'si üzerinden doğrulanmıştır.

- Genel sonuç: `PASS / REP02_FILE_API_EXACT_BYTES_VERIFIED`
- REP-03 taban commit'i: `{repo03_head}`
- Wheel: `{wheel['file_name']}`
- Wheel SHA-256: `{wheel['sha256']}`
- Artifact: `{ARTIFACT_RELATIVE_PATH}`
- Artifact boyutu: `{handoff['artifact_size_bytes']}` bayt
- Artifact SHA-256: `{handoff['artifact_sha256']}`
- Descriptor input hash: `{handoff['descriptor_input_hash']}`
- REP-02 sonucu: `{positive['status']} / {positive['reason_code']}`

## Kanıt sınırı

Bu `PASS` yalnız descriptor yapısı, pinlenmiş sözleşme provenance'ı ve dosyanın
exact-byte SHA-256 bütünlüğü içindir. REP-03 raporunun içindeki tarihsel D2
capability map hâlâ `integration_status=BLOCKED` ve `execution_status=NOT_RUN`
durumundadır. REP-02 `adapter_results` kayıtları da `NOT_RUN` kalır.

Kanıt; semantik güç eşlemesi, REP-02 rail-budget/sequencing motor yürütmesi,
canlı adaptör, gerçek Raspberry Pi kapanışı, fiziksel power-cut, OEM/ISO/AEC,
EMC, RF veya donanım uygunluğu iddiası değildir.

## Negatif doğrulamalar

| Vaka | Gözlenen durum | Zorunlu neden | Sonuç |
| --- | --- | --- | --- |
{case_rows}

## Yeniden üretim

Depo kökünden:

```powershell
python scripts/verify_int02a_wheel.py `
  --rep02-wheel ..\\power-rail-validation-and-review\\dist\\power_rail_validation-0.5.0-py3-none-any.whl
```

Normal REP-03 test paketi sibling repo veya REP-02 kurulumu gerektirmez. Gerçek
wheel kapısı ayrı çalışır ve wheel yoksa ya da hash uyuşmazsa başarıya düşmez.

## Provenance notu

Dependency kaydı mevcut wheel'in gerçek build kaydını (`b0a823e... + DIRTY`
yalnız `.gitattributes` değişikliği) korur. Güncel incelenen REP-02 kaynak tabanı
`000c884...` olarak ayrıca yazılmıştır; aynı committen yeniden build edilen
wheel'in byte-identical olacağı iddia edilmez. Kabul kimliği exact wheel
SHA-256'sıdır.
"""


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _assert_source_snapshot(snapshot: Mapping[Path, Mapping[str, Any]]) -> None:
    for path, expected in snapshot.items():
        if _file_record(path) != dict(expected):
            raise VerificationError(
                f"source changed during INT-02A verification: "
                f"{path.relative_to(REPO_ROOT).as_posix()}"
            )


def _manifest_inventory(
    paths: Iterable[Path],
    pinned_records: Optional[Mapping[Path, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    pinned = pinned_records or {}
    records = []
    for path in sorted(paths, key=lambda item: item.relative_to(REPO_ROOT).as_posix()):
        records.append(dict(pinned[path]) if path in pinned else _file_record(path))
    return records


def verify(wheel_path: Path, output_dir: Path, temporary_root: Path) -> dict[str, Any]:
    wheel_path = wheel_path.resolve(strict=False)
    output_dir = output_dir.resolve(strict=False)
    temporary_root = temporary_root.resolve(strict=False)
    resolved_repo_root = REPO_ROOT.resolve(strict=True)
    source_snapshot = {path: _file_record(path) for path in SOURCE_EVIDENCE_PATHS}
    dependency = dependency_contract()
    _assert_source_snapshot(source_snapshot)
    try:
        output_dir.relative_to(resolved_repo_root)
    except ValueError as exc:
        raise VerificationError(
            f"evidence output directory must be inside the REP-03 repository: {output_dir}"
        ) from exc
    repo03_head = _git_head()
    scenario = json.loads(
        SCENARIO_PATH.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_json_object,
        parse_constant=_reject_json_constant,
    )
    canonical_scenario = _canonical_json_bytes(scenario)
    scenario_record = {
        "path": SCENARIO_PATH.relative_to(REPO_ROOT).as_posix(),
        "identity": "CANONICAL_JSON_SHA256",
        "canonical_size_bytes": len(canonical_scenario),
        "canonical_sha256": _sha256_bytes(canonical_scenario),
    }
    if scenario_record["canonical_sha256"] != REPORT_INPUT_HASH:
        raise VerificationError(
            "nominal scenario canonical hash differs from the pinned report input hash"
        )
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="repo03-int02a-", dir=temporary_root) as temporary:
        scratch = Path(temporary)
        staged_handoff_root = scratch / "evidence" / "handoff"
        handoff = materialize_power_handoff(scenario, staged_handoff_root)
        if handoff["report_binding"]["input_hash"] != scenario_record["canonical_sha256"]:
            raise VerificationError(
                "REP-03 report input hash does not bind the canonical nominal scenario"
            )
        staged_wheel = scratch / "wheel" / wheel_path.name
        staged_wheel.parent.mkdir()
        shutil.copyfile(wheel_path, staged_wheel)
        wheel_record = _verify_wheel(staged_wheel, dependency)
        process_temp = scratch / "process-temp"
        process_temp.mkdir()
        environment = dict(os.environ)
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        for variable in ("TEMP", "TMP", "TMPDIR"):
            environment[variable] = str(process_temp)
        venv = scratch / "venv"
        _run(
            [sys.executable, "-m", "venv", str(venv)],
            environment=environment,
        )
        python = _venv_python(venv)
        _run(
            [
                str(python),
                "-I",
                "-B",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                str(staged_wheel.resolve()),
            ],
            environment=environment,
        )

        positive_envelope = _call_rep02(
            python,
            handoff["descriptor_path"],
            environment,
        )
        _verify_runtime(positive_envelope["runtime"], dependency)
        positive = positive_envelope["result"]
        _assert_positive(positive, handoff["artifact_sha256"])

        descriptor = handoff["descriptor"]
        artifact_source = handoff["artifact_path"]
        cases = [
            _negative_descriptor_case(
                python,
                environment,
                scratch,
                "artifact_hash_mismatch",
                descriptor,
                artifact_source,
                lambda value: value["configurations"][0]["artifacts"][0].update(
                    {"sha256": "0" * 64}
                ),
                "ARTIFACT_HASH_MISMATCH",
            ),
            _negative_descriptor_case(
                python,
                environment,
                scratch,
                "missing_artifact",
                descriptor,
                artifact_source,
                lambda value: value["configurations"][0]["artifacts"][0].update(
                    {"file_name": "artifacts/missing.report.json"}
                ),
                "ARTIFACT_FILE_MISSING",
            ),
            _negative_descriptor_case(
                python,
                environment,
                scratch,
                "api_version_mismatch",
                descriptor,
                artifact_source,
                lambda value: value.update({"api_version": "2.0.0"}),
                "API_VERSION_INCOMPATIBLE",
            ),
            _negative_descriptor_case(
                python,
                environment,
                scratch,
                "endpoint_version_mismatch",
                descriptor,
                artifact_source,
                lambda value: value["producer"].update({"api_version": "2.0.0"}),
                "ENDPOINT_API_VERSION_INCOMPATIBLE",
            ),
            _negative_descriptor_case(
                python,
                environment,
                scratch,
                "path_traversal",
                descriptor,
                artifact_source,
                lambda value: value["configurations"][0]["artifacts"][0].update(
                    {"file_name": "../outside.json"}
                ),
                "PATH_TRAVERSAL_BLOCKED",
            ),
            _malformed_json_case(python, environment, scratch),
        ]
        cases.extend(
            _local_guard_cases(
                handoff["report"],
                staged_wheel,
                dependency,
                scratch,
            )
        )
        artifact_bytes = handoff["artifact_path"].read_bytes()
        descriptor_bytes = handoff["descriptor_path"].read_bytes()

    handoff_root = output_dir / "handoff"
    artifact_path = handoff_root.joinpath(*ARTIFACT_RELATIVE_PATH.split("/"))
    descriptor_path = handoff_root / DESCRIPTOR_FILE_NAME

    negative_results = {
        "schema_version": "repo03.int02a.negative-results.v1",
        "integration_id": "INT-02A",
        "status": "PASS",
        "reason_code": "ALL_FAIL_CLOSED_GUARDS_CONFIRMED",
        "case_count": len(cases),
        "cases": cases,
    }

    verification_result = {
        "schema_version": "repo03.int02a.verification-result.v1",
        "integration_id": "INT-02A",
        "status": "PASS",
        "reason_code": "REP02_FILE_API_EXACT_BYTES_VERIFIED",
        "scope": "OFFLINE_FILE_INTEGRITY_ONLY",
        "repo03": {
            "base_commit": repo03_head,
            "source_state": "UNCOMMITTED_INT02A_WORKTREE",
        },
        "dependency_contract": {
            "path": DEPENDENCY_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": source_snapshot[DEPENDENCY_PATH]["sha256"],
        },
        "scenario": scenario_record,
        "wheel": wheel_record,
        "installed_runtime": positive_envelope["runtime"],
        "handoff": {
            "artifact_path": artifact_path.relative_to(REPO_ROOT).as_posix(),
            "artifact_size_bytes": handoff["artifact_size_bytes"],
            "artifact_sha256": handoff["artifact_sha256"],
            "descriptor_path": descriptor_path.relative_to(REPO_ROOT).as_posix(),
            "descriptor_input_hash": handoff["descriptor_input_hash"],
            "embedded_d2_integration_status": handoff["report_binding"][
                "embedded_d2_integration_status"
            ],
            "embedded_d2_execution_status": handoff["report_binding"][
                "embedded_d2_execution_status"
            ],
        },
        "rep02_validation": positive,
        "claim_boundary": {
            "descriptor_and_exact_bytes": True,
            "semantic_power_mapping": False,
            "live_adapter_execution": False,
            "rep02_power_engine_execution": False,
            "physical_or_compliance_validation": False,
        },
    }

    _assert_source_snapshot(source_snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.resolve(strict=True) != output_dir:
        raise VerificationError(
            f"evidence output directory changed after path validation: {output_dir}"
        )
    for stale_marker in (output_dir / "manifest.json.sha256", output_dir / "manifest.json"):
        stale_marker.unlink(missing_ok=True)
    _publish_bytes(output_dir, artifact_path, artifact_bytes)
    _publish_bytes(output_dir, descriptor_path, descriptor_bytes)
    verification_path = output_dir / "verification-result.json"
    negative_path = output_dir / "negative-results.json"
    record_path = output_dir / "verification-record.md"
    _publish_bytes(output_dir, verification_path, _json_bytes(verification_result))
    _publish_bytes(output_dir, negative_path, _json_bytes(negative_results))
    record_text = _verification_record(
        wheel_record,
        handoff,
        positive,
        negative_results,
        repo03_head,
    )
    _publish_bytes(output_dir, record_path, record_text.encode("utf-8"))

    inventory_paths = [
        artifact_path,
        descriptor_path,
        verification_path,
        negative_path,
        record_path,
        *SOURCE_EVIDENCE_PATHS,
    ]
    manifest = {
        "schema_version": "repo03.int02a.manifest.v1",
        "integration_id": "INT-02A",
        "status": "PASS",
        "reason_code": "INT02A_ACCEPTANCE_EVIDENCE_COMPLETE",
        "repo03_base_commit": repo03_head,
        "source_state": "UNCOMMITTED_INT02A_WORKTREE",
        "wheel_sha256": wheel_record["sha256"],
        "scenario": scenario_record,
        "descriptor_input_hash": handoff["descriptor_input_hash"],
        "artifact_sha256": handoff["artifact_sha256"],
        "negative_case_count": len(cases),
        "files": _manifest_inventory(inventory_paths, source_snapshot),
        "claim_limits": list(dependency["claim_limits"]),
    }
    manifest_path = output_dir / "manifest.json"
    _publish_bytes(output_dir, manifest_path, _json_bytes(manifest))
    manifest_hash = _sha256(manifest_path)
    checksum_path = output_dir / "manifest.json.sha256"
    _publish_bytes(
        output_dir,
        checksum_path,
        f"{manifest_hash} *manifest.json\n".encode("ascii"),
    )

    return {
        "status": "PASS",
        "reason_code": "INT02A_ACCEPTANCE_EVIDENCE_COMPLETE",
        "artifact_sha256": handoff["artifact_sha256"],
        "descriptor_input_hash": handoff["descriptor_input_hash"],
        "manifest_sha256": manifest_hash,
        "negative_case_count": len(cases),
        "evidence_dir": output_dir.relative_to(REPO_ROOT).as_posix(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify INT-02A using an exact, local REP-02 wheel."
    )
    parser.add_argument(
        "--rep02-wheel",
        type=Path,
        required=True,
        help="path to the pinned REP-02 0.5.0 wheel",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "evidence" / "INT-02A",
        help="evidence destination (default: evidence/INT-02A)",
    )
    parser.add_argument(
        "--temporary-root",
        type=Path,
        default=DEFAULT_TEMPORARY_ROOT,
        help="temporary venv parent; each per-run child is removed",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify(
            args.rep02_wheel.resolve(),
            args.output_dir.resolve(),
            args.temporary_root.resolve(),
        )
    except (HandoffValidationError, VerificationError, OSError, ValueError) as exc:
        sys.stderr.write(f"INT-02A verification failed: {exc}\n")
        return 3
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

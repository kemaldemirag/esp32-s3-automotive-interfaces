"""Standard-library command-line interface for REP-03 synthetic validators."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Sequence, TextIO

from repo03_can import run_scenario as run_can
from repo03_contract import validate_profile
from repo03_gnss import run_scenario as run_gnss
from repo03_lin import run_scenario as run_lin
from repo03_power import run_scenario as run_automotive_power
from repo03_shutdown import run_scenario as run_shutdown

from . import __version__
from .report import build_report


EXIT_BY_STATUS = {
    "PASS": 0,
    "FAIL": 10,
    "UNKNOWN": 11,
    "BLOCKED": 12,
    "NOT_RUN": 13,
}
EX_USAGE = 64
EX_DATAERR = 65
EX_NOINPUT = 66
EX_SOFTWARE = 70
EX_CANTCREAT = 73

_ENGINE_COMMANDS: dict[
    str, tuple[str, Callable[[Any], dict[str, Any]]]
] = {
    "can": ("A", run_can),
    "lin": ("A", run_lin),
    "gnss": ("A", run_gnss),
    "automotive-power": ("B", run_automotive_power),
    "shutdown": ("B", run_shutdown),
}
_REPORT_MODULE_FLAGS = {
    "can": "can",
    "lin": "lin",
    "gnss": "gnss",
    "automotive_power": "automotive-power",
    "shutdown": "shutdown",
}
_REPORT_MODULES_BY_VARIANT = {
    "A": ("can", "lin", "gnss"),
    "B": ("automotive_power", "shutdown"),
}


class _CliError(Exception):
    exit_code = EX_SOFTWARE


class _UsageError(_CliError):
    exit_code = EX_USAGE


class _MalformedJsonError(_CliError):
    exit_code = EX_DATAERR


class _InputError(_CliError):
    exit_code = EX_NOINPUT


class _OutputError(_CliError):
    exit_code = EX_CANTCREAT


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="repo03",
        description="REP-03 deterministic synthetic validation tools",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a variant profile")
    validate.add_argument("--variant", choices=("A", "B"), required=True)
    validate.add_argument("input", help="profile JSON path, or '-' for stdin")
    validate.add_argument("--output", help="output JSON path, or '-' for stdout")

    for command in _ENGINE_COMMANDS:
        engine = subparsers.add_parser(command, help=f"run the {command} engine")
        engine.add_argument("--variant", choices=("A", "B"), required=True)
        engine.add_argument("input", help="scenario JSON path, or '-' for stdin")
        engine.add_argument("--output", help="output JSON path, or '-' for stdout")

    report = subparsers.add_parser(
        "report", help="run a complete, isolated variant report"
    )
    report.add_argument("--variant", choices=("A", "B"), required=True)
    report.add_argument("--profile", help="variant profile JSON path")
    report.add_argument("--can", help="CAN scenario JSON path")
    report.add_argument("--lin", help="LIN scenario JSON path")
    report.add_argument("--gnss", help="GNSS scenario JSON path")
    report.add_argument(
        "--automotive-power",
        dest="automotive_power",
        help="automotive-power scenario JSON path",
    )
    report.add_argument("--shutdown", help="shutdown scenario JSON path")
    report.add_argument("--output", help="output JSON path, or '-' for stdout")
    return parser


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _MalformedJsonError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise _MalformedJsonError(f"non-finite number is not permitted: {value}")


def _require_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise _MalformedJsonError("non-finite number is not permitted")
    if isinstance(value, dict):
        for nested in value.values():
            _require_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _require_finite(nested)


def _stdin_text() -> str:
    try:
        stream = getattr(sys.stdin, "buffer", None)
        if stream is not None:
            return stream.read().decode("utf-8", errors="strict")
        return sys.stdin.read()
    except UnicodeDecodeError as exc:
        raise _MalformedJsonError("stdin is not valid UTF-8") from exc
    except OSError as exc:
        raise _InputError(f"cannot read stdin: {exc}") from exc


def _load_object(path_text: str) -> dict[str, Any]:
    if path_text == "-":
        text = _stdin_text()
        label = "stdin"
    else:
        path = Path(path_text)
        label = str(path)
        try:
            text = path.read_bytes().decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _MalformedJsonError(f"{label} is not valid UTF-8") from exc
        except OSError as exc:
            raise _InputError(f"cannot read {label}: {exc}") from exc

    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except _MalformedJsonError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise _MalformedJsonError(f"malformed JSON in {label}: {exc}") from exc
    _require_finite(value)
    if not isinstance(value, dict):
        raise _MalformedJsonError(f"JSON root in {label} must be an object")
    return value


def _require_payload_variant(
    value: dict[str, Any], variant_id: str, label: str
) -> None:
    if value.get("variant_id") != variant_id:
        raise _UsageError(f"{label} variant_id must match --variant {variant_id}")


def _canonical_line(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise RuntimeError("report is not canonical JSON serializable") from exc


def _write_stdout(data: bytes) -> None:
    try:
        stream = getattr(sys.stdout, "buffer", None)
        if stream is not None:
            stream.write(data)
            stream.flush()
        else:
            sys.stdout.write(data.decode("utf-8"))
            sys.stdout.flush()
    except (OSError, UnicodeError) as exc:
        raise _OutputError(f"cannot write stdout: {exc}") from exc


def _write_output(value: Any, output: str | None) -> None:
    data = _canonical_line(value)
    if output in (None, "-"):
        _write_stdout(data)
        return

    target = Path(output)
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    except OSError as exc:
        raise _OutputError(f"cannot write {target}: {exc}") from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _run_report(arguments: argparse.Namespace) -> dict[str, Any]:
    expected = _REPORT_MODULES_BY_VARIANT[arguments.variant]
    forbidden = tuple(
        name
        for name in _REPORT_MODULE_FLAGS
        if name not in expected
    )
    missing = ["profile"] if arguments.profile is None else []
    missing.extend(name for name in expected if getattr(arguments, name) is None)
    supplied_forbidden = [
        name for name in forbidden if getattr(arguments, name) is not None
    ]
    if missing:
        flags = ", ".join(
            f"--{_REPORT_MODULE_FLAGS.get(name, name)}" for name in missing
        )
        raise _UsageError(
            f"variant {arguments.variant} report requires: {flags}"
        )
    if supplied_forbidden:
        flags = ", ".join(
            f"--{_REPORT_MODULE_FLAGS[name]}" for name in supplied_forbidden
        )
        raise _UsageError(
            f"variant {arguments.variant} report forbids: {flags}"
        )

    paths = [arguments.profile, *(getattr(arguments, name) for name in expected)]
    if paths.count("-") > 1:
        raise _UsageError("stdin '-' may be used for only one report input")

    profile = _load_object(arguments.profile)
    _require_payload_variant(profile, arguments.variant, "profile")
    modules: dict[str, dict[str, Any]] = {}
    for module_name in expected:
        module_input = _load_object(getattr(arguments, module_name))
        _require_payload_variant(module_input, arguments.variant, module_name)
        modules[module_name] = module_input
    return build_report(arguments.variant, profile, modules)


def _dispatch(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.command == "validate":
        profile = _load_object(arguments.input)
        _require_payload_variant(profile, arguments.variant, "profile")
        return validate_profile(profile)
    if arguments.command == "report":
        return _run_report(arguments)

    required_variant, runner = _ENGINE_COMMANDS[arguments.command]
    if arguments.variant != required_variant:
        raise _UsageError(
            f"{arguments.command} requires --variant {required_variant}"
        )
    scenario = _load_object(arguments.input)
    _require_payload_variant(scenario, arguments.variant, arguments.command)
    return runner(scenario)


def _write_error(message: str, stream: TextIO) -> None:
    try:
        stream.write(f"repo03: error: {message}\n")
        stream.flush()
    except (OSError, UnicodeError):
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its documented process exit code."""

    try:
        try:
            arguments = _parser().parse_args(argv)
        except SystemExit as exc:
            return int(exc.code or 0)
        report = _dispatch(arguments)
        status = report.get("status")
        if not isinstance(status, str) or status not in EXIT_BY_STATUS:
            raise RuntimeError("validator returned an unsupported status")
        _write_output(report, arguments.output)
        return EXIT_BY_STATUS[status]
    except _CliError as exc:
        _write_error(str(exc), sys.stderr)
        return exc.exit_code
    except Exception as exc:
        _write_error(f"internal error: {exc}", sys.stderr)
        return EX_SOFTWARE


if __name__ == "__main__":
    raise SystemExit(main())

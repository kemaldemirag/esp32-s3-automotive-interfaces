"""REP-03 cross-repository integration boundaries.

INT-02A materializes one synthetic Variant B automotive-power report as an
offline REP-02 file-API handoff.  It does not execute a live adapter, a REP-02
power engine, or physical hardware.
"""

from .rep02_file_api import (
    ARTIFACT_RELATIVE_PATH,
    DESCRIPTOR_FILE_NAME,
    HandoffValidationError,
    REPORT_ARTIFACT_SHA256,
    REPORT_INPUT_HASH,
    build_descriptor,
    canonical_report_bytes,
    dependency_contract,
    descriptor_input_hash,
    materialize_power_handoff,
    validate_report_binding,
)

__all__ = [
    "ARTIFACT_RELATIVE_PATH",
    "DESCRIPTOR_FILE_NAME",
    "HandoffValidationError",
    "REPORT_ARTIFACT_SHA256",
    "REPORT_INPUT_HASH",
    "build_descriptor",
    "canonical_report_bytes",
    "dependency_contract",
    "descriptor_input_hash",
    "materialize_power_handoff",
    "validate_report_binding",
]

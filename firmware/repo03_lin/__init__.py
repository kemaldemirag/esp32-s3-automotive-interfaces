"""Synthetic LIN state-machine tooling for REP-03 Variant A.

The package models deterministic events only.  It does not access a UART,
control a LIN transceiver, observe a physical bus, or provide hardware evidence.
"""

from .engine import (
    APPROVED_VARIANT_A_PROFILE_HASH,
    ENGINE_ID,
    MODULE_ID,
    SCHEMA_VERSION,
    TOOL_VERSION,
    VARIANT_CONTRACT_SCHEMA,
    normalized_input_hash,
    run_scenario,
)

__all__ = [
    "SCHEMA_VERSION",
    "TOOL_VERSION",
    "ENGINE_ID",
    "MODULE_ID",
    "VARIANT_CONTRACT_SCHEMA",
    "APPROVED_VARIANT_A_PROFILE_HASH",
    "normalized_input_hash",
    "run_scenario",
]

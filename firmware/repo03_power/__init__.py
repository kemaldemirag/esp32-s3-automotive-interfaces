"""Synthetic automotive-power profile contracts for REP-03 Variant B.

The package validates versioned scenario metadata and a file-only REP-02
adapter envelope.  It does not model a regulator, choose a component, execute
REP-02, or make a physical/OEM compliance claim.
"""

from .engine import (
    APPROVED_VARIANT_B_PROFILE_HASH,
    ENGINE_ID,
    MODULE_ID,
    REP02_ADAPTER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TOOL_VERSION,
    VARIANT_CONTRACT_SCHEMA,
    normalized_input_hash,
    rep02_adapter_profile_hash,
    run_scenario,
)

__all__ = [
    "APPROVED_VARIANT_B_PROFILE_HASH",
    "ENGINE_ID",
    "MODULE_ID",
    "REP02_ADAPTER_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "TOOL_VERSION",
    "VARIANT_CONTRACT_SCHEMA",
    "normalized_input_hash",
    "rep02_adapter_profile_hash",
    "run_scenario",
]

"""REP-03 Variant A synthetic GNSS validation package.

The package validates deterministic test vectors only.  It does not operate a
GNSS receiver, inspect an antenna/RF path, or turn coordinates into measured
evidence.
"""

from .validator import (
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

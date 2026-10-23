"""Synthetic ignition-shutdown contract for REP-03 Variant B.

The package exposes a deterministic state machine.  It never sends a host
notification, shuts down an operating system, or controls physical power.
"""

from .engine import (
    APPROVED_VARIANT_B_PROFILE_HASH,
    ENGINE_ID,
    EVENTS,
    MODULE_ID,
    SCHEMA_VERSION,
    STATES,
    TOOL_VERSION,
    VARIANT_CONTRACT_SCHEMA,
    ShutdownStateMachine,
    normalized_input_hash,
    run_scenario,
)

__all__ = [
    "APPROVED_VARIANT_B_PROFILE_HASH",
    "ENGINE_ID",
    "EVENTS",
    "MODULE_ID",
    "SCHEMA_VERSION",
    "STATES",
    "TOOL_VERSION",
    "VARIANT_CONTRACT_SCHEMA",
    "ShutdownStateMachine",
    "normalized_input_hash",
    "run_scenario",
]

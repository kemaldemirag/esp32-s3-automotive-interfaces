"""Synthetic CAN/TWAI scenario engine for REP-03 Variant A."""

from .engine import (
    SCHEMA_VERSION,
    TOOL_VERSION,
    run_scenario,
    scenario_input_hash,
)

__all__ = [
    "SCHEMA_VERSION",
    "TOOL_VERSION",
    "run_scenario",
    "scenario_input_hash",
]

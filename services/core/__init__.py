"""Deterministic feasibility core for ADU Atlas.

Everything in this package is deterministic and free of any LLM call. Network
access is confined to injected seams (the geocoder client and the Postgres
repository); the analytical logic itself - address normalization, compliance
evaluation, envelope math, and feasibility-status selection - is pure and
unit-testable.
"""

from .constants import (
    ANALYSIS_VERSION,
    DISCLAIMER,
    RULES_VERSION,
    STATE_BASELINE_VERSION,
)

__all__ = [
    "ANALYSIS_VERSION",
    "RULES_VERSION",
    "STATE_BASELINE_VERSION",
    "DISCLAIMER",
]

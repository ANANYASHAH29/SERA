"""Central registry of the six condition modules.

Everything downstream (diff classification, ranking, experiment runner)
goes through this registry instead of importing individual `inject_*`
modules directly, so adding a new condition means registering it here once.
"""
from __future__ import annotations

from sera.conditions import (
    inject_d1_covariate_shift,
    inject_f1_resize,
    inject_f2_channel_swap,
    inject_f3_normalization,
    inject_f4_corruption,
    inject_f5_checkpoint,
)

CONFIG_CONDITIONS = {
    "F1": inject_f1_resize,
    "F2": inject_f2_channel_swap,
    "F3": inject_f3_normalization,
    "F4": inject_f4_corruption,
    "F5": inject_f5_checkpoint,
}

DRIFT_CONDITION = inject_d1_covariate_shift

ALL_CATEGORIES = ["F1", "F2", "F3", "F4", "F5", "D1"]

DRIFT_LABEL = "D1"
NO_COMMIT_CANDIDATE_ID = "__no_commit_drift__"


def risk_patterns_for(category: str) -> list:
    if category == DRIFT_LABEL:
        return list(DRIFT_CONDITION.RISK_FILE_PATTERNS)
    return list(CONFIG_CONDITIONS[category].RISK_FILE_PATTERNS)


def all_risk_patterns() -> dict:
    """category -> list[pattern], excluding D1 (which has none by design)."""
    return {cat: mod.RISK_FILE_PATTERNS for cat, mod in CONFIG_CONDITIONS.items()}


# Fields on PipelineConfig that each F-condition's `apply()` touches. Used by
# the validator to know which single field to revert when testing a
# candidate commit's hypothesis.
CONDITION_FIELDS = {
    "F1": ["resize_dim"],
    "F2": ["channel_order"],
    "F3": ["norm_mean", "norm_std"],
    "F4": ["corruption_filter_enabled", "corruption_injection_rate", "corruption_injection_severity"],
    "F5": ["checkpoint_name"],
}

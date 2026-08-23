"""F3: normalization mean/std drifted.

Simulates a commit that edits the normalization constants (e.g. someone
copy-pasted ImageNet stats over CIFAR-10 stats, or a unit conversion bug).
Shifts and rescales every pixel's normalized value, causing a broad
confidence collapse across the whole canary set.
"""
from __future__ import annotations

from dataclasses import replace

from sera.config import PipelineConfig

CATEGORY = "F3"
RISK_FILE_PATTERNS = [
    "preprocessing_config",
    "normalization_config",
    "mean_std_config",
]
DESCRIPTION = "normalization mean/std drifted from the values the model was trained with"


def apply(config: PipelineConfig, severity: float = 0.6) -> PipelineConfig:
    """severity in [0, 1]: magnitude of the mean shift / std rescale."""
    severity = max(0.0, min(1.0, severity))
    mean_shift = 0.35 * severity
    std_scale = 1.0 + 1.5 * severity
    new_mean = tuple(m + mean_shift for m in config.norm_mean)
    new_std = tuple(s * std_scale for s in config.norm_std)
    return replace(config, norm_mean=new_mean, norm_std=new_std)

"""F4: corrupted/noisy images injected above threshold.

Simulates a commit that breaks (or disables) the ingestion data-quality
filter, letting a *subset* of already-corrupted images leak into the
canary batch. Unlike F2/F3, only a fraction of images are affected, so the
symptom is a spike concentrated in a subset rather than a broad shift.
"""
from __future__ import annotations

from dataclasses import replace

from sera.config import PipelineConfig

CATEGORY = "F4"
RISK_FILE_PATTERNS = [
    "ingestion_validation",
    "data_quality_filter",
    "corruption_filter",
    "ingestion_config",
]
DESCRIPTION = "data-quality filter disabled/broken, corrupted images leaked into the batch"


def apply(config: PipelineConfig, rate: float = 0.3, severity: float = 0.8) -> PipelineConfig:
    return replace(
        config,
        corruption_filter_enabled=False,
        corruption_injection_rate=rate,
        corruption_injection_severity=severity,
    )

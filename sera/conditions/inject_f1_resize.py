"""F1: resize dimension changed.

Simulates a commit that edits a resize config constant, e.g.
`resize_config.yaml: resize_dim: 32 -> 12`. Causes a lossy down/up-sample
round trip that shifts every image away from the scale the model was
trained at. Empirically this hits images unevenly (some survive the round
trip fine, others don't), so its shape signature is concentrated rather
than broad -- see scripts/calibrate_templates.py.

Deliberately does NOT include the generic "preprocessing_config" pattern
here -- that one is F3's (normalization constants), and a real codebase
would plausibly keep resize dimensions in their own file. Sharing a
pattern between two categories would make a single commit ambiguously
match both, which defeats the point of risk-category classification.
"""
from __future__ import annotations

from dataclasses import replace

from sera.config import PipelineConfig

CATEGORY = "F1"
RISK_FILE_PATTERNS = [
    "resize_config",
    "transform_config",
    "image_pipeline_config",
]
DESCRIPTION = "resize dimension changed away from the model's native input scale"


def apply(config: PipelineConfig, severity: float = 0.6) -> PipelineConfig:
    """severity in [0, 1]: how far the resize dim is pushed away from 32x32."""
    severity = max(0.0, min(1.0, severity))
    bad_dim = max(6, round(32 - severity * 24))
    return replace(config, resize_dim=(bad_dim, bad_dim))

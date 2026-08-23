"""F5: wrong model checkpoint loaded.

Simulates a commit that changes which checkpoint file/tag the inference
stage points at (e.g. a model-registry pointer rollback), swapping in a
stale, undertrained checkpoint of the same architecture.
"""
from __future__ import annotations

from dataclasses import replace

from sera.config import PipelineConfig

CATEGORY = "F5"
RISK_FILE_PATTERNS = [
    "model_config",
    "checkpoint",
    "model_registry",
    ".ckpt",
]
DESCRIPTION = "wrong/stale model checkpoint loaded at inference time"

WRONG_CHECKPOINT_NAME = "resnet18_cifar10_stale"  # rollback target for the F5 demo commit


def apply(config: PipelineConfig, severity: float = 1.0) -> PipelineConfig:
    """severity is unused (checkpoint choice is discrete) but kept for API symmetry."""
    return replace(config, checkpoint_name=WRONG_CHECKPOINT_NAME)

"""Central configuration objects for the SERA pipeline.

`PipelineConfig` captures every knob that a real commit could plausibly
change (resize dimension, channel order, normalization stats, checkpoint
choice, ingestion corruption filtering). It is deliberately a plain,
serializable dataclass so that "reverting a candidate's change" can be
expressed as "swap one field back to the baseline value".

Genuine covariate shift (D1) is intentionally NOT a field on this class:
it is applied directly to raw canary images by the caller, independent of
any pipeline configuration, so no commit / config diff can ever explain it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

CIFAR10_MEAN: Tuple[float, float, float] = (0.4914, 0.4822, 0.4465)
CIFAR10_STD: Tuple[float, float, float] = (0.2470, 0.2435, 0.2616)

DEFAULT_RESIZE_DIM: Tuple[int, int] = (32, 32)
DEFAULT_CHECKPOINT_NAME = "resnet18_cifar10"

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = REPO_ROOT / "checkpoints"
DATA_DIR = REPO_ROOT / "data"
CANARY_DIR = REPO_ROOT / "canary"
RESULTS_DIR = REPO_ROOT / "results"
DB_PATH = REPO_ROOT / "sera_state.db"

CANARY_SIZE = 200
CANARY_SEED = 1234  # fixed so the canary set is stable across runs


@dataclass(frozen=True)
class PipelineConfig:
    """Everything about the pipeline that a commit could change."""

    resize_dim: Tuple[int, int] = DEFAULT_RESIZE_DIM
    norm_mean: Tuple[float, float, float] = CIFAR10_MEAN
    norm_std: Tuple[float, float, float] = CIFAR10_STD
    channel_order: str = "rgb"  # "rgb" or "bgr"
    checkpoint_name: str = DEFAULT_CHECKPOINT_NAME

    # F4: a data-quality filter that is supposed to reject corrupted
    # images at ingestion time. When disabled/broken, noisy images leak
    # into the canary batch.
    corruption_filter_enabled: bool = True
    corruption_injection_rate: float = 0.0  # fraction of images corrupted
    corruption_injection_severity: float = 0.0  # 0..1

    def field_dict(self) -> dict:
        return {
            "resize_dim": list(self.resize_dim),
            "norm_mean": list(self.norm_mean),
            "norm_std": list(self.norm_std),
            "channel_order": self.channel_order,
            "checkpoint_name": self.checkpoint_name,
            "corruption_filter_enabled": self.corruption_filter_enabled,
            "corruption_injection_rate": self.corruption_injection_rate,
            "corruption_injection_severity": self.corruption_injection_severity,
        }


def baseline_config() -> PipelineConfig:
    return PipelineConfig()

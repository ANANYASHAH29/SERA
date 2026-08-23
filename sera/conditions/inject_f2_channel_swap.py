"""F2: RGB/BGR channel order swapped.

Simulates a commit that introduces a cv2.imread/PIL mismatch (or an
accidental `img[..., ::-1]`) in the input-prep stage. Every image is
affected identically and severely, since color statistics leave the
distribution the model was trained on entirely.
"""
from __future__ import annotations

from dataclasses import replace

from sera.config import PipelineConfig

CATEGORY = "F2"
RISK_FILE_PATTERNS = [
    "input_prep",
    "channel_order",
    "color_convert",
    "image_loader",
]
DESCRIPTION = "RGB/BGR channel order swapped before the model sees the image"


def apply(config: PipelineConfig, severity: float = 1.0) -> PipelineConfig:
    """severity is unused (swap is binary) but kept for a uniform condition API."""
    return replace(config, channel_order="bgr")

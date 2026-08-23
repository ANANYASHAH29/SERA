"""Stage 3: input preparation (channel order + tensor conversion).

Converts normalized (N,H,W,3) float32 arrays into (N,3,H,W) torch tensors
ready for the model. F2 (RGB/BGR channel swap) lives here: if
`config.channel_order == "bgr"`, channels are reversed right before the
model sees them, exactly like a cv2.imread/PIL mismatch bug would do.
"""
from __future__ import annotations

import numpy as np
import torch

from sera.config import PipelineConfig


def to_tensor(images: np.ndarray, config: PipelineConfig) -> torch.Tensor:
    """images: (N,H,W,3) float32, channel order currently RGB."""
    if config.channel_order == "bgr":
        images = images[..., ::-1].copy()
    elif config.channel_order != "rgb":
        raise ValueError(f"unknown channel_order {config.channel_order!r}")

    chw = np.transpose(images, (0, 3, 1, 2)).copy()  # (N,3,H,W)
    return torch.from_numpy(chw).float()

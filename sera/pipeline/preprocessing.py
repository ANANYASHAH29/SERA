"""Stage 2: preprocessing (resize + normalize).

Resizes raw uint8 HWC images to `config.resize_dim` and normalizes to
float32 using `config.norm_mean` / `config.norm_std`. Output is still HWC,
float32, in [approximately] the model's expected input distribution.

F1 (resize dimension changed) and F3 (normalization mean/std drift) are
both expressed purely through `PipelineConfig` fields consumed here — no
special-casing, so "reverting F1/F3" is just restoring these fields.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from sera.config import PipelineConfig


def resize_batch(images: np.ndarray, resize_dim: tuple) -> np.ndarray:
    """Resize (N,H,W,3) uint8 images to resize_dim, then back to the model's
    native 32x32 input grid via bilinear interpolation. This mirrors a real
    pipeline bug: a resize stage configured for the wrong target size still
    ultimately has to feed a fixed-size tensor to the model, so the image
    goes through a lossy down/up-sample round trip at the wrong scale.
    """
    target_h, target_w = resize_dim
    out = np.empty((len(images), 32, 32, 3), dtype=np.uint8)
    for i, img in enumerate(images):
        resized = Image.fromarray(img).resize((target_w, target_h), Image.BILINEAR)
        if (target_h, target_w) != (32, 32):
            resized = resized.resize((32, 32), Image.BILINEAR)
        out[i] = np.array(resized)
    return out


def normalize_batch(images: np.ndarray, mean: tuple, std: tuple) -> np.ndarray:
    """images: (N,H,W,3) uint8 -> (N,H,W,3) float32 normalized."""
    arr = images.astype(np.float32) / 255.0
    mean_arr = np.array(mean, dtype=np.float32).reshape(1, 1, 1, 3)
    std_arr = np.array(std, dtype=np.float32).reshape(1, 1, 1, 3)
    return (arr - mean_arr) / std_arr


def preprocess_batch(images: np.ndarray, config: PipelineConfig) -> np.ndarray:
    resized = resize_batch(images, config.resize_dim)
    return normalize_batch(resized, config.norm_mean, config.norm_std)

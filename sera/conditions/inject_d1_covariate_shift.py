"""D1: genuine covariate shift via real image corruptions.

Applies simplified versions of the classic "common corruptions" (fog,
motion blur, Gaussian noise) directly to the raw canary images. This is
the one condition with NO risk-file mapping and NO PipelineConfig field:
it represents the world changing while the pipeline code stays untouched,
so no commit diff can ever explain it and RISK_FILE_PATTERNS is empty.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d

CATEGORY = "D1"
RISK_FILE_PATTERNS: list = []  # intentionally empty: no commit can cause drift
DESCRIPTION = "genuine covariate shift (fog / motion blur / sensor noise), no code change"

ALL_CORRUPTIONS = ("fog", "motion_blur", "gaussian_noise")


def _gaussian_noise(img: np.ndarray, severity: float, rng: np.random.RandomState) -> np.ndarray:
    noise = rng.normal(0, 40 * severity, size=img.shape)
    return np.clip(img.astype(np.float32) + noise, 0, 255)


def _motion_blur(img: np.ndarray, severity: float) -> np.ndarray:
    kernel_size = max(1, int(round(3 + severity * 12)))
    blurred = uniform_filter1d(img.astype(np.float32), size=kernel_size, axis=1, mode="nearest")
    return blurred


def _fog(img: np.ndarray, severity: float, rng: np.random.RandomState) -> np.ndarray:
    h, w = img.shape[:2]
    small = rng.rand(max(2, h // 8), max(2, w // 8))
    from PIL import Image

    fog_map = np.array(
        Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    ).astype(np.float32)
    fog_map = (fog_map - fog_map.min()) / (fog_map.max() - fog_map.min() + 1e-6)
    alpha = 0.75 * severity
    fog_color = 240.0
    fogged = img.astype(np.float32) * (1 - alpha) + (
        fog_color * (0.6 + 0.4 * fog_map[..., None])
    ) * alpha
    return fogged


def apply_to_images(
    images: np.ndarray,
    severity: float = 0.6,
    corruption_types=ALL_CORRUPTIONS,
    fraction: float = 1.0,
    seed: int = 777,
) -> np.ndarray:
    """images: (N,H,W,3) uint8. Applies one randomly-chosen corruption type
    (from `corruption_types`) per affected image. `fraction` controls how
    much of the canary set the drift has reached (1.0 = the whole world
    has shifted; <1.0 models a partial/gradual rollout of the shift).
    """
    severity = max(0.0, min(1.0, severity))
    rng = np.random.RandomState(seed)
    n = len(images)
    n_affected = int(round(fraction * n))
    affected_idx = set(rng.choice(n, size=n_affected, replace=False)) if n_affected else set()

    out = images.copy()
    for i in range(n):
        if i not in affected_idx:
            continue
        kind = corruption_types[rng.randint(len(corruption_types))]
        img = images[i]
        if kind == "gaussian_noise":
            result = _gaussian_noise(img, severity, rng)
        elif kind == "motion_blur":
            result = _motion_blur(img, severity)
        elif kind == "fog":
            result = _fog(img, severity, rng)
        else:
            raise ValueError(f"unknown corruption type {kind!r}")
        out[i] = np.clip(result, 0, 255).astype(np.uint8)
    return out

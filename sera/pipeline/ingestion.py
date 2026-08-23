"""Stage 1: ingestion & validation.

Loads the fixed 200-image canary set drawn from the CIFAR-10 test split,
validates shapes/dtypes, and (optionally) applies a data-quality-filter
failure (F4) that lets corrupted images leak through.

Images are returned as uint8 HWC RGB numpy arrays — the "raw" format a
camera/upload pipeline would hand off — so channel-order and normalization
bugs are genuinely introduced downstream, not baked in here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from sera.config import CANARY_DIR, CANARY_SEED, CANARY_SIZE, DATA_DIR


@dataclass
class CanaryBatch:
    images: np.ndarray  # (N, H, W, 3) uint8 RGB
    labels: np.ndarray  # (N,) int64
    class_names: list

    def __len__(self) -> int:
        return len(self.images)


def _canary_cache_path():
    CANARY_DIR.mkdir(parents=True, exist_ok=True)
    return CANARY_DIR / f"canary_{CANARY_SIZE}_seed{CANARY_SEED}.npz"


def build_canary_set(force_rebuild: bool = False) -> CanaryBatch:
    """Deterministically select CANARY_SIZE images from the CIFAR-10 test split.

    Cached to disk after first build so repeated runs (and CI) don't need to
    re-touch torchvision's dataset object every time.
    """
    cache_path = _canary_cache_path()
    if cache_path.exists() and not force_rebuild:
        data = np.load(cache_path, allow_pickle=True)
        return CanaryBatch(
            images=data["images"], labels=data["labels"], class_names=list(data["class_names"])
        )

    import torchvision

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test_set = torchvision.datasets.CIFAR10(root=str(DATA_DIR), train=False, download=True)
    rng = np.random.RandomState(CANARY_SEED)
    indices = rng.choice(len(test_set), size=CANARY_SIZE, replace=False)

    images = np.stack([np.array(test_set[i][0]) for i in indices]).astype(np.uint8)
    labels = np.array([test_set[i][1] for i in indices], dtype=np.int64)
    class_names = test_set.classes

    np.savez_compressed(cache_path, images=images, labels=labels, class_names=class_names)
    return CanaryBatch(images=images, labels=labels, class_names=class_names)


def validate_batch(batch: CanaryBatch) -> None:
    if batch.images.ndim != 4 or batch.images.shape[-1] != 3:
        raise ValueError(f"expected (N, H, W, 3) images, got shape {batch.images.shape}")
    if batch.images.dtype != np.uint8:
        raise ValueError(f"expected uint8 images, got {batch.images.dtype}")
    if len(batch.images) != len(batch.labels):
        raise ValueError("images/labels length mismatch")


def inject_corruption_leak(
    batch: CanaryBatch,
    rate: float,
    severity: float,
    seed: Optional[int] = None,
) -> CanaryBatch:
    """Simulate F4: a broken/disabled data-quality filter lets `rate` fraction
    of images through with heavy salt-and-pepper + Gaussian noise added,
    at magnitude `severity` (0..1).
    """
    if rate <= 0 or severity <= 0:
        return batch
    rng = np.random.RandomState(seed if seed is not None else 0)
    n = len(batch)
    n_corrupt = int(round(rate * n))
    corrupt_idx = rng.choice(n, size=n_corrupt, replace=False)

    images = batch.images.copy()
    for i in corrupt_idx:
        img = images[i].astype(np.float32)
        noise = rng.normal(0, 255 * 0.5 * severity, size=img.shape)
        img = img + noise
        # salt & pepper
        sp_mask = rng.random(img.shape[:2]) < (0.15 * severity)
        salt = rng.random(img.shape[:2]) < 0.5
        img[sp_mask & salt] = 255
        img[sp_mask & ~salt] = 0
        images[i] = np.clip(img, 0, 255).astype(np.uint8)

    return CanaryBatch(images=images, labels=batch.labels, class_names=batch.class_names)

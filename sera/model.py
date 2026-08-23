"""ResNet-18 adapted for CIFAR-sized (32x32) inputs, plus checkpoint I/O.

Standard torchvision resnet18 uses a 7x7 stride-2 stem + maxpool designed
for 224x224 ImageNet images; on 32x32 CIFAR images that discards almost
all spatial resolution before the first residual block. We use the
well-known CIFAR adaptation: a 3x3 stride-1 stem and no initial maxpool.
"""
from __future__ import annotations

import functools
from pathlib import Path

import torch
import torch.nn as nn
import torchvision.models as tv_models

from sera.config import CHECKPOINT_DIR


def make_resnet18_cifar(num_classes: int = 10) -> nn.Module:
    model = tv_models.resnet18(weights=None, num_classes=num_classes)
    model.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
    model.maxpool = nn.Identity()
    return model


def checkpoint_path(name: str) -> Path:
    return CHECKPOINT_DIR / f"{name}.pt"


def save_checkpoint(model: nn.Module, name: str, num_classes: int = 10) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(name)
    torch.save({"state_dict": model.state_dict(), "num_classes": num_classes}, path)
    return path


@functools.lru_cache(maxsize=8)
def load_checkpoint(name: str) -> nn.Module:
    path = checkpoint_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"checkpoint {name!r} not found at {path}. Run scripts/train_baseline_model.py first."
        )
    payload = torch.load(path, map_location="cpu")
    model = make_resnet18_cifar(num_classes=payload.get("num_classes", 10))
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return model

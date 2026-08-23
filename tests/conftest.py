import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sera.model import checkpoint_path


def _checkpoints_ready() -> bool:
    return checkpoint_path("resnet18_cifar10").exists() and checkpoint_path(
        "resnet18_cifar10_stale"
    ).exists()


requires_checkpoint = pytest.mark.skipif(
    not _checkpoints_ready(),
    reason="run scripts/train_baseline_model.py first to produce the CIFAR-10 checkpoints",
)

"""Stage 4: model inference.

Loads the checkpoint named in `config.checkpoint_name` and runs a forward
pass, returning per-image softmax probabilities. F5 (wrong checkpoint
loaded) is expressed purely by which checkpoint name the config points at.
"""
from __future__ import annotations

import torch

from sera.config import PipelineConfig
from sera.model import load_checkpoint


def run_inference(input_tensor: torch.Tensor, config: PipelineConfig) -> torch.Tensor:
    """input_tensor: (N,3,H,W) float32 -> (N, num_classes) softmax probabilities."""
    model = load_checkpoint(config.checkpoint_name)
    with torch.no_grad():
        logits = model(input_tensor)
        probs = torch.softmax(logits, dim=1)
    return probs

"""Stage 5: prediction evaluation against the labeled canary set.

Computes accuracy, mean confidence, and mean prediction entropy — plus the
full per-image arrays, which `method.evidence_signals` needs to tell
"broad, uniform degradation" apart from "a subset of images went bad" from
"confidently wrong on specific inputs".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch


@dataclass
class RunMetrics:
    accuracy: float
    mean_confidence: float
    mean_entropy: float
    per_image_confidence: np.ndarray  # (N,) max softmax prob per image
    per_image_entropy: np.ndarray  # (N,) shannon entropy (nats) per image
    per_image_correct: np.ndarray  # (N,) bool
    predictions: np.ndarray  # (N,) predicted class ids

    def to_summary_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "mean_confidence": self.mean_confidence,
            "mean_entropy": self.mean_entropy,
        }


def evaluate_predictions(probs: torch.Tensor, labels: np.ndarray) -> RunMetrics:
    probs_np = probs.numpy()
    predictions = probs_np.argmax(axis=1)
    confidence = probs_np.max(axis=1)
    eps = 1e-12
    entropy = -(probs_np * np.log(probs_np + eps)).sum(axis=1)
    correct = predictions == labels

    return RunMetrics(
        accuracy=float(correct.mean()),
        mean_confidence=float(confidence.mean()),
        mean_entropy=float(entropy.mean()),
        per_image_confidence=confidence,
        per_image_entropy=entropy,
        per_image_correct=correct,
        predictions=predictions,
    )

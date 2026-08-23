"""Turns two RunMetrics (a healthy baseline, a regressed run) into a
3-dimensional "shape" fingerprint describing HOW the regression looks,
independent of any commit evidence:

  broadness           -- fraction of canary images whose confidence
                          dropped meaningfully. High = nearly every image
                          affected (channel swap, normalization drift,
                          wrong checkpoint). Low = only some images hit.
  subset_concentration -- Gini coefficient of the per-image confidence
                          drop. High = the damage is concentrated in a
                          few images (a corrupted subset). Low = the drop
                          is spread evenly across the whole set.
  confident_but_wrong  -- mean confidence on images that were correct at
                          baseline and are now wrong. High = the model is
                          still confidently making calls, just wrong ones
                          (classic genuine covariate shift). Low = errors
                          come with visibly collapsed confidence (a
                          pipeline-level corruption of the input signal).

Each condition has an expected template in this same 3D space (see
CONDITION_SHAPE_TEMPLATES below, calibrated empirically against real
model runs -- see scripts/calibrate_templates.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sera.pipeline.evaluation import RunMetrics

CONFIDENCE_DROP_THRESHOLD = 0.05


@dataclass
class ShapeFeatures:
    broadness: float
    subset_concentration: float
    confident_but_wrong: float

    def as_vector(self) -> np.ndarray:
        return np.array([self.broadness, self.subset_concentration, self.confident_but_wrong])


def _gini(values: np.ndarray) -> float:
    values = np.clip(values, 0, None)
    total = values.sum()
    if total <= 1e-9:
        return 0.0
    sorted_v = np.sort(values)
    n = len(sorted_v)
    cum = np.cumsum(sorted_v)
    gini = (n + 1 - 2 * (cum.sum() / cum[-1])) / n
    return float(np.clip(gini, 0.0, 1.0))


def compute_shape_features(baseline: RunMetrics, current: RunMetrics) -> ShapeFeatures:
    conf_drop = baseline.per_image_confidence - current.per_image_confidence
    broadness = float((conf_drop > CONFIDENCE_DROP_THRESHOLD).mean())
    subset_concentration = _gini(conf_drop)

    newly_wrong = baseline.per_image_correct & (~current.per_image_correct)
    if newly_wrong.any():
        confident_but_wrong = float(current.per_image_confidence[newly_wrong].mean())
    else:
        confident_but_wrong = 0.0

    return ShapeFeatures(
        broadness=broadness,
        subset_concentration=subset_concentration,
        confident_but_wrong=confident_but_wrong,
    )


# Expected (broadness, subset_concentration, confident_but_wrong) profile for
# each condition. Calibrated against real ResNet-18/CIFAR-10 runs -- see
# scripts/calibrate_templates.py, which prints observed vectors so these can
# be refreshed if the model/canary set changes.
CONDITION_SHAPE_TEMPLATES = {
    "F1": ShapeFeatures(0.29, 0.78, 0.31),
    "F2": ShapeFeatures(0.46, 0.66, 0.31),
    "F3": ShapeFeatures(0.43, 0.69, 0.29),
    "F4": ShapeFeatures(0.11, 0.91, 0.39),
    "F5": ShapeFeatures(0.79, 0.45, 0.24),
    "D1": ShapeFeatures(0.22, 0.77, 0.37),
}


def shape_similarity(observed: ShapeFeatures, template: ShapeFeatures) -> float:
    """1.0 = identical shape, 0.0 = maximally different (L1 distance in the
    3D unit cube, normalized so the max possible distance maps to 0).
    """
    diff = np.abs(observed.as_vector() - template.as_vector())
    max_dist = 3.0  # each axis in [0,1], 3 axes
    return float(1.0 - diff.sum() / max_dist)

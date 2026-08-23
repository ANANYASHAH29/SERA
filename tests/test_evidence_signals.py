import numpy as np

from sera.method.evidence_signals import compute_shape_features, shape_similarity, ShapeFeatures
from sera.pipeline.evaluation import RunMetrics


def _metrics(confidence, entropy, correct):
    confidence = np.array(confidence, dtype=float)
    entropy = np.array(entropy, dtype=float)
    correct = np.array(correct, dtype=bool)
    return RunMetrics(
        accuracy=float(correct.mean()),
        mean_confidence=float(confidence.mean()),
        mean_entropy=float(entropy.mean()),
        per_image_confidence=confidence,
        per_image_entropy=entropy,
        per_image_correct=correct,
        predictions=np.zeros(len(confidence), dtype=int),
    )


def test_broad_uniform_drop_has_high_broadness_low_concentration():
    n = 100
    baseline = _metrics([0.9] * n, [0.2] * n, [True] * n)
    # every image drops by the same amount, half become wrong
    regressed = _metrics([0.5] * n, [1.0] * n, [True] * (n // 2) + [False] * (n // 2))

    shape = compute_shape_features(baseline, regressed)
    assert shape.broadness > 0.9
    assert shape.subset_concentration < 0.3  # uniform drop -> low Gini


def test_subset_spike_has_low_broadness_high_concentration():
    n = 100
    baseline = _metrics([0.9] * n, [0.2] * n, [True] * n)
    conf = [0.9] * 85 + [0.1] * 15  # only 15% of images crater
    correct = [True] * 85 + [False] * 15
    regressed = _metrics(conf, [0.2] * 85 + [2.0] * 15, correct)

    shape = compute_shape_features(baseline, regressed)
    assert shape.broadness < 0.3
    assert shape.subset_concentration > 0.5


def test_confident_but_wrong_detected_when_errors_stay_confident():
    n = 100
    baseline = _metrics([0.9] * n, [0.2] * n, [True] * n)
    # newly-wrong images keep high confidence (drift-like: still sure, just wrong)
    conf = [0.85] * n
    correct = [True] * 60 + [False] * 40
    regressed = _metrics(conf, [0.3] * n, correct)

    shape = compute_shape_features(baseline, regressed)
    assert shape.confident_but_wrong > 0.7


def test_no_newly_wrong_images_gives_zero_confident_but_wrong():
    n = 50
    baseline = _metrics([0.9] * n, [0.2] * n, [True] * n)
    regressed = _metrics([0.9] * n, [0.2] * n, [True] * n)  # unchanged
    shape = compute_shape_features(baseline, regressed)
    assert shape.confident_but_wrong == 0.0


def test_shape_similarity_identical_is_one():
    f = ShapeFeatures(0.5, 0.5, 0.5)
    assert shape_similarity(f, f) == 1.0


def test_shape_similarity_opposite_is_zero():
    a = ShapeFeatures(0.0, 0.0, 0.0)
    b = ShapeFeatures(1.0, 1.0, 1.0)
    assert shape_similarity(a, b) == 0.0

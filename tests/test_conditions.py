"""Confirms each of F1-F5, D1 individually produces a clear, measurable
accuracy drop and a distinguishable confidence/entropy-shift shape when
injected alone, with everything else held at baseline. Requires a trained
checkpoint (see scripts/train_baseline_model.py).
"""
import pytest

from experiments.scenario import build_scenario, run_baseline_and_regressed
from sera.conditions.registry import ALL_CATEGORIES
from sera.method.evidence_signals import compute_shape_features
from tests.conftest import requires_checkpoint

MIN_ACCURACY_DROP = 0.05


@requires_checkpoint
@pytest.mark.parametrize("condition", ALL_CATEGORIES)
def test_condition_produces_a_clear_accuracy_drop(condition):
    scenario = build_scenario(condition, seed=0)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    drop = baseline_metrics.accuracy - regressed_metrics.accuracy
    assert drop > MIN_ACCURACY_DROP, (
        f"{condition} only dropped accuracy by {drop:.3f}; "
        "increase its severity in experiments/scenario.DEFAULT_SEVERITY"
    )


@requires_checkpoint
def test_f2_and_f3_are_more_broad_than_f4_and_d1():
    # F2/F3 corrupt the whole image stream (channel order / normalization
    # constants apply uniformly); F4/D1 only affect a subset of images.
    # Empirically neither reaches >0.5 broadness on this model/canary set
    # (see scripts/calibrate_templates.py), but they're clearly more broad
    # than the subset-concentrated conditions.
    def broadness_of(condition):
        scenario = build_scenario(condition, seed=0)
        baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
        return compute_shape_features(baseline_metrics, regressed_metrics).broadness

    f2, f3 = broadness_of("F2"), broadness_of("F3")
    f4, d1 = broadness_of("F4"), broadness_of("D1")
    assert min(f2, f3) > max(f4, d1)


@requires_checkpoint
def test_f4_corruption_is_more_concentrated_than_broad():
    scenario = build_scenario("F4", seed=0)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    shape = compute_shape_features(baseline_metrics, regressed_metrics)
    assert shape.subset_concentration > shape.broadness


@requires_checkpoint
def test_d1_drift_leaves_errors_more_confident_than_f2_channel_swap():
    d1_scenario = build_scenario("D1", seed=0)
    f2_scenario = build_scenario("F2", seed=0)

    d1_baseline, d1_regressed = run_baseline_and_regressed(d1_scenario)
    f2_baseline, f2_regressed = run_baseline_and_regressed(f2_scenario)

    d1_shape = compute_shape_features(d1_baseline, d1_regressed)
    f2_shape = compute_shape_features(f2_baseline, f2_regressed)

    assert d1_shape.confident_but_wrong > f2_shape.confident_but_wrong


@requires_checkpoint
def test_f5_wrong_checkpoint_changes_accuracy_substantially():
    scenario = build_scenario("F5", seed=0)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    assert regressed_metrics.accuracy < baseline_metrics.accuracy - MIN_ACCURACY_DROP

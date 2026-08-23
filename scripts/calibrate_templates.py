"""Prints observed (broadness, subset_concentration, confident_but_wrong)
shape vectors for each of F1-F5/D1, averaged over a few seeds, against a
real trained ResNet-18/CIFAR-10 model. Use this to refresh
CONDITION_SHAPE_TEMPLATES in sera/method/evidence_signals.py if the model,
canary set, or condition severities change.

Usage:
    python scripts/calibrate_templates.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from experiments.scenario import build_scenario, run_baseline_and_regressed
from sera.conditions.registry import ALL_CATEGORIES
from sera.method.evidence_signals import compute_shape_features


def main():
    seeds = [0, 1, 2]
    for condition in ALL_CATEGORIES:
        vecs = []
        drops = []
        for seed in seeds:
            scenario = build_scenario(condition, seed=seed)
            baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
            shape = compute_shape_features(baseline_metrics, regressed_metrics)
            vecs.append(shape.as_vector())
            drops.append(baseline_metrics.accuracy - regressed_metrics.accuracy)
        mean_vec = np.mean(vecs, axis=0)
        print(
            f"{condition}: acc_drop={np.mean(drops):.3f}  "
            f"broadness={mean_vec[0]:.3f}  subset_concentration={mean_vec[1]:.3f}  "
            f"confident_but_wrong={mean_vec[2]:.3f}"
        )


if __name__ == "__main__":
    main()

"""Shared scenario-construction helpers used by the experiment runner, the
confusion-matrix/cost-comparison analysis scripts, and the pytest suite.

A "scenario" fixes: which condition is the ground-truth cause (one of
F1-F5, or None for D1/genuine-drift), a synthetic commit history around
it, and the resulting baseline/regressed pipeline runs. All four methods
(SERA + 3 baselines) are then pointed at the exact same scenario so their
guesses are directly comparable.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional

from sera.conditions.registry import (
    ALL_CATEGORIES,
    CONFIG_CONDITIONS,
    DRIFT_CONDITION,
    DRIFT_LABEL,
    NO_COMMIT_CANDIDATE_ID,
)
from sera.config import PipelineConfig, baseline_config
from sera.github_integration.commit_types import CommitInfo
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.synthetic_history import generate_synthetic_history
from sera.method.evidence_signals import ShapeFeatures, compute_shape_features
from sera.pipeline.ingestion import CanaryBatch, build_canary_set
from sera.pipeline.runner import run_pipeline

DEFAULT_SEVERITY = {
    "F1": 1.0,
    "F2": 1.0,
    "F3": 0.7,
    "F4": 1.0,  # severity of the corruption itself; rate set below
    "F5": 1.0,
    "D1": 1.0,
}


@dataclass
class Scenario:
    ground_truth_condition: Optional[str]  # one of F1-F5, or None for drift
    seed: int
    baseline_config: PipelineConfig
    regressed_config: PipelineConfig
    baseline_batch: CanaryBatch
    regressed_batch: CanaryBatch
    commits: List[CommitInfo]
    guilty_commit_sha: Optional[str]

    @property
    def ground_truth_candidate_id(self) -> str:
        return self.guilty_commit_sha if self.guilty_commit_sha else NO_COMMIT_CANDIDATE_ID


def build_scenario(
    condition: str,
    seed: int,
    num_harmless: int = 4,
    include_concurrent_unrelated: bool = False,
    severity: Optional[float] = None,
    extra_drift_severity: float = 0.0,
) -> Scenario:
    """condition: one of ALL_CATEGORIES (F1-F5 or D1).

    extra_drift_severity > 0 additionally applies mild covariate shift on
    top of an F1-F5 condition -- used for the "hard concurrent confound"
    test, where a real code-caused regression coincides with genuine drift.
    """
    if condition not in ALL_CATEGORIES:
        raise ValueError(f"unknown condition {condition!r}")

    sev = severity if severity is not None else DEFAULT_SEVERITY[condition]
    base_config = baseline_config()
    canary = build_canary_set()

    guilty_category = None if condition == DRIFT_LABEL else condition
    commits = generate_synthetic_history(
        num_harmless=num_harmless,
        guilty_category=guilty_category,
        include_concurrent_unrelated=include_concurrent_unrelated,
        seed=seed,
    )
    classify_commits(commits)
    guilty_commit_sha = None
    if guilty_category is not None:
        matches = [c for c in commits if guilty_category in c.risk_categories]
        guilty_commit_sha = matches[0].sha if matches else None

    if condition == "F4":
        regressed_config = CONFIG_CONDITIONS["F4"].apply(base_config, rate=0.4, severity=sev)
    elif condition in CONFIG_CONDITIONS:
        regressed_config = CONFIG_CONDITIONS[condition].apply(base_config, severity=sev)
    else:
        regressed_config = base_config

    regressed_batch = canary
    if condition == DRIFT_LABEL:
        shifted = DRIFT_CONDITION.apply_to_images(canary.images, severity=sev, seed=seed + 900)
        regressed_batch = replace(canary, images=shifted)

    if extra_drift_severity > 0:
        shifted = DRIFT_CONDITION.apply_to_images(
            regressed_batch.images, severity=extra_drift_severity, seed=seed + 901, fraction=0.5
        )
        regressed_batch = replace(regressed_batch, images=shifted)

    return Scenario(
        ground_truth_condition=guilty_category,
        seed=seed,
        baseline_config=base_config,
        regressed_config=regressed_config,
        baseline_batch=canary,
        regressed_batch=regressed_batch,
        commits=commits,
        guilty_commit_sha=guilty_commit_sha,
    )


def run_baseline_and_regressed(scenario: Scenario):
    baseline_metrics = run_pipeline(scenario.baseline_config, scenario.baseline_batch)
    regressed_metrics = run_pipeline(scenario.regressed_config, scenario.regressed_batch)
    return baseline_metrics, regressed_metrics


def observed_shape_for(scenario: Scenario) -> ShapeFeatures:
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    return compute_shape_features(baseline_metrics, regressed_metrics)


def config_as_of_factory(scenario: Scenario):
    """Build the `accuracy_as_of(i)` callback full_bisection needs: the
    cumulative pipeline config after applying commits[0..i], re-evaluated
    against the scenario's regressed canary images (which already carry
    any D1 drift baked in, independent of config).
    """
    commits = scenario.commits
    guilty_sha = scenario.guilty_commit_sha

    def accuracy_as_of(i: int) -> float:
        commit_applied = any(c.sha == guilty_sha for c in commits[: i + 1]) if guilty_sha else False
        config = scenario.regressed_config if commit_applied else scenario.baseline_config
        metrics = run_pipeline(config, scenario.regressed_batch)
        return metrics.accuracy

    return accuracy_as_of


def bisection_bad_threshold(baseline_accuracy: float, regressed_accuracy: float) -> float:
    return (baseline_accuracy + regressed_accuracy) / 2.0

"""Isolated re-evaluation / validation tests: reverting the *correct*
candidate's change should recover accuracy and confirm the hypothesis;
reverting the wrong thing (or validating a drift hypothesis) should behave
as expected.
"""
from datetime import datetime

from experiments.scenario import build_scenario, run_baseline_and_regressed
from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.method.ranker import RankedCandidate
from sera.method.validator import validate_top_candidate
from tests.conftest import requires_checkpoint


def _commit_candidate(sha, category):
    return RankedCandidate(
        candidate_id=sha,
        kind="commit",
        hypothesized_category=category,
        provenance_score=1.0,
        shape_match_score=1.0,
        combined_score=1.0,
        commit=CommitInfo(sha=sha, message="m", author="a", timestamp=datetime.utcnow()),
    )


def _drift_candidate():
    return RankedCandidate(
        candidate_id=NO_COMMIT_CANDIDATE_ID,
        kind="drift",
        hypothesized_category="D1",
        provenance_score=0.35,
        shape_match_score=1.0,
        combined_score=1.0,
    )


@requires_checkpoint
def test_reverting_the_correct_condition_recovers_accuracy_and_confirms():
    scenario = build_scenario("F3", seed=0)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)

    candidate = _commit_candidate("guiltyF3", "F3")
    outcome = validate_top_candidate(
        candidate,
        scenario.regressed_config,
        scenario.baseline_config,
        scenario.regressed_batch,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    assert outcome.recovered is True
    assert outcome.confirmed is True
    assert outcome.after_accuracy > outcome.before_accuracy


@requires_checkpoint
def test_reverting_the_wrong_category_does_not_confirm():
    scenario = build_scenario("F3", seed=0)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)

    # F5 (checkpoint) is unrelated to the actual F3 (normalization) cause.
    candidate = _commit_candidate("wrongGuess", "F5")
    outcome = validate_top_candidate(
        candidate,
        scenario.regressed_config,
        scenario.baseline_config,
        scenario.regressed_batch,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    assert outcome.confirmed is False


@requires_checkpoint
def test_drift_hypothesis_confirmed_when_reverting_config_does_not_help():
    scenario = build_scenario("D1", seed=0)
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)

    outcome = validate_top_candidate(
        _drift_candidate(),
        scenario.regressed_config,
        scenario.baseline_config,
        scenario.regressed_batch,
        before_accuracy=regressed_metrics.accuracy,
        baseline_accuracy=baseline_metrics.accuracy,
    )
    assert outcome.recovered is False  # baseline config doesn't fix drifted images
    assert outcome.confirmed is True  # ...which is exactly what confirms drift

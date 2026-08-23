"""THE most important test in this suite (see README "How to test it,
end to end", step 2): inject genuine drift (D1) on the canary set while a
harmless commit (touching no risk-category file) sits in the same window.
SERA must rank "no commit responsible -- genuine drift" above the
harmless commit. If this fails, nothing downstream matters.

This is a full end-to-end integration test through the real pipeline and
a real trained model -- not just the ranker in isolation (see
tests/test_ranker.py for the fast, model-free version of this check).
"""
from experiments.scenario import build_scenario, run_baseline_and_regressed
from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.method.evidence_signals import compute_shape_features
from sera.method.ranker import rank_candidates
from tests.conftest import requires_checkpoint


@requires_checkpoint
def test_drift_plus_harmless_commit_ranks_drift_first():
    scenario = build_scenario(
        "D1",
        seed=0,
        num_harmless=1,
        include_concurrent_unrelated=False,
    )
    assert scenario.guilty_commit_sha is None  # ground truth: no commit caused this
    assert all(c.risk_categories == [] for c in scenario.commits)

    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)

    ranked = rank_candidates(scenario.commits, observed_shape)

    assert ranked[0].candidate_id == NO_COMMIT_CANDIDATE_ID, (
        f"expected drift to rank first, got {ranked[0].candidate_id!r} "
        f"(scores: {[(c.candidate_id, c.combined_score) for c in ranked]})"
    )


@requires_checkpoint
def test_drift_plus_several_harmless_commits_still_ranks_drift_first():
    scenario = build_scenario(
        "D1",
        seed=1,
        num_harmless=4,
        include_concurrent_unrelated=True,
    )
    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)
    ranked = rank_candidates(scenario.commits, observed_shape)
    assert ranked[0].candidate_id == NO_COMMIT_CANDIDATE_ID

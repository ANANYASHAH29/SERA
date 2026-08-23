"""The hard case (README step 4): a real failure (F3) plus a harmless
commit plus a mild concurrent drift event, all in the same window. SERA
must still rank F3's commit above both the harmless commit and the drift
hypothesis -- proof the evidence fusion is doing real work, not just
"any provenance signal = guilty".
"""
from experiments.scenario import build_scenario, run_baseline_and_regressed
from sera.method.evidence_signals import compute_shape_features
from sera.method.ranker import rank_candidates
from tests.conftest import requires_checkpoint


@requires_checkpoint
def test_f3_commit_wins_despite_concurrent_mild_drift_and_harmless_commit():
    scenario = build_scenario(
        "F3",
        seed=0,
        num_harmless=1,
        include_concurrent_unrelated=False,
        extra_drift_severity=0.25,  # mild concurrent covariate shift, not the main cause
    )
    assert scenario.guilty_commit_sha is not None

    baseline_metrics, regressed_metrics = run_baseline_and_regressed(scenario)
    observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)
    ranked = rank_candidates(scenario.commits, observed_shape)

    assert ranked[0].candidate_id == scenario.guilty_commit_sha, (
        f"expected the F3 commit to win, got {ranked[0].candidate_id!r} "
        f"(scores: {[(c.candidate_id, c.kind, c.combined_score) for c in ranked]})"
    )

"""Unit tests for the joint ranking logic, in isolation from the model
(observed shapes are constructed directly). The most important test here
is `test_null_hypothesis_wins_against_a_harmless_commit`: SERA's entire
premise depends on ranking "no commit responsible, it's drift" above a
commit that touches no risk-category file, when the observed shape looks
like genuine drift.
"""
from datetime import datetime, timedelta

from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.method.evidence_signals import CONDITION_SHAPE_TEMPLATES
from sera.method.ranker import rank_candidates


def _commit(sha, files, ts):
    from sera.github_integration.diff_analyzer import classify_commit

    c = CommitInfo(sha=sha, message="msg", author="a", timestamp=ts, files_changed=files)
    classify_commit(c)
    return c


def test_null_hypothesis_wins_against_a_harmless_commit():
    now = datetime.utcnow()
    harmless = _commit("harmless1", ["README.md"], now - timedelta(hours=2))

    # Observed shape looks exactly like genuine drift.
    observed = CONDITION_SHAPE_TEMPLATES["D1"]

    ranked = rank_candidates([harmless], observed)

    assert ranked[0].candidate_id == NO_COMMIT_CANDIDATE_ID
    assert ranked[0].kind == "drift"
    assert ranked[1].candidate_id == "harmless1"
    assert ranked[0].combined_score > ranked[1].combined_score


def test_guilty_commit_beats_drift_hypothesis_and_harmless_commits():
    now = datetime.utcnow()
    harmless_commits = [
        _commit(f"harmless{i}", ["README.md"], now - timedelta(hours=10 - i)) for i in range(3)
    ]
    guilty = _commit("guiltyF3", ["preprocessing_config.yaml"], now - timedelta(hours=1))

    observed = CONDITION_SHAPE_TEMPLATES["F3"]
    ranked = rank_candidates(harmless_commits + [guilty], observed)

    assert ranked[0].candidate_id == "guiltyF3"
    assert ranked[0].hypothesized_category == "F3"
    for other in ranked[1:]:
        assert other.combined_score < ranked[0].combined_score


def test_commit_touching_no_risk_file_gets_zero_shape_credit():
    now = datetime.utcnow()
    harmless = _commit("h1", ["utils/logging.py"], now)
    observed = CONDITION_SHAPE_TEMPLATES["F2"]  # a strong, unambiguous shape
    ranked = rank_candidates([harmless], observed)
    harmless_rank = next(c for c in ranked if c.candidate_id == "h1")
    assert harmless_rank.provenance_score == 0.0
    assert harmless_rank.shape_match_score == 0.0


def test_drift_candidate_always_present_even_with_no_commits():
    ranked = rank_candidates([], CONDITION_SHAPE_TEMPLATES["D1"])
    assert len(ranked) == 1
    assert ranked[0].candidate_id == NO_COMMIT_CANDIDATE_ID


def test_ranking_is_deterministic_for_equal_scores():
    now = datetime.utcnow()
    c1 = _commit("c1", ["README.md"], now - timedelta(hours=1))
    c2 = _commit("c2", ["README.md"], now - timedelta(hours=2))
    observed = CONDITION_SHAPE_TEMPLATES["D1"]
    ranked1 = rank_candidates([c1, c2], observed)
    ranked2 = rank_candidates([c1, c2], observed)
    assert [c.candidate_id for c in ranked1] == [c.candidate_id for c in ranked2]
    # tie-break among equally-scored harmless commits: most recent first
    harmless_ranked = [c for c in ranked1 if c.kind == "commit"]
    assert harmless_ranked[0].candidate_id == "c1"

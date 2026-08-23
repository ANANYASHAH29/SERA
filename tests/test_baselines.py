from datetime import datetime, timedelta

from sera.baselines.confidence_only import guess_from_shape_only
from sera.baselines.full_bisection import bisect_commits
from sera.baselines.naive_latest_commit import guess_latest_commit
from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.method.evidence_signals import CONDITION_SHAPE_TEMPLATES


def _commit(sha, files, ts):
    from sera.github_integration.diff_analyzer import classify_commit

    c = CommitInfo(sha=sha, message="m", author="a", timestamp=ts, files_changed=files)
    classify_commit(c)
    return c


def test_naive_latest_commit_picks_most_recent_regardless_of_content():
    now = datetime.utcnow()
    commits = [
        _commit("old", ["preprocessing_config.yaml"], now - timedelta(hours=5)),
        _commit("new", ["README.md"], now - timedelta(hours=1)),
    ]
    guess = guess_latest_commit(commits)
    assert guess.candidate_id == "new"


def test_naive_latest_commit_with_no_commits_guesses_drift():
    guess = guess_latest_commit([])
    assert guess.candidate_id == NO_COMMIT_CANDIDATE_ID


def test_confidence_only_picks_drift_when_shape_matches_drift_template():
    now = datetime.utcnow()
    commits = [_commit("h1", ["README.md"], now)]
    guess = guess_from_shape_only(commits, CONDITION_SHAPE_TEMPLATES["D1"])
    assert guess.candidate_id == NO_COMMIT_CANDIDATE_ID


def test_confidence_only_picks_matching_commit_when_shape_matches_a_category():
    now = datetime.utcnow()
    commits = [
        _commit("harmless", ["README.md"], now - timedelta(hours=1)),
        _commit("guiltyF2", ["channel_order.py"], now - timedelta(hours=2)),
    ]
    guess = guess_from_shape_only(commits, CONDITION_SHAPE_TEMPLATES["F2"])
    assert guess.candidate_id == "guiltyF2"


def test_confidence_only_never_uses_provenance_score():
    commits = [_commit("h1", ["preprocessing_config.yaml"], datetime.utcnow())]
    guess = guess_from_shape_only(commits, CONDITION_SHAPE_TEMPLATES["F1"])
    assert guess.provenance_score == 0.0


def test_bisection_finds_the_guilty_commit_with_log_n_evaluations():
    now = datetime.utcnow()
    commits = [
        _commit(f"c{i}", ["README.md"], now - timedelta(hours=10 - i)) for i in range(7)
    ]
    guilty_index = 4
    commits[guilty_index] = _commit(
        "guilty", ["preprocessing_config.yaml"], now - timedelta(hours=10 - guilty_index)
    )

    def accuracy_as_of(i):
        # accuracy is "bad" (0.3) from the guilty commit onward, "good" (0.9) before
        return 0.3 if i >= guilty_index else 0.9

    result = bisect_commits(commits, accuracy_as_of, bad_threshold=0.6)
    assert result.guessed_candidate_id == "guilty"
    assert result.num_reevaluations <= 3  # ceil(log2(7)) == 3


def test_bisection_on_pure_drift_still_blames_some_commit_and_this_is_the_known_limitation():
    now = datetime.utcnow()
    commits = [_commit(f"c{i}", ["README.md"], now - timedelta(hours=5 - i)) for i in range(5)]

    def accuracy_as_of(i):
        return 0.3  # bad everywhere -- nothing in the code actually caused it

    result = bisect_commits(commits, accuracy_as_of, bad_threshold=0.6)
    # bisection has no null hypothesis: it always names a commit, even though
    # the true cause here is drift. This is the documented limitation SERA fixes.
    assert result.guessed_candidate_id != NO_COMMIT_CANDIDATE_ID
    assert result.guessed_candidate_id in {c.sha for c in commits}


def test_bisection_with_no_commits_costs_nothing():
    result = bisect_commits([], lambda i: 0.9, bad_threshold=0.5)
    assert result.num_reevaluations == 0
    assert result.guessed_candidate_id == NO_COMMIT_CANDIDATE_ID

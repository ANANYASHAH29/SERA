"""Real-world commit-history edge cases: a squashed merge commit that
bundles one genuinely risky file change with a pile of unrelated ones,
and confirming the ranker doesn't over-weight it just because it "touches
something". This exercises the frozen ranker/evidence-fusion logic
against a harder, more realistic input shape -- it does not change that
logic (see sera/method/ranker.py, untouched in this phase).
"""
from datetime import datetime, timedelta

from sera.github_integration.commit_types import CommitInfo
from sera.github_integration.diff_analyzer import classify_commit
from sera.method.evidence_signals import CONDITION_SHAPE_TEMPLATES
from sera.method.ranker import rank_candidates


def _squashed_merge_commit(sha, risky_file, n_unrelated=20, ts=None):
    unrelated = [f"src/module_{i}/file_{i}.py" for i in range(n_unrelated)]
    files = unrelated + [risky_file]
    commit = CommitInfo(
        sha=sha,
        message="Merge branch 'feature/big-refactor' (squashed)",
        author="bot",
        timestamp=ts or datetime.utcnow(),
        files_changed=files,
    )
    classify_commit(commit)
    return commit


def test_squashed_merge_touching_one_risky_file_still_gets_classified():
    # Touching a risk file among 20 unrelated ones is still real provenance
    # evidence -- classification itself should not suppress it.
    commit = _squashed_merge_commit("squash1", "preprocessing_config.yaml")
    assert commit.risk_categories == ["F3"]


def test_squashed_merge_incidental_risk_touch_loses_to_a_better_matching_candidate():
    # The squash commit incidentally touches an F3 (normalization) file
    # among 20 unrelated ones, so it gets full provenance credit (1.0) --
    # but the OBSERVED shape actually matches F5 (wrong checkpoint), not
    # F3. A second commit genuinely touches F5's file. "Touched something"
    # alone must not be enough for the squash commit to outrank the
    # candidate whose evidence actually fits: shape match still has to
    # pull its weight, not just provenance. (A single-candidate comparison
    # against the drift baseline isn't a fair test of this: this ranker's
    # calibrated weights make ANY real risk-file touch beat drift's fixed
    # 0.35 provenance floor almost regardless of shape, by design -- that's
    # provenance doing its job, not a bug. The real "don't over-weight it"
    # claim is about *relative* ranking against a better-fitting commit.)
    now = datetime.utcnow()
    squash_commit = _squashed_merge_commit("squash1", "preprocessing_config.yaml", ts=now)
    genuine_f5_commit = CommitInfo(
        sha="genuine_f5",
        message="Update model checkpoint pointer",
        author="a",
        timestamp=now - timedelta(hours=1),
        files_changed=["models/registry.checkpoint"],
    )
    classify_commit(genuine_f5_commit)
    observed = CONDITION_SHAPE_TEMPLATES["F5"]

    ranked = rank_candidates([squash_commit, genuine_f5_commit], observed)

    assert ranked[0].candidate_id == "genuine_f5"
    assert ranked[0].combined_score > ranked[1].combined_score
    # both got full provenance (1.0) -- the tiebreaker was shape match, not
    # "who touched more files" or file count, confirming shape isn't ignored.
    squash_rank = next(c for c in ranked if c.candidate_id == "squash1")
    genuine_rank = next(c for c in ranked if c.candidate_id == "genuine_f5")
    assert squash_rank.provenance_score == genuine_rank.provenance_score == 1.0
    assert genuine_rank.shape_match_score > squash_rank.shape_match_score


def test_squashed_merge_wins_when_shape_actually_matches_its_category():
    # Same squash commit, but this time the observed shape genuinely
    # matches F3 -- now it *should* win, since both evidence dimensions
    # agree. Confirms the previous test isn't just "squash commits always
    # lose" but a real function of shape match.
    now = datetime.utcnow()
    squash_commit = _squashed_merge_commit("squash1", "preprocessing_config.yaml", ts=now)
    harmless = CommitInfo(
        sha="harmless1",
        message="Update docs",
        author="a",
        timestamp=now - timedelta(hours=1),
        files_changed=["README.md"],
    )
    classify_commit(harmless)
    observed = CONDITION_SHAPE_TEMPLATES["F3"]

    ranked = rank_candidates([squash_commit, harmless], observed)

    assert ranked[0].candidate_id == "squash1"


def test_squash_commit_with_many_risky_files_gets_multi_category_classification():
    commit = CommitInfo(
        sha="squash2",
        message="Merge (squashed)",
        author="bot",
        timestamp=datetime.utcnow(),
        files_changed=[
            "preprocessing_config.yaml",  # F3
            "models/registry.checkpoint",  # F5
            "src/unrelated/thing.py",
        ],
    )
    classify_commit(commit)
    assert set(commit.risk_categories) == {"F3", "F5"}

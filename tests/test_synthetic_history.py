from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.synthetic_history import generate_synthetic_history


def test_harmless_only_history_has_no_risk_categories():
    commits = generate_synthetic_history(num_harmless=5, guilty_category=None, seed=1)
    classify_commits(commits)
    assert len(commits) == 5
    assert all(c.risk_categories == [] for c in commits)


def test_guilty_commit_is_classified_to_its_category():
    commits = generate_synthetic_history(num_harmless=3, guilty_category="F3", seed=2)
    classify_commits(commits)
    guilty = [c for c in commits if "F3" in c.risk_categories]
    assert len(guilty) == 1


def test_concurrent_unrelated_adds_one_extra_harmless_commit():
    without = generate_synthetic_history(
        num_harmless=3, guilty_category="F1", include_concurrent_unrelated=False, seed=3
    )
    with_concurrent = generate_synthetic_history(
        num_harmless=3, guilty_category="F1", include_concurrent_unrelated=True, seed=3
    )
    assert len(with_concurrent) == len(without) + 1


def test_commits_are_chronologically_sorted():
    commits = generate_synthetic_history(num_harmless=6, guilty_category="F2", seed=4)
    timestamps = [c.timestamp for c in commits]
    assert timestamps == sorted(timestamps)


def test_seed_is_deterministic():
    a = generate_synthetic_history(num_harmless=4, guilty_category="F5", seed=99)
    b = generate_synthetic_history(num_harmless=4, guilty_category="F5", seed=99)
    assert [c.sha for c in a] == [c.sha for c in b]

"""Generates a fake commit history for testing without a real populated repo.

Mixes harmless commits (touching files that map to no risk category) with
optionally one "guilty" commit (touching a file matching a chosen F1-F5
risk category) and optionally a concurrent unrelated harmless commit --
exactly the scenarios the null-hypothesis and hard-confound tests need.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List, Optional

from sera.conditions.registry import CONFIG_CONDITIONS
from sera.github_integration.commit_types import CommitInfo

HARMLESS_FILES = [
    "README.md",
    "docs/architecture.md",
    "utils/logging.py",
    "tests/test_utils.py",
    ".github/workflows/ci.yml",
    "requirements-dev.txt",
    "notebooks/exploration.ipynb",
    "scripts/format_code.sh",
    "CHANGELOG.md",
    "utils/timing.py",
]

HARMLESS_MESSAGES = [
    "Update README with install instructions",
    "Add logging around request handler",
    "Fix flaky test in CI",
    "Bump dev dependency versions",
    "Clean up exploration notebook",
    "Add code formatting script",
    "Update changelog for release",
    "Refactor timing utility for clarity",
]

AUTHORS = ["alice", "bob", "carol", "dave", "erin"]


def _random_harmless_commit(rng: random.Random, timestamp: datetime, idx: int) -> CommitInfo:
    return CommitInfo(
        sha=f"harmless{idx:04d}" + rng.randbytes(4).hex(),
        message=rng.choice(HARMLESS_MESSAGES),
        author=rng.choice(AUTHORS),
        timestamp=timestamp,
        files_changed=[rng.choice(HARMLESS_FILES)],
        pr_number=1000 + idx,
        pr_html_url=f"https://github.com/example/repo/pull/{1000 + idx}",
    )


def _guilty_commit(rng: random.Random, timestamp: datetime, category: str, idx: int) -> CommitInfo:
    module = CONFIG_CONDITIONS[category]
    filename = module.RISK_FILE_PATTERNS[0] + ".yaml"
    return CommitInfo(
        sha=f"guilty{category}" + rng.randbytes(4).hex(),
        message=f"Update {filename} for new deployment target",
        author=rng.choice(AUTHORS),
        timestamp=timestamp,
        files_changed=[filename],
        pr_number=2000 + idx,
        pr_html_url=f"https://github.com/example/repo/pull/{2000 + idx}",
    )


def generate_synthetic_history(
    num_harmless: int = 4,
    guilty_category: Optional[str] = None,
    include_concurrent_unrelated: bool = False,
    window_hours: int = 72,
    seed: int = 42,
    end_time: Optional[datetime] = None,
) -> List[CommitInfo]:
    """Build a fake, chronologically-ordered commit list.

    guilty_category: one of F1-F5, or None for "no code cause in this window".
    include_concurrent_unrelated: adds one extra harmless commit clustered
        near the same time as the guilty commit (or near the end of the
        window if there is no guilty commit), to stress-test that the
        ranker doesn't just credit "most recent" or "closest in time".
    """
    rng = random.Random(seed)
    end_time = end_time or datetime.utcnow()
    start_time = end_time - timedelta(hours=window_hours)

    commits: List[CommitInfo] = []
    timestamps = sorted(
        start_time + timedelta(hours=rng.uniform(0, window_hours)) for _ in range(num_harmless)
    )
    for i, ts in enumerate(timestamps):
        commits.append(_random_harmless_commit(rng, ts, i))

    if guilty_category is not None:
        guilty_ts = start_time + timedelta(hours=rng.uniform(window_hours * 0.4, window_hours * 0.9))
        commits.append(_guilty_commit(rng, guilty_ts, guilty_category, len(commits)))

        if include_concurrent_unrelated:
            concurrent_ts = guilty_ts + timedelta(minutes=rng.uniform(-30, 30))
            commits.append(_random_harmless_commit(rng, concurrent_ts, len(commits)))
    elif include_concurrent_unrelated:
        concurrent_ts = end_time - timedelta(hours=rng.uniform(0, window_hours * 0.2))
        commits.append(_random_harmless_commit(rng, concurrent_ts, len(commits)))

    commits.sort(key=lambda c: c.timestamp)
    return commits

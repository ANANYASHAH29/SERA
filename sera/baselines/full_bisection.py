"""Baseline 1: full brute-force bisection.

Classic `git bisect`-style binary search over the commit window: at each
step, actually rebuild the pipeline config "as of" the midpoint commit and
re-run the full canary evaluation (an expensive re-evaluation), narrowing
down to the first commit after which accuracy is bad.

This baseline has no concept of a "no commit responsible" hypothesis --
it always names some commit, even when the true cause is drift. That
blind spot is the entire point of contrasting it against SERA.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo


@dataclass
class BisectionResult:
    guessed_candidate_id: str
    guessed_commit: Optional[CommitInfo]
    num_reevaluations: int


def bisect_commits(
    commits: List[CommitInfo],
    accuracy_as_of: Callable[[int], float],
    bad_threshold: float,
) -> BisectionResult:
    """commits: chronologically sorted (oldest first).
    accuracy_as_of(i): re-evaluates the pipeline with the cumulative effect
    of commits[0..i] applied and returns accuracy. Each call is one
    expensive re-evaluation.
    bad_threshold: accuracy below this counts as "still regressed".
    """
    if not commits:
        return BisectionResult(NO_COMMIT_CANDIDATE_ID, None, 0)

    n = len(commits)
    low, high = 0, n - 1
    evals = 0
    first_bad = n - 1  # fallback: blame the most recent commit

    while low <= high:
        mid = (low + high) // 2
        acc = accuracy_as_of(mid)
        evals += 1
        if acc < bad_threshold:
            first_bad = mid
            high = mid - 1
        else:
            low = mid + 1

    return BisectionResult(
        guessed_candidate_id=commits[first_bad].sha,
        guessed_commit=commits[first_bad],
        num_reevaluations=evals,
    )

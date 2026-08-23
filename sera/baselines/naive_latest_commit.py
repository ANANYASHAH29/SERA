"""Baseline 2: naive "blame the most recent commit".

No provenance evidence, no shape evidence -- just picks the chronologically
last commit in the window (or drift, if the window has no commits at all).
"""
from __future__ import annotations

from typing import List, Optional

from sera.conditions.registry import NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.method.ranker import RankedCandidate


def guess_latest_commit(commits: List[CommitInfo]) -> RankedCandidate:
    if not commits:
        return RankedCandidate(
            candidate_id=NO_COMMIT_CANDIDATE_ID,
            kind="drift",
            hypothesized_category="D1",
            provenance_score=0.0,
            shape_match_score=0.0,
            combined_score=0.0,
        )
    latest = max(commits, key=lambda c: c.timestamp)
    category = latest.risk_categories[0] if latest.risk_categories else None
    return RankedCandidate(
        candidate_id=latest.sha,
        kind="commit",
        hypothesized_category=category,
        provenance_score=1.0 if category else 0.0,
        shape_match_score=0.0,
        combined_score=0.0,
        commit=latest,
    )

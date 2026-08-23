"""Baseline 3: confidence-shift-only ranking, with no commit/provenance
evidence at all.

Picks whichever of the 6 shape templates (F1-F5, D1) best matches the
observed confidence/entropy shift, then -- only to be able to name a
single "top candidate" for cost/accuracy comparison -- maps that category
to a commit in the window if one happens to touch it, otherwise falls back
to the most recent commit. It never checks whether the diff actually
supports the guess, which is exactly what should make it fragile in the
"hard confound" scenarios where SERA's provenance term helps.
"""
from __future__ import annotations

from typing import List

from sera.conditions.registry import DRIFT_LABEL, NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.method.evidence_signals import CONDITION_SHAPE_TEMPLATES, ShapeFeatures, shape_similarity
from sera.method.ranker import RankedCandidate


def guess_from_shape_only(
    commits: List[CommitInfo], observed_shape: ShapeFeatures
) -> RankedCandidate:
    scores = {
        cat: shape_similarity(observed_shape, template)
        for cat, template in CONDITION_SHAPE_TEMPLATES.items()
    }
    best_category = max(scores, key=scores.get)
    best_score = scores[best_category]

    if best_category == DRIFT_LABEL:
        return RankedCandidate(
            candidate_id=NO_COMMIT_CANDIDATE_ID,
            kind="drift",
            hypothesized_category=DRIFT_LABEL,
            provenance_score=0.0,
            shape_match_score=best_score,
            combined_score=best_score,
        )

    matching = [c for c in commits if best_category in c.risk_categories]
    if matching:
        chosen = max(matching, key=lambda c: c.timestamp)
    elif commits:
        chosen = max(commits, key=lambda c: c.timestamp)
    else:
        return RankedCandidate(
            candidate_id=NO_COMMIT_CANDIDATE_ID,
            kind="drift",
            hypothesized_category=DRIFT_LABEL,
            provenance_score=0.0,
            shape_match_score=best_score,
            combined_score=best_score,
        )

    return RankedCandidate(
        candidate_id=chosen.sha,
        kind="commit",
        hypothesized_category=best_category,
        provenance_score=0.0,  # by design: this baseline never uses provenance
        shape_match_score=best_score,
        combined_score=best_score,
        commit=chosen,
    )

"""Joint ranking over commits + an explicit "no commit, it's drift" hypothesis.

This is the core novel step: build one ranked candidate list containing
every commit in the window PLUS a `NO_COMMIT_CANDIDATE_ID` sentinel, score
each with cheap (zero re-execution) evidence, and sort. Only the winner
gets an expensive validation re-evaluation (see `validator.py`).

Score = PROVENANCE_WEIGHT * provenance_score + SHAPE_WEIGHT * shape_match_score

- provenance_score: 1.0 if the commit's diff touches a risk-category file
  matching its best-fit hypothesis, else 0.0. The drift hypothesis gets a
  fixed, commit-independent base rate (DRIFT_BASE_PROVENANCE) -- it is
  always a live hypothesis, never zero, and never boosted by any commit.
- shape_match_score: similarity between the observed confidence/entropy
  shift shape and the expected shape template for the candidate's
  hypothesized category (best-matching category for multi-category
  commits; the drift template for the drift candidate).

A commit that touches no risk-category file gets shape_match_score = 0:
it has no hypothesis to be credited for matching.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sera.conditions.registry import DRIFT_LABEL, NO_COMMIT_CANDIDATE_ID
from sera.github_integration.commit_types import CommitInfo
from sera.method.evidence_signals import (
    CONDITION_SHAPE_TEMPLATES,
    ShapeFeatures,
    shape_similarity,
)
from sera.repo_config import RepoConfig, stage_label

PROVENANCE_WEIGHT = 0.4
SHAPE_WEIGHT = 0.6
DRIFT_BASE_PROVENANCE = 0.35


@dataclass
class RankedCandidate:
    candidate_id: str
    kind: str  # "commit" or "drift"
    hypothesized_category: Optional[str]
    provenance_score: float
    shape_match_score: float
    combined_score: float
    commit: Optional[CommitInfo] = None

    def to_dict(self, repo_config: Optional[RepoConfig] = None) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "hypothesized_category": self.hypothesized_category,
            "stage_label": stage_label(self.hypothesized_category, repo_config)
            if self.hypothesized_category
            else None,
            "provenance_score": self.provenance_score,
            "shape_match_score": self.shape_match_score,
            "combined_score": self.combined_score,
            "commit_sha": self.commit.sha if self.commit else None,
            "commit_message": self.commit.message if self.commit else None,
            "commit_files": self.commit.files_changed if self.commit else None,
            "commit_file_patches": self.commit.file_patches if self.commit else None,
        }


def _best_category_match(
    risk_categories: List[str], observed: ShapeFeatures
) -> tuple:
    best_cat, best_score = None, 0.0
    for cat in risk_categories:
        template = CONDITION_SHAPE_TEMPLATES[cat]
        score = shape_similarity(observed, template)
        if score > best_score or best_cat is None:
            best_cat, best_score = cat, score
    return best_cat, best_score


def rank_candidates(
    commits: List[CommitInfo],
    observed_shape: ShapeFeatures,
    drift_prior: float = DRIFT_BASE_PROVENANCE,
) -> List[RankedCandidate]:
    candidates: List[RankedCandidate] = []

    for commit in commits:
        if commit.risk_categories:
            best_cat, shape_score = _best_category_match(commit.risk_categories, observed_shape)
            provenance = 1.0
        else:
            best_cat, shape_score, provenance = None, 0.0, 0.0
        combined = PROVENANCE_WEIGHT * provenance + SHAPE_WEIGHT * shape_score
        candidates.append(
            RankedCandidate(
                candidate_id=commit.sha,
                kind="commit",
                hypothesized_category=best_cat,
                provenance_score=provenance,
                shape_match_score=shape_score,
                combined_score=combined,
                commit=commit,
            )
        )

    drift_shape_score = shape_similarity(observed_shape, CONDITION_SHAPE_TEMPLATES[DRIFT_LABEL])
    drift_combined = PROVENANCE_WEIGHT * drift_prior + SHAPE_WEIGHT * drift_shape_score
    candidates.append(
        RankedCandidate(
            candidate_id=NO_COMMIT_CANDIDATE_ID,
            kind="drift",
            hypothesized_category=DRIFT_LABEL,
            provenance_score=drift_prior,
            shape_match_score=drift_shape_score,
            combined_score=drift_combined,
        )
    )

    # Deterministic ordering: score desc, then most-recent-commit-first as a
    # tie-break (drift sentinel has no timestamp -> sorts after equal-score commits).
    def sort_key(c: RankedCandidate):
        ts = c.commit.timestamp if c.commit else None
        return (-c.combined_score, -(ts.timestamp() if ts else 0))

    candidates.sort(key=sort_key)
    return candidates

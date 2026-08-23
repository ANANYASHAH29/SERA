"""Pydantic request/response models for the FastAPI app."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class RunSummary(BaseModel):
    run_id: int
    accuracy: float
    mean_confidence: float
    mean_entropy: float
    is_baseline: bool


class InjectRequest(BaseModel):
    condition: str  # F1, F2, F3, F4, F5, or D1
    severity: float = 0.9
    seed: Optional[int] = None


class IncidentSummary(BaseModel):
    incident_id: int
    baseline_run_id: int
    regressed_run_id: int
    accuracy_drop: float
    status: str


class SyntheticHistoryRequest(BaseModel):
    num_harmless: int = 4
    guilty_category: Optional[str] = None
    include_concurrent_unrelated: bool = False
    window_hours: int = 72
    seed: int = 42


class GithubHistoryRequest(BaseModel):
    repo_full_name: str
    since: str  # ISO datetime
    until: str  # ISO datetime
    token: Optional[str] = None


class RankedCandidateOut(BaseModel):
    rank: int
    candidate_id: str
    kind: str
    hypothesized_category: Optional[str]
    provenance_score: float
    shape_match_score: float
    combined_score: float
    commit_sha: Optional[str] = None
    commit_message: Optional[str] = None
    commit_files: Optional[List[str]] = None


class RankingResponse(BaseModel):
    incident_id: int
    observed_shape: dict
    candidates: List[RankedCandidateOut]


class ValidationResponse(BaseModel):
    incident_id: int
    candidate_id: str
    kind: str
    before_accuracy: float
    after_accuracy: float
    baseline_accuracy: float
    recovered: bool
    confirmed: bool

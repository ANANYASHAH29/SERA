"""Endpoints for detecting a regression, attaching commit-history evidence
(synthetic or real GitHub), and producing SERA's joint ranking.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from sera.api import state
from sera.api.schemas import (
    GithubHistoryRequest,
    IncidentSummary,
    RankedCandidateOut,
    RankingResponse,
    SyntheticHistoryRequest,
)
from sera.db.models import Incident, Run
from sera.db.session import session_scope
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.fetch_commits import fetch_commit_history
from sera.github_integration.synthetic_history import generate_synthetic_history
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_incident
from sera.method.ranker import rank_candidates

REGRESSION_THRESHOLD = 0.05

router = APIRouter(tags=["incidents"])


@router.post("/incidents/detect", response_model=IncidentSummary)
def detect_incident(baseline_run_id: int, regressed_run_id: int):
    with session_scope() as session:
        baseline_run = session.get(Run, baseline_run_id)
        regressed_run = session.get(Run, regressed_run_id)
        if baseline_run is None or regressed_run is None:
            raise HTTPException(404, "run not found")

        drop = baseline_run.accuracy - regressed_run.accuracy
        if drop < REGRESSION_THRESHOLD:
            raise HTTPException(
                400, f"accuracy drop {drop:.3f} below detection threshold {REGRESSION_THRESHOLD}"
            )

        incident = record_incident(session, baseline_run, regressed_run)
        return IncidentSummary(
            incident_id=incident.id,
            baseline_run_id=baseline_run.id,
            regressed_run_id=regressed_run.id,
            accuracy_drop=drop,
            status=incident.status,
        )


@router.post("/incidents/{incident_id}/history/synthetic")
def attach_synthetic_history(incident_id: int, req: SyntheticHistoryRequest):
    commits = generate_synthetic_history(
        num_harmless=req.num_harmless,
        guilty_category=req.guilty_category,
        include_concurrent_unrelated=req.include_concurrent_unrelated,
        window_hours=req.window_hours,
        seed=req.seed,
    )
    classify_commits(commits)
    state.store_incident_commits(incident_id, commits)
    return {"incident_id": incident_id, "num_commits": len(commits)}


@router.post("/incidents/{incident_id}/history/github")
def attach_github_history(incident_id: int, req: GithubHistoryRequest):
    commits = fetch_commit_history(
        req.repo_full_name,
        since=datetime.fromisoformat(req.since),
        until=datetime.fromisoformat(req.until),
        token=req.token,
    )
    classify_commits(commits)
    state.store_incident_commits(incident_id, commits)
    return {"incident_id": incident_id, "num_commits": len(commits)}


@router.post("/incidents/{incident_id}/rank", response_model=RankingResponse)
def rank_incident(incident_id: int):
    from sera.pipeline.runner import run_pipeline

    with session_scope() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(404, "incident not found")

        baseline_ctx = state.get_run_context(incident.baseline_run_id)
        regressed_ctx = state.get_run_context(incident.regressed_run_id)
        if baseline_ctx is None or regressed_ctx is None:
            raise HTTPException(
                409, "run context not in memory (runs must be created in this API session)"
            )

        baseline_config, baseline_batch, _ = baseline_ctx
        regressed_config, regressed_batch, _ = regressed_ctx

        baseline_metrics = run_pipeline(baseline_config, baseline_batch)
        regressed_metrics = run_pipeline(regressed_config, regressed_batch)
        observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)

        commits = state.get_incident_commits(incident_id)
        ranked = rank_candidates(commits, observed_shape)
        state.store_incident_ranking(incident_id, ranked)

        return RankingResponse(
            incident_id=incident_id,
            observed_shape=observed_shape.__dict__,
            candidates=[
                RankedCandidateOut(rank=i, **c.to_dict()) for i, c in enumerate(ranked)
            ],
        )

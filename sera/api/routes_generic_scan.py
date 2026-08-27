"""B3 API: confidence-gated sklearn/tabular auto-detection, wired to a
manual JSON-paste ingestion endpoint. Nothing here executes a connected
repo's code -- detect-signals and canary-draft are static analysis only
(see repo_scanner.py's docstring for why), and ingest-scan-result only
ever receives JSON the repo owner pasted in themselves after running the
(draft or hand-written) canary_eval.py on their own machine or CI.

This is deliberately a separate ingestion path from routes_report.py's
token-authenticated /report/{repo_id}/scan: that one is for an unattended
CI step reporting on a schedule; this one is for a logged-in tenant
manually confirming a result through the dashboard UI, so it's
user_id-authenticated (via sera.method.tenancy) instead of token-authenticated.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sera.api.routes_report import _fetch_and_classify_commits
from sera.db.models import ConnectedRepo, ScanResult
from sera.db.session import session_scope
from sera.method import tenancy
from sera.method.canary_draft_generator import generate_canary_draft
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_run
from sera.method.ranker import rank_candidates
from sera.method.repo_scanner import scan_repo_for_sklearn_signals
from sera.pipeline.evaluation import RunMetrics

router = APIRouter(prefix="/tenant", tags=["generic-scan"])

REGRESSION_THRESHOLD = 0.05


class GenericScanResult(BaseModel):
    task_type: str
    primary_metric: float
    primary_metric_name: str
    secondary_metrics: Dict[str, float] = {}
    per_sample_scores: List[int]
    n_samples: int
    canary_set_hash: Optional[str] = None


def _generic_to_run_metrics(result: GenericScanResult) -> RunMetrics:
    """Adapts the generic (task-agnostic) schema into the same RunMetrics
    shape the frozen ranker/evidence_signals already consume. The generic
    schema has no per-sample confidence field (only per-sample
    correctness) -- broadcasting the aggregate mean_confidence to every
    sample is a documented approximation, same pattern as
    canary_interface.to_run_metrics uses for entropy when only a mean is
    given. This weakens the "confident_but_wrong" shape signal's fidelity
    specifically; it doesn't break the pipeline.
    """
    correct = np.array([bool(x) for x in result.per_sample_scores], dtype=bool)
    mean_confidence = result.secondary_metrics.get("mean_confidence", 0.5)
    mean_entropy = result.secondary_metrics.get("mean_entropy", 0.0)
    confidence = np.full(len(correct), mean_confidence, dtype=float)
    entropy = np.full(len(correct), mean_entropy, dtype=float)

    return RunMetrics(
        accuracy=result.primary_metric,
        mean_confidence=mean_confidence,
        mean_entropy=mean_entropy,
        per_image_confidence=confidence,
        per_image_entropy=entropy,
        per_image_correct=correct,
        predictions=np.zeros(len(correct), dtype=int),
    )


@router.get("/repos/{repo_id}/detect-signals")
def detect_signals(repo_id: int, user_id: int):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
        repo_full_name = repo.repo_full_name
        token = tenancy.get_installation_token_for_repo(session, repo)

    signals = scan_repo_for_sklearn_signals(repo_full_name, token=token)
    return signals.to_dict()


@router.get("/repos/{repo_id}/canary-draft")
def canary_draft(repo_id: int, user_id: int):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
        repo_full_name = repo.repo_full_name
        token = tenancy.get_installation_token_for_repo(session, repo)

    signals = scan_repo_for_sklearn_signals(repo_full_name, token=token)
    if not signals.all_signals_found:
        raise HTTPException(
            409,
            {
                "message": "not all signals detected -- use the manual canary_eval.py + JSON-paste flow instead",
                "missing_signals": signals.missing_signals(),
            },
        )
    return {"draft": generate_canary_draft(signals), "signals": signals.to_dict()}


@router.post("/repos/{repo_id}/ingest-scan-result")
def ingest_scan_result(repo_id: int, user_id: int, result: GenericScanResult):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")

        current_metrics = _generic_to_run_metrics(result)

        if repo.generic_baseline_snapshot_json is None:
            repo.generic_baseline_snapshot_json = json.dumps(result.model_dump())
            repo.last_scan_at = datetime.utcnow()
            # Record the bootstrap itself as a healthy scan too -- otherwise
            # the accuracy-over-time graph has no starting point until a
            # SECOND result ever arrives, which looks like data went missing.
            run = record_run(session, _placeholder_config(), current_metrics, seed=None, is_baseline=True)
            scan = ScanResult(
                repo_id=repo.id,
                run_id=run.id,
                status="healthy",
                summary_json=json.dumps(
                    {
                        "task_type": result.task_type,
                        "primary_metric_name": result.primary_metric_name,
                        "baseline_metric": result.primary_metric,
                        "current_metric": result.primary_metric,
                        "metric_drop": 0.0,
                        "secondary_metrics": result.secondary_metrics,
                        "candidates": [],
                    }
                ),
            )
            session.add(scan)
            session.flush()
            return {"status": "baseline_set", "primary_metric": result.primary_metric, "scan_id": scan.id}

        baseline_dict = json.loads(repo.generic_baseline_snapshot_json)
        baseline_result = GenericScanResult(**baseline_dict)
        baseline_metrics = _generic_to_run_metrics(baseline_result)

        drop = baseline_result.primary_metric - result.primary_metric
        observed_shape = compute_shape_features(baseline_metrics, current_metrics)

        if drop < REGRESSION_THRESHOLD:
            status = "healthy"
            repo.generic_baseline_snapshot_json = json.dumps(result.model_dump())  # rolling baseline
            candidates_out = []
        else:
            status = "incident"
            commits = _fetch_and_classify_commits(session, repo)
            ranked = rank_candidates(commits, observed_shape)
            candidates_out = [
                {
                    "rank": i,
                    "candidate_id": c.candidate_id,
                    "kind": c.kind,
                    "hypothesized_category": c.hypothesized_category,
                    "provenance_score": c.provenance_score,
                    "shape_match_score": c.shape_match_score,
                    "combined_score": c.combined_score,
                    "commit_sha": c.commit.sha if c.commit else None,
                    "commit_message": c.commit.message if c.commit else None,
                }
                for i, c in enumerate(ranked)
            ]

        run = record_run(session, _placeholder_config(), current_metrics, seed=None, is_baseline=False)
        scan = ScanResult(
            repo_id=repo.id,
            run_id=run.id,
            status=status,
            summary_json=json.dumps(
                {
                    "task_type": result.task_type,
                    "primary_metric_name": result.primary_metric_name,
                    "baseline_metric": baseline_result.primary_metric,
                    "current_metric": result.primary_metric,
                    "metric_drop": drop,
                    "secondary_metrics": result.secondary_metrics,
                    "observed_shape": {
                        "broadness": observed_shape.broadness,
                        "subset_concentration": observed_shape.subset_concentration,
                        "confident_but_wrong": observed_shape.confident_but_wrong,
                    },
                    "candidates": candidates_out,
                }
            ),
        )
        session.add(scan)
        repo.last_scan_at = datetime.utcnow()
        session.flush()

        return {"status": status, "scan_id": scan.id, "metric_drop": drop}


def _placeholder_config():
    from sera.config import baseline_config

    return baseline_config()

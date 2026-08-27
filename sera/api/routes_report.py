"""Ingestion endpoint for real scan results, reported by a connected
repo's OWN CI -- not run by SERA's infrastructure. This is the actual
answer to "how would someone really use this": SERA never clones or
executes a stranger's code (see the long comment on
ConnectedRepo.report_token in sera/db/models.py for why that would be a
real security liability, not just missing work). Instead:

  1. The repo owner adds a small step to their own GitHub Actions workflow
     (see templates/sera_report_scan.yml) that runs THEIR OWN canary
     entrypoint -- already sandboxed by GitHub Actions, already has their
     real dependencies installed, already running their real code.
  2. That step POSTs the resulting accuracy/confidence/entropy JSON here,
     authenticated by a per-repo secret token (never the GitHub
     installation token, which would be far too broad a credential to
     hand to a repo's own CI).
  3. This endpoint diffs against the last known-good baseline (stored on
     ConnectedRepo, bootstrapped by the first report ever received), and
     on a regression, fetches that repo's own recent commit history
     (via the *installation's* scoped GitHub client) and runs the same
     frozen ranking logic every other path in this codebase uses.

This is the same pattern Codecov/Sentry/DeepSource use: you run their
small reporter in your own CI, you never hand them your code to execute.
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sera.canary_interface import CanaryEvalResult, to_run_metrics
from sera.db.models import ConnectedRepo, ScanResult, User
from sera.db.session import session_scope
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.fetch_commits import fetch_commit_history
from sera.github_integration.github_app import get_installation_token
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_run
from sera.method.ranker import rank_candidates
from sera.repo_config import load_repo_config_from_github

router = APIRouter(prefix="/report", tags=["report"])

REGRESSION_THRESHOLD = 0.05
LOOKBACK_HOURS = 24


class ReportScanRequest(BaseModel):
    report_token: str
    accuracy: float
    mean_confidence: float
    mean_entropy: float = 0.0
    per_sample_confidence: list[float]
    per_sample_correct: list[bool]


def _snapshot_to_result(snapshot_json: str) -> CanaryEvalResult:
    d = json.loads(snapshot_json)
    return CanaryEvalResult.from_dict(d)


def _result_to_snapshot(result: CanaryEvalResult) -> str:
    return json.dumps(
        {
            "accuracy": result.accuracy,
            "mean_confidence": result.mean_confidence,
            "mean_entropy": result.mean_entropy,
            "per_sample_confidence": result.per_sample_confidence,
            "per_sample_correct": result.per_sample_correct,
        }
    )


@router.post("/{repo_id}/scan")
def report_scan(repo_id: int, req: ReportScanRequest):
    with session_scope() as session:
        repo = session.query(ConnectedRepo).filter_by(id=repo_id).one_or_none()
        # constant-time compare, and the same 404 regardless of "repo
        # missing" vs "token wrong" -- don't let a prober distinguish
        # valid repo ids from invalid ones via response differences.
        if repo is None or not repo.report_token or not hmac.compare_digest(
            repo.report_token, req.report_token
        ):
            raise HTTPException(404, "not found")

        current = CanaryEvalResult(
            accuracy=req.accuracy,
            mean_confidence=req.mean_confidence,
            mean_entropy=req.mean_entropy,
            per_sample_confidence=req.per_sample_confidence,
            per_sample_correct=req.per_sample_correct,
        )

        if repo.baseline_snapshot_json is None:
            repo.baseline_snapshot_json = _result_to_snapshot(current)
            repo.last_scan_at = datetime.utcnow()
            session.flush()
            return {"status": "baseline_set", "accuracy": current.accuracy}

        baseline = _snapshot_to_result(repo.baseline_snapshot_json)
        drop = baseline.accuracy - current.accuracy

        baseline_metrics = to_run_metrics(baseline)
        current_metrics = to_run_metrics(current)

        if drop < REGRESSION_THRESHOLD:
            status = "healthy"
            repo.baseline_snapshot_json = _result_to_snapshot(current)  # rolling baseline
            candidates_out = []
        else:
            status = "incident"
            observed_shape = compute_shape_features(baseline_metrics, current_metrics)
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
            # baseline deliberately NOT advanced on incident -- keeps
            # measuring against the last known-good state until it's
            # actually fixed, matching real monitoring semantics.

        run = record_run(session, _placeholder_config(), current_metrics, seed=None, is_baseline=False)
        scan = ScanResult(
            repo_id=repo.id,
            run_id=run.id,
            status=status,
            summary_json=json.dumps(
                {
                    "baseline_accuracy": baseline.accuracy,
                    "regressed_accuracy": current.accuracy,
                    "accuracy_drop": drop,
                    "candidates": candidates_out,
                }
            ),
        )
        session.add(scan)
        repo.last_scan_at = datetime.utcnow()
        session.flush()

        return {"status": status, "scan_id": scan.id, "accuracy_drop": drop}


def _fetch_and_classify_commits(session, repo: ConnectedRepo):
    user = session.query(User).filter_by(id=repo.user_id).one_or_none()
    if user is None or not user.github_app_installation_id:
        return []  # no installation to fetch commits with -- rank against drift-only
    try:
        token = get_installation_token(user.github_app_installation_id)
        since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
        until = datetime.now(timezone.utc)
        commits = fetch_commit_history(repo.repo_full_name, since=since, until=until, token=token)
        repo_config = load_repo_config_from_github(repo.repo_full_name, ref="HEAD", token=token)
        classify_commits(commits, repo_config=repo_config)
        return commits
    except Exception:
        # commit history is supporting evidence, not required to detect
        # the regression at all -- degrade to a drift-only ranking rather
        # than failing the whole report.
        return []


def _placeholder_config():
    from sera.config import baseline_config

    return baseline_config()

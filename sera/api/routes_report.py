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
from sera.db.models import ConnectedRepo, ScanResult, to_utc_iso
from sera.db.session import session_scope
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.fetch_commits import fetch_commit_history
from sera.method.evidence_signals import compute_shape_features
from sera.method.generic_scan import GenericScanResult, process_generic_scan_result
from sera.method.memory import record_run
from sera.method.ranker import rank_candidates
from sera.method.validation import record_interventions, record_validation
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
            commits, repo_config, window_since = _fetch_and_classify_commits(session, repo)
            ranked = rank_candidates(commits, observed_shape)
            visible = [c for c in ranked if c.kind == "drift" or c.combined_score > 0]
            candidates_out = [{"rank": i, **c.to_dict(repo_config)} for i, c in enumerate(visible)]
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
                    # window_since is already tz-aware (see _candidate_window_start) --
                    # plain isoformat() already carries a correct +00:00 offset.
                    "window_since": window_since.isoformat() if status == "incident" else None,
                    "commits_analyzed": len(commits) if status == "incident" else 0,
                    "commits_relevant": sum(1 for c in visible if c.kind == "commit") if status == "incident" else 0,
                    "candidates": candidates_out,
                }
            ),
        )
        session.add(scan)
        repo.last_scan_at = datetime.utcnow()
        session.flush()

        return {"status": status, "scan_id": scan.id, "accuracy_drop": drop}


class GenericReportRequest(GenericScanResult):
    report_token: str


@router.post("/{repo_id}/generic-scan")
def report_generic_scan(repo_id: int, req: GenericReportRequest):
    """Same token-auth contract as /scan above, for the generic (e.g.
    sklearn/tabular) schema instead of the CV-style one -- so a repo
    using scripts/report_scan.py's auto-detected schema can report
    through CI the exact same way a CV pipeline does. Shares its
    processing logic with the dashboard's manual-paste endpoint via
    sera.method.generic_scan, so a result behaves identically either way.
    """
    with session_scope() as session:
        repo = session.query(ConnectedRepo).filter_by(id=repo_id).one_or_none()
        if repo is None or not repo.report_token or not hmac.compare_digest(
            repo.report_token, req.report_token
        ):
            raise HTTPException(404, "not found")

        result = GenericScanResult(**req.model_dump(exclude={"report_token"}))
        return process_generic_scan_result(session, repo, result, _fetch_and_classify_commits, source="ci")


class ValidateScanRequest(BaseModel):
    report_token: str
    scan_id: int
    files_reverted: list[str]
    after_metric: float


@router.post("/{repo_id}/validate-scan")
def report_validation(repo_id: int, req: ValidateScanRequest):
    """Second, follow-up report for the controlled-intervention step: the
    tenant's own CI reverted the suspect commit's flagged files, re-ran the
    canary, and is reporting whether accuracy recovered. Same token-auth
    contract as the scan-report endpoints above; entirely optional -- an
    incident is complete evidence on its own, this just adds confirmation.
    """
    with session_scope() as session:
        repo = session.query(ConnectedRepo).filter_by(id=repo_id).one_or_none()
        if repo is None or not repo.report_token or not hmac.compare_digest(
            repo.report_token, req.report_token
        ):
            raise HTTPException(404, "not found")

        scan = session.query(ScanResult).filter_by(id=req.scan_id, repo_id=repo_id).one_or_none()
        if scan is None:
            raise HTTPException(404, "scan not found")

        validation = record_validation(scan, req.files_reverted, req.after_metric)
        session.flush()
        return {"status": "validated", "recovered": validation["recovered"]}


class InterventionAttemptIn(BaseModel):
    commit_sha: str
    stage_label: Optional[str] = None
    files_reverted: list[str]
    after_metric: float
    combined: bool = False


class ValidateScanSequenceRequest(BaseModel):
    report_token: str
    scan_id: int
    interventions: list[InterventionAttemptIn]


@router.post("/{repo_id}/validate-scan-sequence")
def report_validation_sequence(repo_id: int, req: ValidateScanSequenceRequest):
    """Sequential-validation version of /validate-scan: the tenant's CI
    tried more than one candidate's revert (and, if none alone recovered
    the baseline, the combined revert of every candidate that showed
    real individual improvement) -- see scripts/report_scan.py's
    run_intervention_sequence. Stores the full attempt sequence with a
    three-way verdict per attempt (validated / insufficient-as-sole-cause
    / not-supported) instead of collapsing everything to one
    recovered/not-recovered boolean, which is what makes a deterministic
    multi-fault recovery plan possible afterward.
    """
    with session_scope() as session:
        repo = session.query(ConnectedRepo).filter_by(id=repo_id).one_or_none()
        if repo is None or not repo.report_token or not hmac.compare_digest(
            repo.report_token, req.report_token
        ):
            raise HTTPException(404, "not found")

        scan = session.query(ScanResult).filter_by(id=req.scan_id, repo_id=repo_id).one_or_none()
        if scan is None:
            raise HTTPException(404, "scan not found")

        attempts = [a.model_dump() for a in req.interventions]
        recorded = record_interventions(scan, attempts)
        session.flush()
        return {"status": "recorded", "interventions": recorded}


def _candidate_window_start(session, repo: ConnectedRepo):
    """Bisection interval start: the timestamp this repo was LAST known
    healthy, not a fixed clock window. A fixed 24h lookback keeps already
    -fixed regressions in the candidate pool right alongside the new one
    -- every commit since the last real fix looks equally guilty (same
    risk category, same file, same observed shape), so the ranking can't
    tell them apart and picks an arbitrary winner. Bounding to "since
    last healthy" is what real commit-bisection does: only changes that
    happened between the last known-good state and now could possibly be
    the cause of THIS regression.
    """
    last_healthy = (
        session.query(ScanResult)
        .filter_by(repo_id=repo.id, status="healthy")
        .order_by(ScanResult.created_at.desc())
        .first()
    )
    if last_healthy is not None:
        return last_healthy.created_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)


def _fetch_and_classify_commits(session, repo: ConnectedRepo):
    """Returns (commits, repo_config, window_since) -- repo_config is
    surfaced alongside the commits (not just used internally for
    classification) so callers can render real pipeline-stage names for
    the risk categories it declares, e.g. `.sera.yml`'s "F5_checkpoint"
    -> "Checkpoint". window_since is the bisection interval's start, for
    callers that want to show "N commits analyzed since <time>".
    """
    from sera.method.tenancy import get_installation_token_for_repo

    since = _candidate_window_start(session, repo)
    token = get_installation_token_for_repo(session, repo)
    if token is None:
        return [], None, since  # no installation to fetch commits with -- rank against drift-only
    try:
        until = datetime.now(timezone.utc)
        commits = fetch_commit_history(repo.repo_full_name, since=since, until=until, token=token)
        repo_config = load_repo_config_from_github(repo.repo_full_name, ref="HEAD", token=token)
        classify_commits(commits, repo_config=repo_config)
        return commits, repo_config, since
    except Exception:
        # commit history is supporting evidence, not required to detect
        # the regression at all -- degrade to a drift-only ranking rather
        # than failing the whole report.
        return [], None, since


def _placeholder_config():
    from sera.config import baseline_config

    return baseline_config()

"""B3 API: confidence-gated sklearn/tabular auto-detection, wired to a
manual JSON-paste ingestion endpoint. Nothing here executes a connected
repo's code -- detect-signals and canary-draft are static analysis only
(see repo_scanner.py's docstring for why), and ingest-scan-result only
ever receives JSON the repo owner pasted in themselves after running the
(draft or hand-written) canary_eval.py on their own machine or CI.

This is deliberately a separate ingestion path from routes_report.py's
token-authenticated /report/{repo_id}/generic-scan: that one is for an
unattended CI step reporting on a schedule; this one is for a logged-in
tenant manually confirming a result through the dashboard UI, so it's
user_id-authenticated (via sera.method.tenancy) instead of
token-authenticated. Both share the same core processing logic in
sera.method.generic_scan, so a result behaves identically either way.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sera.api.routes_report import _fetch_and_classify_commits
from sera.db.session import session_scope
from sera.method import tenancy
from sera.method.canary_draft_generator import generate_canary_draft
from sera.method.generic_scan import GenericScanResult, process_generic_scan_result
from sera.method.repo_scanner import scan_repo_for_sklearn_signals

router = APIRouter(prefix="/tenant", tags=["generic-scan"])


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
        return process_generic_scan_result(session, repo, result, _fetch_and_classify_commits)

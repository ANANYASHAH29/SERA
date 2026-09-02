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

import secrets

from fastapi import APIRouter, HTTPException

from sera.api.routes_report import _fetch_and_classify_commits
from sera.db.session import session_scope
from sera.method import tenancy
from sera.method.canary_draft_generator import generate_canary_draft
from sera.method.ci_autosetup import setup_ci_reporting
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


@router.post("/repos/{repo_id}/setup-ci-automation")
def setup_ci_automation(repo_id: int, user_id: int, base_url: str = "http://127.0.0.1:8000"):
    """Replaces the "copy these files, set these three secrets by hand"
    Settings-page instructions with one click: commits the workflow +
    reporter script and sets SERA_DASHBOARD_URL/SERA_REPO_ID/
    SERA_REPORT_TOKEN directly via the installation token. Needs the App
    to actually hold Contents+Workflows+Secrets write permission on this
    installation -- a 403 here means the repo owner hasn't approved that
    broader permission grant on GitHub's own consent screen yet, which is
    a real, necessary step this endpoint can't skip.
    """
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")

        if not repo.report_token:
            repo.report_token = secrets.token_urlsafe(32)
            session.flush()

        token = tenancy.get_installation_token_for_repo(session, repo)
        if token is None:
            raise HTTPException(409, "no live GitHub installation for this repo -- reconnect it first")

        repo_full_name = repo.repo_full_name
        repo_pk = repo.id
        report_token = repo.report_token

    try:
        return setup_ci_reporting(repo_full_name, token, base_url, repo_pk, report_token)
    except Exception as e:
        # Broad on purpose: PyGithub's exception hierarchy for a 403 from
        # the /actions/secrets endpoints isn't consistent across versions
        # (a bare `except GithubException` here previously let some of
        # them escape as an unhandled 500) -- every failure mode from this
        # call is "GitHub rejected the automated setup," so surface all of
        # them as the same actionable 403 rather than crash.
        raise HTTPException(
            403,
            {
                "message": (
                    "GitHub rejected the automated setup -- the App likely doesn't have "
                    "Contents, Workflows, and Secrets write permission approved on this "
                    "installation yet. Update the App's permissions and approve the request "
                    "on GitHub, then retry."
                ),
                "github_error": str(e),
            },
        )


@router.post("/repos/{repo_id}/ingest-scan-result")
def ingest_scan_result(repo_id: int, user_id: int, result: GenericScanResult):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
        return process_generic_scan_result(session, repo, result, _fetch_and_classify_commits)

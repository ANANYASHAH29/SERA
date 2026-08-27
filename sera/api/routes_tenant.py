"""Multi-tenant "connect your repo" API: install-url, repo picker,
connect/disconnect, and settings (.sera.yml status + template, badge
markdown). Every route that takes a repo id resolves it through
sera.method.tenancy so one user can never see another's data.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sera.conditions.registry import ALL_CATEGORIES, CONFIG_CONDITIONS, DRIFT_CONDITION, DRIFT_LABEL
from sera.config import baseline_config
from sera.db.models import ConnectedRepo, ScanResult, User
from sera.db.session import session_scope
from sera.github_integration.diff_analyzer import classify_commits
from sera.github_integration.github_app import (
    GitHubAppNotConfigured,
    get_installation_client,
)
from sera.github_integration.synthetic_history import generate_synthetic_history
from sera.method import tenancy
from sera.method.evidence_signals import compute_shape_features
from sera.method.memory import record_run
from sera.method.ranker import rank_candidates
from sera.pipeline.ingestion import build_canary_set
from sera.pipeline.runner import run_pipeline
from sera.repo_config import generate_starter_template, load_repo_config_from_github

router = APIRouter(prefix="/tenant", tags=["tenant"])


class ConnectRepoRequest(BaseModel):
    user_id: int
    repo_full_name: str


class RepoOut(BaseModel):
    id: int
    repo_full_name: str
    sera_yml_status: str
    connected_at: str
    last_scan_at: Optional[str]
    health_status: str  # healthy | incident | pending | never_scanned
    incident_count: int


def _repo_to_out(session, repo: ConnectedRepo) -> RepoOut:
    latest_scan = (
        session.query(ScanResult)
        .filter_by(repo_id=repo.id)
        .order_by(ScanResult.created_at.desc())
        .first()
    )
    incident_count = (
        session.query(ScanResult).filter_by(repo_id=repo.id, status="incident").count()
    )
    return RepoOut(
        id=repo.id,
        repo_full_name=repo.repo_full_name,
        sera_yml_status=repo.sera_yml_status,
        connected_at=repo.connected_at.isoformat(),
        last_scan_at=repo.last_scan_at.isoformat() if repo.last_scan_at else None,
        health_status=latest_scan.status if latest_scan else "never_scanned",
        incident_count=incident_count,
    )


@router.get("/install-url")
def install_url():
    slug = os.environ.get("GITHUB_APP_SLUG")
    if not slug:
        raise HTTPException(
            500,
            "GITHUB_APP_SLUG is not set -- run scripts/register_github_app.py first "
            "(see README 'Setting up the GitHub App').",
        )
    return {"install_url": f"https://github.com/apps/{slug}/installations/new"}


@router.get("/users/by-installation/{installation_id}")
def get_user_by_installation(installation_id: int):
    """Called after the GitHub install redirect lands back on the
    frontend with an installation_id -- resolves it to (or creates) the
    local User row, since the webhook may not have arrived yet.
    """
    with session_scope() as session:
        user = (
            session.query(User)
            .filter_by(github_app_installation_id=installation_id)
            .one_or_none()
        )
        if user is None:
            raise HTTPException(
                404,
                "no user found for this installation yet -- the installation webhook "
                "may still be in flight, try again in a moment",
            )
        return {"user_id": user.id, "github_username": user.github_username}


@router.get("/installations/{installation_id}/available-repos")
def available_repos(installation_id: int) -> List[str]:
    """Repos this installation was granted access to, per GitHub -- not
    yet necessarily connected (enabled) in SERA.
    """
    try:
        client = get_installation_client(installation_id)
    except GitHubAppNotConfigured as e:
        raise HTTPException(500, str(e))
    return [repo.full_name for repo in client.get_repos()]


@router.get("/repos", response_model=List[RepoOut])
def list_repos(user_id: int):
    with session_scope() as session:
        repos = tenancy.list_owned_repos(session, user_id)
        return [_repo_to_out(session, r) for r in repos]


@router.post("/repos", response_model=RepoOut)
def connect_repo(req: ConnectRepoRequest):
    with session_scope() as session:
        existing = (
            session.query(ConnectedRepo)
            .filter_by(user_id=req.user_id, repo_full_name=req.repo_full_name)
            .one_or_none()
        )
        if existing:
            return _repo_to_out(session, existing)

        repo = ConnectedRepo(
            user_id=req.user_id, repo_full_name=req.repo_full_name, sera_yml_status="missing"
        )
        session.add(repo)
        session.flush()

        try:
            config = load_repo_config_from_github(req.repo_full_name, ref="HEAD")
            repo.sera_yml_status = "present" if config else "missing"
        except Exception:
            repo.sera_yml_status = "missing"  # can't reach the repo yet -- not fatal to connecting

        session.flush()
        return _repo_to_out(session, repo)


@router.delete("/repos/{repo_id}")
def disconnect_repo(repo_id: int, user_id: int):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
        session.delete(repo)
    return {"status": "disconnected"}


@router.get("/repos/{repo_id}/sera-yml-template")
def sera_yml_template(repo_id: int, user_id: int):
    with session_scope() as session:
        try:
            tenancy.get_owned_repo(session, user_id, repo_id)  # raises if not owned
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
    return {"template": generate_starter_template()}


@router.get("/repos/{repo_id}/scans")
def repo_scans(repo_id: int, user_id: int):
    with session_scope() as session:
        try:
            results = tenancy.list_owned_scan_results(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
        return [
            {
                "id": r.id,
                "run_id": r.run_id,
                "status": r.status,
                "summary_json": r.summary_json,
                "created_at": r.created_at.isoformat(),
            }
            for r in results
        ]


@router.get("/repos/{repo_id}/badge-markdown")
def badge_markdown(repo_id: int, user_id: int, base_url: str = "http://127.0.0.1:8000"):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")
        owner, name = repo.repo_full_name.split("/", 1)
        badge_url = f"{base_url}/badge/{owner}/{name}"
        return {"markdown": f"![SERA status]({badge_url})", "badge_url": badge_url}


class ScanRequest(BaseModel):
    # None -> healthy scan. Otherwise one of F1-F5/D1 -- injected against
    # SERA's own reference CIFAR-10 pipeline, NOT the tenant's actual repo
    # code. Actually cloning and executing an arbitrary connected repo's
    # own canary entrypoint per scan needs sandboxed execution and a
    # background job queue, neither of which exist in this build (see the
    # same documented boundary in routes_webhook._handle_pull_request_event).
    # This still exercises the real diagnostic engine end-to-end -- real
    # inference, real ranking -- it just isn't scanning the tenant's own
    # code. Labeled as such in the dashboard UI, not silently implied.
    condition: Optional[str] = None
    seed: int = 0


@router.post("/repos/{repo_id}/scan")
def run_demo_scan(repo_id: int, user_id: int, req: ScanRequest):
    import datetime as dt

    if req.condition is not None and req.condition not in ALL_CATEGORIES:
        raise HTTPException(400, f"unknown condition {req.condition!r}")

    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")

        base_config = baseline_config()
        canary = build_canary_set()
        baseline_metrics = run_pipeline(base_config, canary, corruption_seed=req.seed)

        if req.condition is None:
            regressed_config, regressed_batch = base_config, canary
        elif req.condition == DRIFT_LABEL:
            from dataclasses import replace

            shifted = DRIFT_CONDITION.apply_to_images(canary.images, severity=1.0, seed=req.seed + 900)
            regressed_config, regressed_batch = base_config, replace(canary, images=shifted)
        else:
            regressed_config = CONFIG_CONDITIONS[req.condition].apply(base_config, severity=1.0)
            regressed_batch = canary
        regressed_metrics = run_pipeline(regressed_config, regressed_batch, corruption_seed=req.seed)

        drop = baseline_metrics.accuracy - regressed_metrics.accuracy
        if drop < 0.05:
            status = "healthy"
            candidates_out = []
        else:
            status = "incident"
            observed_shape = compute_shape_features(baseline_metrics, regressed_metrics)
            guilty_category = None if req.condition == DRIFT_LABEL else req.condition
            commits = generate_synthetic_history(
                num_harmless=4, guilty_category=guilty_category, seed=req.seed
            )
            classify_commits(commits)
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

        run = record_run(session, regressed_config, regressed_metrics, seed=req.seed, is_baseline=False)
        scan = ScanResult(
            repo_id=repo.id,
            run_id=run.id,
            status=status,
            summary_json=json.dumps(
                {
                    "baseline_accuracy": baseline_metrics.accuracy,
                    "regressed_accuracy": regressed_metrics.accuracy,
                    "accuracy_drop": drop,
                    "candidates": candidates_out,
                }
            ),
        )
        session.add(scan)
        repo.last_scan_at = dt.datetime.utcnow()
        session.flush()

        return {
            "scan_id": scan.id,
            "status": status,
            "baseline_accuracy": baseline_metrics.accuracy,
            "regressed_accuracy": regressed_metrics.accuracy,
        }

"""Receives GitHub App webhook events (installation created/deleted,
repos added/removed, PRs opened). Every payload is signature-verified
before anything in it is trusted -- see github_app.verify_webhook_signature.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from sera.db.models import ConnectedRepo
from sera.db.session import session_scope
from sera.github_integration.github_app import (
    GitHubAppNotConfigured,
    verify_webhook_signature,
)
from sera.method.tenancy import get_or_create_user

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("sera.webhooks")


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=None),
    x_github_event: str = Header(default=None),
):
    body = await request.body()
    try:
        if not verify_webhook_signature(body, x_hub_signature_256):
            raise HTTPException(401, "invalid webhook signature")
    except GitHubAppNotConfigured as e:
        raise HTTPException(500, str(e))

    payload = json.loads(body)
    action = payload.get("action")

    if x_github_event == "installation":
        _handle_installation_event(action, payload)
    elif x_github_event == "installation_repositories":
        _handle_installation_repositories_event(action, payload)
    elif x_github_event == "pull_request":
        _handle_pull_request_event(action, payload)
    else:
        logger.info("unhandled webhook event type: %s", x_github_event)

    return {"status": "accepted"}


def _handle_installation_event(action: str, payload: dict) -> None:
    installation = payload["installation"]
    installation_id = installation["id"]
    account_login = installation["account"]["login"]

    with session_scope() as session:
        if action == "created":
            user = get_or_create_user(session, account_login, installation_id)
            repos = payload.get("repositories", [])
            for repo in repos:
                _upsert_connected_repo(session, user.id, repo["full_name"])
        elif action == "deleted":
            user = get_or_create_user(session, account_login, None)
            user.github_app_installation_id = None
            # repos stay in connected_repos (historical scan data preserved)
            # but future scans will fail auth until reinstalled -- that's
            # the correct behavior, not a bug to paper over.


def _handle_installation_repositories_event(action: str, payload: dict) -> None:
    installation = payload["installation"]
    account_login = installation["account"]["login"]
    installation_id = installation["id"]

    with session_scope() as session:
        user = get_or_create_user(session, account_login, installation_id)
        if action == "added":
            for repo in payload.get("repositories_added", []):
                _upsert_connected_repo(session, user.id, repo["full_name"])
        elif action == "removed":
            removed_names = {r["full_name"] for r in payload.get("repositories_removed", [])}
            for repo in (
                session.query(ConnectedRepo)
                .filter(ConnectedRepo.user_id == user.id, ConnectedRepo.repo_full_name.in_(removed_names))
                .all()
            ):
                session.delete(repo)


def _handle_pull_request_event(action: str, payload: dict) -> None:
    # A full PR scan needs a real inference pass (seconds to minutes) --
    # too slow to run inline in a webhook handler, which GitHub expects to
    # respond to in well under 10s. A production deployment would enqueue
    # this onto a background worker; that queue doesn't exist in this
    # research-prototype build, so we log intent only. scripts/pr_check.py
    # remains the way to actually run a PR scan today (see its own
    # workflow for the single-tenant/demo path).
    if action in ("opened", "synchronize", "reopened"):
        repo_full_name = payload["repository"]["full_name"]
        pr_number = payload["pull_request"]["number"]
        logger.info(
            "pull_request %s on %s#%d -- would enqueue a scan here in a full deployment",
            action,
            repo_full_name,
            pr_number,
        )


def _upsert_connected_repo(session, user_id: int, repo_full_name: str) -> ConnectedRepo:
    existing = (
        session.query(ConnectedRepo)
        .filter_by(user_id=user_id, repo_full_name=repo_full_name)
        .one_or_none()
    )
    if existing:
        return existing
    repo = ConnectedRepo(user_id=user_id, repo_full_name=repo_full_name, sera_yml_status="missing")
    session.add(repo)
    session.flush()
    return repo

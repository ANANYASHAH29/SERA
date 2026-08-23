"""Tenant-scoping guard rails for the multi-tenant dashboard.

Every multi-tenant route resolves data through these functions instead of
querying `ConnectedRepo`/`ScanResult`/`Incident` directly by id. A repo id
or incident id alone is not proof of ownership -- always join through the
owning user_id, and use `get_owned_repo` (which raises rather than
returning None) at every route boundary that takes a repo id from an
untrusted caller, so a stranger passing another tenant's repo id gets a
404, not their data.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from sera.db.models import ConnectedRepo, Incident, ScanResult, User


class NotFoundOrNotOwned(Exception):
    """Raised when a repo/incident id doesn't exist OR belongs to a
    different user. Deliberately the same error either way -- telling a
    caller "that repo exists but isn't yours" leaks which repo ids are
    valid, which is its own small tenant-isolation leak.
    """


def get_or_create_user(session: Session, github_username: str, installation_id: Optional[int]) -> User:
    user = session.query(User).filter_by(github_username=github_username).one_or_none()
    if user is None:
        user = User(github_username=github_username, github_app_installation_id=installation_id)
        session.add(user)
        session.flush()
    elif installation_id is not None and user.github_app_installation_id != installation_id:
        user.github_app_installation_id = installation_id
    return user


def list_owned_repos(session: Session, user_id: int) -> List[ConnectedRepo]:
    return session.query(ConnectedRepo).filter_by(user_id=user_id).all()


def get_owned_repo(session: Session, user_id: int, repo_id: int) -> ConnectedRepo:
    repo = (
        session.query(ConnectedRepo)
        .filter(ConnectedRepo.id == repo_id, ConnectedRepo.user_id == user_id)
        .one_or_none()
    )
    if repo is None:
        raise NotFoundOrNotOwned(f"repo {repo_id} not found for this user")
    return repo


def get_owned_incident(session: Session, user_id: int, incident_id: int) -> Incident:
    incident = (
        session.query(Incident)
        .join(ConnectedRepo, Incident.connected_repo_id == ConnectedRepo.id)
        .filter(Incident.id == incident_id, ConnectedRepo.user_id == user_id)
        .one_or_none()
    )
    if incident is None:
        raise NotFoundOrNotOwned(f"incident {incident_id} not found for this user")
    return incident


def list_owned_scan_results(session: Session, user_id: int, repo_id: int) -> List[ScanResult]:
    get_owned_repo(session, user_id, repo_id)  # raises if not owned
    return (
        session.query(ScanResult)
        .filter_by(repo_id=repo_id)
        .order_by(ScanResult.created_at.desc())
        .all()
    )

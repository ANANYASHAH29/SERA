"""Developer-approved automated recovery: propose a deterministic
recovery plan from an incident's already-recorded intervention evidence,
then -- only on the developer's explicit confirmation -- execute it as
one new commit via the same installation-token GitHub access every
other real-write path in this codebase uses. See sera.method.recovery
for the actual plan/execution logic and the safety rules it enforces
(no history rewrite, no force-push, idempotent, aborts if the repo
changed since diagnosis).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from github import GithubException
from pydantic import BaseModel

from sera.db.models import RecoveryAction, ScanResult, to_utc_iso
from sera.db.session import session_scope
from sera.method import tenancy
from sera.method.recovery import RecoveryError, build_recovery_plan, execute_recovery, propose_recovery

router = APIRouter(prefix="/tenant", tags=["recovery"])


def _action_to_dict(action: RecoveryAction) -> dict:
    return {
        "id": action.id,
        "source_scan_id": action.source_scan_id,
        "healthy_sha": action.healthy_sha,
        "degraded_sha": action.degraded_sha,
        "contributing": json.loads(action.contributing_json),
        "files": json.loads(action.files_json),
        "status": action.status,
        "recovery_commit_sha": action.recovery_commit_sha,
        "before_metric": action.before_metric,
        "after_metric": action.after_metric,
        "resolved_scan_id": action.resolved_scan_id,
        "created_at": to_utc_iso(action.created_at),
        "resolved_at": to_utc_iso(action.resolved_at),
    }


@router.get("/repos/{repo_id}/scans/{scan_id}/recovery-plan")
def get_recovery_plan(repo_id: int, scan_id: int, user_id: int):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")

        scan = session.query(ScanResult).filter_by(id=scan_id, repo_id=repo_id).one_or_none()
        if scan is None:
            raise HTTPException(404, "scan not found")

        try:
            action = propose_recovery(session, repo, scan)
        except RecoveryError as e:
            raise HTTPException(409, str(e))

        session.flush()
        return _action_to_dict(action)


class ConfirmRecoveryRequest(BaseModel):
    expected_head_sha: str


@router.post("/repos/{repo_id}/scans/{scan_id}/recover")
def confirm_recovery(repo_id: int, scan_id: int, user_id: int, req: ConfirmRecoveryRequest):
    with session_scope() as session:
        try:
            repo = tenancy.get_owned_repo(session, user_id, repo_id)
        except tenancy.NotFoundOrNotOwned:
            raise HTTPException(404, "repo not found")

        scan = session.query(ScanResult).filter_by(id=scan_id, repo_id=repo_id).one_or_none()
        if scan is None:
            raise HTTPException(404, "scan not found")

        try:
            action = propose_recovery(session, repo, scan)
        except RecoveryError as e:
            raise HTTPException(409, str(e))

        if action.status != "proposed":
            # Idempotent: already executed (or aborted) -- return the
            # existing outcome rather than acting again.
            return _action_to_dict(action)

        token = tenancy.get_installation_token_for_repo(session, repo)
        if token is None:
            raise HTTPException(409, "no live GitHub installation for this repo -- reconnect it first")

        try:
            execute_recovery(repo, action, token, req.expected_head_sha)
        except RecoveryError as e:
            session.flush()
            raise HTTPException(409, str(e))
        except GithubException as e:
            action.status = "aborted"
            session.flush()
            raise HTTPException(502, f"GitHub rejected the recovery commit: {e}")

        session.flush()
        return _action_to_dict(action)

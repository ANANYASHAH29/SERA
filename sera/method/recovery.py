"""Developer-approved automated recovery.

Once an incident's candidate commits have been sequentially validated
(see scripts/report_scan.py's run_intervention loop and
sera.method.validation.record_interventions), this module turns that
evidence into a deterministic recovery plan -- which files, restored to
which "last known healthy" Git state -- and, only on explicit developer
confirmation, creates ONE new commit doing exactly that restoration.

Hard rules, enforced here, not just documented:
  - never rewrite history, never force-push -- a plain fast-forward ref
    update (GitHub's Git Data API: new blobs + a tree layered on the
    current HEAD's tree + one commit + `ref.edit(sha)`, no `force=True`)
  - never silently mutate the repository -- execute_recovery only runs
    on an explicit call from the confirmed endpoint, never from a GET
  - idempotent -- a RecoveryAction row is created at PROPOSE time
    (before any GitHub write), so a repeated confirm on the same
    incident finds the existing row and returns its current status
    instead of creating a second commit
  - abort, don't overwrite, if the repository changed since diagnosis
    (the branch HEAD the plan was proposed against no longer matches
    the branch HEAD at confirm time)
  - no LLM anywhere in this decision path -- the recovery set is
    computed from the same structured intervention records already used
    for ranking/validation display, nothing else

Reuses the same installation-token GitHub access every other real-write
path in this codebase uses (see ci_autosetup.py) -- no second auth
system, no second GitHub client construction pattern.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from github import Github, UnknownObjectException
from github.InputGitTreeElement import InputGitTreeElement

from sera.db.models import ConnectedRepo, RecoveryAction, ScanResult

REGRESSION_THRESHOLD = 0.05


class RecoveryError(Exception):
    """Any condition that should abort recovery safely. The caller (the
    API route) turns this into a 409 with this message shown verbatim on
    the dashboard -- never a silent failure, never a partial mutation.
    """


def find_last_healthy_scan(session, repo_id: int, before_scan_id: int) -> Optional[ScanResult]:
    return (
        session.query(ScanResult)
        .filter(ScanResult.repo_id == repo_id, ScanResult.status == "healthy", ScanResult.id < before_scan_id)
        .order_by(ScanResult.id.desc())
        .first()
    )


def build_recovery_plan(session, repo: ConnectedRepo, scan: ScanResult) -> dict:
    """Deterministic recovery-plan computation from already-recorded
    intervention evidence -- never re-derives evidence itself, never
    guesses. Raises RecoveryError if there isn't enough evidence yet.
    """
    if scan.status != "incident":
        raise RecoveryError("This scan is not an active incident.")

    healthy_scan = find_last_healthy_scan(session, repo.id, scan.id)
    if healthy_scan is None or not healthy_scan.head_sha:
        raise RecoveryError(
            "No known healthy commit SHA on record for this repo -- cannot determine a recovery target."
        )
    if not scan.head_sha:
        raise RecoveryError("This scan has no recorded commit SHA -- cannot build a recovery plan.")

    interventions = json.loads(scan.interventions_json) if scan.interventions_json else []
    if not interventions:
        raise RecoveryError(
            "No intervention has been run for this incident yet -- diagnosis must validate at least one "
            "hypothesis before recovery."
        )

    # A single fully-validated cause takes priority; otherwise the
    # combined-contributing-set attempt (if one was run and it worked)
    # is authoritative; otherwise fall back to whichever candidates
    # showed real (if individually insufficient) improvement -- that is
    # still actual evidence of contribution, not a guess.
    validated = [a for a in interventions if a["verdict"] in ("validated", "validated_combined")]
    contributing = validated or [a for a in interventions if a["verdict"] == "insufficient_as_sole_cause"]
    if not contributing:
        raise RecoveryError(
            "No candidate has been validated as a contributing cause -- SERA has no evidentiary basis for "
            "a recovery action yet."
        )

    files = sorted({f for a in contributing for f in a["files_reverted"]})

    return {
        "healthy_sha": healthy_scan.head_sha,
        "degraded_sha": scan.head_sha,
        "contributing": [
            {"commit_sha": a["commit_sha"], "stage_label": a.get("stage_label"), "verdict": a["verdict"]}
            for a in contributing
        ],
        "files": files,
    }


def propose_recovery(session, repo: ConnectedRepo, scan: ScanResult) -> RecoveryAction:
    existing = session.query(RecoveryAction).filter_by(source_scan_id=scan.id).one_or_none()
    if existing:
        return existing

    plan = build_recovery_plan(session, repo, scan)
    action = RecoveryAction(
        repo_id=repo.id,
        source_scan_id=scan.id,
        healthy_sha=plan["healthy_sha"],
        degraded_sha=plan["degraded_sha"],
        contributing_json=json.dumps(plan["contributing"]),
        files_json=json.dumps(plan["files"]),
        status="proposed",
    )
    session.add(action)
    session.flush()
    return action


def execute_recovery(repo: ConnectedRepo, action: RecoveryAction, token: str, expected_head_sha: str) -> RecoveryAction:
    """Only call this from the confirmed-by-a-human endpoint. Mutates the
    real repository. Idempotent: if `action` is already past "proposed",
    returns it unchanged rather than creating a second commit.
    """
    if action.status != "proposed":
        return action

    client = Github(token)
    gh_repo = client.get_repo(repo.repo_full_name)
    default_branch = gh_repo.default_branch
    ref = gh_repo.get_git_ref(f"heads/{default_branch}")
    actual_head = ref.object.sha

    if actual_head != expected_head_sha:
        action.status = "aborted"
        raise RecoveryError(
            f"Repository changed since diagnosis (expected {expected_head_sha[:10]}, found {actual_head[:10]}). "
            "Re-run diagnosis before recovery."
        )

    base_commit = gh_repo.get_git_commit(actual_head)
    files = json.loads(action.files_json)

    tree_elements = []
    restored = []
    for path in files:
        try:
            healthy_content = gh_repo.get_contents(path, ref=action.healthy_sha)
        except UnknownObjectException:
            continue  # didn't exist at the healthy ref -- nothing to restore for it
        blob = gh_repo.create_git_blob(healthy_content.content, "base64")
        tree_elements.append(InputGitTreeElement(path=path, mode="100644", type="blob", sha=blob.sha))
        restored.append(path)

    if not tree_elements:
        action.status = "aborted"
        raise RecoveryError("None of the planned files could be restored (already matching, or missing at the healthy ref).")

    new_tree = gh_repo.create_git_tree(tree_elements, base_commit.tree)
    message = (
        f"SERA Recovery: restore {', '.join(restored)} to last known healthy state ({action.healthy_sha[:10]})"
    )
    new_commit = gh_repo.create_git_commit(message, new_tree, [base_commit])
    ref.edit(new_commit.sha)  # fast-forward only -- never force

    action.recovery_commit_sha = new_commit.sha
    action.status = "pending_ci"
    return action


def resolve_pending_recovery(session, repo: ConnectedRepo, new_scan: ScanResult) -> None:
    """Called on every new scan report: if this scan's head_sha matches a
    pending recovery's own commit, that recovery is now resolved by this
    scan's real, independently-reported result -- not by re-running
    anything here.
    """
    if not new_scan.head_sha:
        return
    pending = (
        session.query(RecoveryAction)
        .filter_by(repo_id=repo.id, status="pending_ci", recovery_commit_sha=new_scan.head_sha)
        .one_or_none()
    )
    if pending is None:
        return

    source_summary = json.loads(pending.source_scan.summary_json or "{}")
    new_summary = json.loads(new_scan.summary_json or "{}")
    pending.before_metric = source_summary.get("current_metric")
    pending.after_metric = new_summary.get("current_metric")
    pending.status = "recovered" if new_scan.status == "healthy" else "recovery_failed"
    pending.resolved_scan_id = new_scan.id
    pending.resolved_at = datetime.utcnow()

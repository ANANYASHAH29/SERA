"""Route-level tests for the recovery API
(GET .../recovery-plan, POST .../recover) -- auth/ownership wiring and
error-translation. The plan/execution logic itself is covered by
test_recovery.py; this covers what the dashboard actually calls.
"""
import json

import pytest
from fastapi.testclient import TestClient
from github import GithubException

from sera.method.recovery import RecoveryError


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_recovery_route.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )

    from sera.api.main import app

    return TestClient(app)


def _connect_repo(client, username="alice", installation_id=None):
    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, username, installation_id=installation_id)
        session.flush()
        user_id = user.id

    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": f"{username}/repo"})
    return user_id, resp.json()["id"]


def _seed_scans(repo_id):
    """Directly seeds a healthy scan + an incident scan with recorded
    interventions -- bypassing the report pipeline since we only need the
    resulting rows, not to re-test scan ingestion here.
    """
    from sera.db.session import session_scope
    from sera.db.models import ScanResult

    with session_scope() as session:
        session.add(ScanResult(repo_id=repo_id, status="healthy", head_sha="sha-healthy", summary_json="{}"))
        session.flush()
        incident = ScanResult(
            repo_id=repo_id,
            status="incident",
            head_sha="sha-degraded",
            summary_json=json.dumps({"baseline_metric": 0.965, "current_metric": 0.6}),
            interventions_json=json.dumps(
                [{"commit_sha": "c1", "stage_label": "Checkpoint", "verdict": "validated", "files_reverted": ["model.pkl"]}]
            ),
        )
        session.add(incident)
        session.flush()
        return incident.id


def test_recovery_plan_requires_ownership(client):
    user_id, repo_id = _connect_repo(client, "alice")
    other_user_id, _ = _connect_repo(client, "bob")
    scan_id = _seed_scans(repo_id)

    resp = client.get(f"/tenant/repos/{repo_id}/scans/{scan_id}/recovery-plan", params={"user_id": other_user_id})
    assert resp.status_code == 404


def test_recovery_plan_returns_409_without_evidence(client):
    from sera.db.session import session_scope
    from sera.db.models import ScanResult

    user_id, repo_id = _connect_repo(client)
    with session_scope() as session:
        scan = ScanResult(repo_id=repo_id, status="incident", head_sha="sha-degraded", summary_json="{}")
        session.add(scan)
        session.flush()
        scan_id = scan.id

    resp = client.get(f"/tenant/repos/{repo_id}/scans/{scan_id}/recovery-plan", params={"user_id": user_id})
    assert resp.status_code == 409


def test_recovery_plan_succeeds_with_evidence(client):
    user_id, repo_id = _connect_repo(client)
    scan_id = _seed_scans(repo_id)

    resp = client.get(f"/tenant/repos/{repo_id}/scans/{scan_id}/recovery-plan", params={"user_id": user_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "proposed"
    assert body["files"] == ["model.pkl"]
    assert body["healthy_sha"] == "sha-healthy"


def test_confirm_recovery_requires_installation(client):
    user_id, repo_id = _connect_repo(client, installation_id=None)
    scan_id = _seed_scans(repo_id)

    resp = client.post(
        f"/tenant/repos/{repo_id}/scans/{scan_id}/recover",
        params={"user_id": user_id},
        json={"expected_head_sha": "sha-degraded"},
    )
    assert resp.status_code == 409
    assert "installation" in resp.json()["detail"]


def test_confirm_recovery_executes_and_is_idempotent(client, monkeypatch):
    user_id, repo_id = _connect_repo(client, installation_id=111)
    scan_id = _seed_scans(repo_id)

    monkeypatch.setattr("sera.method.tenancy.get_installation_token_for_repo", lambda session, repo: "fake-token")

    calls = {"n": 0}

    def fake_execute(repo, action, token, expected_head_sha):
        calls["n"] += 1
        action.status = "pending_ci"
        action.recovery_commit_sha = "recovery-sha-1"
        return action

    monkeypatch.setattr("sera.api.routes_recovery.execute_recovery", fake_execute)

    resp1 = client.post(
        f"/tenant/repos/{repo_id}/scans/{scan_id}/recover",
        params={"user_id": user_id},
        json={"expected_head_sha": "sha-degraded"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "pending_ci"
    assert calls["n"] == 1

    # Second confirm on the same scan must not re-execute.
    resp2 = client.post(
        f"/tenant/repos/{repo_id}/scans/{scan_id}/recover",
        params={"user_id": user_id},
        json={"expected_head_sha": "sha-degraded"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["recovery_commit_sha"] == "recovery-sha-1"
    assert calls["n"] == 1  # NOT called again


def test_confirm_recovery_translates_recovery_error_to_409(client, monkeypatch):
    user_id, repo_id = _connect_repo(client, installation_id=111)
    scan_id = _seed_scans(repo_id)

    monkeypatch.setattr("sera.method.tenancy.get_installation_token_for_repo", lambda session, repo: "fake-token")

    def fake_execute(repo, action, token, expected_head_sha):
        raise RecoveryError("Repository changed since diagnosis.")

    monkeypatch.setattr("sera.api.routes_recovery.execute_recovery", fake_execute)

    resp = client.post(
        f"/tenant/repos/{repo_id}/scans/{scan_id}/recover",
        params={"user_id": user_id},
        json={"expected_head_sha": "sha-degraded"},
    )
    assert resp.status_code == 409
    assert "changed since diagnosis" in resp.json()["detail"]


def test_confirm_recovery_translates_github_exception_to_502(client, monkeypatch):
    user_id, repo_id = _connect_repo(client, installation_id=111)
    scan_id = _seed_scans(repo_id)

    monkeypatch.setattr("sera.method.tenancy.get_installation_token_for_repo", lambda session, repo: "fake-token")

    def fake_execute(repo, action, token, expected_head_sha):
        raise GithubException(403, {"message": "Resource not accessible"}, {})

    monkeypatch.setattr("sera.api.routes_recovery.execute_recovery", fake_execute)

    resp = client.post(
        f"/tenant/repos/{repo_id}/scans/{scan_id}/recover",
        params={"user_id": user_id},
        json={"expected_head_sha": "sha-degraded"},
    )
    assert resp.status_code == 502

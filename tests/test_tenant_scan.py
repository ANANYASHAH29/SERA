"""Tests for the demo-scan endpoint: runs the real diagnostic engine
(real inference, real ranking) against a connected repo, and confirms it
writes a ScanResult that the dashboard can read back correctly.
"""
import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import requires_checkpoint


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_scan.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref: None
    )

    from sera.api.main import app

    return TestClient(app)


def _connect(client, username="alice"):
    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, username, None)
        session.flush()
        user_id = user.id

    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": f"{username}/repo"})
    return user_id, resp.json()["id"]


def test_scan_rejects_unknown_condition(client):
    user_id, repo_id = _connect(client)
    resp = client.post(f"/tenant/repos/{repo_id}/scan?user_id={user_id}", json={"condition": "F99"})
    assert resp.status_code == 400


@requires_checkpoint
def test_healthy_scan_produces_healthy_status(client):
    user_id, repo_id = _connect(client)
    resp = client.post(f"/tenant/repos/{repo_id}/scan?user_id={user_id}", json={"condition": None})
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"

    scans = client.get(f"/tenant/repos/{repo_id}/scans?user_id={user_id}").json()
    assert len(scans) == 1
    assert scans[0]["status"] == "healthy"


@requires_checkpoint
def test_condition_scan_produces_incident_with_ranking(client):
    user_id, repo_id = _connect(client)
    resp = client.post(f"/tenant/repos/{repo_id}/scan?user_id={user_id}", json={"condition": "F3"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "incident"

    scans = client.get(f"/tenant/repos/{repo_id}/scans?user_id={user_id}").json()
    summary = json.loads(scans[0]["summary_json"])
    assert summary["candidates"][0]["hypothesized_category"] == "F3"


@requires_checkpoint
def test_scan_updates_repo_health_status_and_incident_count(client):
    user_id, repo_id = _connect(client)
    client.post(f"/tenant/repos/{repo_id}/scan?user_id={user_id}", json={"condition": "F5"})

    repos = client.get(f"/tenant/repos?user_id={user_id}").json()
    assert repos[0]["health_status"] == "incident"
    assert repos[0]["incident_count"] == 1
    assert repos[0]["last_scan_at"] is not None


@requires_checkpoint
def test_scan_rejects_cross_tenant_repo_id(client):
    alice_id, alice_repo_id = _connect(client, "alice")
    bob_id, _ = _connect(client, "bob")

    resp = client.post(f"/tenant/repos/{alice_repo_id}/scan?user_id={bob_id}", json={"condition": None})
    assert resp.status_code == 404

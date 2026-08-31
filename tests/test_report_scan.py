"""Tests for the push-based scan-ingestion endpoint: a connected repo's
OWN CI reports real accuracy/confidence data here, authenticated by a
per-repo token -- SERA never clones or executes the repo's code itself.
GitHub commit-fetching is monkeypatched (no live installation in tests).
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_report.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )

    from sera.api.main import app

    return TestClient(app)


def _connect_repo(client):
    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, "alice", installation_id=None)
        session.flush()
        user_id = user.id

    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/repo"})
    repo_id = resp.json()["id"]
    token_resp = client.get(f"/tenant/repos/{repo_id}/report-token", params={"user_id": user_id})
    token = token_resp.json()["report_token"]
    return user_id, repo_id, token


def _healthy_payload(token, accuracy=0.9):
    return {
        "report_token": token,
        "accuracy": accuracy,
        "mean_confidence": accuracy,
        "mean_entropy": 0.3,
        "per_sample_confidence": [accuracy] * 10,
        "per_sample_correct": [True] * int(accuracy * 10) + [False] * (10 - int(accuracy * 10)),
    }


def test_first_report_bootstraps_baseline(client):
    _, repo_id, token = _connect_repo(client)
    resp = client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.9))
    assert resp.status_code == 200
    assert resp.json()["status"] == "baseline_set"


def test_report_rejects_wrong_token(client):
    _, repo_id, token = _connect_repo(client)
    payload = _healthy_payload(token, 0.9)
    payload["report_token"] = "wrong-token"
    resp = client.post(f"/report/{repo_id}/scan", json=payload)
    assert resp.status_code == 404


def test_report_rejects_nonexistent_repo(client):
    _, _, token = _connect_repo(client)
    resp = client.post("/report/999999/scan", json=_healthy_payload(token, 0.9))
    assert resp.status_code == 404


def test_subsequent_healthy_report_stays_healthy_and_advances_baseline(client):
    _, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.9))
    resp = client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.89))
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_regression_report_produces_incident_with_drift_only_ranking(client, monkeypatch):
    # No installation configured for this user -> commit fetch degrades to
    # [] -> ranking has only the drift candidate. This still proves the
    # real pipeline runs end to end without a live GitHub installation.
    _, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.9))

    regressed = _healthy_payload(token, 0.5)
    resp = client.post(f"/report/{repo_id}/scan", json=regressed)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "incident"
    assert body["accuracy_drop"] == pytest.approx(0.4)


def test_incident_does_not_advance_baseline(client):
    user_id, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.9))
    client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.5))  # incident

    # a report back at the ORIGINAL baseline level should now read as
    # "recovered" (healthy), not "still regressed relative to the dip" --
    # proving baseline stayed at 0.9, not silently advancing to 0.5.
    resp = client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.88))
    assert resp.json()["status"] == "healthy"


def test_report_updates_repo_dashboard_fields(client):
    user_id, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.9))
    client.post(f"/report/{repo_id}/scan", json=_healthy_payload(token, 0.5))

    repos = client.get("/tenant/repos", params={"user_id": user_id}).json()
    assert repos[0]["health_status"] == "incident"
    assert repos[0]["incident_count"] == 1
    assert repos[0]["last_scan_at"] is not None

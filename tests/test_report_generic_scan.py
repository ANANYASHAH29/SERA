"""Tests for the token-authenticated CI reporting path for the generic
(sklearn/tabular) schema -- POST /report/{repo_id}/generic-scan. This is
what scripts/report_scan.py actually calls when a repo's canary_eval.py
produces the generic schema instead of the CV-style one.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_report_generic.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref: None
    )

    from sera.api.main import app

    return TestClient(app)


def _connect_repo(client, username="alice"):
    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, username, installation_id=None)
        session.flush()
        user_id = user.id

    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": f"{username}/repo"})
    repo_id = resp.json()["id"]
    token_resp = client.get(f"/tenant/repos/{repo_id}/report-token", params={"user_id": user_id})
    token = token_resp.json()["report_token"]
    return user_id, repo_id, token


def _generic_payload(accuracy, token, n=10):
    correct_n = round(accuracy * n)
    return {
        "report_token": token,
        "task_type": "classification",
        "primary_metric": accuracy,
        "primary_metric_name": "accuracy",
        "secondary_metrics": {"mean_confidence": accuracy, "mean_entropy": 0.2},
        "per_sample_scores": [1] * correct_n + [0] * (n - correct_n),
        "n_samples": n,
        "canary_set_hash": "deadbeef",
    }


def test_generic_report_bootstraps_baseline(client):
    _, repo_id, token = _connect_repo(client)
    resp = client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.95, token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "baseline_set"


def test_generic_report_rejects_wrong_token(client):
    _, repo_id, token = _connect_repo(client)
    payload = _generic_payload(0.95, token)
    payload["report_token"] = "wrong"
    resp = client.post(f"/report/{repo_id}/generic-scan", json=payload)
    assert resp.status_code == 404


def test_generic_report_regression_produces_incident(client):
    _, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.95, token, n=100))
    resp = client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.6, token, n=100))
    assert resp.status_code == 200
    assert resp.json()["status"] == "incident"


def test_generic_report_and_dashboard_paste_share_the_same_baseline(client):
    # Both ingestion paths write to the same generic_baseline_snapshot_json
    # -- a result reported via CI and one pasted manually must be
    # comparable against each other, not siloed into two separate states.
    user_id, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.95, token, n=100))

    dashboard_payload = _generic_payload(0.6, token, n=100)
    del dashboard_payload["report_token"]
    resp = client.post(
        f"/tenant/repos/{repo_id}/ingest-scan-result", params={"user_id": user_id}, json=dashboard_payload
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "incident"  # correctly compared against the CI-reported baseline

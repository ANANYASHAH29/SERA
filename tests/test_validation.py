"""Tests for the controlled-intervention ("validation") report path:
POST /report/{repo_id}/validate-scan. This is the follow-up report a
tenant's CI sends after reverting a suspect commit's flagged files and
re-running the canary, confirming (or not) that the regression recovers.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_validation.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
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


def _generic_payload(accuracy, token, n=100):
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


def _fake_commit():
    from sera.github_integration.commit_types import CommitInfo

    return CommitInfo(
        sha="af3033d08b8be99163c55abbdaf162f974288ba9",
        message="Update model",
        author="alice",
        timestamp=datetime.utcnow(),
        files_changed=["model.pkl"],
        risk_categories=["F5"],
        file_patches={"model.pkl": None},
    )


def _irrelevant_commit():
    from sera.github_integration.commit_types import CommitInfo

    return CommitInfo(
        sha="deadbeef00000000000000000000000000000000",
        message="Update README",
        author="bob",
        timestamp=datetime.utcnow(),
        files_changed=["README.md"],
        risk_categories=[],  # touches no risk-category file -- no evidence at all
        file_patches={"README.md": "+docs line"},
    )


def _patch_commit_fetch(monkeypatch, commits=None):
    from datetime import datetime

    commits = commits if commits is not None else [_fake_commit()]
    monkeypatch.setattr(
        "sera.api.routes_report._fetch_and_classify_commits",
        lambda session, repo: (commits, None, datetime.utcnow()),
    )


def _report_incident(client, monkeypatch, repo_id, token, commits=None):
    _patch_commit_fetch(monkeypatch, commits)
    client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.95, token))
    return client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.60, token))


def test_zero_evidence_commits_are_excluded_from_visible_ranking(client, monkeypatch):
    # A commit that touches no risk-category file contributes nothing to
    # the hypothesis space -- it shouldn't clutter the ranking table
    # alongside the commit that actually has evidence.
    _, repo_id, token = _connect_repo(client)
    resp = _report_incident(client, monkeypatch, repo_id, token, commits=[_fake_commit(), _irrelevant_commit()])
    body = resp.json()
    assert body["status"] == "incident"

    from sera.db.session import session_scope
    from sera.db.models import ScanResult
    import json

    with session_scope() as session:
        scan = session.get(ScanResult, body["scan_id"])
        summary = json.loads(scan.summary_json)

    shas = [c["commit_sha"] for c in summary["candidates"]]
    assert _fake_commit().sha in shas
    assert _irrelevant_commit().sha not in shas
    assert summary["commits_analyzed"] == 2
    assert summary["commits_relevant"] == 1


def test_incident_response_surfaces_top_candidate_for_intervention(client, monkeypatch):
    _, repo_id, token = _connect_repo(client)
    resp = _report_incident(client, monkeypatch, repo_id, token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "incident"
    assert body["top_candidate"]["commit_sha"] == "af3033d08b8be99163c55abbdaf162f974288ba9"
    assert body["top_candidate"]["files_changed"] == ["model.pkl"]


def test_validate_scan_recorded_as_recovered(client, monkeypatch):
    _, repo_id, token = _connect_repo(client)
    resp = _report_incident(client, monkeypatch, repo_id, token)
    scan_id = resp.json()["scan_id"]

    validate_resp = client.post(
        f"/report/{repo_id}/validate-scan",
        json={
            "report_token": token,
            "scan_id": scan_id,
            "files_reverted": ["model.pkl"],
            "after_metric": 0.94,  # close to the 0.95 baseline -- recovered
        },
    )
    assert validate_resp.status_code == 200
    assert validate_resp.json()["recovered"] is True


def test_validate_scan_recorded_as_not_recovered(client, monkeypatch):
    _, repo_id, token = _connect_repo(client)
    resp = _report_incident(client, monkeypatch, repo_id, token)
    scan_id = resp.json()["scan_id"]

    validate_resp = client.post(
        f"/report/{repo_id}/validate-scan",
        json={
            "report_token": token,
            "scan_id": scan_id,
            "files_reverted": ["model.pkl"],
            "after_metric": 0.61,  # still regressed -- reverting this file didn't fix it
        },
    )
    assert validate_resp.status_code == 200
    assert validate_resp.json()["recovered"] is False


def test_validate_scan_rejects_wrong_token(client, monkeypatch):
    _, repo_id, token = _connect_repo(client)
    resp = _report_incident(client, monkeypatch, repo_id, token)
    scan_id = resp.json()["scan_id"]

    validate_resp = client.post(
        f"/report/{repo_id}/validate-scan",
        json={"report_token": "wrong", "scan_id": scan_id, "files_reverted": ["model.pkl"], "after_metric": 0.94},
    )
    assert validate_resp.status_code == 404


def test_validate_scan_stored_and_visible_in_scan_history(client, monkeypatch):
    user_id, repo_id, token = _connect_repo(client)
    resp = _report_incident(client, monkeypatch, repo_id, token)
    scan_id = resp.json()["scan_id"]

    client.post(
        f"/report/{repo_id}/validate-scan",
        json={"report_token": token, "scan_id": scan_id, "files_reverted": ["model.pkl"], "after_metric": 0.94},
    )

    history = client.get(f"/tenant/repos/{repo_id}/scans", params={"user_id": user_id}).json()
    scan = next(s for s in history if s["id"] == scan_id)
    assert scan["validation_json"] is not None
    assert "recovered" in scan["validation_json"]

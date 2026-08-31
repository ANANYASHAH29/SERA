"""Route-level tests for POST /tenant/repos/{repo_id}/setup-ci-automation
-- the one-click replacement for the copy-paste-by-hand CI setup. The
actual GitHub-writing logic is covered by test_ci_autosetup.py; this
covers the route's auth/ownership/error-translation wiring.
"""
import pytest
from fastapi.testclient import TestClient
from github import GithubException


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_ci_autosetup_route.db"
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


def test_setup_rejects_repo_with_no_live_installation(client):
    user_id, repo_id = _connect_repo(client, installation_id=None)
    resp = client.post(f"/tenant/repos/{repo_id}/setup-ci-automation", params={"user_id": user_id})
    assert resp.status_code == 409


def test_setup_rejects_cross_tenant_access(client):
    _, repo_id = _connect_repo(client, "alice")
    bob_id, _ = _connect_repo(client, "bob")
    resp = client.post(f"/tenant/repos/{repo_id}/setup-ci-automation", params={"user_id": bob_id})
    assert resp.status_code == 404


def test_setup_succeeds_and_generates_a_report_token_if_missing(client, monkeypatch):
    user_id, repo_id = _connect_repo(client, installation_id=111)
    monkeypatch.setattr(
        "sera.method.tenancy.get_installation_token_for_repo", lambda session, repo: "fake-installation-token"
    )
    monkeypatch.setattr(
        "sera.api.routes_generic_scan.setup_ci_reporting",
        lambda repo_full_name, token, base_url, repo_id_, report_token: {
            "status": "configured",
            "workflow_file": "created",
            "reporter_script": "created",
        },
    )

    resp = client.post(f"/tenant/repos/{repo_id}/setup-ci-automation", params={"user_id": user_id})
    assert resp.status_code == 200
    assert resp.json()["status"] == "configured"

    token_resp = client.get(f"/tenant/repos/{repo_id}/report-token", params={"user_id": user_id})
    assert token_resp.json()["report_token"]  # a real token was generated, not left null


def test_setup_translates_github_permission_error_into_403(client, monkeypatch):
    user_id, repo_id = _connect_repo(client, installation_id=111)
    monkeypatch.setattr(
        "sera.method.tenancy.get_installation_token_for_repo", lambda session, repo: "fake-installation-token"
    )

    def _raise(*args, **kwargs):
        raise GithubException(403, {"message": "Resource not accessible by integration"}, {})

    monkeypatch.setattr("sera.api.routes_generic_scan.setup_ci_reporting", _raise)

    resp = client.post(f"/tenant/repos/{repo_id}/setup-ci-automation", params={"user_id": user_id})
    assert resp.status_code == 403

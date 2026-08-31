"""API-level tests for the multi-tenant routes. GitHub network calls
(load_repo_config_from_github, get_installation_client) are monkeypatched
-- we have no live App installation to test against in CI/dev, but the
route logic, persistence, and tenant scoping are all real.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_tenant.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    # _seed_user's fake installation_id=111 doesn't correspond to a real
    # GitHub App installation -- without this, connect_repo's real
    # get_installation_token_for_repo call attempts genuine network I/O
    # against that bogus id and burns minutes retrying before giving up.
    monkeypatch.setattr("sera.method.tenancy.get_installation_token_for_repo", lambda session, repo: None)

    from sera.api.main import app

    return TestClient(app)


def _seed_user(client, monkeypatch, username="alice", installation_id=111):
    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, username, installation_id)
        session.flush()
        return user.id


def test_install_url_requires_app_slug(client, monkeypatch):
    monkeypatch.delenv("GITHUB_APP_SLUG", raising=False)
    resp = client.get("/tenant/install-url")
    assert resp.status_code == 500


def test_install_url_returns_link_when_configured(client, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_SLUG", "sera-demo")
    resp = client.get("/tenant/install-url")
    assert resp.status_code == 200
    assert resp.json()["install_url"] == "https://github.com/apps/sera-demo/installations/new"


def test_list_repos_empty_for_new_user(client, monkeypatch):
    user_id = _seed_user(client, monkeypatch)
    resp = client.get("/tenant/repos", params={"user_id": user_id})
    assert resp.status_code == 200
    assert resp.json() == []


def test_connect_repo_creates_row_with_sera_yml_status(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github",
        lambda repo_full_name, ref, token=None: object(),  # truthy -> "present"
    )
    user_id = _seed_user(client, monkeypatch)

    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/cv-repo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_full_name"] == "alice/cv-repo"
    assert body["sera_yml_status"] == "present"
    assert body["health_status"] == "never_scanned"
    assert body["incident_count"] == 0


def test_connect_repo_marks_missing_sera_yml_when_absent(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github",
        lambda repo_full_name, ref, token=None: None,
    )
    user_id = _seed_user(client, monkeypatch)
    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/no-config-repo"})
    assert resp.json()["sera_yml_status"] == "missing"


def test_connect_repo_is_idempotent(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    user_id = _seed_user(client, monkeypatch)
    client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/repo"})
    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/repo"})
    assert resp.status_code == 200
    list_resp = client.get("/tenant/repos", params={"user_id": user_id})
    assert len(list_resp.json()) == 1


def test_disconnect_rejects_cross_tenant_repo(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    alice_id = _seed_user(client, monkeypatch, "alice", 111)
    bob_id = _seed_user(client, monkeypatch, "bob", 222)

    connect_resp = client.post("/tenant/repos", json={"user_id": alice_id, "repo_full_name": "alice/repo"})
    alice_repo_id = connect_resp.json()["id"]

    resp = client.delete(f"/tenant/repos/{alice_repo_id}", params={"user_id": bob_id})
    assert resp.status_code == 404

    still_there = client.get("/tenant/repos", params={"user_id": alice_id})
    assert len(still_there.json()) == 1


def test_disconnect_own_repo_succeeds(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    user_id = _seed_user(client, monkeypatch)
    connect_resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/repo"})
    repo_id = connect_resp.json()["id"]

    resp = client.delete(f"/tenant/repos/{repo_id}", params={"user_id": user_id})
    assert resp.status_code == 200
    assert client.get("/tenant/repos", params={"user_id": user_id}).json() == []


def test_sera_yml_template_rejects_cross_tenant_access(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    alice_id = _seed_user(client, monkeypatch, "alice", 111)
    bob_id = _seed_user(client, monkeypatch, "bob", 222)
    connect_resp = client.post("/tenant/repos", json={"user_id": alice_id, "repo_full_name": "alice/repo"})
    alice_repo_id = connect_resp.json()["id"]

    resp = client.get(f"/tenant/repos/{alice_repo_id}/sera-yml-template", params={"user_id": bob_id})
    assert resp.status_code == 404


def test_sera_yml_template_returns_starter_template(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    user_id = _seed_user(client, monkeypatch)
    connect_resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/repo"})
    repo_id = connect_resp.json()["id"]

    resp = client.get(f"/tenant/repos/{repo_id}/sera-yml-template", params={"user_id": user_id})
    assert resp.status_code == 200
    assert "risk_categories" in resp.json()["template"]


def test_badge_markdown_uses_repo_owner_and_name(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    user_id = _seed_user(client, monkeypatch)
    connect_resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/cv-repo"})
    repo_id = connect_resp.json()["id"]

    resp = client.get(f"/tenant/repos/{repo_id}/badge-markdown", params={"user_id": user_id})
    assert resp.status_code == 200
    assert "/badge/alice/cv-repo" in resp.json()["badge_url"]


def test_badge_endpoint_returns_svg_for_unconnected_repo(client):
    resp = client.get("/badge/nobody/nothing")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "not yet scanned" in resp.text


def test_badge_endpoint_reflects_incident_status(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )
    from sera.db.models import ScanResult
    from sera.db.session import session_scope

    user_id = _seed_user(client, monkeypatch)
    connect_resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": "alice/cv-repo"})
    repo_id = connect_resp.json()["id"]

    with session_scope() as session:
        session.add(ScanResult(repo_id=repo_id, status="incident", summary_json="{}"))

    resp = client.get("/badge/alice/cv-repo")
    assert resp.status_code == 200
    assert "regression detected" in resp.text
    assert "#cf222e" in resp.text

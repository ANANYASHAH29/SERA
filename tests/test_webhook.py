"""Webhook route tests: signature enforcement, and that installation /
installation_repositories events correctly create users and connected
repos. Payloads are minimal but real-shaped (subset of GitHub's actual
webhook schema).
"""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

WEBHOOK_SECRET = "test-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_webhook.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setenv("GITHUB_APP_ID", "999")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)

    from sera.api.main import app

    return TestClient(app)


def _sign(body: bytes) -> str:
    digest = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _post_webhook(client, event: str, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": event,
            "Content-Type": "application/json",
        },
    )


def test_webhook_rejects_missing_signature(client):
    body = json.dumps({"action": "created"}).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "installation", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_webhook_rejects_wrong_signature(client):
    body = json.dumps({"action": "created"}).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "installation",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_installation_created_event_creates_user_and_repos(client):
    payload = {
        "action": "created",
        "installation": {"id": 555, "account": {"login": "newuser"}},
        "repositories": [{"full_name": "newuser/repo-a"}, {"full_name": "newuser/repo-b"}],
    }
    resp = _post_webhook(client, "installation", payload)
    assert resp.status_code == 200

    from sera.db.models import ConnectedRepo, User
    from sera.db.session import session_scope

    with session_scope() as session:
        user = session.query(User).filter_by(github_username="newuser").one()
        assert user.github_app_installation_id == 555
        repos = session.query(ConnectedRepo).filter_by(user_id=user.id).all()
        assert {r.repo_full_name for r in repos} == {"newuser/repo-a", "newuser/repo-b"}


def test_installation_repositories_added_event_adds_repo(client):
    _post_webhook(
        client,
        "installation",
        {
            "action": "created",
            "installation": {"id": 556, "account": {"login": "someuser"}},
            "repositories": [],
        },
    )
    resp = _post_webhook(
        client,
        "installation_repositories",
        {
            "action": "added",
            "installation": {"id": 556, "account": {"login": "someuser"}},
            "repositories_added": [{"full_name": "someuser/newly-added"}],
        },
    )
    assert resp.status_code == 200

    from sera.db.models import ConnectedRepo, User
    from sera.db.session import session_scope

    with session_scope() as session:
        user = session.query(User).filter_by(github_username="someuser").one()
        repos = session.query(ConnectedRepo).filter_by(user_id=user.id).all()
        assert [r.repo_full_name for r in repos] == ["someuser/newly-added"]


def test_installation_repositories_removed_event_deletes_repo(client):
    _post_webhook(
        client,
        "installation",
        {
            "action": "created",
            "installation": {"id": 557, "account": {"login": "thirduser"}},
            "repositories": [{"full_name": "thirduser/keep-me"}, {"full_name": "thirduser/remove-me"}],
        },
    )
    resp = _post_webhook(
        client,
        "installation_repositories",
        {
            "action": "removed",
            "installation": {"id": 557, "account": {"login": "thirduser"}},
            "repositories_removed": [{"full_name": "thirduser/remove-me"}],
        },
    )
    assert resp.status_code == 200

    from sera.db.models import ConnectedRepo, User
    from sera.db.session import session_scope

    with session_scope() as session:
        user = session.query(User).filter_by(github_username="thirduser").one()
        repos = session.query(ConnectedRepo).filter_by(user_id=user.id).all()
        assert [r.repo_full_name for r in repos] == ["thirduser/keep-me"]


def test_installation_deleted_event_clears_installation_id(client):
    _post_webhook(
        client,
        "installation",
        {
            "action": "created",
            "installation": {"id": 558, "account": {"login": "fourthuser"}},
            "repositories": [],
        },
    )
    resp = _post_webhook(
        client,
        "installation",
        {
            "action": "deleted",
            "installation": {"id": 558, "account": {"login": "fourthuser"}},
        },
    )
    assert resp.status_code == 200

    from sera.db.models import User
    from sera.db.session import session_scope

    with session_scope() as session:
        user = session.query(User).filter_by(github_username="fourthuser").one()
        assert user.github_app_installation_id is None


def test_pull_request_event_is_accepted_without_error(client):
    resp = _post_webhook(
        client,
        "pull_request",
        {
            "action": "opened",
            "repository": {"full_name": "someuser/repo"},
            "pull_request": {"number": 42},
        },
    )
    assert resp.status_code == 200


def test_unhandled_event_type_is_accepted_without_error(client):
    resp = _post_webhook(client, "star", {"action": "created"})
    assert resp.status_code == 200

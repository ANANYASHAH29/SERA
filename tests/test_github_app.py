"""GitHub App auth: config loading and webhook signature verification.
No real App registration or network access needed -- signature
verification is pure HMAC, and config loading is pure env-var parsing.
"""
import hashlib
import hmac

import pytest

from sera.github_integration.github_app import (
    GitHubAppConfig,
    GitHubAppNotConfigured,
    verify_webhook_signature,
)


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_config_from_env_requires_app_id_and_private_key(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    with pytest.raises(GitHubAppNotConfigured):
        GitHubAppConfig.from_env()


def test_config_from_env_loads_all_fields(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "shhh")
    config = GitHubAppConfig.from_env()
    assert config.app_id == "12345"
    assert config.webhook_secret == "shhh"


def test_verify_webhook_signature_accepts_correctly_signed_payload():
    config = GitHubAppConfig(app_id="1", private_key="k", webhook_secret="topsecret")
    body = b'{"action": "created"}'
    signature = _sign("topsecret", body)
    assert verify_webhook_signature(body, signature, config) is True


def test_verify_webhook_signature_rejects_wrong_secret():
    config = GitHubAppConfig(app_id="1", private_key="k", webhook_secret="topsecret")
    body = b'{"action": "created"}'
    signature = _sign("wrong-secret", body)
    assert verify_webhook_signature(body, signature, config) is False


def test_verify_webhook_signature_rejects_tampered_body():
    config = GitHubAppConfig(app_id="1", private_key="k", webhook_secret="topsecret")
    original_body = b'{"action": "created"}'
    signature = _sign("topsecret", original_body)
    tampered_body = b'{"action": "deleted"}'
    assert verify_webhook_signature(tampered_body, signature, config) is False


def test_verify_webhook_signature_rejects_missing_header():
    config = GitHubAppConfig(app_id="1", private_key="k", webhook_secret="topsecret")
    assert verify_webhook_signature(b"{}", None, config) is False


def test_verify_webhook_signature_rejects_malformed_header():
    config = GitHubAppConfig(app_id="1", private_key="k", webhook_secret="topsecret")
    assert verify_webhook_signature(b"{}", "sha1=deadbeef", config) is False


def test_verify_webhook_signature_requires_configured_secret():
    config = GitHubAppConfig(app_id="1", private_key="k", webhook_secret=None)
    with pytest.raises(GitHubAppNotConfigured):
        verify_webhook_signature(b"{}", "sha256=abc", config)

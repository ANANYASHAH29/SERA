"""GitHub App authentication: replaces a personal-access-token with a
proper App installation flow for the multi-tenant dashboard.

Why this exists instead of just reusing GITHUB_TOKEN (see
fetch_commits.py, pr_check.py, run_scheduled_canary.py): those all
assume *you* hold a token for a repo *you* control. A stranger
connecting their repo to SERA can't reasonably be asked to hand over a
personal access token -- that's real credential custody risk for both
sides. A GitHub App instead:

  - is registered once (by you, the SERA operator)
  - gets "installed" by each user on their own repos, through GitHub's
    own consent UI (the same pattern as installing Dependabot/Codecov)
  - hands your backend a short-lived, installation-scoped token per
    request -- never a durable personal credential

Three pieces of App-level config identify SERA as an App, loaded from
environment variables (never hardcoded, never committed):
  GITHUB_APP_ID            -- numeric App id
  GITHUB_APP_PRIVATE_KEY   -- PEM private key contents (the App's
                               signing key, downloaded once at
                               registration time)
  GITHUB_WEBHOOK_SECRET    -- shared secret for verifying webhook payloads

The single-tenant scripts (fetch_commits.py etc.) are UNCHANGED and
still use GITHUB_TOKEN -- that path remains valid for "you, scanning a
repo you control directly" (e.g. the scheduled Action's automatic
per-repo token). This module is additive, for the new multi-tenant path.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional

from github import Auth, Github, GithubIntegration


class GitHubAppNotConfigured(Exception):
    pass


@dataclass
class GitHubAppConfig:
    app_id: str
    private_key: str
    webhook_secret: Optional[str] = None

    @staticmethod
    def from_env() -> "GitHubAppConfig":
        app_id = os.environ.get("GITHUB_APP_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        if not app_id or not private_key:
            raise GitHubAppNotConfigured(
                "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY must be set. "
                "Run scripts/register_github_app.py once to create the App "
                "and populate these (see README 'Setting up the GitHub App')."
            )
        return GitHubAppConfig(
            app_id=app_id,
            private_key=private_key,
            webhook_secret=os.environ.get("GITHUB_WEBHOOK_SECRET"),
        )


def get_integration(config: Optional[GitHubAppConfig] = None) -> GithubIntegration:
    config = config or GitHubAppConfig.from_env()
    return GithubIntegration(auth=Auth.AppAuth(config.app_id, config.private_key))


def get_installation_client(installation_id: int, config: Optional[GitHubAppConfig] = None) -> Github:
    """Returns a PyGithub client authenticated as one specific installation
    -- scoped to exactly the repos that installation was granted, nothing
    more. This is what every multi-tenant API call must use, never a
    global token.
    """
    integration = get_integration(config)
    return integration.get_github_for_installation(installation_id)


def get_installation_token(installation_id: int, config: Optional[GitHubAppConfig] = None) -> str:
    """Returns the raw, short-lived (~1hr) installation access token
    string -- for call sites like fetch_commit_history that take a plain
    `token: str` rather than a pre-built Github client.
    """
    integration = get_integration(config)
    return integration.get_access_token(installation_id).token


def verify_webhook_signature(payload_body: bytes, signature_header: Optional[str], config: Optional[GitHubAppConfig] = None) -> bool:
    """Verifies GitHub's `X-Hub-Signature-256` HMAC header. Always verify
    this before trusting ANY webhook payload -- otherwise anyone who
    finds your webhook URL can forge "installation created" events and
    make your backend believe an attacker is a legitimate installer.
    """
    config = config or GitHubAppConfig.from_env()
    if not config.webhook_secret:
        raise GitHubAppNotConfigured("GITHUB_WEBHOOK_SECRET is not set")
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        config.webhook_secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()
    provided = signature_header[len("sha256=") :]
    return hmac.compare_digest(expected, provided)

"""One-click automation for the "copy these two files, set these three
secrets" setup a repo owner previously had to do by hand. This is the ONE
part of SERA's design that needs MORE than read-only GitHub App access:
committing the workflow/script files needs Contents + Workflows write,
and setting repo secrets needs the Secrets permission. Every other part
of SERA stays read-only -- this is a deliberate, narrow exception, and
the repo owner has to explicitly approve the broader permission grant on
GitHub's own consent screen before any of this can work (a 403 from
GitHub here means that approval hasn't happened yet, not a bug).

All three values are set as secrets, including SERA_DASHBOARD_URL --
not because a URL is sensitive, but because GitHub Apps gate repository
Variables behind a permission scope separate from Secrets, and asking
for a 4th narrow permission just to avoid putting a non-secret value in
a secret slot isn't worth the extra consent friction.

Still never executes the tenant's code: this only writes files and
config values, then the SAME CI-runs-your-own-canary pattern as before
takes over.
"""
from __future__ import annotations

from pathlib import Path

from github import Github, UnknownObjectException

WORKFLOW_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / "sera_report_scan.yml"
REPORTER_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "report_scan.py"

WORKFLOW_DEST_PATH = ".github/workflows/sera_report_scan.yml"
REPORTER_DEST_PATH = ".github/scripts/report_scan.py"


def _create_or_update_file(gh_repo, path: str, content: str, message: str) -> str:
    try:
        existing = gh_repo.get_contents(path)
        gh_repo.update_file(path, message, content, existing.sha)
        return "updated"
    except UnknownObjectException:
        gh_repo.create_file(path, message, content)
        return "created"


def setup_ci_reporting(repo_full_name: str, token: str, dashboard_url: str, repo_id: int, report_token: str) -> dict:
    """Commits the workflow + reporter script and sets the three secrets
    a repo needs for fully automated SERA scanning -- the same three
    things the Settings page previously asked a human to copy-paste by
    hand. Raises GithubException (uncaught) if the installation lacks the
    write permissions this needs; the caller turns that into an
    actionable 4xx for the dashboard to show.
    """
    client = Github(token)
    gh_repo = client.get_repo(repo_full_name)

    gh_repo.create_secret("SERA_DASHBOARD_URL", dashboard_url)
    gh_repo.create_secret("SERA_REPO_ID", str(repo_id))
    gh_repo.create_secret("SERA_REPORT_TOKEN", report_token)

    workflow_status = _create_or_update_file(
        gh_repo,
        WORKFLOW_DEST_PATH,
        WORKFLOW_TEMPLATE_PATH.read_text(encoding="utf-8"),
        "Add SERA automated CI reporting workflow",
    )
    script_status = _create_or_update_file(
        gh_repo,
        REPORTER_DEST_PATH,
        REPORTER_SCRIPT_PATH.read_text(encoding="utf-8"),
        "Add SERA CI reporter script",
    )

    return {
        "status": "configured",
        "workflow_file": workflow_status,
        "reporter_script": script_status,
    }

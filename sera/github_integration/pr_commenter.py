"""Optional stretch: post the attribution result as a comment on the
responsible PR via the GitHub API.
"""
from __future__ import annotations

import os
from datetime import date
from typing import List, Optional

from github import Github

COMMENT_TEMPLATE = (
    "**SERA regression attribution**\n\n"
    "This PR is the likely cause of a measured accuracy regression "
    "({before:.0%} → {after:.0%}) detected on {detected_date}.\n\n"
    "**Evidence:**\n{evidence_bullets}\n"
)


def format_comment(
    before_accuracy: float,
    after_accuracy: float,
    detected_date: date,
    evidence: List[str],
) -> str:
    bullets = "\n".join(f"- {e}" for e in evidence)
    return COMMENT_TEMPLATE.format(
        before=before_accuracy,
        after=after_accuracy,
        detected_date=detected_date.isoformat(),
        evidence_bullets=bullets,
    )


def post_pr_comment(
    repo_full_name: str,
    pr_number: int,
    comment_body: str,
    token: Optional[str] = None,
) -> str:
    """Posts `comment_body` on the given PR. Returns the comment's HTML URL.

    Requires a token with `repo` (or `public_repo`) scope, via the `token`
    argument or the GITHUB_TOKEN environment variable. Never called
    automatically -- this is an explicit, user-triggered action since it
    writes to a shared, external system.
    """
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("a GitHub token is required to post PR comments")
    client = Github(token)
    repo = client.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)
    comment = pr.create_issue_comment(comment_body)
    return comment.html_url

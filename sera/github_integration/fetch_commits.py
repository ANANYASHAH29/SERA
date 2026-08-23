"""Fetches real commit/PR history for a repo + time window via the GitHub
REST API (through PyGithub).

Handles the messy edges real repos have:
  - merge commits and commits with huge file lists (files_changed degrades
    to [] rather than crashing -- GitHub's API also silently truncates the
    file list on very large diffs, which is a known, documented limit we
    can't work around from the client side)
  - commits with no associated PR
  - transient API errors and rate limiting (retried with backoff)
  - a SHA that stops existing mid-fetch because the branch got force-pushed
    underneath us (degrades to skipping that commit, not crashing the run)

All of these degrade to "no evidence for this one commit" rather than
crashing the whole fetch -- a partial, honest commit list beats no list.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable, List, Optional, TypeVar

from github import Github, GithubException, RateLimitExceededException, UnknownObjectException

from sera.github_integration.commit_types import CommitInfo

T = TypeVar("T")

MAX_RETRIES = 3
MAX_BACKOFF_SECONDS = 900  # never sleep more than 15 minutes for one retry


def _get_client(token: Optional[str] = None) -> Github:
    token = token or os.environ.get("GITHUB_TOKEN")
    if token:
        return Github(token)
    return Github()  # unauthenticated, low rate limit


def _call_with_rate_limit_retry(
    fn: Callable[[], T],
    max_retries: int = MAX_RETRIES,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Retries `fn` on RateLimitExceededException with a backoff derived
    from GitHub's rate-limit-reset header when available, capped at
    MAX_BACKOFF_SECONDS. `sleep_fn` is injectable so tests never actually
    sleep for real.
    """
    last_error: Optional[RateLimitExceededException] = None
    for attempt in range(max_retries):
        try:
            return fn()
        except RateLimitExceededException as e:
            last_error = e
            if attempt == max_retries - 1:
                raise
            reset_ts = None
            headers = getattr(e, "headers", None) or {}
            if "x-ratelimit-reset" in headers:
                try:
                    reset_ts = int(headers["x-ratelimit-reset"])
                except (TypeError, ValueError):
                    reset_ts = None
            if reset_ts:
                wait_s = max(1, reset_ts - int(time.time()))
            else:
                wait_s = 2 ** attempt * 30  # 30s, 60s, 120s, ...
            sleep_fn(min(wait_s, MAX_BACKOFF_SECONDS))
    raise last_error  # pragma: no cover — unreachable, loop always returns or raises


def _files_changed(gh_commit) -> List[str]:
    try:
        files = _call_with_rate_limit_retry(lambda: gh_commit.files or [])
        return [f.filename for f in files]
    except (GithubException, UnknownObjectException):
        # commit disappeared (force-push) or diff too large to list -- no
        # evidence available for this commit, not a fatal error.
        return []


def _associated_pr(repo, gh_commit):
    try:
        pulls = list(_call_with_rate_limit_retry(lambda: gh_commit.get_pulls()))
        if pulls:
            return pulls[0].number, pulls[0].html_url
    except (GithubException, UnknownObjectException):
        pass
    return None, None


def fetch_commit_history(
    repo_full_name: str,
    since: datetime,
    until: datetime,
    token: Optional[str] = None,
    max_commits: int = 200,
    fetch_pr_links: bool = True,
) -> List[CommitInfo]:
    """Fetch commits on the repo's default branch within [since, until].

    Returns plain CommitInfo objects (risk_categories left empty -- run
    `diff_analyzer.classify_commits` on the result).
    """
    client = _get_client(token)
    repo = _call_with_rate_limit_retry(lambda: client.get_repo(repo_full_name))

    results: List[CommitInfo] = []
    commits = _call_with_rate_limit_retry(lambda: repo.get_commits(since=since, until=until))
    iterator = iter(commits)

    count = 0
    while count < max_commits:
        try:
            gh_commit = _call_with_rate_limit_retry(lambda: next(iterator))
        except StopIteration:
            break
        except UnknownObjectException:
            # the branch got force-pushed and this page of history no
            # longer resolves the same way -- stop rather than fetch a
            # potentially inconsistent mix of old and new history.
            break
        count += 1

        try:
            commit_data = gh_commit.commit
            author_name = (
                commit_data.author.name if commit_data.author else (gh_commit.author.login if gh_commit.author else "unknown")
            )
            timestamp = commit_data.author.date if commit_data.author else datetime.utcnow()
            message = commit_data.message.splitlines()[0] if commit_data.message else ""
        except (GithubException, UnknownObjectException):
            continue

        pr_number, pr_url = (None, None)
        if fetch_pr_links:
            pr_number, pr_url = _associated_pr(repo, gh_commit)

        results.append(
            CommitInfo(
                sha=gh_commit.sha,
                message=message,
                author=author_name,
                timestamp=timestamp,
                files_changed=_files_changed(gh_commit),
                pr_number=pr_number,
                pr_html_url=pr_url,
            )
        )
    return results

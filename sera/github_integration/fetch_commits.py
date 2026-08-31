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


MAX_PATCH_CHARS = 2000  # enough for a "what changed" preview, not a full diff viewer


def _files_changed_and_patches(gh_commit):
    """One API call (gh_commit.files, already fetched for the filename
    list) also carries each file's unified diff text -- pull both out
    together instead of fetching the same data twice.
    """
    try:
        files = _call_with_rate_limit_retry(lambda: gh_commit.files or [])
    except (GithubException, UnknownObjectException):
        # commit disappeared (force-push) or diff too large to list -- no
        # evidence available for this commit, not a fatal error.
        return [], {}
    filenames = [f.filename for f in files]
    patches = {}
    for f in files:
        patch = getattr(f, "patch", None)
        if patch and len(patch) > MAX_PATCH_CHARS:
            patch = patch[:MAX_PATCH_CHARS] + "\n... (truncated)"
        patches[f.filename] = patch  # None for binary files (e.g. a .pkl checkpoint)
    return filenames, patches


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

        files_changed, file_patches = _files_changed_and_patches(gh_commit)
        results.append(
            CommitInfo(
                sha=gh_commit.sha,
                message=message,
                author=author_name,
                timestamp=timestamp,
                files_changed=files_changed,
                file_patches=file_patches,
                pr_number=pr_number,
                pr_html_url=pr_url,
            )
        )
    return results

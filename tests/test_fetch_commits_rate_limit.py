"""Rate-limit backoff and force-push tolerance for real GitHub API fetches.
Mocks PyGithub exceptions directly so these never hit the network or
actually sleep.
"""
import time

import pytest
from github import RateLimitExceededException, UnknownObjectException

from sera.github_integration.fetch_commits import (
    MAX_BACKOFF_SECONDS,
    _call_with_rate_limit_retry,
    _files_changed_and_patches,
)


def _rate_limit_error(reset_in_seconds=None):
    headers = {}
    if reset_in_seconds is not None:
        headers["x-ratelimit-reset"] = str(int(time.time()) + reset_in_seconds)
    return RateLimitExceededException(403, {"message": "rate limited"}, headers)


def test_retries_and_succeeds_after_transient_rate_limit():
    calls = {"n": 0}
    sleeps = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _rate_limit_error(reset_in_seconds=5)
        return "ok"

    result = _call_with_rate_limit_retry(flaky, max_retries=5, sleep_fn=sleeps.append)
    assert result == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert all(s <= MAX_BACKOFF_SECONDS for s in sleeps)


def test_raises_after_exhausting_retries():
    def always_limited():
        raise _rate_limit_error(reset_in_seconds=5)

    with pytest.raises(RateLimitExceededException):
        _call_with_rate_limit_retry(always_limited, max_retries=2, sleep_fn=lambda s: None)


def test_backoff_falls_back_to_exponential_without_reset_header():
    sleeps = []
    calls = {"n": 0}

    def flaky_no_header():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _rate_limit_error(reset_in_seconds=None)
        return "ok"

    result = _call_with_rate_limit_retry(flaky_no_header, max_retries=3, sleep_fn=sleeps.append)
    assert result == "ok"
    assert sleeps == [30]  # 2**0 * 30


def test_backoff_never_exceeds_cap():
    sleeps = []
    calls = {"n": 0}

    def flaky_huge_reset():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _rate_limit_error(reset_in_seconds=100000)
        return "ok"

    _call_with_rate_limit_retry(flaky_huge_reset, max_retries=3, sleep_fn=sleeps.append)
    assert sleeps == [MAX_BACKOFF_SECONDS]


def test_files_changed_degrades_gracefully_on_force_pushed_commit():
    class VanishedCommit:
        @property
        def files(self):
            raise UnknownObjectException(404, {"message": "Not Found"}, {})

    assert _files_changed_and_patches(VanishedCommit()) == ([], {})

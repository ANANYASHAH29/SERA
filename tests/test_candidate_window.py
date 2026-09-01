"""Tests for _candidate_window_start: the fix for multiple same-category
commits getting identical, indistinguishable ranking scores. The bug was
a fixed 24h lookback that kept already-fixed regressions in the
candidate pool right alongside a new one -- every commit since the last
real fix looked equally guilty. The fix bounds the candidate window to
"since the repo was last known healthy," matching real bisection.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sera.api.routes_report import LOOKBACK_HOURS, _candidate_window_start
from sera.db.models import ConnectedRepo, ScanResult
from sera.db.session import session_scope


@pytest.fixture
def db(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_candidate_window.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    return session_mod


def _make_repo(session, user_id=1):
    repo = ConnectedRepo(user_id=user_id, repo_full_name="alice/repo", sera_yml_status="present")
    session.add(repo)
    session.flush()
    return repo


def test_falls_back_to_fixed_lookback_when_never_healthy(db):
    with session_scope() as session:
        repo = _make_repo(session)
        since = _candidate_window_start(session, repo)

    expected = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    assert abs((since - expected).total_seconds()) < 5


def test_uses_last_healthy_scan_timestamp_not_fixed_window(db):
    with session_scope() as session:
        repo = _make_repo(session)
        healthy_at = datetime.utcnow() - timedelta(hours=2)
        session.add(ScanResult(repo_id=repo.id, status="healthy", summary_json="{}", created_at=healthy_at))
        session.flush()

        since = _candidate_window_start(session, repo)

    # 2 hours ago, NOT the fixed 24h-ago fallback -- a commit older than
    # the last healthy scan (but still inside 24h) must be excludable.
    assert since.tzinfo is not None
    assert abs((since - healthy_at.replace(tzinfo=timezone.utc)).total_seconds()) < 1


def test_uses_the_most_recent_healthy_scan_when_several_exist(db):
    with session_scope() as session:
        repo = _make_repo(session)
        older = datetime.utcnow() - timedelta(hours=10)
        newer = datetime.utcnow() - timedelta(hours=1)
        session.add(ScanResult(repo_id=repo.id, status="healthy", summary_json="{}", created_at=older))
        session.add(ScanResult(repo_id=repo.id, status="healthy", summary_json="{}", created_at=newer))
        session.flush()

        since = _candidate_window_start(session, repo)

    assert abs((since - newer.replace(tzinfo=timezone.utc)).total_seconds()) < 1

"""Tests for the deterministic recovery-plan/execution logic in
sera.method.recovery -- the developer-approved "Recover Pipeline"
workflow. Covers: plan construction from intervention evidence (single
cause, combined cause, fallback-to-contributing-set), idempotent
propose/execute, safe abort on HEAD mismatch, and resolving a pending
recovery once its own CI run reports back. GitHub API calls are faked;
nothing here touches a real repository.
"""
import json

import pytest
from github import GithubException, UnknownObjectException

from sera.db.models import ConnectedRepo, RecoveryAction, ScanResult
from sera.db.session import session_scope
from sera.method.recovery import (
    RecoveryError,
    build_recovery_plan,
    execute_recovery,
    propose_recovery,
    resolve_pending_recovery,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_recovery.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    return session_mod


def _make_repo(session):
    repo = ConnectedRepo(user_id=1, repo_full_name="alice/repo", sera_yml_status="present")
    session.add(repo)
    session.flush()
    return repo


def _make_scan(session, repo, status, head_sha, summary=None, interventions=None):
    scan = ScanResult(
        repo_id=repo.id,
        status=status,
        head_sha=head_sha,
        summary_json=json.dumps(summary or {}),
        interventions_json=json.dumps(interventions) if interventions is not None else None,
    )
    session.add(scan)
    session.flush()
    return scan


# ---------------------------------------------------------------------------
# build_recovery_plan
# ---------------------------------------------------------------------------


def test_plan_rejects_non_incident_scan(db):
    with session_scope() as session:
        repo = _make_repo(session)
        scan = _make_scan(session, repo, "healthy", "sha_h")
        with pytest.raises(RecoveryError, match="not an active incident"):
            build_recovery_plan(session, repo, scan)


def test_plan_requires_a_known_healthy_sha(db):
    with session_scope() as session:
        repo = _make_repo(session)
        # No healthy scan at all on record.
        scan = _make_scan(
            session, repo, "incident", "sha_bad",
            summary={"baseline_metric": 0.965, "current_metric": 0.6},
            interventions=[{"commit_sha": "c1", "verdict": "validated", "files_reverted": ["a.py"]}],
        )
        with pytest.raises(RecoveryError, match="No known healthy commit SHA"):
            build_recovery_plan(session, repo, scan)


def test_plan_requires_interventions_to_have_run(db):
    with session_scope() as session:
        repo = _make_repo(session)
        _make_scan(session, repo, "healthy", "sha_healthy")
        scan = _make_scan(session, repo, "incident", "sha_bad", summary={"baseline_metric": 0.965, "current_metric": 0.6})
        with pytest.raises(RecoveryError, match="No intervention has been run"):
            build_recovery_plan(session, repo, scan)


def test_plan_uses_single_validated_cause(db):
    with session_scope() as session:
        repo = _make_repo(session)
        _make_scan(session, repo, "healthy", "sha_healthy")
        scan = _make_scan(
            session, repo, "incident", "sha_bad",
            summary={"baseline_metric": 0.965, "current_metric": 0.6},
            interventions=[
                {"commit_sha": "c1", "stage_label": "Checkpoint", "verdict": "validated", "files_reverted": ["model.pkl"]},
                {"commit_sha": "c2", "stage_label": "Preprocessing", "verdict": "not_supported", "files_reverted": ["preprocess.py"]},
            ],
        )
        plan = build_recovery_plan(session, repo, scan)
        assert plan["healthy_sha"] == "sha_healthy"
        assert plan["degraded_sha"] == "sha_bad"
        assert plan["files"] == ["model.pkl"]
        assert [c["commit_sha"] for c in plan["contributing"]] == ["c1"]


def test_plan_prefers_validated_combined_over_partial_individuals(db):
    with session_scope() as session:
        repo = _make_repo(session)
        _make_scan(session, repo, "healthy", "sha_healthy")
        scan = _make_scan(
            session, repo, "incident", "sha_bad",
            summary={"baseline_metric": 0.965, "current_metric": 0.377},
            interventions=[
                {"commit_sha": "c1", "verdict": "insufficient_as_sole_cause", "files_reverted": ["label_mapping.py"]},
                {"commit_sha": "c2", "verdict": "insufficient_as_sole_cause", "files_reverted": ["preprocess.py"]},
                {"commit_sha": "c1,c2", "verdict": "validated_combined", "files_reverted": ["label_mapping.py", "preprocess.py"], "combined": True},
            ],
        )
        plan = build_recovery_plan(session, repo, scan)
        # The combined attempt is authoritative once it validates -- not
        # the two individually-insufficient ones separately.
        assert len(plan["contributing"]) == 1
        assert plan["contributing"][0]["verdict"] == "validated_combined"
        assert plan["files"] == ["label_mapping.py", "preprocess.py"]


def test_plan_falls_back_to_insufficient_contributing_set_when_nothing_validated(db):
    with session_scope() as session:
        repo = _make_repo(session)
        _make_scan(session, repo, "healthy", "sha_healthy")
        scan = _make_scan(
            session, repo, "incident", "sha_bad",
            summary={"baseline_metric": 0.965, "current_metric": 0.6},
            interventions=[
                {"commit_sha": "c1", "verdict": "insufficient_as_sole_cause", "files_reverted": ["a.py"]},
                {"commit_sha": "c2", "verdict": "not_supported", "files_reverted": ["b.py"]},
            ],
        )
        plan = build_recovery_plan(session, repo, scan)
        # Only the commit with real (if partial) evidence -- never the
        # not_supported one, and never "revert everything in the window".
        assert plan["files"] == ["a.py"]


def test_plan_raises_when_no_candidate_has_any_evidence(db):
    with session_scope() as session:
        repo = _make_repo(session)
        _make_scan(session, repo, "healthy", "sha_healthy")
        scan = _make_scan(
            session, repo, "incident", "sha_bad",
            summary={"baseline_metric": 0.965, "current_metric": 0.6},
            interventions=[{"commit_sha": "c1", "verdict": "not_supported", "files_reverted": ["a.py"]}],
        )
        with pytest.raises(RecoveryError, match="no evidentiary basis"):
            build_recovery_plan(session, repo, scan)


# ---------------------------------------------------------------------------
# propose_recovery: idempotency
# ---------------------------------------------------------------------------


def test_propose_recovery_is_idempotent(db):
    with session_scope() as session:
        repo = _make_repo(session)
        _make_scan(session, repo, "healthy", "sha_healthy")
        scan = _make_scan(
            session, repo, "incident", "sha_bad",
            summary={"baseline_metric": 0.965, "current_metric": 0.6},
            interventions=[{"commit_sha": "c1", "verdict": "validated", "files_reverted": ["a.py"]}],
        )
        first = propose_recovery(session, repo, scan)
        second = propose_recovery(session, repo, scan)
        assert first.id == second.id
        assert session.query(RecoveryAction).filter_by(source_scan_id=scan.id).count() == 1


# ---------------------------------------------------------------------------
# execute_recovery: fakes for the GitHub Git Data API
# ---------------------------------------------------------------------------


class FakeGitObject:
    def __init__(self, sha):
        self.sha = sha


class FakeRef:
    def __init__(self, sha):
        self.object = FakeGitObject(sha)
        self.edited_to = None

    def edit(self, sha):
        self.edited_to = sha
        self.object = FakeGitObject(sha)


class FakeTree:
    def __init__(self, sha="base-tree-sha"):
        self.sha = sha


class FakeCommit:
    def __init__(self, sha):
        self.sha = sha
        self.tree = FakeTree()


class FakeContentFile:
    def __init__(self, content_b64):
        self.content = content_b64


class FakeBlob:
    def __init__(self, sha):
        self.sha = sha


class FakeGithubRepo:
    default_branch = "main"

    def __init__(self, head_sha="degraded-sha", healthy_files=None):
        self._ref = FakeRef(head_sha)
        self.healthy_files = healthy_files or {}
        self.created_commits = []
        self.blobs_created = []

    def get_git_ref(self, ref):
        return self._ref

    def get_git_commit(self, sha):
        return FakeCommit(sha)

    def get_contents(self, path, ref=None):
        if path not in self.healthy_files:
            raise UnknownObjectException(404, {"message": "Not Found"}, {})
        return FakeContentFile(self.healthy_files[path])

    def create_git_blob(self, content, encoding):
        blob = FakeBlob(f"blob-{path_counter[0]}")
        path_counter[0] += 1
        self.blobs_created.append((content, encoding))
        return blob

    def create_git_tree(self, elements, base_tree):
        return FakeTree("new-tree-sha")

    def create_git_commit(self, message, tree, parents):
        commit = FakeCommit(f"recovery-commit-{len(self.created_commits)}")
        self.created_commits.append((message, tree, parents))
        return commit


path_counter = [0]


class FakeGithubClient:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, full_name):
        return self._repo


def _make_action(session, repo, healthy_sha="healthy-sha", degraded_sha="degraded-sha", files=("model.pkl",)):
    action = RecoveryAction(
        repo_id=repo.id,
        source_scan_id=_make_scan(
            session, repo, "incident", degraded_sha, summary={"baseline_metric": 0.965, "current_metric": 0.6}
        ).id,
        healthy_sha=healthy_sha,
        degraded_sha=degraded_sha,
        contributing_json=json.dumps([{"commit_sha": "c1", "stage_label": "Checkpoint", "verdict": "validated"}]),
        files_json=json.dumps(list(files)),
        status="proposed",
    )
    session.add(action)
    session.flush()
    return action


def test_execute_recovery_aborts_on_head_mismatch(db, monkeypatch):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(session, repo, degraded_sha="degraded-sha")
        fake_repo = FakeGithubRepo(head_sha="SOMETHING-ELSE-NOW")
        monkeypatch.setattr("sera.method.recovery.Github", lambda token: FakeGithubClient(fake_repo))

        with pytest.raises(RecoveryError, match="Repository changed since diagnosis"):
            execute_recovery(repo, action, "fake-token", expected_head_sha="degraded-sha")

        assert action.status == "aborted"
        assert not fake_repo.created_commits


def test_execute_recovery_creates_one_commit_for_multiple_files(db, monkeypatch):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(
            session, repo, healthy_sha="healthy-sha", degraded_sha="degraded-sha",
            files=("label_mapping.py", "preprocess.py"),
        )
        fake_repo = FakeGithubRepo(
            head_sha="degraded-sha",
            healthy_files={"label_mapping.py": "aGVhbHRoeQ==", "preprocess.py": "aGVhbHRoeTI="},
        )
        monkeypatch.setattr("sera.method.recovery.Github", lambda token: FakeGithubClient(fake_repo))

        result = execute_recovery(repo, action, "fake-token", expected_head_sha="degraded-sha")

        assert result.status == "pending_ci"
        assert result.recovery_commit_sha is not None
        assert len(fake_repo.created_commits) == 1  # ONE commit, not one per file
        assert fake_repo._ref.edited_to == result.recovery_commit_sha


def test_execute_recovery_is_idempotent_on_repeat_confirm(db, monkeypatch):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(session, repo)
        fake_repo = FakeGithubRepo(head_sha="degraded-sha", healthy_files={"model.pkl": "aGVhbHRoeQ=="})
        monkeypatch.setattr("sera.method.recovery.Github", lambda token: FakeGithubClient(fake_repo))

        first = execute_recovery(repo, action, "fake-token", expected_head_sha="degraded-sha")
        sha_after_first = first.recovery_commit_sha

        # Second confirm on the same (now non-"proposed") action must not
        # create a second commit.
        second = execute_recovery(repo, action, "fake-token", expected_head_sha="degraded-sha")

        assert second.recovery_commit_sha == sha_after_first
        assert len(fake_repo.created_commits) == 1


def test_execute_recovery_aborts_when_nothing_to_restore(db, monkeypatch):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(session, repo, files=("missing_file.py",))
        fake_repo = FakeGithubRepo(head_sha="degraded-sha", healthy_files={})  # file never existed at healthy ref
        monkeypatch.setattr("sera.method.recovery.Github", lambda token: FakeGithubClient(fake_repo))

        with pytest.raises(RecoveryError, match="None of the planned files"):
            execute_recovery(repo, action, "fake-token", expected_head_sha="degraded-sha")

        assert action.status == "aborted"


# ---------------------------------------------------------------------------
# resolve_pending_recovery
# ---------------------------------------------------------------------------


def test_resolve_pending_recovery_marks_recovered_on_healthy_followup(db):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(session, repo)
        action.status = "pending_ci"
        action.recovery_commit_sha = "recovery-sha-1"
        session.flush()

        new_scan = _make_scan(
            session, repo, "healthy", "recovery-sha-1", summary={"baseline_metric": 0.965, "current_metric": 0.965}
        )
        resolve_pending_recovery(session, repo, new_scan)

        assert action.status == "recovered"
        assert action.resolved_scan_id == new_scan.id
        assert action.after_metric == 0.965


def test_resolve_pending_recovery_marks_failed_on_still_degraded_followup(db):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(session, repo)
        action.status = "pending_ci"
        action.recovery_commit_sha = "recovery-sha-1"
        session.flush()

        new_scan = _make_scan(
            session, repo, "incident", "recovery-sha-1", summary={"baseline_metric": 0.965, "current_metric": 0.7}
        )
        resolve_pending_recovery(session, repo, new_scan)

        assert action.status == "recovery_failed"


def test_resolve_pending_recovery_ignores_unrelated_scans(db):
    with session_scope() as session:
        repo = _make_repo(session)
        action = _make_action(session, repo)
        action.status = "pending_ci"
        action.recovery_commit_sha = "recovery-sha-1"
        session.flush()

        unrelated_scan = _make_scan(session, repo, "healthy", "some-other-sha", summary={"current_metric": 0.9})
        resolve_pending_recovery(session, repo, unrelated_scan)

        assert action.status == "pending_ci"  # untouched

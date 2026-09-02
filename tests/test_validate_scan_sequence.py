"""Tests for POST /report/{repo_id}/validate-scan-sequence and the
record_interventions verdict logic it delegates to -- the three-way
verdict (validated / insufficient-as-sole-cause / not-supported) plus
the combined-attempt variants, replacing a single collapsed
recovered/not-recovered boolean. Also verifies resolve_pending_recovery
is wired into the real report pipeline: a pending recovery action gets
resolved by the very next scan report, end to end, not just at the unit
level.
"""
import json

import pytest
from fastapi.testclient import TestClient

from sera.method.validation import _verdict_for, record_interventions


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_validate_scan_sequence.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref, token=None: None
    )

    from sera.api.main import app

    return TestClient(app)


def _connect_repo(client, username="alice"):
    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, username, installation_id=None)
        session.flush()
        user_id = user.id

    resp = client.post("/tenant/repos", json={"user_id": user_id, "repo_full_name": f"{username}/repo"})
    repo_id = resp.json()["id"]
    token_resp = client.get(f"/tenant/repos/{repo_id}/report-token", params={"user_id": user_id})
    token = token_resp.json()["report_token"]
    return user_id, repo_id, token


def _generic_payload(accuracy, token, n=100, head_sha=None):
    correct_n = round(accuracy * n)
    payload = {
        "report_token": token,
        "task_type": "classification",
        "primary_metric": accuracy,
        "primary_metric_name": "accuracy",
        "secondary_metrics": {"mean_confidence": accuracy, "mean_entropy": 0.2},
        "per_sample_scores": [1] * correct_n + [0] * (n - correct_n),
        "n_samples": n,
        "canary_set_hash": "deadbeef",
    }
    if head_sha:
        payload["head_sha"] = head_sha
    return payload


# ---------------------------------------------------------------------------
# _verdict_for
# ---------------------------------------------------------------------------


def test_verdict_validated_when_recovered():
    assert _verdict_for(before_metric=0.6, after_metric=0.96, baseline_metric=0.965, combined=False) == "validated"


def test_verdict_insufficient_as_sole_cause_when_partial_improvement():
    assert (
        _verdict_for(before_metric=0.6, after_metric=0.75, baseline_metric=0.965, combined=False)
        == "insufficient_as_sole_cause"
    )


def test_verdict_not_supported_when_no_improvement():
    assert _verdict_for(before_metric=0.6, after_metric=0.59, baseline_metric=0.965, combined=False) == "not_supported"


def test_verdict_combined_variants():
    assert _verdict_for(before_metric=0.6, after_metric=0.96, baseline_metric=0.965, combined=True) == "validated_combined"
    assert _verdict_for(before_metric=0.6, after_metric=0.7, baseline_metric=0.965, combined=True) == "insufficient_combined"


# ---------------------------------------------------------------------------
# /validate-scan-sequence route + head_sha/resolve_pending_recovery wiring
# ---------------------------------------------------------------------------


def test_validate_scan_sequence_records_full_attempt_list_and_syncs_validation_json(client):
    user_id, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.95, token, head_sha="sha-healthy"))
    resp = client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.6, token, head_sha="sha-degraded"))
    scan_id = resp.json()["scan_id"]

    interventions = [
        {"commit_sha": "c1", "stage_label": "Checkpoint", "files_reverted": ["model.pkl"], "after_metric": 0.7, "combined": False},
        {"commit_sha": "c2", "stage_label": "Preprocessing", "files_reverted": ["preprocess.py"], "after_metric": 0.96, "combined": False},
    ]
    seq_resp = client.post(
        f"/report/{repo_id}/validate-scan-sequence",
        json={"report_token": token, "scan_id": scan_id, "interventions": interventions},
    )
    assert seq_resp.status_code == 200
    recorded = seq_resp.json()["interventions"]
    assert recorded[0]["verdict"] == "insufficient_as_sole_cause"
    assert recorded[1]["verdict"] == "validated"

    from sera.db.session import session_scope
    from sera.db.models import ScanResult

    with session_scope() as session:
        scan = session.get(ScanResult, scan_id)
        assert json.loads(scan.interventions_json) == recorded
        # validation_json (the field the existing single-attempt UI reads)
        # stays in sync with the FIRST attempt for backward compatibility.
        assert json.loads(scan.validation_json)["suspect_commit_sha"] == "c1"


def test_head_sha_stored_and_recovery_resolved_by_next_real_scan(client, monkeypatch):
    """End-to-end (through the real report pipeline, not a unit call):
    a pending recovery for this repo gets resolved the moment the NEXT
    scan reports the recovery commit's own sha -- proving
    resolve_pending_recovery is actually wired into
    process_generic_scan_result, not just unit-tested in isolation.
    """
    user_id, repo_id, token = _connect_repo(client)
    client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.95, token, head_sha="sha-healthy"))
    resp = client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.6, token, head_sha="sha-degraded"))
    incident_scan_id = resp.json()["scan_id"]

    from sera.db.session import session_scope
    from sera.db.models import ConnectedRepo, RecoveryAction

    with session_scope() as session:
        repo = session.query(ConnectedRepo).filter_by(id=repo_id).one()
        action = RecoveryAction(
            repo_id=repo.id,
            source_scan_id=incident_scan_id,
            healthy_sha="sha-healthy",
            degraded_sha="sha-degraded",
            contributing_json="[]",
            files_json="[]",
            status="pending_ci",
            recovery_commit_sha="sha-recovery",
        )
        session.add(action)
        session.flush()
        action_id = action.id

    # The recovery commit's own CI run reports back -- a completely
    # ordinary generic-scan report, head_sha matching the pending action.
    client.post(f"/report/{repo_id}/generic-scan", json=_generic_payload(0.965, token, head_sha="sha-recovery"))

    with session_scope() as session:
        resolved = session.get(RecoveryAction, action_id)
        assert resolved.status == "recovered"
        assert resolved.after_metric == pytest.approx(0.965)

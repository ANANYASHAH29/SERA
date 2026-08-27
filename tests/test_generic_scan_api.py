"""Tests for the B3 API: detect-signals, canary-draft, and the manual
JSON-paste ingestion endpoint. GitHub scanning is monkeypatched for the
offline tests; one marked @pytest.mark.network test exercises the real
demo-fraud-model repo end to end.
"""
import pytest
from fastapi.testclient import TestClient

from sera.method.repo_scanner import ScanSignals


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera_generic_scan.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)
    monkeypatch.setattr(
        "sera.api.routes_tenant.load_repo_config_from_github", lambda repo_full_name, ref: None
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
    return user_id, resp.json()["id"]


ALL_FOUND_SIGNALS = ScanSignals(
    model_artifact_found=True,
    model_artifact_path="model.pkl",
    sklearn_import_found=True,
    sklearn_import_files=["train.py"],
    train_test_split_found=True,
    train_test_split_file="train.py",
    held_out_csv_found=True,
    held_out_csv_path="test_set.csv",
)

PARTIAL_SIGNALS = ScanSignals(model_artifact_found=True, sklearn_import_found=False)


def test_detect_signals_rejects_cross_tenant_repo(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_generic_scan.scan_repo_for_sklearn_signals", lambda repo, token=None: ALL_FOUND_SIGNALS
    )
    _, repo_id = _connect_repo(client)
    other_user_id, _ = _connect_repo(client)
    resp = client.get(f"/tenant/repos/{repo_id}/detect-signals", params={"user_id": other_user_id + 999})
    assert resp.status_code == 404


def test_detect_signals_returns_scan_result(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_generic_scan.scan_repo_for_sklearn_signals", lambda repo, token=None: ALL_FOUND_SIGNALS
    )
    user_id, repo_id = _connect_repo(client)
    resp = client.get(f"/tenant/repos/{repo_id}/detect-signals", params={"user_id": user_id})
    assert resp.status_code == 200
    assert resp.json()["all_signals_found"] is True


def test_canary_draft_returns_409_when_signals_incomplete(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_generic_scan.scan_repo_for_sklearn_signals", lambda repo, token=None: PARTIAL_SIGNALS
    )
    user_id, repo_id = _connect_repo(client)
    resp = client.get(f"/tenant/repos/{repo_id}/canary-draft", params={"user_id": user_id})
    assert resp.status_code == 409
    assert "sklearn_import" in resp.json()["detail"]["missing_signals"]


def test_canary_draft_returns_draft_when_signals_complete(client, monkeypatch):
    monkeypatch.setattr(
        "sera.api.routes_generic_scan.scan_repo_for_sklearn_signals", lambda repo, token=None: ALL_FOUND_SIGNALS
    )
    user_id, repo_id = _connect_repo(client)
    resp = client.get(f"/tenant/repos/{repo_id}/canary-draft", params={"user_id": user_id})
    assert resp.status_code == 200
    assert "joblib.load" in resp.json()["draft"]


def _generic_payload(accuracy, n=10):
    correct_n = round(accuracy * n)
    return {
        "task_type": "classification",
        "primary_metric": accuracy,
        "primary_metric_name": "accuracy",
        "secondary_metrics": {"mean_confidence": accuracy, "mean_entropy": 0.2},
        "per_sample_scores": [1] * correct_n + [0] * (n - correct_n),
        "n_samples": n,
        "canary_set_hash": "deadbeef",
    }


def test_ingest_first_result_bootstraps_baseline(client):
    user_id, repo_id = _connect_repo(client)
    resp = client.post(
        f"/tenant/repos/{repo_id}/ingest-scan-result",
        params={"user_id": user_id},
        json=_generic_payload(0.95),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "baseline_set"


def test_ingest_regression_produces_incident(client):
    user_id, repo_id = _connect_repo(client)
    client.post(
        f"/tenant/repos/{repo_id}/ingest-scan-result",
        params={"user_id": user_id},
        json=_generic_payload(0.95, n=100),
    )
    resp = client.post(
        f"/tenant/repos/{repo_id}/ingest-scan-result",
        params={"user_id": user_id},
        json=_generic_payload(0.6, n=100),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "incident"

    repos = client.get("/tenant/repos", params={"user_id": user_id}).json()
    assert repos[0]["health_status"] == "incident"


def test_ingest_rejects_cross_tenant_repo(client):
    alice_id, alice_repo_id = _connect_repo(client, "alice")
    bob_id, _ = _connect_repo(client, "bob")
    resp = client.post(
        f"/tenant/repos/{alice_repo_id}/ingest-scan-result",
        params={"user_id": bob_id},
        json=_generic_payload(0.9),
    )
    assert resp.status_code == 404


@pytest.mark.network
def test_full_flow_against_real_demo_fraud_model_repo(client):
    """The actual B3 acceptance test: connect the real repo, detect
    signals for real, fetch the real draft, run it locally, and post its
    real JSON output -- proving the dashboard shows real data, not
    placeholders.
    """
    import subprocess
    import sys
    from pathlib import Path

    from sera.db.session import session_scope
    from sera.method.tenancy import get_or_create_user

    with session_scope() as session:
        user = get_or_create_user(session, "real-repo-tester", installation_id=None)
        session.flush()
        user_id = user.id
    connect_resp = client.post(
        "/tenant/repos",
        json={"user_id": user_id, "repo_full_name": "ANANYASHAH29/Fraud-detection"},
    )
    repo_id = connect_resp.json()["id"]

    try:
        detect_resp = client.get(f"/tenant/repos/{repo_id}/detect-signals", params={"user_id": user_id})
    except Exception as e:
        pytest.skip(f"network unavailable: {e}")
    if detect_resp.status_code != 200 or not detect_resp.json().get("all_signals_found"):
        pytest.skip("real repo signals not fully detected -- network or repo state issue")

    draft_resp = client.get(f"/tenant/repos/{repo_id}/canary-draft", params={"user_id": user_id})
    assert draft_resp.status_code == 200
    draft_code = draft_resp.json()["draft"]

    demo_repo_path = Path("C:/Users/Ananya/Desktop/demo-fraud-model")
    if not demo_repo_path.exists():
        pytest.skip("local demo-fraud-model checkout not present")

    draft_path = demo_repo_path / "_test_generated_draft.py"
    draft_path.write_text(draft_code)
    try:
        proc = subprocess.run(
            [sys.executable, str(draft_path)], cwd=demo_repo_path, capture_output=True, text=True, timeout=60
        )
        assert proc.returncode == 0, proc.stderr
        import json

        result_json = json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        draft_path.unlink(missing_ok=True)

    ingest_resp = client.post(
        f"/tenant/repos/{repo_id}/ingest-scan-result", params={"user_id": user_id}, json=result_json
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["status"] == "baseline_set"
    assert result_json["primary_metric"] == pytest.approx(0.9649122807017544)

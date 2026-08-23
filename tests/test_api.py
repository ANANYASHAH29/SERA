"""End-to-end smoke test of the FastAPI app via TestClient: baseline run ->
injected run -> incident detection -> synthetic history -> ranking ->
validation. Uses a throwaway SQLite DB so it doesn't touch sera_state.db.
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import requires_checkpoint


@pytest.fixture
def client(tmp_path, monkeypatch):
    import sera.db.session as session_mod

    db_path = tmp_path / "test_sera.db"
    monkeypatch.setattr(session_mod, "_default_engine", None)
    monkeypatch.setattr(session_mod, "_default_session_factory", None)
    monkeypatch.setattr(session_mod, "DB_PATH", db_path)

    from sera.api.main import app

    return TestClient(app)


@requires_checkpoint
def test_full_flow_f1_resize(client):
    baseline_resp = client.post("/runs/baseline", params={"seed": 0})
    assert baseline_resp.status_code == 200
    baseline_run_id = baseline_resp.json()["run_id"]

    inject_resp = client.post("/runs/inject", json={"condition": "F1", "severity": 1.0, "seed": 0})
    assert inject_resp.status_code == 200
    regressed_run_id = inject_resp.json()["run_id"]

    detect_resp = client.post(
        "/incidents/detect",
        params={"baseline_run_id": baseline_run_id, "regressed_run_id": regressed_run_id},
    )
    assert detect_resp.status_code == 200
    incident_id = detect_resp.json()["incident_id"]

    hist_resp = client.post(
        f"/incidents/{incident_id}/history/synthetic",
        json={"num_harmless": 3, "guilty_category": "F1"},
    )
    assert hist_resp.status_code == 200

    rank_resp = client.post(f"/incidents/{incident_id}/rank")
    assert rank_resp.status_code == 200
    candidates = rank_resp.json()["candidates"]
    assert candidates[0]["hypothesized_category"] == "F1"

    validate_resp = client.post(f"/incidents/{incident_id}/validate")
    assert validate_resp.status_code == 200
    assert validate_resp.json()["confirmed"] is True


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

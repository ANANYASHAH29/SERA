"""Endpoints for producing pipeline runs: a healthy baseline, or a run with
one of F1-F5/D1 injected.
"""
from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException

from sera.api import state
from sera.api.schemas import InjectRequest, RunSummary
from sera.conditions.registry import CONFIG_CONDITIONS, DRIFT_CONDITION
from sera.config import baseline_config
from sera.db.session import session_scope
from sera.method.memory import record_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("/baseline", response_model=RunSummary)
def create_baseline_run(seed: int = 0):
    from sera.pipeline.ingestion import build_canary_set
    from sera.pipeline.runner import run_pipeline

    config = baseline_config()
    batch = build_canary_set()
    metrics = run_pipeline(config, batch, corruption_seed=seed)

    with session_scope() as session:
        run = record_run(session, config, metrics, seed=seed, is_baseline=True)
        run_id = run.id

    state.store_run_context(run_id, config, batch, metrics.accuracy)
    return RunSummary(
        run_id=run_id,
        accuracy=metrics.accuracy,
        mean_confidence=metrics.mean_confidence,
        mean_entropy=metrics.mean_entropy,
        is_baseline=True,
    )


@router.post("/inject", response_model=RunSummary)
def create_injected_run(req: InjectRequest):
    from sera.pipeline.ingestion import build_canary_set
    from sera.pipeline.runner import run_pipeline

    base_config = baseline_config()
    batch = build_canary_set()
    seed = req.seed if req.seed is not None else 0

    if req.condition in CONFIG_CONDITIONS:
        config = CONFIG_CONDITIONS[req.condition].apply(base_config, severity=req.severity)
    elif req.condition == "D1":
        config = base_config
        shifted_images = DRIFT_CONDITION.apply_to_images(
            batch.images, severity=req.severity, seed=seed
        )
        batch = replace(batch, images=shifted_images)
    else:
        raise HTTPException(400, f"unknown condition {req.condition!r}")

    metrics = run_pipeline(config, batch, corruption_seed=seed)

    with session_scope() as session:
        run = record_run(session, config, metrics, seed=seed, is_baseline=False)
        run_id = run.id

    state.store_run_context(run_id, config, batch, metrics.accuracy)
    return RunSummary(
        run_id=run_id,
        accuracy=metrics.accuracy,
        mean_confidence=metrics.mean_confidence,
        mean_entropy=metrics.mean_entropy,
        is_baseline=False,
    )

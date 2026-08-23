"""Process-local state the API needs beyond what's persisted in SQLite:
the actual config/canary-images each Run used, so a later `/validate` call
can re-run the pipeline. Images are not persisted to the DB (they're
derived, reproducible data, not something worth duplicating into SQLite).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from sera.config import PipelineConfig
from sera.pipeline.ingestion import CanaryBatch

_RUN_CONTEXT: Dict[int, Tuple[PipelineConfig, CanaryBatch, float]] = {}
_INCIDENT_COMMITS: Dict[int, list] = {}
_INCIDENT_RANKING: Dict[int, list] = {}


def store_run_context(run_id: int, config: PipelineConfig, batch: CanaryBatch, accuracy: float) -> None:
    _RUN_CONTEXT[run_id] = (config, batch, accuracy)


def get_run_context(run_id: int) -> Optional[Tuple[PipelineConfig, CanaryBatch, float]]:
    return _RUN_CONTEXT.get(run_id)


def store_incident_commits(incident_id: int, commits: list) -> None:
    _INCIDENT_COMMITS[incident_id] = commits


def get_incident_commits(incident_id: int) -> list:
    return _INCIDENT_COMMITS.get(incident_id, [])


def store_incident_ranking(incident_id: int, ranking: list) -> None:
    _INCIDENT_RANKING[incident_id] = ranking


def get_incident_ranking(incident_id: int) -> list:
    return _INCIDENT_RANKING.get(incident_id, [])
